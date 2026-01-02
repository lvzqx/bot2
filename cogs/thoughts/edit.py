import discord
from discord import app_commands
from discord.ext import commands
from datetime import datetime

class Edit(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.db = bot.db

    class EditModal(discord.ui.Modal, title='投稿を編集'):
        def __init__(self, bot, post_id, current_content, current_category, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.bot = bot
            self.post_id = post_id
            
            # 現在の内容を設定
            self.content = discord.ui.TextInput(
                label='内容',
                style=discord.TextStyle.paragraph,
                default=current_content,
                required=True,
                max_length=1000
            )
            self.add_item(self.content)
            
            self.category = discord.ui.TextInput(
                label='カテゴリー',
                default=current_category,
                required=True,
                max_length=50
            )
            self.add_item(self.category)
        
        async def on_submit(self, interaction: discord.Interaction):
            await interaction.response.defer(ephemeral=True)
            
            # 権限チェック
            cursor = self.bot.db.cursor()
            cursor.execute('''
                UPDATE thoughts 
                SET content = ?, category = ?, updated_at = ?
                WHERE id = ? AND user_id = ?
            ''', (
                self.content.value,
                self.category.value,
                datetime.now().isoformat(),
                self.post_id,
                interaction.user.id
            ))
            
            self.bot.db.commit()
            
            if cursor.rowcount > 0:
                await interaction.followup.send("投稿を更新しました。")
            else:
                await interaction.followup.send("投稿の更新に失敗しました。")

    @app_commands.command(name="edit", description="投稿を編集します")
    @app_commands.describe(
        post_id="編集する投稿のID",
        field="編集する項目 (content, category)",
        new_value="新しい値"
    )
    async def edit_post(
        self, 
        interaction: discord.Interaction, 
        post_id: int,
        field: str = None,
        new_value: str = None
    ):
        """投稿を編集します（モーダルまたはコマンド引数で）"""
        await interaction.response.defer(ephemeral=True)
        
        # 現在の投稿を取得
        cursor = self.bot.db.cursor()
        cursor.execute('''
            SELECT content, category, user_id 
            FROM thoughts 
            WHERE id = ?
        ''', (post_id,))
        
        post = cursor.fetchone()
        
        if not post:
            await interaction.followup.send("投稿が見つかりません。")
            return
            
        if post[2] != interaction.user.id:
            await interaction.followup.send("この投稿を編集する権限がありません。")
            return
        
        # モーダルで編集
        if field is None or new_value is None:
            modal = self.EditModal(
                bot=self.bot,
                post_id=post_id,
                current_content=post[0],
                current_category=post[1],
                title='投稿を編集'
            )
            await interaction.response.send_modal(modal)
            return
        
        # コマンド引数で編集
        if field.lower() not in ['content', 'category']:
            await interaction.followup.send("無効なフィールドです。'content' または 'category' を指定してください。")
            return
        
        cursor.execute(f'''
            UPDATE thoughts 
            SET {field} = ?, updated_at = ?
            WHERE id = ? AND user_id = ?
        ''', (
            new_value,
            datetime.now().isoformat(),
            post_id,
            interaction.user.id
        ))
        
        self.bot.db.commit()
        
        if cursor.rowcount > 0:
            await interaction.followup.send("投稿を更新しました。")
        else:
            await interaction.followup.send("投稿の更新に失敗しました。")

async def setup(bot):
    await bot.add_cog(Edit(bot))
