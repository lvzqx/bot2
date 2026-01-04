import discord
from discord.ext import commands
import re
import asyncio

class AutoDelete(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        # 削除対象のキーワード（必要に応じて追加・変更可能）
        self.keywords = [
            "削除して",
            "消して",
            "delete",
            "消えろ",
            "消えなさい"
        ]
        # 削除対象のメッセージの有効期限（秒）
        self.max_message_age = 300  # 5分
        print("AutoDelete cog が読み込まれました")

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        # ボット自身のメッセージは無視
        if message.author == self.bot.user:
            return
            
        # メッセージ内容を取得
        content = message.content.strip()
        
        # キーワードが含まれているかチェック
        if not any(keyword in content for keyword in self.keywords):
            return

        try:
            # メッセージIDを抽出（例: "削除して 1234567890" から 1234567890 を抽出）
            match = re.search(r'\b(\d{17,20})\b', content)
            if not match:
                return
                
            message_id = int(match.group(1))
            
            # メッセージを検索して削除
            found = False
            async for msg in message.channel.history(limit=100):
                # 古すぎるメッセージは無視
                if (discord.utils.utcnow() - msg.created_at).total_seconds() > self.max_message_age:
                    continue
                    
                if msg.id == message_id and msg.author == self.bot.user:
                    # 埋め込みメッセージの場合はデータベースからも削除
                    if msg.embeds and msg.embeds[0].footer and 'ID:' in msg.embeds[0].footer.text:
                        try:
                            # 投稿IDを抽出
                            post_id = int(msg.embeds[0].footer.text.split('ID:')[-1].strip())
                            
                            # データベースから削除
                            db = self.bot.get_cog('Post').db if hasattr(self.bot.get_cog('Post'), 'db') else None
                            if db:
                                cursor = db.cursor()
                                cursor.execute('DELETE FROM thoughts WHERE id = ? AND user_id = ?', 
                                            (post_id, message.author.id))
                                cursor.execute('DELETE FROM message_references WHERE post_id = ?', (post_id,))
                                db.commit()
                        except Exception as e:
                            print(f"[ERROR] データベース削除エラー: {e}")
                    
                    # メッセージを削除
                    await msg.delete()
                    
                    # 確認メッセージを送信（5秒後に削除）
                    confirm = await message.channel.send("✅ メッセージを削除しました", delete_after=5.0)
                    
                    # 元のメッセージを削除
                    try:
                        await message.delete()
                    except:
                        pass
                        
                    found = True
                    break
            
            # メッセージが見つからない場合
            if not found:
                not_found = await message.channel.send("❌ 削除対象のメッセージが見つかりませんでした。5分以内のメッセージにのみ有効です。", delete_after=5.0)
                await asyncio.sleep(5)
                try:
                    await message.delete()
                    await not_found.delete()
                except:
                    pass
                    
        except Exception as e:
            print(f"[ERROR] メッセージ削除中にエラー: {e}")
            try:
                error_msg = await message.channel.send("⚠️ エラーが発生しました。もう一度お試しください。", delete_after=5.0)
                await asyncio.sleep(5)
                await message.delete()
                await error_msg.delete()
            except:
                pass

async def setup(bot):
    await bot.add_cog(AutoDelete(bot))
