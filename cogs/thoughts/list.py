import discord
from discord import app_commands
from discord.ext import commands
from datetime import datetime

class List(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.db = bot.db

    @app_commands.command(name="list", description="自分の投稿一覧を表示します")
    @app_commands.describe(limit="表示する件数 (デフォルト: 10, 最大: 25)")
    async def list_posts(self, interaction: discord.Interaction, limit: int = 10):
        """自分の投稿一覧を表示します"""
        try:
            # 即座に応答して処理中であることを伝える
            await interaction.response.defer(ephemeral=True)
            
            # 入力バリデーション
            limit = max(1, min(25, limit))  # 1〜25件に制限
            
            # データベースから投稿を取得
            cursor = self.bot.db.cursor()
            try:
                cursor.execute('''
                    SELECT id, content, category, created_at, is_private, display_name
                    FROM thoughts 
                    WHERE user_id = ?
                    ORDER BY created_at DESC
                    LIMIT ?
                ''', (interaction.user.id, limit))
                
                posts = cursor.fetchall()
                
                if not posts:
                    embed = discord.Embed(
                        title="📭 投稿がありません",
                        description="まだ投稿がありません。`/post` コマンドで新しい投稿を作成しましょう！",
                        color=discord.Color.blue()
                    )
                    return await interaction.followup.send(embed=embed, ephemeral=True)
                
                # ページネーションの設定
                items_per_page = 5
                pages = []
                
                for i in range(0, len(posts), items_per_page):
                    embed = discord.Embed(
                        title=f"📋 {interaction.user.display_name} さんの投稿一覧",
                        color=discord.Color.blue(),
                        timestamp=datetime.now()
                    )
                    
                    for post in posts[i:i + items_per_page]:
                        post_id, content, category, created_at, is_private, display_name = post
                        created_at_dt = datetime.fromisoformat(created_at)
                        created_at_str = created_at_dt.strftime('%Y-%m-%d %H:%M')
                        
                        # 内容が長すぎる場合は省略
                        display_content = content[:100] + '...' if len(content) > 100 else content
                        
                        # 投稿者情報を設定
                        is_anonymous = display_name is None
                        author_name = "匿名" if is_anonymous else display_name
                        
                        # 投稿カード風の埋め込みメッセージを作成
                        post_embed = discord.Embed(
                            description=display_content,
                            color=discord.Color.blue(),
                            timestamp=created_at_dt
                        )
                        
                        # 投稿者情報を設定（アバター付き）
                        post_embed.set_author(
                            name=author_name,
                            icon_url=str(interaction.user.display_avatar.url) if not is_anonymous else None
                        )
                        
                        # フッターに投稿日時とカテゴリーを表示
                        footer_text = f"カテゴリー: {category}"
                        if is_private:
                            footer_text += " | 🔒 非公開"
                        post_embed.set_footer(text=footer_text)
                        
                        # メインの埋め込みに追加
                        embed.add_field(
                            name=f"ID: {post_id}",
                            value="",
                            inline=False
                        )
                        pages[-1] = (embed, post_embed)  # タプルで保存
                    
                    embed.set_footer(text=f"ページ {i//items_per_page + 1}/{((len(posts)-1)//items_per_page) + 1}")
                    pages.append(embed)
                
                if not pages:
                    embed = discord.Embed(
                        title="📭 表示できる投稿がありません",
                        description="表示できる投稿が見つかりませんでした。",
                        color=discord.Color.blue()
                    )
                    return await interaction.followup.send(embed=embed, ephemeral=True)
                
                # ページネーションで表示
                current_page = 0
                main_embed, post_embed = pages[current_page]
                view = ListPaginationView(pages, current_page)
                await interaction.followup.send(embed=main_embed, view=view)
                # 投稿カードを別メッセージとして送信
                await interaction.followup.send(embed=post_embed)
                
            except Exception as e:
                self.bot.db.rollback()
                raise e
                
        except Exception as e:
            error_embed = discord.Embed(
                title='❌ エラー',
                description=f'投稿一覧の取得中にエラーが発生しました: {str(e)}',
                color=discord.Color.red()
            )
            try:
                if not interaction.response.is_done():
                    await interaction.response.send_message(embed=error_embed, ephemeral=True)
                else:
                    await interaction.followup.send(embed=error_embed, ephemeral=True)
            except:
                try:
                    await interaction.user.send(embed=error_embed)
                except:
                    pass  # DMがブロックされている場合は無視

class ListPaginationView(discord.ui.View):
    def __init__(self, pages, current_page):
        super().__init__(timeout=180)  # 3分でタイムアウト
        self.pages = pages
        self.current_page = current_page
        self.update_buttons()
    
    def update_buttons(self):
        self.first_page.disabled = self.current_page == 0
        self.prev_page.disabled = self.current_page == 0
        self.next_page.disabled = self.current_page == len(self.pages) - 1
        self.last_page.disabled = self.current_page == len(self.pages) - 1
    
    @discord.ui.button(emoji="⏪", style=discord.ButtonStyle.gray)
    async def first_page(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.current_page = 0
        self.update_buttons()
        await interaction.response.edit_message(embed=self.pages[self.current_page], view=self)
    
    @discord.ui.button(emoji="◀️", style=discord.ButtonStyle.gray)
    async def prev_page(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.current_page > 0:
            self.current_page -= 1
            self.update_buttons()
            await interaction.response.edit_message(embed=self.pages[self.current_page], view=self)
    
    @discord.ui.button(emoji="▶️", style=discord.ButtonStyle.gray)
    async def next_page(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.current_page < len(self.pages) - 1:
            self.current_page += 1
            self.update_buttons()
            await interaction.response.edit_message(embed=self.pages[self.current_page], view=self)
    
    @discord.ui.button(emoji="⏩", style=discord.ButtonStyle.gray)
    async def last_page(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.current_page = len(self.pages) - 1
        self.update_buttons()
        await interaction.response.edit_message(embed=self.pages[self.current_page], view=self)

@app_commands.guild_only()
async def setup(bot):
    await bot.add_cog(List(bot))
