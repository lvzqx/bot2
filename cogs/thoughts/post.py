import discord
from discord import app_commands
from discord.ext import commands
from datetime import datetime
from .base import BaseCog

class ThoughtModal(discord.ui.Modal, title="つぶやきを投稿"):
    content = discord.ui.TextInput(
        label="つぶやく内容",
        style=discord.TextStyle.paragraph,
        placeholder="つぶやきたいことを自由に入力してください...",
        required=True,
        max_length=2000
    )
    
    category = discord.ui.TextInput(
        label="カテゴリー",
        placeholder="例: 独り言, 愚痴, アイデア, 日記",
        required=True,
        max_length=50
    )
    
    image_url = discord.ui.TextInput(
        label="画像URL（任意）",
        placeholder="https://example.com/image.jpg",
        required=False
    )
    
    show_name = discord.ui.TextInput(
        label="名前を表示しますか？（はい/いいえ）",
        placeholder="はい または いいえ",
        default="はい",
        required=True,
        max_length=3
    )
    
    is_private = discord.ui.TextInput(
        label="非公開にしますか？（はい/いいえ）",
        placeholder="はい または いいえ",
        default="いいえ",
        required=True,
        max_length=3
    )

    async def on_submit(self, interaction: discord.Interaction):
        try:
            # 入力の処理
            show_name = self.show_name.value.lower() in ['はい', 'yes', 'y', 'true']
            is_private = self.is_private.value.lower() in ['はい', 'yes', 'y', 'true']
            
            # データベースに保存
            async with interaction.client.db.execute('''
                INSERT INTO thoughts (user_id, content, category, image_url, show_name, is_private, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (
                interaction.user.id,
                self.content.value,
                self.category.value,
                self.image_url.value if self.image_url.value else None,
                show_name,
                is_private,
                datetime.utcnow()
            )) as cursor:
                thought_id = cursor.lastrowid
                await interaction.client.db.commit()
            
            # 非公開の場合はDMに送信
            if is_private:
                try:
                    embed = discord.Embed(
                        title=f"メモ #{thought_id} - {self.category.value} 🔒",
                        description=self.content.value,
                        color=discord.Color.blue()
                    )
                    if self.image_url.value:
                        embed.set_image(url=self.image_url.value)
                    
                    await interaction.user.send(embed=embed)
                    await interaction.response.send_message(
                        "✅ 非公開のメモを保存しました！",
                        ephemeral=True
                    )
                except discord.Forbidden:
                    await interaction.followup.send(
                        "⚠️ DMを送信できませんでした。プライバシー設定を確認してください。",
                        ephemeral=True
                    )
                return
            
            # 公開の場合はチャンネルに投稿
            embed = discord.Embed(
                title=f"メモ #{thought_id} - {self.category.value}",
                description=self.content.value,
                color=discord.Color.blue(),
                timestamp=datetime.utcnow()
            )
            
            if not show_name:
                embed.set_author(name="匿名ユーザー")
            else:
                embed.set_author(
                    name=interaction.user.display_name,
                    icon_url=interaction.user.display_avatar.url
                )
            
            if self.image_url.value:
                embed.set_image(url=self.image_url.value)
            
            await interaction.response.send_message(embed=embed)
            
        except Exception as e:
            await interaction.response.send_message(
                f"エラーが発生しました: {str(e)}",
                ephemeral=True
            )

class PostCog(BaseCog):
    def __init__(self, bot):
        super().__init__(bot)
    
    @app_commands.command(name="post", description="つぶやきを投稿します")
    async def post_thought(self, interaction: discord.Interaction):
        """つぶやき投稿用のモーダルを開きます"""
        if not await self.check_channel(interaction):
            return
            
        try:
            await interaction.response.send_modal(ThoughtModal())
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
