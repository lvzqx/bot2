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
        try:
            with self._get_db_connection() as conn:
                with self._get_cursor(conn) as cursor:
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
                    
                    if row := cursor.fetchone():
                        return dict(row)
                    return None
        except sqlite3.Error as e:
            logger.error(f"メッセージデータの取得中にエラーが発生しました: {e}")
            return None

    async def _delete_post(self, post_id: int, user_id: int, is_admin: bool = False) -> bool:
        """投稿を削除します"""
        try:
            with self._get_db_connection() as conn:
                with conn:
                    with self._get_cursor(conn) as cursor:
                        # 投稿が存在するか確認
                        cursor.execute('''
                            SELECT user_id FROM thoughts 
                            WHERE id = ?
                        ''', (post_id,))
                        
                        if result := cursor.fetchone():
                            post_owner_id = result[0]
                            # 投稿者または管理者でない場合は削除不可
                            if post_owner_id != user_id and not is_admin:
                                return False
                        else:
                            return False  # 投稿が見つからない
                        
                        # 投稿を削除（外部キー制約により関連するメッセージ参照も削除される）
                        cursor.execute('''
                            DELETE FROM thoughts 
                            WHERE id = ?
                        ''', (post_id,))
                        
                        return cursor.rowcount > 0
        except sqlite3.Error as e:
            logger.error(f"投稿の削除中にエラーが発生しました: {e}")
            return False

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
            success = await self._delete_post(
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
            
            # メッセージを削除
            try:
                channel = interaction.guild.get_channel(int(message_data['channel_id']))
                if channel:
                    message = await channel.fetch_message(int(message_data['message_id']))
                    await message.delete()
            except (discord.NotFound, discord.Forbidden, discord.HTTPException) as e:
                logger.warning(f"メッセージの削除に失敗しました: {e}")
            
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
