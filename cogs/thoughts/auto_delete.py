import discord
from discord.ext import commands

class AutoDelete(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        # 削除するキーワードのリスト（必要に応じて追加・編集可能）
        self.delete_keywords = [
            '削除して',
            '消して',
            'delete',
            'remove'
        ]
        print("AutoDelete cog が読み込まれました")

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        # ボット自身のメッセージは無視
        if message.author == self.bot.user:
            return
            
        # DMのみを処理
        if not isinstance(message.channel, discord.DMChannel):
            return
            
        # メッセージが削除キーワードを含むかチェック
        content = message.content.lower().strip()
        if any(keyword in content for keyword in self.delete_keywords):
            try:
                # メッセージを編集して「削除済み」に変更
                await message.edit(content="[削除されました]")
                # 編集確認メッセージを送信（5秒後に削除）
                confirm = await message.channel.send("✅ メッセージを編集しました", delete_after=5.0)
            except discord.NotFound:
                # メッセージが既に削除されている場合
                pass
            except discord.Forbidden:
                # メッセージ編集の権限がない場合
                await message.channel.send("❌ メッセージを編集する権限がありません", delete_after=5.0)
            except Exception as e:
                print(f"[ERROR] メッセージ編集処理中にエラー: {e}")
                await message.channel.send("❌ エラーが発生しました", delete_after=5.0)

async def setup(bot):
    await bot.add_cog(AutoDelete(bot))
