from __future__ import annotations

import logging
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from typing import Any, Dict, Iterator, List, Optional, Tuple, Union, cast, TypedDict

import discord
from discord import app_commands, ui, Embed, ButtonStyle, Interaction, Message
from discord.ext import commands

# ロガーの設定
logger = logging.getLogger(__name__)

# 定数
MAX_SEARCH_RESULTS = 50  # 最大検索結果数
ITEMS_PER_PAGE = 3  # 1ページあたりの表示数

# 型定義
class PostData(TypedDict):
    """投稿データの型定義"""
    id: int
    content: str
    category: Optional[str]
    created_at: str
    display_name: Optional[str]
    user_id: int
    is_anonymous: bool
    is_private: bool
    image_url: Optional[str]
    attachments: List[str]
    attachment_urls: Optional[str]  # データベースから取得した生の添付URL（|区切り）

class Search(commands.Cog):
    """投稿検索機能を提供するCog
    
    Attributes:
        bot: Discord Bot インスタンス
    """
    
    def __init__(self, bot: commands.Bot) -> None:
        """Search Cog を初期化します。
        
        Args:
            bot: Discord Bot インスタンス
        """
        self.bot: commands.Bot = bot
        logger.info("Search cog が初期化されました")
    
    @contextmanager
    def _get_db_connection(self) -> Iterator[sqlite3.Connection]:
        """データベース接続を取得するコンテキストマネージャー
        
        Yields:
            sqlite3.Connection: データベース接続オブジェクト
            
        Raises:
            sqlite3.Error: データベース接続に失敗した場合
        """
        conn = None
        try:
            # Post コグからデータベース接続を取得
            post_cog = self.bot.get_cog('Post')
            if not post_cog or not hasattr(post_cog, '_get_db_connection'):
                logger.error("Post コグが見つからないか、データベースにアクセスできません")
                raise sqlite3.Error("データベースに接続できません")
                
            with post_cog._get_db_connection() as conn:
                # PRAGMA 設定を適用
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
            
    @contextmanager
    def _get_cursor(self, conn: sqlite3.Connection) -> Iterator[sqlite3.Cursor]:
        """データベースカーソルを取得するコンテキストマネージャー
        
        Args:
            conn: データベース接続オブジェクト
            
        Yields:
            sqlite3.Cursor: データベースカーソル
        """
        cursor = conn.cursor()
        try:
            yield cursor
        finally:
            cursor.close()

    async def _search_posts(
        self,
        keyword: Optional[str] = None,
        category: Optional[str] = None,
        limit: int = 10,
        user_id: Optional[str] = None,
        current_user_id: Optional[int] = None
    ) -> List[PostData]:
        """データベースから投稿を検索します。
        
        Args:
            keyword: 検索キーワード（部分一致）
            category: カテゴリー名（完全一致）
            limit: 取得する最大件数
            user_id: ユーザーID（任意）
            current_user_id: 現在のユーザーID（プライベート投稿の確認用）
            
        Returns:
            List[PostData]: 検索結果の投稿リスト
            
        Raises:
            sqlite3.Error: データベースエラーが発生した場合
        """
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
                    
                    if user_id:
                        query += " AND t.user_id = ?"
                        params.append(int(user_id))
                    
                    # プライベート投稿は投稿者本人のみ表示
                    if current_user_id:
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
                    
                    # PostData 形式に変換
                    posts: List[PostData] = []
                    for row in rows:
                        post = dict(zip(columns, row))
                        
                        posts.append({
                            'id': post['id'],
                            'content': post['content'],
                            'category': post['category'],
                            'created_at': post['created_at'],
                            'display_name': post['display_name'],
                            'user_id': post['user_id'],
                            'is_anonymous': bool(post['is_anonymous']),
                            'is_private': bool(post['is_private']),
                            'image_url': post.get('image_url'),
                            'attachments': [],
                            'attachment_urls': None
                        })
                    
                    return posts
                    
        except sqlite3.Error as e:
            logger.error(f"投稿の検索中にエラーが発生しました: {e}", exc_info=True)
            raise
    
    async def _create_embeds(
        self, 
        interaction: discord.Interaction,
        posts: List[PostData]
    ) -> List[discord.Embed]:
        """検索結果から埋め込みメッセージのリストを作成します。
        
        Args:
            interaction: Discord インタラクションオブジェクト
            posts: 投稿データのリスト
            
        Returns:
            List[discord.Embed]: 埋め込みメッセージのリスト
        """
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
        """投稿を検索します
        
        Args:
            interaction: Discordのインタラクションオブジェクト
            keyword: 検索キーワード（部分一致）
            category: カテゴリー名（完全一致）
            limit: 表示する件数（1-50）
            user_id: ユーザーID（任意）
            
        Raises:
            Exception: 予期せぬエラーが発生した場合
        """
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
        logger.info(
            f"検索を開始: user_id={interaction.user.id}, "
            f"keyword={keyword}, category={category}, limit={limit}, target_user={user_id}"
        )
        
        try:
            # 投稿を検索
            posts = await self._search_posts(
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
            view = PaginationView(embeds, 0, timeout=300)  # 5分でタイムアウト
            await interaction.followup.send(
                f"🔍 検索結果 ({len(posts)}件)",
                embed=embeds[0], 
                view=view, 
                ephemeral=True
            )
            
        except Exception as e:
            logger.error(f"検索中にエラーが発生しました: {e}", exc_info=True)
            await interaction.followup.send(
                "❌ 検索中にエラーが発生しました。しばらくしてからもう一度お試しください。",
                ephemeral=True
            )

async def setup(bot: commands.Bot) -> None:
    """Cogをボットに追加"""
    await bot.add_cog(Search(bot))
