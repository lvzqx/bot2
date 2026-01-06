from __future__ import annotations

import logging
import sqlite3
from contextlib import contextmanager
from typing import Optional, Tuple

import discord
from discord import app_commands
from discord.ext import commands

# ロガーの設定
logger = logging.getLogger(__name__)

class Delete(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        logger.info("Delete cog が初期化されました")

    @contextmanager
    def _get_db_connection(self) -> sqlite3.Connection:
        """データベース接続を取得するコンテキストマネージャ"""
        conn = sqlite3.connect(self.bot.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        except sqlite3.Error as e:
            logger.error(f"データベースエラー: {e}")
            conn.rollback()
            raise
        finally:
            conn.close()

    @contextmanager
    def _get_cursor(self, conn: sqlite3.Connection) -> sqlite3.Cursor:
        """カーソルを取得するコンテキストマネージャ"""
        cursor = conn.cursor()
        try:
            yield cursor
        finally:
            cursor.close()

    async def _get_message_data(self, message_id: str) -> Optional[dict]:
        """メッセージIDからメッセージデータを取得します"""
        logger.info(f"メッセージデータを取得中: message_id={message_id}")
        try:
            with self._get_db_connection() as conn:
                with self._get_cursor(conn) as cursor:
                    # データベース内のメッセージ参照を確認
                    cursor.execute('''
                        SELECT 
                            mr.post_id, 
                            mr.channel_id, 
                            mr.message_id, 
                            t.user_id,
                            t.is_public
                        FROM message_references mr
                        JOIN thoughts t ON mr.post_id = t.id
                        WHERE mr.message_id = ?
                    ''', (message_id,))
                    
                    row = cursor.fetchone()
                    if row:
                        logger.info(f"メッセージデータを取得しました: {dict(row)}")
                        return dict(row)
                    
                    # デバッグ用: データベース内の全メッセージIDをログに出力
                    cursor.execute('SELECT message_id FROM message_references LIMIT 10')
                    sample_message_ids = [r[0] for r in cursor.fetchall()]
                    logger.info(f"データベース内のサンプルメッセージID: {sample_message_ids}")
                    
                    return None
        except sqlite3.Error as e:
            logger.error(f"メッセージデータの取得中にエラーが発生しました: {e}")
            return None

    async def _delete_post(self, post_id: int, user_id: int, is_admin: bool = False) -> Tuple[bool, Optional[bool]]:
        """投稿を削除します
        
        Returns:
            Tuple[成功したかどうか, 削除した投稿が非公開だったかどうか]
        """
        try:
            with self._get_db_connection() as conn:
                with conn:
                    with self._get_cursor(conn) as cursor:
                        # 投稿が存在するか確認（非公開かどうかも取得）
                        cursor.execute('''
                            SELECT user_id, is_public FROM thoughts 
                            WHERE id = ?
                        ''', (post_id,))
                        
                        if result := cursor.fetchone():
                            post_owner_id, is_public = result[0], bool(result[1])
                            # 投稿者または管理者でない場合は削除不可
                            if str(post_owner_id) != str(user_id) and not is_admin:
                                return False, None
                        else:
                            return False, None  # 投稿が見つからない
                        
                        # 投稿を削除（外部キー制約により関連するメッセージ参照も削除される）
                        cursor.execute('''
                            DELETE FROM thoughts 
                            WHERE id = ?
                        ''', (post_id,))
                        
                        # 削除された投稿が非公開かどうかを返す
                        return cursor.rowcount > 0, not is_public
        except sqlite3.Error as e:
            logger.error(f"投稿の削除中にエラーが発生しました: {e}")
            return False, None
            
    async def _check_and_remove_private_role(self, guild: discord.Guild, user_id: int) -> None:
        """ユーザーの非公開投稿がなくなった場合、非公開ロールを削除します"""
        try:
            with self._get_db_connection() as conn:
                with self._get_cursor(conn) as cursor:
                    # ユーザーの非公開投稿が残っているか確認
                    cursor.execute('''
                        SELECT COUNT(*) as count 
                        FROM thoughts 
                        WHERE user_id = ? AND is_public = 0
                    ''', (user_id,))
                    remaining_posts = cursor.fetchone()['count']
                    
                    if remaining_posts == 0:
                        # 非公開ロールを検索
                        private_role = discord.utils.get(guild.roles, name="非公開")
                        if private_role:
                            member = guild.get_member(int(user_id))
                            if member and private_role in member.roles:
                                await member.remove_roles(private_role, reason="非公開投稿がなくなりました")
                                logger.info(f"ユーザー {member} から非公開ロールを削除しました")
        except Exception as e:
            logger.error(f"非公開ロールの削除中にエラーが発生しました: {e}")

    @app_commands.command(name="delete", description="投稿を削除します")
    @app_commands.describe(message_id="削除するメッセージのID")
    @app_commands.guild_only()
    async def delete(self, interaction: discord.Interaction, message_id: str) -> None:
        """メッセージIDで投稿を削除します"""
        logger.info(f"delete コマンドが呼び出されました。ユーザー: {interaction.user}, メッセージID: {message_id}")
        
        # 応答を遅延
        await interaction.response.defer(ephemeral=True)
        
        try:
            # メッセージデータを取得
            message_data = await self._get_message_data(message_id)
            if not message_data:
                await interaction.followup.send(
                    "❌ メッセージが見つかりませんでした。正しいメッセージIDを入力してください。",
                    ephemeral=True
                )
                return
            
            # 管理者権限を確認
            is_admin = interaction.user.guild_permissions.administrator
            
            # 非公開の投稿で、投稿者でも管理者でもない場合はエラー
            if not message_data['is_public'] and message_data['user_id'] != interaction.user.id and not is_admin:
                await interaction.followup.send(
                    "❌ この投稿は非公開のため、投稿者または管理者のみが削除できます。",
                    ephemeral=True
                )
                return
            
            # 投稿を削除
            success, was_private = await self._delete_post(
                message_data['post_id'], 
                interaction.user.id,
                is_admin
            )
            
            if not success:
                await interaction.followup.send(
                    "❌ 投稿の削除に失敗しました。権限がないか、既に削除されています。",
                    ephemeral=True
                )
                return
                
            # 非公開投稿を削除した場合、非公開ロールを確認
            if was_private:
                await self._check_and_remove_private_role(interaction.guild, message_data['user_id'])
            
            # メッセージを削除
            try:
                channel = interaction.guild.get_channel_or_thread(int(message_data['channel_id']))
                if not channel:
                    logger.warning(f"チャンネルが見つかりません: {message_data['channel_id']}")
                    return
                
                # スレッドの場合はスレッド全体を削除
                if isinstance(channel, discord.Thread):
                    # 権限チェック
                    has_permission = (
                        channel.owner_id == interaction.user.id or  # スレッドの作成者
                        interaction.user.guild_permissions.administrator or  # 管理者
                        interaction.user.guild_permissions.manage_threads  # スレッド管理権限
                    )
                    
                    if not has_permission:
                        await interaction.followup.send(
                            "❌ このスレッドを削除する権限がありません。",
                            ephemeral=True
                        )
                        return
                    
                    # スレッドをアーカイブして削除
                    try:
                        # スレッドをアーカイブ
                        await channel.edit(archived=True, locked=True)
                        # スレッドを削除
                        await channel.delete(reason=f"投稿削除 by {interaction.user}")
                        logger.info(f"スレッド {channel.id} を削除しました")
                    except discord.Forbidden:
                        logger.warning(f"スレッドの削除権限がありません: {channel.id}")
                        await interaction.followup.send(
                            "❌ スレッドを削除する権限がありません。",
                            ephemeral=True
                        )
                        return
                    except discord.HTTPException as e:
                        logger.error(f"スレッドの削除中にエラーが発生しました: {e}")
                        raise
                else:
                    # 通常のメッセージを削除
                    try:
                        message = await channel.fetch_message(int(message_data['message_id']))
                        await message.delete()
                        logger.info(f"メッセージ {message.id} を削除しました")
                    except discord.NotFound:
                        logger.warning(f"メッセージが見つかりません: {message_data['message_id']}")
                    except discord.Forbidden:
                        logger.warning(f"メッセージの削除権限がありません: {message_data['message_id']}")
                        await interaction.followup.send(
                            "❌ メッセージを削除する権限がありません。",
                            ephemeral=True
                        )
                        return
            except discord.NotFound:
                logger.warning(f"メッセージまたはチャンネルが見つかりませんでした: {message_data['message_id']}")
            except discord.Forbidden:
                logger.warning(f"メッセージの削除権限がありません: {message_data['message_id']}")
            except discord.HTTPException as e:
                logger.warning(f"メッセージの削除中にエラーが発生しました: {e}")
            
            # 完了メッセージを送信
            await interaction.followup.send(
                f"✅ 投稿 (ID: {message_data['post_id']}) を削除しました。",
                ephemeral=True
            )
            
        except Exception as e:
            logger.error(f"削除処理中にエラーが発生しました: {e}", exc_info=True)
            await interaction.followup.send(
                "❌ 削除処理中にエラーが発生しました。しばらくしてからもう一度お試しください。",
                ephemeral=True
            )

async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Delete(bot))
    logger.info("Delete cog が読み込まれました")
