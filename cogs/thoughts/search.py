from __future__ import annotations

import logging
import sqlite3
from contextlib import contextmanager
from typing import List, Dict, Any, Optional, Tuple, Union
from datetime import datetime

import discord
from discord import app_commands, ui, Interaction, Embed, File
from discord.ext import commands

# ロガーの設定
logger = logging.getLogger(__name__)

# 定数
MAX_SEARCH_RESULTS = 50  # 最大検索結果数
ITEMS_PER_PAGE = 3  # 1ページあたりの表示数

# 型定義
PostData = Dict[str, Any]  # 投稿データの型

class Search(commands.Cog):
    """投稿検索機能を提供するCog"""
    
    def __init__(self, bot: commands.Bot) -> None:
        """Search Cog を初期化します。"""
        self.bot: commands.Bot = bot
        logger.info("Search cog が初期化されました")
    
    @contextmanager
    def _get_db_connection(self) -> Iterator[sqlite3.Connection]:
        """データベース接続を取得するコンテキストマネージャー"""
        conn = None
        try:
            conn = sqlite3.connect('thoughts.db')
            conn.execute("PRAGMA foreign_keys = ON")
            conn.execute("PRAGMA journal_mode = WAL")
            conn.execute("PRAGMA synchronous = NORMAL")
            conn.execute("PRAGMA cache_size = -2000000")  # 2GB
            conn.execute("PRAGMA temp_store = MEMORY")
            conn.row_factory = sqlite3.Row
            yield conn
        except sqlite3.Error as e:
            logger.error(f"データベース接続エラー: {e}", exc_info=True)
            raise
        finally:
            if conn:
                conn.close()
    
    @contextmanager
    def _get_cursor(self, conn: sqlite3.Connection) -> Iterator[sqlite3.Cursor]:
        """データベースカーソルを取得するコンテキストマネージャー"""
        cursor = conn.cursor()
        try:
            yield cursor
        finally:
            cursor.close()

    def _search_posts(
        self,
        keyword: Optional[str] = None,
        category: Optional[str] = None,
        limit: int = 10,
        user_id: Optional[str] = None,
        current_user_id: Optional[int] = None
    ) -> List[PostData]:
        """データベースから投稿を検索します。"""
        try:
            with self._get_db_connection() as conn:
                with self._get_cursor(conn) as cursor:
                    # クエリの構築
                    query = """
                        SELECT 
                            t.id, t.content, t.category, t.created_at, 
                            t.display_name, t.user_id, t.is_anonymous, t.is_private,
                            t.image_url
                        FROM thoughts t
                        WHERE 1=1
                    """
                    
                    params: List[Any] = []
                    
                    # 検索条件の追加
                    if keyword:
                        query += " AND t.content LIKE ?"
                        params.append(f"%{keyword}%")
                    
                    if category:
                        query += " AND t.category = ?"
                        params.append(category)
                    
                    if user_id and user_id.isdigit():
                        query += " AND t.user_id = ?"
                        params.append(int(user_id))
                    
                    # プライベート投稿は投稿者本人のみ表示
                    if current_user_id is not None:
                        query += " AND (t.is_private = 0 OR t.user_id = ?)"
                        params.append(current_user_id)
                    
                    # ソートとリミット
                    query += " ORDER BY t.created_at DESC LIMIT ?"
                    params.append(limit)
                    
                    # クエリ実行
                    cursor.execute(query, params)
                    
                    # 結果を辞書のリストに変換
                    columns = [column[0] for column in cursor.description]
                    rows = cursor.fetchall()
                    
                    return [dict(zip(columns, row)) for row in rows]
                    
        except sqlite3.Error as e:
            logger.error(f"投稿の検索中にエラーが発生しました: {e}", exc_info=True)
            raise

    async def _create_embeds(
        self, 
        interaction: discord.Interaction,
        posts: List[PostData]
    ) -> List[discord.Embed]:
        """検索結果から埋め込みメッセージのリストを作成します。"""
        embeds: List[discord.Embed] = []
        
        # 1ページあたりの投稿数
        for i in range(0, len(posts), ITEMS_PER_PAGE):
            page_posts = posts[i:i + ITEMS_PER_PAGE]
            
            # 埋め込みメッセージを作成
            embed = discord.Embed(
                title=f"🔍 検索結果 ({len(posts)}件)",
                color=discord.Color.blue(),
                timestamp=datetime.now()
            )
            
            for post in page_posts:
                # 投稿者情報を設定
                if post['is_anonymous']:
                    author_name = "匿名"
                    author_icon = "https://cdn.discordapp.com/embed/avatars/0.png"
                else:
                    author_name = post['display_name'] or "名無し"
                    # ユーザー情報を取得してアイコンを設定
                    user = interaction.guild.get_member(post['user_id'])
                    author_icon = user.display_avatar.url if user and user.display_avatar else None
                
                # 投稿内容を作成
                content = post['content'][:200] + "..." if len(post['content']) > 200 else post['content']
                
                # フィールドに追加
                field_value = f"{content}\n"
                if post['category']:
                    field_value += f"\nカテゴリー: {post['category']}\n"
                
                if post['is_private']:
                    field_value += "🔒 非公開\n"
                
                # 添付ファイルがある場合
                if post.get('image_url'):
                    field_value += "\n🖼️ 画像が添付されています"
                    
                    # 最初の画像をサムネイルに設定
                    if not embed.thumbnail and i == 0 and post == page_posts[0]:
                        embed.set_thumbnail(url=post['image_url'])
                
                # フィールドを追加
                embed.add_field(
                    name=f"ID: {post['id']} | {author_name} | {post['created_at'].split(' ')[0]}",
                    value=field_value,
                    inline=False
                )
            
            embeds.append(embed)
        
        return embeds

    @app_commands.command(name="search", description="投稿を検索します")
    @app_commands.describe(
        keyword="検索キーワード",
        category="カテゴリーで絞り込み",
        limit=f"表示する件数 (デフォルト: 10, 最大{MAX_SEARCH_RESULTS}件)",
        user_id="ユーザーIDで絞り込み (任意)"
    )
    async def search_posts(
        self,
        interaction: discord.Interaction,
        keyword: Optional[str] = None,
        category: Optional[str] = None,
        limit: int = 10,
        user_id: Optional[str] = None
    ) -> None:
        """投稿を検索します"""
        # DMの場合は無効化
        if isinstance(interaction.channel, discord.DMChannel):
            await interaction.response.send_message(
                "❌ このコマンドはDMでは使用できません。サーバー内でお試しください。", 
                ephemeral=True
            )
            return
        
        # 制限値の検証
        limit = max(1, min(limit, MAX_SEARCH_RESULTS))
        
        # 処理中であることをユーザーに通知
        await interaction.response.defer(ephemeral=True)
        
        try:
            # 投稿を検索
            posts = self._search_posts(
                keyword=keyword,
                category=category,
                limit=limit,
                user_id=user_id,
                current_user_id=interaction.user.id
            )
            
            if not posts:
                await interaction.followup.send(
                    "🔍 該当する投稿が見つかりませんでした。検索条件を変えてお試しください。",
                    ephemeral=True
                )
                return
            
            # 埋め込みメッセージを作成
            embeds = await self._create_embeds(interaction, posts)
            
            # ページネーションで表示
            view = PaginationView(embeds, 0, interaction.user.id)
            await interaction.followup.send(
                f"🔍 検索結果 ({len(posts)}件)",
                embed=embeds[0], 
                view=view, 
                ephemeral=True
            )
            
        except Exception as e:
            print(f"[SEARCH ERROR] {e}")
            print(f"[SEARCH ERROR TYPE] {type(e).__name__}")
            import traceback
            traceback.print_exc()
            logger.error(f"検索中にエラーが発生しました: {e}", exc_info=True)
            await interaction.followup.send(
                "❌ 検索中にエラーが発生しました。しばらくしてからもう一度お試しください。",
                ephemeral=True
            )

