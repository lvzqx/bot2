import discord
from discord import app_commands, ui
from discord.ext import commands
from datetime import datetime, timedelta
from .base import BaseCog

class SearchThoughtsModal(ui.Modal, title="つぶやきを検索"):
    keyword = ui.TextInput(
        label="検索キーワード",
        placeholder="検索したいキーワードを入力（空欄可）",
        required=False
    )
    
    category = ui.TextInput(
        label="カテゴリー",
        placeholder="カテゴリーで絞り込み（空欄可）",
        required=False
    )
    
    days = ui.TextInput(
        label="何日分遡るか",
        placeholder="7（1週間前から検索）",
        default="30",
        required=True
    )
    
    show_private = ui.TextInput(
        label="非公開のつぶやきも含める（はい/いいえ）",
        placeholder="はい または いいえ",
        default="いいえ",
        required=True
    )
    
    async def on_submit(self, interaction: discord.Interaction):
        try:
            await interaction.response.defer(ephemeral=True)
            
            # パラメータを取得
            keyword = f"%{self.keyword.value}%" if self.keyword.value else "%"
            category = f"%{self.category.value}%" if self.category.value else "%"
            days_ago = int(self.days.value) if self.days.value.isdigit() else 30
            show_private = self.show_private.value.lower() in ['はい', 'yes', 'y', 'true']
            
            # 日付範囲を計算
            since_date = (datetime.utcnow() - timedelta(days=days_ago)).strftime('%Y-%m-%d %H:%M:%S')
            
            # クエリを構築
            query = '''
                SELECT * FROM thoughts 
                WHERE user_id = ? 
                AND content LIKE ?
                AND category LIKE ?
                AND created_at >= ?
            '''
            params = [interaction.user.id, keyword, category, since_date]
            
            if not show_private:
                query += ' AND is_private = 0'
                
            query += ' ORDER BY created_at DESC'
            
            # データベースから検索
            async with interaction.client.db.execute(query, params) as cursor:
                thoughts = await cursor.fetchall()
            
            if not thoughts:
                await interaction.followup.send(
                    "条件に合うつぶやきが見つかりませんでした。",
                    ephemeral=True
                )
                return
            
            # 結果をページネーションで表示
            await self.show_search_results(interaction, thoughts)
            
        except ValueError:
            await interaction.followup.send(
                "日数には数値を入力してください。",
                ephemeral=True
            )
        except Exception as e:
            await interaction.followup.send(
                f"検索中にエラーが発生しました: {str(e)}",
                ephemeral=True
            )
    
    async def show_search_results(self, interaction: discord.Interaction, thoughts: list):
        """検索結果をページネーションで表示"""
        class SearchView(ui.View):
            def __init__(self, thoughts: list):
                super().__init__(timeout=180)
                self.thoughts = thoughts
                self.current_page = 0
                self.items_per_page = 5
                self.total_pages = (len(thoughts) + self.items_per_page - 1) // self.items_per_page
                
                # 初期ボタン状態を設定
                self.update_buttons()
            
            def update_buttons(self):
                self.previous_button.disabled = self.current_page == 0
                self.next_button.disabled = (self.current_page + 1) * self.items_per_page >= len(self.thoughts)
                self.page_label.label = f"{self.current_page + 1}/{self.total_pages}"
            
            def create_embed(self, page_thoughts: list):
                embed = discord.Embed(
                    title=f"検索結果 ({len(self.thoughts)}件)",
                    color=discord.Color.blue()
                )
                
                for thought in page_thoughts:
                    thought_id, _, content, category, _, show_name, is_private, _ = thought
                    
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
                    
                    # メモを追加
                    embed.add_field(
                        name=f"{is_private_mark}つぶやき #{thought_id} - {category_display}",
                        value=f"{content}\n\n*{display_name}*",
                        inline=False
                    )
                
                return embed
            
            @ui.button(emoji="⬅️", style=discord.ButtonStyle.secondary)
            async def previous_button(self, interaction: discord.Interaction, button: ui.Button):
                if self.current_page > 0:
                    self.current_page -= 1
                    self.update_buttons()
                    start = self.current_page * self.items_per_page
                    end = start + self.items_per_page
                    await interaction.response.edit_message(
                        embed=self.create_embed(self.thoughts[start:end]),
                        view=self
                    )
            
            @ui.button(label="1/1", style=discord.ButtonStyle.primary, disabled=True)
            async def page_label(self, interaction: discord.Interaction, button: ui.Button):
                pass
            
            @ui.button(emoji="➡️", style=discord.ButtonStyle.secondary)
            async def next_button(self, interaction: discord.Interaction, button: ui.Button):
                if (self.current_page + 1) * self.items_per_page < len(self.thoughts):
                    self.current_page += 1
                    self.update_buttons()
                    start = self.current_page * self.items_per_page
                    end = start + self.items_per_page
                    await interaction.response.edit_message(
                        embed=self.create_embed(self.thoughts[start:end]),
                        view=self
                    )
        
        # ビューを作成して最初のページを表示
        view = SearchView(thoughts)
        start = 0
        end = view.items_per_page
        
        await interaction.followup.send(
            embed=view.create_embed(thoughts[start:end]),
            view=view,
            ephemeral=True
        )

class SearchCog(BaseCog):
    def __init__(self, bot):
        super().__init__(bot)
    
    @app_commands.command(name="search", description="つぶやきを検索します")
    async def search_thoughts(self, interaction: discord.Interaction):
        """つぶやきを検索するモーダルを開きます"""
        if not await self.check_channel(interaction):
            return
            
        try:
            await interaction.response.send_modal(SearchThoughtsModal())
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
