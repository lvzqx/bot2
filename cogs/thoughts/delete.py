import discord
from discord import app_commands
from discord.ext import commands
import sqlite3
import traceback
import logging
import re
from typing import Tuple, Dict, Any, Optional, Union, List
from contextlib import contextmanager

# ロガーの設定
logger = logging.getLogger(__name__)

# 型定義
class MessageData:
    def __init__(self, message_id: int, channel_id: int, post_id: int):
        self.id = message_id
        self.channel_id = channel_id
        self.post_id = post_id

class PostData:
    def __init__(self, post_id: int, user_id: int, content: str, category: str, 
                 is_anonymous: bool, is_private: bool, display_name: Optional[str] = None):
        self.id = post_id
        self.user_id = user_id
        self.content = content
        self.category = category
        self.is_anonymous = is_anonymous
        self.is_private = is_private
        self.display_name = display_name

class Delete(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self._init_db()
        logger.info("Delete cog が初期化されました")
    
    def _init_db(self) -> None:
        """データベースの初期化"""
        with self._get_db_connection() as conn:
            # パフォーマンス向上のためのPRAGMA設定
            conn.execute('''
                PRAGMA journal_mode=WAL;
                PRAGMA synchronous=NORMAL;
                PRAGMA foreign_keys=ON;
            ''')
            
            # テーブルが存在するか確認し、なければ作成
            with self._get_cursor(conn) as cursor:
                # thoughts テーブル
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS thoughts (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        user_id INTEGER NOT NULL,
                        content TEXT NOT NULL,
                        category TEXT,
                        image_url TEXT,
                        is_anonymous BOOLEAN DEFAULT 0,
                        is_private BOOLEAN DEFAULT 0,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        display_name TEXT,
                        UNIQUE(id, user_id)
                    )
                ''')
                
                # message_references テーブル（messagesからリネーム）
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS message_references (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        channel_id TEXT NOT NULL,
                        message_id TEXT NOT NULL UNIQUE,
                        post_id INTEGER NOT NULL,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        FOREIGN KEY (post_id) REFERENCES thoughts (id) ON DELETE CASCADE
                    )
                ''')
                
                # インデックスを作成
                cursor.execute('''
                    CREATE INDEX IF NOT EXISTS idx_message_references_post_id 
                    ON message_references(post_id);
                ''')
                
                cursor.execute('''
                    CREATE INDEX IF NOT EXISTS idx_message_references_message_id 
                    ON message_references(message_id);
                ''')
                
                # attachments テーブル
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS attachments (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        post_id INTEGER NOT NULL,
                        url TEXT NOT NULL,
                        FOREIGN KEY (post_id) REFERENCES thoughts (id) ON DELETE CASCADE
                    )
                ''')
                
                # インデックスを作成
                cursor.execute('''
                    CREATE INDEX IF NOT EXISTS idx_attachments_post_id 
                    ON attachments(post_id);
                ''')
                
                conn.commit()
                logger.info("データベーステーブルの初期化が完了しました")
    
    @contextmanager
    def _get_db_connection(self) -> sqlite3.Connection:
        """データベース接続を取得するコンテキストマネージャー
        
        Yields:
            sqlite3.Connection: データベース接続オブジェクト
        """
        conn = sqlite3.connect(self.bot.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        except sqlite3.Error as e:
            logger.error(f"Database error: {e}", exc_info=True)
            conn.rollback()
            raise
        finally:
            conn.close()
    
    @contextmanager
    def _get_cursor(self, conn: sqlite3.Connection) -> sqlite3.Cursor:
        """カーソルを取得するコンテキストマネージャー
        
        Args:
            conn: データベース接続オブジェクト
            
        Yields:
            sqlite3.Cursor: データベースカーソル
        """
        cursor = conn.cursor()
        try:
            yield cursor
        finally:
            cursor.close()

    async def _get_message_data(self, message_id: int) -> Optional[MessageData]:
        """メッセージIDからメッセージデータを取得します。
        
        Args:
            message_id: メッセージID
            
        Returns:
            Optional[MessageData]: メッセージデータ、見つからない場合はNone
        """
        try:
            with self._get_db_connection() as conn:
                with self._get_cursor(conn) as cursor:
                    cursor.execute('''
                        SELECT message_id, channel_id, post_id 
                        FROM message_references 
                        WHERE message_id = ?
                    ''', (str(message_id),))
                    
                    if row := cursor.fetchone():
                        return MessageData(
                            message_id=int(row['message_id']),
                            channel_id=int(row['channel_id']),
                            post_id=row['post_id']
                        )
                    return None
                    
        except sqlite3.Error as e:
            logger.error(f"Failed to get message data for ID {message_id}: {e}", exc_info=True)
            return None
    
    async def _get_post_data(self, post_id: int, user_id: int) -> Optional[PostData]:
        """投稿データを取得します。
        
        Args:
            post_id: 投稿ID
            user_id: ユーザーID（認証用）
            
        Returns:
            Optional[PostData]: 投稿データ、見つからないか権限がない場合はNone
        """
        try:
            with self._get_db_connection() as conn:
                with self._get_cursor(conn) as cursor:
                    cursor.execute('''
                        SELECT id, user_id, content, category, is_anonymous, is_private, display_name
                        FROM thoughts 
                        WHERE id = ? AND user_id = ?
                    ''', (post_id, user_id))
                    
                    if row := cursor.fetchone():
                        return PostData(
                            post_id=row['id'],
                            user_id=row['user_id'],
                            content=row['content'],
                            category=row['category'],
                            is_anonymous=bool(row['is_anonymous']),
                            is_private=bool(row['is_private']),
                            display_name=row['display_name']
                        )
                    return None
                    
        except sqlite3.Error as e:
            logger.error(f"Failed to get post data for ID {post_id}: {e}", exc_info=True)
            return None
    
    async def _delete_post(self, post_id: int, user_id: int) -> bool:
        """投稿を削除します。
        
        Args:
            post_id: 削除する投稿のID
            user_id: 削除をリクエストしたユーザーのID
            
        Returns:
            bool: 削除に成功したかどうか
        """
        try:
            with self._get_db_connection() as conn:
                with conn:
                    with self._get_cursor(conn) as cursor:
                        # 投稿が存在し、ユーザーが所有者であることを確認
                        cursor.execute('''
                            SELECT 1 FROM thoughts 
                            WHERE id = ? AND user_id = ?
                        ''', (post_id, user_id))
                        
                        if not cursor.fetchone():
                            return False
                        
                        # 投稿を削除（外部キー制約により関連するメッセージ参照も削除される）
                        cursor.execute('''
                            DELETE FROM thoughts 
                            WHERE id = ?
                        ''', (post_id,))
                        
                        return cursor.rowcount > 0
                        
        except sqlite3.Error as e:
            logger.error(f"Failed to delete post {post_id}: {e}", exc_info=True)
            return False
    
    async def delete_message_by_id(
        self, 
        interaction: discord.Interaction, 
        message_id: int
    ) -> Tuple[bool, str]:
        """メッセージIDで投稿を削除します。
        
        Args:
            interaction: Discordインタラクション
            message_id: 削除するメッセージのID
            
        Returns:
            Tuple[bool, str]: (成功可否, メッセージ)
        """
        try:
            # メッセージデータを取得
            message_data = await self._get_message_data(message_id)
            if not message_data:
                return False, "❌ メッセージが見つかりませんでした。"
            
            # メッセージを取得
            try:
                channel = interaction.guild.get_channel(message_data.channel_id) if interaction.guild else None
                if not channel:
                    channel = await self.bot.fetch_channel(message_data.channel_id)
                
                message = await channel.fetch_message(message_data.message_id)
                
                # ボットのメッセージか確認
                if message.author != self.bot.user:
                    return False, "❌ ボットのメッセージのみ削除できます"
                    
                # 埋め込みメッセージか確認
                if not message.embeds or not message.embeds[0].footer:
                    return False, "❌ 投稿メッセージを削除できません"
                
            except discord.NotFound:
                # メッセージが既に削除されている場合はデータベースから削除を続行
                logger.info(f"Message {message_id} not found, but will continue with database cleanup")
            except discord.Forbidden:
                return False, "❌ メッセージを削除する権限がありません"
            except discord.HTTPException as e:
                logger.error(f"Failed to fetch message {message_id}: {e}")
                return False, f"❌ メッセージの取得中にエラーが発生しました: {e}"
            
            # 投稿を削除
            user_id = interaction.user.id
            success = await self._delete_post(message_data.post_id, user_id)
            
            if not success:
                return False, "❌ 投稿の削除に失敗しました。権限がないか、既に削除されています。"
            
            # メッセージが存在する場合は削除を試みる
            try:
                if 'message' in locals():
                    await message.delete()
            except discord.HTTPException as e:
                logger.warning(f"Failed to delete message {message_id}: {e}")
                # データベースからの削除は成功しているので、エラーを無視して続行
            
            return True, f"✅ 投稿 (ID: {message_data.post_id}) を削除しました"
            
        except Exception as e:
            error_msg = f"❌ エラーが発生しました: {type(e).__name__}: {str(e)}"
            logger.error(error_msg, exc_info=True)
            return False, error_msg

    async def _process_delete(
        self, 
        interaction: discord.Interaction, 
        message_id: str
    ) -> None:
        """削除処理を実行し、結果をユーザーに通知します。
        
        Args:
            interaction: Discordインタラクション
            message_id: 削除するメッセージのID（文字列）
        """
        try:
            # メッセージIDを数値に変換
            try:
                message_id_int = int(message_id)
            except ValueError:
                await interaction.response.send_message(
                    "❌ 無効なメッセージIDです。数値を入力してください。", 
                    ephemeral=True
                )
                return
            
            # DMの場合はdelete_dmに処理を委譲
            if isinstance(interaction.channel, discord.DMChannel):
                from .delete_dm import DeleteDM
                delete_dm_cog = DeleteDM(self.bot)
                success, result = await delete_dm_cog.delete_message_by_id(
                    interaction=interaction,
                    message_id=message_id_int,
                    user_id=interaction.user.id
                )
                
                if success:
                    await interaction.response.send_message(result, ephemeral=True)
                else:
                    await interaction.response.send_message(result, ephemeral=True)
                return
                
            # サーバー内の処理
            await interaction.response.defer(ephemeral=True)
            success, result = await self.delete_message_by_id(interaction, message_id_int)
            await interaction.followup.send(result, ephemeral=True)
            
        except Exception as e:
            error_msg = f"❌ 予期せぬエラーが発生しました: {type(e).__name__}: {str(e)}"
            logger.error(error_msg, exc_info=True)
            
            if not interaction.response.is_done():
                await interaction.response.send_message(error_msg, ephemeral=True)
            else:
                await interaction.followup.send(error_msg, ephemeral=True)
    
    @app_commands.command(name="delete", description="メッセージIDで投稿を削除します")
    @app_commands.describe(message_id="削除するメッセージのID")
    async def delete(self, interaction: discord.Interaction, message_id: str):
        """メッセージIDで投稿を削除します（DMでも使用可能）"""
        await self._process_delete(interaction, message_id)

async def setup(bot):
    await bot.add_cog(Delete(bot))
