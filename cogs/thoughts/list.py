import discord
from discord import app_commands, ui
from discord.ext import commands
from datetime import datetime, timedelta
from .base import BaseCog

class ViewThoughtsModal(ui.Modal, title="つぶやきを表示"):
    count = ui.TextInput(
        label="表示する件数",
        placeholder="1〜25の間で入力してください",
        default="10",
        required=True,
        max_length=2
    )

    async def on_submit(self, interaction: discord.Interaction):
        try:
            await interaction.response.defer(ephemeral=True)
            
            # 入力値の検証
            try:
                limit = max(1, min(25, int(self.count.value)))
            except ValueError:
                await interaction.followup.send(
                    "1〜25の数値を入力してください。",
                    ephemeral=True
                )
                return
            
            # データベースからつぶやきを取得
            async with interaction.client.db.execute('''
                SELECT * FROM thoughts 
                WHERE user_id = ? 
                ORDER BY created_at DESC 
                LIMIT ?
            ''', (interaction.user.id, limit)) as cursor:
                thoughts = await cursor.fetchall()
            
            if not thoughts:
                await interaction.followup.send(
                    "まだつぶやきがありません！ `/post` でつぶやいてみましょう。",
                    ephemeral=True
                )
                return
            
            # 埋め込みメッセージを作成
            embed = discord.Embed(
                title=f"最近のつぶやき (最新{len(thoughts)}件)",
                color=discord.Color.blue()
            )
            
            for thought in thoughts:
                thought_id, _, content, category, image_url, show_name, is_private, created_at = thought
                
                # 表示名を決定
                if show_name:
                    user = interaction.user
                    display_name = f"{user.display_name} (#{thought_id})"
                else:
                    display_name = f"匿名ユーザー (#{thought_id})"
                
                # カテゴリーが空の場合は「カテゴリーなし」を表示
                category_display = category if category else "カテゴリーなし"
                
                # 非公開マークを追加
                is_private_mark = "🔒 " if is_private else ""
                
                # つぶやきを追加
                embed.add_field(
                    name=f"{is_private_mark}つぶやき #{thought_id} - {category_display}",
                    value=f"{content}\n\n*{display_name}*",
                    inline=False
                )
            
            await interaction.followup.send(embed=embed, ephemeral=True)
            
        except Exception as e:
            await interaction.followup.send(
                f"エラーが発生しました: {str(e)}",
                ephemeral=True
            )

class ListCog(BaseCog):
    def __init__(self, bot):
        super().__init__(bot)
    
    @app_commands.command(name="myposts", description="あなたのつぶやき一覧を表示します")
    async def view_my_thoughts(self, interaction: discord.Interaction):
        """保存されたつぶやきを表示するモーダルを開きます"""
        if not await self.check_channel(interaction):
            return
            
        try:
            await interaction.response.send_modal(ViewThoughtsModal())
        except Exception as e:
            if not interaction.response.is_done():
                await interaction.response.send_message(
                    f"エラーが発生しました: {str(e)}",
                    ephemeral=True
                )
            else:
                await interaction.followup.send(
                    f"エラーが発生しました: {str(e)}",
                    ephemeral=True
                )
