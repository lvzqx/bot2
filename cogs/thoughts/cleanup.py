from __future__ import annotations

import asyncio
import contextlib
import logging
from datetime import datetime, timedelta
from typing import List, Tuple, Optional, Dict, Any

import discord
from discord import Message, TextChannel, DMChannel
from discord.ext import commands, tasks

# ロガーの設定
logger = logging.getLogger(__name__)

# 型定義
class PostInfo:
    """投稿情報を表すデータクラス"""
    __slots__ = ('post_id', 'is_private', 'user_id', 'message_id', 'channel_id')
    
    def __init__(
        self, 
        post_id: int, 
        is_private: bool, 
        user_id: int, 
        message_id: Optional[str] = None, 
        channel_id: Optional[str] = None
    ) -> None:
        self.post_id = post_id
        self.is_private = bool(is_private)
        self.user_id = user_id
        self.message_id = message_id
        self.channel_id = channel_id

class Cleanup(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        """クリーンアップ機能を初期化します。
        
        Args:
            bot: Discord Bot インスタンス
        """
        self.bot = bot
        self._init_db()
        self.cleanup_loop.start()
        logger.info("Cleanup cog が初期化されました")
    
    def _init_db(self) -> None:
        """データベースを初期化します。"""
        with self._get_db_connection() as conn:
            with self._get_cursor(conn) as cursor:
                # パフォーマンス向上のためのPRAGMA設定
                cursor.execute('''
                    PRAGMA journal_mode=WAL;
                    PRAGMA synchronous=NORMAL;
                    PRAGMA foreign_keys=ON;
                ''')
                conn.commit()
    
    @contextlib.contextmanager
    def _get_db_connection(self) -> sqlite3.Connection:
        """データベース接続を取得するコンテキストマネージャー
        
        Yields:
            sqlite3.Connection: データベース接続オブジェクト
            
        Raises:
            sqlite3.Error: データベース接続に失敗した場合
        """
        conn = None
        try:
            conn = sqlite3.connect('thoughts.db')
            conn.row_factory = sqlite3.Row
            yield conn
        except sqlite3.Error as e:
            logger.error(f"データベース接続エラー: {e}", exc_info=True)
            raise
        finally:
            if conn is not None:
                conn.close()
    
    @contextlib.contextmanager
    def _get_cursor(self, conn: sqlite3.Connection) -> sqlite3.Cursor:
        """データベースカーソルを取得するコンテキストマネージャー
        
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

    def cog_unload(self) -> None:
        """コグがアンロードされる際に実行される処理"""
        self.cleanup_loop.cancel()
        logger.info("Cleanup cog がアンロードされました")

    @tasks.loop(hours=24)  # 24時間ごとに実行
    async def cleanup_loop(self) -> None:
        """定期的に古い投稿をクリーンアップします。"""
        try:
            logger.info("定期的なクリーンアップを開始します")
            
            # 1年以上前の非公開投稿を削除
            deleted_count = await self._cleanup_old_private_posts(days=365)
            
            # メッセージ参照が存在しない投稿を削除
            deleted_count += await self._cleanup_orphaned_posts()
            
            if deleted_count > 0:
                logger.info(f"合計 {deleted_count} 件の古い投稿をクリーンアップしました")
            else:
                logger.info("クリーンアップの対象となる投稿はありませんでした")
                
        except Exception as e:
            logger.error(f"クリーンアップ中にエラーが発生しました: {e}", exc_info=True)
    
    async def _cleanup_old_private_posts(self, days: int = 365) -> int:
        """指定日数以上経過した非公開投稿を削除します。
        
        Args:
            days: 削除対象となる投稿の経過日数
            
        Returns:
            int: 削除した投稿の数
        """
        deleted_count = 0
        cutoff_date = (datetime.utcnow() - timedelta(days=days)).isoformat()
        
        try:
            with self._get_db_connection() as conn:
                with conn:
                    with self._get_cursor(conn) as cursor:
                        # 古い非公開投稿を取得
                        cursor.execute('''
                            SELECT t.id, t.user_id, mr.message_id, mr.channel_id
                            FROM thoughts t
                            LEFT JOIN message_references mr ON t.id = mr.post_id
                            WHERE t.created_at < ? AND t.is_private = 1
                        ''', (cutoff_date,))
                        
                        posts = [
                            PostInfo(
                                post_id=row['id'],
                                is_private=True,
                                user_id=row['user_id'],
                                message_id=row.get('message_id'),
                                channel_id=row.get('channel_id')
                            )
                            for row in cursor.fetchall()
                        ]
                        
                        # 各投稿を処理
                        for post in posts:
                            try:
                                # メッセージが存在する場合はスキップ
                                if post.message_id and post.channel_id:
                                    channel = self.bot.get_channel(int(post.channel_id))
                                    if channel and await self._message_exists(channel, post.message_id):
                                        continue
                                
                                # 投稿を削除
                                await self._delete_post(conn, post)
                                deleted_count += 1
                                
                            except Exception as e:
                                logger.error(
                                    f"投稿の削除中にエラーが発生しました (post_id: {post.post_id}): {e}",
                                    exc_info=True
                                )
                                continue
        
        except sqlite3.Error as e:
            logger.error(f"データベースエラー: {e}", exc_info=True)
            raise
        
        return deleted_count
    
    async def _cleanup_orphaned_posts(self) -> int:
        """メッセージ参照が存在しない投稿を削除します。
        
        Returns:
            int: 削除した投稿の数
        """
        try:
            with self._get_db_connection() as conn:
                with conn:
                    with self._get_cursor(conn) as cursor:
                        # メッセージ参照が存在しない投稿を削除
                        cursor.execute('''
                            DELETE FROM thoughts 
                            WHERE id NOT IN (
                                SELECT DISTINCT post_id 
                                FROM message_references 
                                WHERE post_id IS NOT NULL
                            )
                        ''')
                        return cursor.rowcount
                        
        except sqlite3.Error as e:
            logger.error(f"孤立した投稿の削除中にエラーが発生しました: {e}", exc_info=True)
            return 0
    
    async def _message_exists(self, channel: TextChannel, message_id: str) -> bool:
        """指定されたメッセージが存在するか確認します。
        
        Args:
            channel: メッセージが存在するチャンネル
            message_id: 確認するメッセージのID
            
        Returns:
            bool: メッセージが存在する場合はTrue、それ以外はFalse
        """
        try:
            message = await channel.fetch_message(int(message_id))
            return message is not None
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            return False
    
    async def _delete_post(self, conn: sqlite3.Connection, post: PostInfo) -> None:
        """投稿を削除します。
        
        Args:
            conn: データベース接続
            post: 削除する投稿情報
        """
        with self._get_cursor(conn) as cursor:
            # 外部キー制約により、message_references からも削除される
            cursor.execute('''
                DELETE FROM thoughts 
                WHERE id = ? AND user_id = ?
            ''', (post.post_id, post.user_id))
    
    @cleanup_loop.before_loop
    async def before_cleanup(self) -> None:
        """クリーンアップタスクの前処理を実行します。"""
        await self.bot.wait_until_ready()
        logger.info("クリーンアップタスクの準備が完了しました")

async def setup(bot):
    await bot.add_cog(Cleanup(bot))
