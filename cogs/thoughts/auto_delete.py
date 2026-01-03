import discord
from discord.ext import commands
import re

class AutoDelete(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        # 削除対象のキーワード（必要に応じて変更可能）
        self.delete_keywords = [
            '消して',
            '削除',
            '消えて',
            'delete',
            'remove',
            '消す'
        ]
        # 削除対象の正規表現パターン
        self.pattern = re.compile('|'.join(map(re.escape, self.delete_keywords)), re.IGNORECASE)
        print("✅ AutoDelete cog loaded")

    @commands.Cog.listener()
    async def on_message(self, message):
        # ボット自身のメッセージは無視
        if message.author == self.bot.user:
            return
            
        # DMの場合のみ処理
        if not isinstance(message.channel, discord.DMChannel):
            return
            
        # メッセージの内容をチェック
        if self.pattern.search(message.content):
            try:
                # ボットが送信したメッセージを取得（直近20件）
                async for msg in message.channel.history(limit=20):
                    if msg.author == self.bot.user:
                        try:
                            await msg.delete()
                        except:
                            continue
                
                # 確認メッセージを送信（すぐに削除）
                confirm = await message.channel.send("✅ メッセージを削除しました", delete_after=3)
                
            except Exception as e:
                print(f"[ERROR] メッセージ削除中にエラーが発生: {e}")
                try:
                    await message.channel.send("❌ メッセージの削除中にエラーが発生しました", delete_after=5)
                except:
                    pass

async def setup(bot):
    await bot.add_cog(AutoDelete(bot))
