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
        
        try:
            # 投稿の存在確認
            cursor = self.bot.db.cursor()
            cursor.execute('SELECT user_id, is_private FROM thoughts WHERE id = ?', (post_id,))
            post = cursor.fetchone()
            
            if not post:
                await interaction.followup.send("❌ 指定された投稿が見つかりません。")
                return
                
            post_user_id, is_private = post
            
            # 権限チェック（投稿者本人または管理者のみ削除可能）
            is_owner = post_user_id == interaction.user.id
            is_admin = interaction.user.guild_permissions.administrator
            
            if not (is_owner or is_admin):
                await interaction.followup.send("❌ この投稿を削除する権限がありません。")
                return
            
            # 削除実行
            cursor.execute('DELETE FROM thoughts WHERE id = ?', (post_id,))
            self.bot.db.commit()
            
            if cursor.rowcount > 0:
                # 削除した投稿の詳細を取得して確認メッセージを送信
                embed = discord.Embed(
                    title="🗑️ 投稿を削除しました",
                    description=f"投稿ID: `{post_id}` を削除しました。",
                    color=discord.Color.green()
                )
                await interaction.followup.send(embed=embed)
            else:
                await interaction.followup.send("❌ 投稿の削除に失敗しました。")
                
        except Exception as e:
            print(f"Error in delete command: {e}")
            await interaction.followup.send("❌ エラーが発生しました。もう一度お試しください。")

async def setup(bot):
    await bot.add_cog(Delete(bot))
