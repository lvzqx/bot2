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
        conn = sqlite3.connect('thoughts.db')
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
        logger.info(f"メッセージデータを取得中: message_id={message_id} (型: {type(message_id)})")
        try:
            with self._get_db_connection() as conn:
                with self._get_cursor(conn) as cursor:
                    # データベース内のメッセージ参照を確認（文字列として比較）
                    cursor.execute('''
                        SELECT 
                            mr.post_id, 
                            mr.channel_id, 
                            mr.message_id, 
                            t.user_id,
                            t.is_private
                        FROM message_references mr
                        JOIN thoughts t ON mr.post_id = t.id
                        WHERE CAST(mr.message_id AS TEXT) = ?
                    ''', (str(message_id),))
                    
                    row = cursor.fetchone()
                    if row:
                        result = dict(row)
                        logger.info(f"メッセージデータを取得しました: {result}")
                        return result
                    
                    # デバッグ用: データベース内の全メッセージIDをログに出力
                    cursor.execute('SELECT message_id, post_id, channel_id FROM message_references LIMIT 10')
                    sample_messages = [dict(r) for r in cursor.fetchall()]
                    logger.info(f"データベース内のサンプルメッセージ: {sample_messages}")
                    
                    # 念のため、数値としても検索を試みる
                    try:
                        if message_id.isdigit():
                            cursor.execute('''
                                SELECT 
                                    mr.post_id, 
                                    mr.channel_id, 
                                    mr.message_id, 
                                    t.user_id,
                                    t.is_private
                                FROM message_references mr
                                JOIN thoughts t ON mr.post_id = t.id
                                WHERE mr.message_id = ?
                            ''', (int(message_id),))
                            
                            if row := cursor.fetchone():
                                result = dict(row)
                                logger.info(f"数値として検索してメッセージデータを取得しました: {result}")
                                return result
                    except (ValueError, TypeError) as e:
                        logger.warning(f"数値としての検索に失敗しました: {e}")
                    
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
                            SELECT user_id, is_private FROM thoughts 
                            WHERE id = ?
                        ''', (post_id,))
                        
                        if result := cursor.fetchone():
                            post_owner_id, is_private = result[0], bool(result[1])
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
                        return cursor.rowcount > 0, is_private
        except sqlite3.Error as e:
            logger.error(f"投稿の削除中にエラーが発生しました: {e}")
            return False, None
            
    async def _check_and_remove_private_role(self, guild: discord.Guild, user_id: int) -> None:
        """ユーザーから非公開ロールを削除します"""
        try:
            # 非公開ロールを検索
            private_role = discord.utils.get(guild.roles, name="非公開")
            if private_role:
                member = guild.get_member(int(user_id))
                if member and private_role in member.roles:
                    # ユーザーの非公開投稿を確認
                    with self._get_db_connection() as conn:
                        with self._get_cursor(conn) as cursor:
                            cursor.execute('''
                                SELECT COUNT(*) as count 
                                FROM thoughts 
                                WHERE user_id = ? AND is_private = 1
                            ''', (user_id,))
                            remaining_posts = cursor.fetchone()['count']
                            
                            if remaining_posts == 0:
                                await member.remove_roles(private_role, reason="非公開投稿がなくなりました")
                                logger.info(f"ユーザー {member} から非公開ロールを削除しました")
                            else:
                                logger.info(f"ユーザー {member} にはまだ {remaining_posts} 件の非公開投稿があります")
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
                # メッセージ参照が見つからない場合、データベースを直接検索
                try:
                    with self._get_db_connection() as conn:
                        with self._get_cursor(conn) as cursor:
                            # thoughtsテーブルから直接検索
                            cursor.execute('''
                                SELECT id, user_id, is_private
                                FROM thoughts 
                                WHERE CAST(id AS TEXT) = ?
                            ''', (str(message_id),))
                            
                            row = cursor.fetchone()
                            if row:
                                # 投稿は存在するがメッセージ参照がない場合
                                await interaction.followup.send(
                                    "❌ この投稿のメッセージ参照が見つかりません。ボットの再起動によりメッセージが失われた可能性があります。\n"
                                    "投稿IDを指定して削除するか、/restore_messages で古い参照を整理してください。",
                                    ephemeral=True
                                )
                                return
                            else:
                                # 投稿自体が存在しない場合
                                await interaction.followup.send(
                                    "❌ 指定された投稿が見つかりませんでした。",
                                    ephemeral=True
                                )
                                return
                except Exception as e:
                    logger.error(f"データベース検索中にエラーが発生しました: {e}")
                    await interaction.followup.send(
                        "❌ エラーが発生しました。しばらくしてからもう一度お試しください。",
                        ephemeral=True
                    )
                    return
            
            # 管理者権限を確認
            is_admin = interaction.user.guild_permissions.administrator
            
            # 非公開の投稿で、投稿者でも管理者でもない場合はエラー
            if bool(message_data['is_private']) and message_data['user_id'] != interaction.user.id and not is_admin:
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
                # チャンネルまたはスレッドを取得
                try:
                    channel = await interaction.guild.fetch_channel(int(message_data['channel_id']))
                    logger.info(f"チャンネル/スレッドを取得しました: {channel} (type: {type(channel)})")
                except discord.NotFound:
                    logger.warning(f"チャンネルが見つかりません: {message_data['channel_id']}")
                    # データベースからは削除するため、処理を続行
                    await interaction.followup.send(
                        "✅ 投稿を削除しました。（メッセージは既に削除されているか、見つかりませんでした）",
                        ephemeral=True
                    )
                    return
                except discord.HTTPException as e:
                    logger.error(f"チャンネルの取得中にエラーが発生しました: {e}")
                    await interaction.followup.send(
                        "❌ エラーが発生しました。しばらくしてからもう一度お試しください。",
                        ephemeral=True
                    )
                    return
                
                # スレッドの場合はスレッド全体を削除
                if isinstance(channel, discord.Thread):
                    # 権限チェック
                    has_permission = (
                        str(message_data['user_id']) == str(interaction.user.id) or  # 投稿者
                        interaction.user.guild_permissions.administrator or  # 管理者
                        interaction.user.guild_permissions.manage_threads  # スレッド管理権限
                    )
                    
                    if not has_permission:
                        await interaction.followup.send(
                            "❌ このスレッドを削除する権限がありません。",
                            ephemeral=True
                        )
                        return
                    
                    # スレッドを削除
                    try:
                        await channel.delete(reason=f"投稿削除 by {interaction.user}")
                        logger.info(f"スレッド {channel.id} を削除しました")
                        await interaction.followup.send(
                            "✅ 非公開スレッドを削除しました。",
                            ephemeral=True
                        )
                        return
                    except discord.Forbidden:
                        logger.warning(f"スレッドの削除権限がありません: {channel.id}")
                        # 削除できない場合はアーカイブ/ロックでフォールバック
                        try:
                            await channel.edit(archived=True, locked=True)
                            logger.info(f"スレッド {channel.id} をアーカイブ/ロックしました")
                            await interaction.followup.send(
                                "✅ 投稿を削除しました。（スレッドは削除権限がないため、アーカイブ/ロックしました）",
                                ephemeral=True
                            )
                            return
                        except Exception as e:
                            logger.warning(f"スレッドのアーカイブ/ロックにも失敗しました: {e}")
                            await interaction.followup.send(
                                "✅ 投稿を削除しました。（スレッドの削除/非表示化に失敗しました。bot権限を確認してください）",
                                ephemeral=True
                            )
                            return
                    except discord.HTTPException as e:
                        logger.error(f"スレッドの削除中にエラーが発生しました: {e}")
                        await interaction.followup.send(
                            "❌ スレッドの削除中にエラーが発生しました。",
                            ephemeral=True
                        )
                        return
                
                # 通常のメッセージを削除
                try:
                    message = await channel.fetch_message(int(message_data['message_id']))
                    await message.delete()
                    logger.info(f"メッセージ {message.id} を削除しました")
                    await interaction.followup.send(
                        "✅ 投稿を削除しました。",
                        ephemeral=True
                    )
                except discord.NotFound:
                    logger.warning(f"メッセージが見つかりません: {message_data['message_id']}")
                    # メッセージが見つからない場合、データベースから参照を削除
                    try:
                        with self._get_db_connection() as conn:
                            with self._get_cursor(conn) as cursor:
                                cursor.execute("""
                                    DELETE FROM message_references 
                                    WHERE post_id = ?
                                """, (post_id,))
                                conn.commit()
                        logger.info(f"無効なメッセージ参照を削除しました: {post_id}")
                    except Exception as e:
                        logger.error(f"メッセージ参照の削除中にエラーが発生しました: {e}")
                    
                    await interaction.followup.send(
                        "✅ 投稿は既に削除されています。（古いメッセージ参照を整理しました）",
                        ephemeral=True
                    )
                except discord.Forbidden:
                    logger.warning(f"メッセージの削除権限がありません: {message_data['message_id']}")
                    await interaction.followup.send(
                        "❌ メッセージを削除する権限がありません。",
                        ephemeral=True
                    )
            except Exception as e:
                logger.error(f"投稿の削除中にエラーが発生しました: {e}")
                await interaction.followup.send(
                    "❌ 投稿の削除中にエラーが発生しました。",
                    ephemeral=True
                )
                logger.warning(f"メッセージの削除中にエラーが発生しました: {e}")
            
        except Exception as e:
            logger.error(f"削除処理中にエラーが発生しました: {e}", exc_info=True)
            await interaction.followup.send(
                "❌ 削除処理中にエラーが発生しました。しばらくしてからもう一度お試しください。",
                ephemeral=True
            )

async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Delete(bot))
    logger.info("Delete cog が読み込まれました")
