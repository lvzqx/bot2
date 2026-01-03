import asyncio
from datetime import datetime, timedelta
import discord
from discord.ext import commands, tasks

class Cleanup(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.db = bot.db
        self.cleanup_loop.start()
        print("✅ Cleanup cog loaded")

    def cog_unload(self):
        self.cleanup_loop.cancel()

    @tasks.loop(hours=24)  # 24時間ごとに実行
    async def cleanup_loop(self):
        try:
            # 30日以上経過した投稿を削除
            cursor = self.db.cursor()
            thirty_days_ago = (datetime.utcnow() - timedelta(days=30)).isoformat()
            
            # 削除対象のメッセージIDを取得
            cursor.execute('''
                SELECT id FROM thoughts 
                WHERE created_at < ? 
                LIMIT 1000
            ''', (thirty_days_ago,))
            
            post_ids = cursor.fetchall()
            
            if post_ids:
                # メッセージ参照を削除
                cursor.executemany('''
                    DELETE FROM message_references 
                    WHERE post_id = ?
                ''', [(post_id[0],) for post_id in post_ids])
                
                # 投稿を削除
                cursor.executemany('''
                    DELETE FROM thoughts 
                    WHERE id = ?
                ''', [(post_id[0],) for post_id in post_ids])
                
                self.db.commit()
                print(f"✅ Cleaned up {len(post_ids)} old posts")
                
        except Exception as e:
            print(f"❌ Cleanup error: {e}")
            self.db.rollback()

    @cleanup_loop.before_loop
    async def before_cleanup(self):
        await self.bot.wait_until_ready()
        print("✅ Cleanup task is ready")

async def setup(bot):
    await bot.add_cog(Cleanup(bot))
