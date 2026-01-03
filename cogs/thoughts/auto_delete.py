import discord
from discord.ext import commands
import re

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
        print("AutoDelete cog が読み込まれました")

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        # ボット自身のメッセージは無視
        if message.author == self.bot.user:
            return
            
        # DMのみを処理
        if not isinstance(message.channel, discord.DMChannel):
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
            async for msg in message.channel.history(limit=100):
                if msg.id == message_id and msg.author == self.bot.user:
                    await msg.delete()
                    await message.add_reaction('✅')  # 削除成功を表すリアクション
                    return
                    
            # メッセージが見つからない場合
            await message.add_reaction('❌')
            
        except Exception as e:
            print(f"[ERROR] メッセージ削除中にエラー: {e}")
            try:
                await message.add_reaction('⚠️')  # エラーを表すリアクション
            except:
                pass

async def setup(bot):
    await bot.add_cog(AutoDelete(bot))
