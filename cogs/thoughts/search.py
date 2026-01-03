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
                t.display_name, t.user_id, t.is_anonymous, t.is_private,
                t.image_url
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
            post_id, content, category, created_at, display_name, post_user_id, is_anonymous, is_private, image_url = post
            created_at_dt = datetime.fromisoformat(created_at)
            
            # 投稿者情報を設定
            author_name = "匿名" if is_anonymous else (display_name or "不明")
            
            # 投稿カード風の埋め込みメッセージを作成
            embed = discord.Embed(
                description=content,
                color=discord.Color.blue()
            )
            
            # 投稿者情報を設定（アバター付き）
            if not is_anonymous:
                try:
                    user = await interaction.guild.fetch_member(post_user_id)
                    if user:
                        embed.set_author(
                            name=author_name,
                            icon_url=str(user.display_avatar.url)
                        )
                except:
                    embed.set_author(name=author_name)
            else:
                embed.set_author(name=author_name)
            
            # フッターにカテゴリーと投稿IDを表示
            footer_text = f"カテゴリー: {category} | ID: {post_id}"
            if is_private:
                footer_text += " | 🔒 非公開"
            
            embed.set_footer(text=footer_text)
            
            # 画像がある場合は追加
            if image_url:
                embed.set_image(url=image_url)
            
            # 検索結果を追加
            embeds.append(embed)
        
        # ページネーションで表示
        if embeds:
            view = PaginationView(embeds, 0)
            await interaction.followup.send(embed=embeds[0], view=view)
        else:
            await interaction.followup.send("表示できる投稿がありません。")

class PaginationView(discord.ui.View):
    def __init__(self, embeds, current_page):
        super().__init__(timeout=180)  # 3分でタイムアウト
        self.embeds = embeds
        self.current_page = current_page
        self.update_buttons()
    
    def update_buttons(self):
        # クリアしてからボタンを追加
        self.clear_items()
        
        # 最初に戻るボタン
        first_button = discord.ui.Button(style=discord.ButtonStyle.secondary, emoji="⏪", disabled=self.current_page == 0)
        first_button.callback = self.first_page
        self.add_item(first_button)
        
        # 前へボタン
        prev_button = discord.ui.Button(style=discord.ButtonStyle.primary, emoji="⬅️", disabled=self.current_page == 0)
        prev_button.callback = self.prev_page
        self.add_item(prev_button)
        
        # ページ表示
        page_button = discord.ui.Button(style=discord.ButtonStyle.gray, label=f'{self.current_page + 1}/{len(self.embeds)}', disabled=True)
        self.add_item(page_button)
        
        # 次へボタン
        next_button = discord.ui.Button(style=discord.ButtonStyle.primary, emoji="➡️", disabled=self.current_page >= len(self.embeds) - 1)
        next_button.callback = self.next_page
        self.add_item(next_button)
        
        # 最後へボタン
        last_button = discord.ui.Button(style=discord.ButtonStyle.secondary, emoji="⏩", disabled=self.current_page >= len(self.embeds) - 1)
        last_button.callback = self.last_page
        self.add_item(last_button)
    
    async def first_page(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.current_page = 0
        self.update_buttons()
        await interaction.response.edit_message(embed=self.embeds[self.current_page], view=self)
    
    async def prev_page(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.current_page > 0:
            self.current_page -= 1
            self.update_buttons()
            await interaction.response.edit_message(embed=self.embeds[self.current_page], view=self)
    
    async def next_page(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.current_page < len(self.embeds) - 1:
            self.current_page += 1
            self.update_buttons()
            await interaction.response.edit_message(embed=self.embeds[self.current_page], view=self)
    
    async def last_page(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.current_page = len(self.embeds) - 1
        self.update_buttons()
        await interaction.response.edit_message(embed=self.embeds[self.current_page], view=self)

async def setup(bot):
    await bot.add_cog(Search(bot))
