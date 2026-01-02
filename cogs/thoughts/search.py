import discord
from discord import app_commands
from discord.ext import commands
from datetime import datetime

class Search(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.db = bot.db

    @app_commands.command(name="search", description="投稿を検索します")
    @app_commands.describe(
        keyword="検索キーワード",
        category="カテゴリーで絞り込み",
        limit="表示する件数 (デフォルト: 10)",
        user_id="ユーザーIDで絞り込み (任意)"
    )
    async def search_posts(
        self,
        interaction: discord.Interaction,
        keyword: str = None,
        category: str = None,
        limit: int = 10,
        user_id: str = None
    ):
        """投稿を検索します"""
        await interaction.response.defer()
        
        # クエリの構築
        query = """
            SELECT 
                t.id, t.content, t.category, t.created_at, 
                t.display_name, t.user_id, t.is_anonymous, t.is_private
            FROM thoughts t
            WHERE 1=1
        """
        params = []
        
        # キーワード検索
        if keyword:
            query += " AND (t.content LIKE ? OR t.category LIKE ?)"
            params.extend([f'%{keyword}%', f'%{keyword}%'])
        
        # カテゴリー検索
        if category:
            query += " AND t.category = ?"
            params.append(category)
        
        # ユーザーIDで絞り込み
        if user_id and user_id.isdigit():
            query += " AND t.user_id = ?"
            params.append(int(user_id))
        
        # 非公開の投稿は自分のものだけ表示
        query += " AND (t.is_private = 0 OR t.user_id = ?)"
        params.append(interaction.user.id)
        
        # ソートとリミット
        query += " ORDER BY t.created_at DESC LIMIT ?"
        params.append(min(limit, 25))  # 最大25件まで
        
        # クエリ実行
        cursor = self.bot.db.cursor()
        cursor.execute(query, params)
        posts = cursor.fetchall()
        
        if not posts:
            await interaction.followup.send("該当する投稿が見つかりませんでした。")
            return
        
        # 結果を表示
        embeds = []
        for post in posts:
            post_id, content, category, created_at, display_name, post_user_id, is_anonymous, is_private = post
            created_at_dt = datetime.fromisoformat(created_at)
            created_at_str = created_at_dt.strftime('%Y-%m-%d %H:%M')
            
            # 投稿者情報を設定
            author_name = "匿名" if is_anonymous else (display_name or "不明")
            
            # 投稿カード風の埋め込みメッセージを作成
            embed = discord.Embed(
                description=content,
                color=discord.Color.blue(),
                timestamp=created_at_dt
            )
            
            # 投稿者情報を設定（アバター付き）
            if not is_anonymous:
                user = await interaction.guild.fetch_member(post_user_id)
                if user:
                    embed.set_author(
                        name=author_name,
                        icon_url=str(user.display_avatar.url)
                    )
            else:
                embed.set_author(name=author_name)
            
            # フッターに投稿日時とカテゴリーを表示
            footer_text = f"カテゴリー: {category} | {created_at_str}"
            if is_private:
                footer_text += " | 🔒 非公開"
            embed.set_footer(text=footer_text)
            
            # 画像が添付されている場合
            cursor.execute("SELECT image_url FROM thoughts WHERE id = ?", (post_id,))
            image_url = cursor.fetchone()[0]
            if image_url:
                embed.set_image(url=image_url)
            
            # 自分の投稿の場合は編集・削除ボタンを追加
            if post_user_id == interaction.user.id:
                view = discord.ui.View()
                view.add_item(EditButton(post_id))
                view.add_item(DeleteButton(post_id))
                embeds.append((embed, view))
            else:
                embeds.append((embed, None))
        
        # 結果を送信
        if not embeds:
            await interaction.followup.send("表示できる投稿がありません。")
            return
        
        # 最初の投稿を表示
        embed, view = embeds[0]
        message = await interaction.followup.send(embed=embed, view=view)
        
        # 複数ある場合はページネーションを追加
        if len(embeds) > 1:
            await message.edit(view=SearchPaginationView(embeds, 0, message))

class EditButton(discord.ui.Button):
    def __init__(self, post_id):
        super().__init__(label='編集', style=discord.ButtonStyle.primary, custom_id=f'edit_{post_id}')
        self.post_id = post_id
    
    async def callback(self, interaction: discord.Interaction):
        # 編集モーダルを表示
        modal = EditModal(self.post_id, interaction.client)
        await interaction.response.send_modal(modal)

class DeleteButton(discord.ui.Button):
    def __init__(self, post_id):
        super().__init__(label='削除', style=discord.ButtonStyle.danger, custom_id=f'delete_{post_id}')
        self.post_id = post_id
    
    async def callback(self, interaction: discord.Interaction):
        # 確認用のビューを作成
        view = discord.ui.View()
        view.add_item(ConfirmDeleteButton(self.post_id, interaction.client))
        view.add_item(CancelButton())
        
        await interaction.response.send_message(
            "本当にこの投稿を削除しますか？この操作は元に戻せません。",
            view=view,
            ephemeral=True
        )

class ConfirmDeleteButton(discord.ui.Button):
    def __init__(self, post_id, bot):
        super().__init__(label='削除する', style=discord.ButtonStyle.danger)
        self.post_id = post_id
        self.bot = bot
    
    async def callback(self, interaction: discord.Interaction):
        # 投稿を削除
        cursor = self.bot.db.cursor()
        cursor.execute("DELETE FROM thoughts WHERE id = ? AND user_id = ?", 
                      (self.post_id, interaction.user.id))
        self.bot.db.commit()
        
        if cursor.rowcount > 0:
            await interaction.response.edit_message(
                content="投稿を削除しました。",
                view=None,
                embed=None
            )
        else:
            await interaction.response.edit_message(
                content="投稿の削除に失敗しました。",
                view=None,
                embed=None
            )

class CancelButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label='キャンセル', style=discord.ButtonStyle.secondary)
    
    async def callback(self, interaction: discord.Interaction):
        await interaction.response.edit_message(
            content="削除をキャンセルしました。",
            view=None,
            embed=None
        )

