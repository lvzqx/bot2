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

    @tasks.loop(hours=24)  # 24時間ごとに実行（非公開投稿のみ1年後に削除）
    async def cleanup_loop(self):
        try:
            cursor = self.db.cursor()
            one_year_ago = (datetime.utcnow() - timedelta(days=365)).isoformat()
            
            # 1年以上経過した投稿を取得
            cursor.execute('''
                SELECT t.id, t.is_private, t.user_id, mr.message_id, mr.channel_id 
                FROM thoughts t
                LEFT JOIN message_references mr ON t.id = mr.post_id
                WHERE t.created_at < ? AND t.is_private = 1
            ''', (one_year_ago,))
            
            posts = cursor.fetchall()
            
            deleted_count = 0
            for post_id, is_private, user_id, message_id, channel_id in posts:
                try:
                    # メッセージが存在するか確認
                    if message_id and channel_id and not is_private:
                        try:
                            channel = self.bot.get_channel(int(channel_id))
                            if channel:
                                # メッセージが存在するか確認
                                try:
                                    message = await channel.fetch_message(int(message_id))
                                    # メッセージが存在する場合はスキップ
                                    continue
                                except discord.NotFound:
                                    pass  # メッセージが存在しない場合は削除処理を続行
                        except Exception as e:
                            print(f"メッセージ確認エラー (post_id: {post_id}): {e}")
                    
                    # メッセージが存在しないか、非公開の場合は削除
                    cursor.execute('DELETE FROM message_references WHERE post_id = ?', (post_id,))
                    cursor.execute('DELETE FROM thoughts WHERE id = ? AND user_id = ?', (post_id, user_id))
                    deleted_count += 1
                    
                except Exception as e:
                    print(f"投稿のクリーンアップ中にエラーが発生しました (post_id: {post_id}): {e}")
                    self.db.rollback()
                    continue
                    
            if deleted_count > 0:
                self.db.commit()
                print(f"✅ {deleted_count}件の古い投稿をクリーンアップしました")
            else:
                print("✅ クリーンアップの対象となる投稿はありませんでした")
                
        except Exception as e:
            print(f"❌ クリーンアップ中にエラーが発生しました: {e}")
            self.db.rollback()

    @cleanup_loop.before_loop
    async def before_cleanup(self):
        await self.bot.wait_until_ready()
        print("✅ Cleanup task is ready")

async def setup(bot):
    await bot.add_cog(Cleanup(bot))
