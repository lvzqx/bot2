import discord
from discord.ext import commands
from discord import app_commands
import sqlite3
import logging
from bot import DatabaseMixin

logger = logging.getLogger(__name__)

class UserFix(commands.Cog, DatabaseMixin):
    """投稿者情報修正用Cog"""
    
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        DatabaseMixin.__init__(self)
    
    @app_commands.command(name="assign_user", description="投稿に正しい投稿者を割り当てます")
    @app_commands.default_permissions(administrator=True)
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.describe(post_id="投稿ID", user="割り当てるユーザー")
    async def assign_user(self, interaction: discord.Interaction, post_id: int, user: discord.User):
        """投稿に正しい投稿者を割り当てます"""
        try:
            await interaction.response.defer(ephemeral=True)
            
            with self._get_db_connection() as conn:
                with self._get_cursor(conn) as cursor:
                    # 投稿が存在するか確認
                    cursor.execute('SELECT id, content FROM thoughts WHERE id = ?', (post_id,))
                    post = cursor.fetchone()
                    
                    if not post:
                        await interaction.followup.send(f"❌ 投稿ID {post_id} が見つかりません", ephemeral=True)
                        return
                    
                    # user_idを更新
                    cursor.execute('UPDATE thoughts SET user_id = ? WHERE id = ?', (user.id, post_id))
                    
                    if cursor.rowcount > 0:
                        await interaction.followup.send(
                            f"✅ 投稿ID {post_id} の投稿者を {user.mention} に修正しました",
                            ephemeral=True
                        )
                        logger.info(f"投稿ID {post_id} のuser_idを {user.id} に更新しました")
                    else:
                        await interaction.followup.send("❌ 更新に失敗しました", ephemeral=True)
                        
        except Exception as e:
            logger.error(f"投稿者割り当てエラー: {e}", exc_info=True)
            await interaction.followup.send(f"❌ エラー: {e}", ephemeral=True)
    
    @app_commands.command(name="list_posts_without_user", description="user_idが未設定の投稿一覧を表示します")
    @app_commands.default_permissions(administrator=True)
    @app_commands.checks.has_permissions(administrator=True)
    async def list_posts_without_user(self, interaction: discord.Interaction):
        """user_idが未設定の投稿一覧を表示します"""
        try:
            await interaction.response.defer(ephemeral=True)
            
            with self._get_db_connection() as conn:
                with self._get_cursor(conn) as cursor:
                    cursor.execute('''
                        SELECT id, content, created_at 
                        FROM thoughts 
                        WHERE user_id IS NULL 
                        ORDER BY created_at DESC 
                        LIMIT 20
                    ''')
                    
                    posts = cursor.fetchall()
                    
                    if not posts:
                        await interaction.followup.send("✅ user_idが未設定の投稿はありません", ephemeral=True)
                        return
                    
                    embed = discord.Embed(
                        title="📋 user_id未設定の投稿一覧",
                        description="これらの投稿に正しい投稿者を割り当ててください",
                        color=discord.Color.orange()
                    )
                    
                    for post_id, content, created_at in posts:
                        content_preview = content[:50] + "..." if len(content) > 50 else content
                        embed.add_field(
                            name=f"投稿ID: {post_id}",
                            value=f"{content_preview}\n作成日: {created_at}",
                            inline=False
                        )
                    
                    await interaction.followup.send(embed=embed, ephemeral=True)
                    
        except Exception as e:
            logger.error(f"user_id未設定投稿一覧エラー: {e}", exc_info=True)
            await interaction.followup.send(f"❌ エラー: {e}", ephemeral=True)

async def setup(bot: commands.Bot):
    await bot.add_cog(UserFix(bot))
