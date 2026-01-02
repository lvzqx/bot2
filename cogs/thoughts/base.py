import discord
from discord import app_commands
from discord.ext import commands

class BaseCog(commands.Cog):    
    def __init__(self, bot):
        self.bot = bot
        self.db = bot.db
    
    async def check_channel(self, interaction: discord.Interaction) -> bool:
        """コマンドが許可されたチャンネルで実行されているか確認"""
        if interaction.channel_id != self.bot.allowed_channel_id:
            try:
                channel = self.bot.get_channel(self.bot.allowed_channel_id)
                channel_mention = f"<#{self.bot.allowed_channel_id}>" if channel else "指定のチャンネル"
                await interaction.response.send_message(
                    f"このコマンドは {channel_mention} でのみ使用できます。",
                    ephemeral=True
                )
            except Exception as e:
                print(f"チャンネルチェックエラー: {e}")
            return False
        return True
