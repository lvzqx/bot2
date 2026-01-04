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
                    SELECT t.id, t.content, t.category, t.created_at, t.is_private, t.display_name,
                           GROUP_CONCAT(a.url, '|') as attachments
                    FROM thoughts t
                    LEFT JOIN attachments a ON t.id = a.thought_id
                    WHERE t.user_id = ?
                    GROUP BY t.id
                    ORDER BY t.created_at DESC
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
                items_per_page = 3  # 画像表示のため1ページあたりの表示数を減らす
                pages = []
                
                for i in range(0, len(posts), items_per_page):
                    embed = discord.Embed(
                        title=f"📋 {interaction.user.display_name} さんの投稿一覧",
                        color=discord.Color.blue()
                    )
                    
                    for post in posts[i:i + items_per_page]:
                        post_id = post['id']
                        content = post['content']
                        category = post['category']
                        is_private = post['is_private']
                        display_name = post['display_name']
                        attachments = post['attachments'].split('|') if post['attachments'] else []
                        
                        # 内容が長すぎる場合は省略
                        display_content = content[:100] + '...' if len(content) > 100 else content
                        
                        # 投稿情報を追加
                        field_value = f"{display_content}\n"
                        field_value += f"カテゴリー: {category}\n"
                        if is_private:
                            field_value += "🔒 非公開\n"
                        
                        # 画像がある場合は最初の1枚をサムネイルとして表示
                        image_urls = [url for url in attachments if url.lower().endswith(('.png', '.jpg', '.jpeg', '.gif', '.webp'))]
                        if image_urls:
                            field_value += "\n🖼️ 画像が添付されています"
                            if len(image_urls) > 1:
                                field_value += f" ({len(image_urls)}枚)"
                        
                        embed.add_field(
                            name=f"ID: {post_id}",
                            value=field_value,
                            inline=False
                        )
                        
                        # 最初の画像をサムネイルとして追加
                        if image_urls:
                            embed.set_thumbnail(url=image_urls[0])
                    
                    pages.append(embed)
                
                # ページネーションで表示
                view = PaginationView(pages, 0)
                await interaction.followup.send(embed=pages[0], view=view, ephemeral=True)
                
            except Exception as e:
                print(f"データベースエラー: {e}")
                error_embed = discord.Embed(
                    title="❌ エラー",
                    description="投稿の取得中にエラーが発生しました。",
                    color=discord.Color.red()
                )
                await interaction.followup.send(embed=error_embed, ephemeral=True)
                
        except Exception as e:
            print(f"エラー: {e}")
            if not interaction.response.is_done():
                error_embed = discord.Embed(
                    title="❌ エラー",
                    description="コマンドの実行中にエラーが発生しました。",
                    color=discord.Color.red()
                )
                await interaction.response.send_message(embed=error_embed, ephemeral=True)

class PaginationView(discord.ui.View):
    def __init__(self, pages, current_page):
        super().__init__(timeout=180)  # 3分でタイムアウト
        self.pages = pages
        self.current_page = current_page
        self.update_buttons()
    
    def update_buttons(self):
        # すべてのボタンをクリア
        self.clear_items()
        
        # 最初に戻るボタン
        self.add_item(discord.ui.Button(style=discord.ButtonStyle.secondary, label='<<', custom_id='first', disabled=self.current_page == 0))
        # 前へボタン
        self.add_item(discord.ui.Button(style=discord.ButtonStyle.primary, label='<', custom_id='prev', disabled=self.current_page == 0))
        # ページ表示
        self.add_item(discord.ui.Button(style=discord.ButtonStyle.gray, label=f'{self.current_page + 1}/{len(self.pages)}', disabled=True))
        # 次へボタン
        self.add_item(discord.ui.Button(style=discord.ButtonStyle.primary, label='>', custom_id='next', disabled=self.current_page >= len(self.pages) - 1))
        # 最後へボタン
        self.add_item(discord.ui.Button(style=discord.ButtonStyle.secondary, label='>>', custom_id='last', disabled=self.current_page >= len(self.pages) - 1))
    
    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        # ボタンが押されたときの処理
        if not interaction.data.get('custom_id'):
            return False
            
        if interaction.data['custom_id'] == 'first':
            self.current_page = 0
        elif interaction.data['custom_id'] == 'prev':
            if self.current_page > 0:
                self.current_page -= 1
        elif interaction.data['custom_id'] == 'next':
            if self.current_page < len(self.pages) - 1:
                self.current_page += 1
        elif interaction.data['custom_id'] == 'last':
            self.current_page = len(self.pages) - 1
        
        self.update_buttons()
        await interaction.response.edit_message(embed=self.pages[self.current_page], view=self)
        return False
    @discord.ui.button(emoji="⏩", style=discord.ButtonStyle.gray)
    async def last_page(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.current_page = len(self.pages) - 1
        self.update_buttons()
        await interaction.response.edit_message(embed=self.pages[self.current_page], view=self)

@app_commands.guild_only()
async def setup(bot):
    await bot.add_cog(List(bot))