class EditModal(discord.ui.Modal, title='投稿を編集'):
    def __init__(self, post_id, bot):
        super().__init__()
        self.post_id = post_id
        self.bot = bot
        
        # 既存の投稿内容を取得
        cursor = bot.db.cursor()
        cursor.execute("SELECT content, category, image_url FROM thoughts WHERE id = ?", (post_id,))
        content, category, image_url = cursor.fetchone()
        
        # フォームフィールドを追加
        self.content = discord.ui.TextInput(
            label='内容',
            style=discord.TextStyle.paragraph,
            default=content,
            required=True,
            max_length=1000
        )
        
        self.category = discord.ui.TextInput(
            label='カテゴリー',
            default=category,
            required=True,
            max_length=50
        )
        
        self.image_url = discord.ui.TextInput(
            label='画像URL (変更する場合のみ入力)',
            default=image_url or '',
            required=False
        )
        
        self.add_item(self.content)
        self.add_item(self.category)
        self.add_item(self.image_url)
    
    async def on_submit(self, interaction: discord.Interaction):
        # 投稿を更新
        cursor = self.bot.db.cursor()
        cursor.execute('''
            UPDATE thoughts 
            SET content = ?, category = ?, image_url = ?
            WHERE id = ? AND user_id = ?
        ''', (
            self.content.value,
            self.category.value,
            self.image_url.value if self.image_url.value else None,
            self.post_id,
            interaction.user.id
        ))
        
        if cursor.rowcount > 0:
            self.bot.db.commit()
            await interaction.response.send_message("投稿を更新しました。", ephemeral=True)
        else:
            await interaction.response.send_message("投稿の更新に失敗しました。", ephemeral=True)

class SearchPaginationView(discord.ui.View):
    def __init__(self, embeds, current_page, message):
        super().__init__(timeout=180)  # 3分でタイムアウト
        self.embeds = embeds
        self.current_page = current_page
        self.message = message
        self.update_buttons()
    
    def update_buttons(self):
        self.first_page.disabled = self.current_page == 0
        self.prev_page.disabled = self.current_page == 0
        self.next_page.disabled = self.current_page == len(self.embeds) - 1
        self.last_page.disabled = self.current_page == len(self.embeds) - 1
    
    @discord.ui.button(emoji="⏪", style=discord.ButtonStyle.gray)
    async def first_page(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.current_page = 0
        self.update_buttons()
        embed, view = self.embeds[self.current_page]
        await interaction.response.edit_message(embed=embed, view=self)
    
    @discord.ui.button(emoji="◀️", style=discord.ButtonStyle.gray)
    async def prev_page(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.current_page > 0:
            self.current_page -= 1
            self.update_buttons()
            embed, view = self.embeds[self.current_page]
            await interaction.response.edit_message(embed=embed, view=self)
    
    @discord.ui.button(emoji="▶️", style=discord.ButtonStyle.gray)
    async def next_page(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.current_page < len(self.embeds) - 1:
            self.current_page += 1
            self.update_buttons()
            embed, view = self.embeds[self.current_page]
            await interaction.response.edit_message(embed=embed, view=self)
    
    @discord.ui.button(emoji="⏩", style=discord.ButtonStyle.gray)
    async def last_page(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.current_page = len(self.embeds) - 1
        self.update_buttons()
        embed, view = self.embeds[self.current_page]
        await interaction.response.edit_message(embed=embed, view=self)

async def setup(bot):
    await bot.add_cog(Search(bot))
