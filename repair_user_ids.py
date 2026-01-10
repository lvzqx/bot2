#!/usr/bin/env python3
"""
既存投稿の user_id を修復するスクリプト
Discordメッセージから投稿者情報を取得してデータベースを更新
"""

import sqlite3
import discord
import asyncio
import logging
from typing import Optional

# ログ設定
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class DatabaseRepair:
    def __init__(self, db_path: str, bot_token: str):
        self.db_path = db_path
        self.bot_token = bot_token
        self.bot = None
        
    async def init_bot(self):
        """Discord Botを初期化"""
        intents = discord.Intents.default()
        intents.message_content = True
        intents.guilds = True
        
        self.bot = discord.Client(intents=intents)
        
    def get_db_connection(self):
        """データベース接続を取得"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn
        
    async def get_message_author(self, message_id: str, channel_id: str) -> Optional[int]:
        """Discordメッセージから投稿者IDを取得"""
        try:
            channel = self.bot.get_channel(int(channel_id))
            if not channel:
                try:
                    channel = await self.bot.fetch_channel(int(channel_id))
                except discord.NotFound:
                    logger.warning(f"チャンネルが見つかりません: {channel_id}")
                    return None
                except discord.Forbidden:
                    logger.warning(f"チャンネルへのアクセス権限がありません: {channel_id}")
                    return None
            
            message = await channel.fetch_message(int(message_id))
            return message.author.id
            
        except discord.NotFound:
            logger.warning(f"メッセージが見つかりません: {message_id}")
            return None
        except discord.Forbidden:
            logger.warning(f"メッセージへのアクセス権限がありません: {message_id}")
            return None
        except Exception as e:
            logger.error(f"メッセージ取得エラー: {e}")
            return None
    
    async def repair_user_ids(self):
        """user_idがNULLまたは0の投稿を修復"""
        conn = self.get_db_connection()
        cursor = conn.cursor()
        
        try:
            # 修復が必要な投稿を取得
            cursor.execute('''
                SELECT t.id, t.user_id, mr.message_id, mr.channel_id
                FROM thoughts t
                LEFT JOIN message_references mr ON t.id = mr.post_id
                WHERE t.user_id IS NULL OR t.user_id = 0 OR t.user_id = ''
            ''')
            
            posts_to_repair = cursor.fetchall()
            
            if not posts_to_repair:
                logger.info("修復が必要な投稿はありません")
                return
                
            logger.info(f"修復対象投稿数: {len(posts_to_repair)}")
            
            repaired_count = 0
            failed_count = 0
            
            for post in posts_to_repair:
                post_id = post['id']
                message_id = post['message_id']
                channel_id = post['channel_id']
                
                if not message_id or not channel_id:
                    logger.warning(f"投稿 {post_id} のメッセージ参照がありません")
                    failed_count += 1
                    continue
                
                logger.info(f"投稿 {post_id} の修復を試行中...")
                
                # Discordメッセージから投稿者を取得
                author_id = await self.get_message_author(message_id, channel_id)
                
                if author_id:
                    # データベースを更新
                    cursor.execute(
                        'UPDATE thoughts SET user_id = ? WHERE id = ?',
                        (str(author_id), post_id)
                    )
                    conn.commit()
                    logger.info(f"投稿 {post_id} の user_id を {author_id} に修復しました")
                    repaired_count += 1
                else:
                    logger.warning(f"投稿 {post_id} の修復に失敗しました")
                    failed_count += 1
            
            logger.info(f"修復完了: 成功={repaired_count}, 失敗={failed_count}")
            
        except Exception as e:
            logger.error(f"修復処理中にエラーが発生しました: {e}")
            conn.rollback()
        finally:
            conn.close()
    
    async def run(self):
        """修復処理を実行"""
        await self.init_bot()
        
        @self.bot.event
        async def on_ready():
            logger.info(f"Botがログインしました: {self.bot.user}")
            await self.repair_user_ids()
            await self.bot.close()
        
        await self.bot.start(self.bot_token)

if __name__ == "__main__":
    import os
    from dotenv import load_dotenv
    
    load_dotenv()
    
    db_path = os.getenv("DB_PATH", "database.db")
    bot_token = os.getenv("DISCORD_BOT_TOKEN")
    
    if not bot_token:
        logger.error("DISCORD_BOT_TOKENが設定されていません")
        exit(1)
    
    repair = DatabaseRepair(db_path, bot_token)
    asyncio.run(repair.run())