class PaginationView(discord.ui.View):
    def __init__(self, pages, current_page, user_id):
        super().__init__(timeout=300)  # 5分に延長
        self.pages = pages
        self.current_page = current_page
        self.user_id = user_id
        self.message = None
        self.update_buttons()
    
    def update_buttons(self):
        # すべてのボタンをクリア
        self.clear_items()
        
        # ボタンのスタイルを定義
        first_disabled = self.current_page == 0
        last_disabled = self.current_page >= len(self.pages) - 1
        
        # ボタンを追加
        buttons = [
            ('<<', 'first', first_disabled, discord.ButtonStyle.secondary),
            ('<', 'prev', first_disabled, discord.ButtonStyle.primary),
            (f'{self.current_page + 1}/{len(self.pages)}', 'page', True, discord.ButtonStyle.gray),
            ('>', 'next', last_disabled, discord.ButtonStyle.primary),
            ('>>', 'last', last_disabled, discord.ButtonStyle.secondary)
        ]
        
        for label, custom_id, disabled, style in buttons:
            button = discord.ui.Button(
                style=style,
                label=label,
                custom_id=custom_id,
                disabled=disabled
            )
            button.callback = self.button_callback
            self.add_item(button)
    
    async def button_callback(self, interaction: discord.Interaction):
        # ボタンを押したユーザーを確認
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("この操作は許可されていません。", ephemeral=True)
            return
            
        # ボタンIDに応じてページを更新
        custom_id = interaction.data['custom_id']
        
        try:
            if custom_id == 'first':
                self.current_page = 0
            elif custom_id == 'prev' and self.current_page > 0:
                self.current_page -= 1
            elif custom_id == 'next' and self.current_page < len(self.pages) - 1:
                self.current_page += 1
            elif custom_id == 'last':
                self.current_page = len(self.pages) - 1
            
            # ボタンの状態を更新
            self.update_buttons()
            
            # メッセージを編集
            await interaction.response.edit_message(
                embed=self.pages[self.current_page],
                view=self
            )
            
        except Exception as e:
            print(f"[ERROR] ページネーション処理中にエラーが発生しました: {e}")
            if not interaction.response.is_done():
                await interaction.response.send_message(
                    "ページの更新中にエラーが発生しました。",
                    ephemeral=True
                )
    
    async def on_timeout(self):
        # タイムアウト時にボタンを無効化
        for item in self.children:
            if isinstance(item, discord.ui.Button):
                item.disabled = True
        
        if self.message:
            try:
                await self.message.edit(view=self)
            except:
                pass

async def setup(bot: commands.Bot) -> None:
    """Cogをボットに追加"""
    await bot.add_cog(Search(bot))
