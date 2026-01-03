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
            # 投稿の存在確認と情報取得
            cursor = self.bot.db.cursor()
            cursor.execute('''
                SELECT t.user_id, t.is_private, t.id, t.content, 
                       m.message_id, m.channel_id
                FROM thoughts t
                LEFT JOIN message_references m ON t.id = m.post_id
                WHERE t.id = ?
            ''', (post_id,))
            
            post = cursor.fetchone()
            
            if not post:
                await interaction.followup.send("❌ 指定された投稿が見つかりません。")
                return
                
            post_user_id, is_private, post_id, content, message_id, channel_id = post
            
            # 権限チェック（投稿者本人または管理者のみ削除可能）
            is_owner = post_user_id == interaction.user.id
            is_admin = interaction.user.guild_permissions.administrator
            
            if not (is_owner or is_admin):
                await interaction.followup.send("❌ この投稿を削除する権限がありません。")
                return
            
            # 確認メッセージを送信
            confirm_embed = discord.Embed(
                title="⚠️ 本当に削除しますか？",
                description=f"以下の投稿を削除しようとしています。\n```{content[:100]}{'...' if len(content) > 100 else ''}```\n**この操作は元に戻せません。**",
                color=discord.Color.orange()
            )
            
            # 確認ボタンを追加
            class ConfirmDelete(discord.ui.View):
                def __init__(self, original_interaction):
                    super().__init__(timeout=30)
                    self.original_interaction = original_interaction
                    self.value = None
                
                @discord.ui.button(label='削除する', style=discord.ButtonStyle.danger)
                async def confirm(self, button_interaction: discord.Interaction, button: discord.ui.Button):
                    if button_interaction.user.id != self.original_interaction.user.id:
                        return
                    
                    try:
                        # データベースから削除
                        cursor = self.original_interaction.client.db.cursor()
                        cursor.execute('DELETE FROM thoughts WHERE id = ?', (post_id,))
                        
                        # メッセージ参照を削除
                        cursor.execute('DELETE FROM message_references WHERE post_id = ?', (post_id,))
                        self.original_interaction.client.db.commit()
                        
                        # チャンネルメッセージを削除
                        try:
                            if message_id and channel_id:
                                channel = self.original_interaction.client.get_channel(channel_id)
                                if channel:
                                    message = await channel.fetch_message(message_id)
                                    await message.delete()
                        except Exception as e:
                            print(f"メッセージ削除エラー: {e}")
                        
                        embed = discord.Embed(
                            title="🗑️ 投稿を削除しました",
                            description=f"投稿ID: `{post_id}` を削除しました。",
                            color=discord.Color.green()
                        )
                        await button_interaction.response.edit_message(embed=embed, view=None)
                        
                    except Exception as e:
                        print(f"削除エラー: {e}")
                        error_embed = discord.Embed(
                            title="❌ エラー",
                            description="投稿の削除中にエラーが発生しました。",
                            color=discord.Color.red()
                        )
                        await button_interaction.response.edit_message(embed=error_embed, view=None)
                
                @discord.ui.button(label='キャンセル', style=discord.ButtonStyle.secondary)
                async def cancel(self, button_interaction: discord.Interaction, button: discord.ui.Button):
                    if button_interaction.user.id == self.original_interaction.user.id:
                        embed = discord.Embed(
                            title="キャンセルされました",
                            description="投稿の削除をキャンセルしました。",
                            color=discord.Color.blue()
                        )
                        await button_interaction.response.edit_message(embed=embed, view=None)
                
                async def on_timeout(self):
                    # タイムアウト時にボタンを無効化
                    for item in self.children:
                        item.disabled = True
                    try:
                        await self.message.edit(view=self)
                    except:
                        pass
            
            view = ConfirmDelete(interaction)
            view.message = await interaction.followup.send(embed=confirm_embed, view=view, wait=True)
                
        except Exception as e:
            print(f"Error in delete command: {e}")
            await interaction.followup.send("❌ エラーが発生しました。もう一度お試しください。")

async def setup(bot):
    await bot.add_cog(Delete(bot))
