import sqlite3
import discord
from discord.ext import commands
import logging
import os
from dotenv import load_dotenv
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

class MessageRestore(commands.Cog):
    """メッセージ復元用Cog"""
    
    def __init__(self, bot):
        self.bot = bot
        self.db_path = os.getenv('DB_PATH', 'thoughts.db')
    
    @commands.command(name="restore_messages", description="古いメッセージ参照を整理します")
    @commands.has_permissions(administrator=True)
    async def restore_messages(self, ctx):
        """古いメッセージ参照を整理します"""
        try:
            # 7日以上前のメッセージ参照を削除
            seven_days_ago = datetime.now() - timedelta(days=7)
            
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                
                # 削除対象のメッセージ参照を取得
                cursor.execute("""
                    SELECT mr.post_id, mr.message_id, mr.channel_id, t.created_at
                    FROM message_references mr
                    JOIN thoughts t ON mr.post_id = t.id
                    WHERE t.created_at < ?
                    ORDER BY t.created_at DESC
                """, (seven_days_ago.isoformat(),))
                
                old_refs = cursor.fetchall()
                
                if not old_refs:
                    await ctx.send("✅ 整理対象のメッセージ参照はありません。")
                    return
                
                # 古い参照を削除
                cursor.execute("""
                    DELETE FROM message_references 
                    WHERE post_id IN (
                        SELECT post_id FROM thoughts 
                        WHERE created_at < ?
                    )
                """, (seven_days_ago.isoformat(),))
                
                conn.commit()
                
                await ctx.send(f"✅ {len(old_refs)}件の古いメッセージ参照を整理しました。")
                
                # 詳細を表示
                if len(old_refs) <= 10:
                    details = "\n".join([f"• ID: {ref[0]} ({ref[2]})" for ref in old_refs])
                    await ctx.send(f"削除された参照:\n{details}")
                
        except Exception as e:
            logger.error(f"メッセージ整理中にエラーが発生しました: {e}", exc_info=True)
            await ctx.send(f"❌ エラーが発生しました: {e}")

async def setup(bot):
    await bot.add_cog(MessageRestore(bot))