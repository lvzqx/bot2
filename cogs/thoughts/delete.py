import discord
from discord import app_commands
from discord.ext import commands

class Delete(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.db = bot.db

    @app_commands.command(name="delete", description="投稿を削除します")
    @app_commands.describe(post_id="削除する投稿のID")
    async def delete_post(self, interaction: discord.Interaction, post_id: int):
        """指定したIDの投稿を削除します"""
        await interaction.response.defer(ephemeral=True)
        
        # 投稿の存在確認と権限チェック
        cursor = self.bot.db.cursor()
        cursor.execute('''
            SELECT user_id FROM thoughts 
            WHERE id = ? AND (user_id = ? OR ? IN (SELECT id FROM users WHERE is_admin = 1))
        ''', (post_id, interaction.user.id, interaction.user.id))
        
        if not cursor.fetchone():
            await interaction.followup.send("投稿が見つからないか、削除する権限がありません。")
            return
        
        # 削除実行
        cursor.execute('DELETE FROM thoughts WHERE id = ?', (post_id,))
        self.bot.db.commit()
        
        if cursor.rowcount > 0:
            await interaction.followup.send("投稿を削除しました。")
        else:
            await interaction.followup.send("投稿の削除に失敗しました。")

async def setup(bot):
    await bot.add_cog(Delete(bot))
