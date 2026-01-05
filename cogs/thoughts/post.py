from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import re
import sys
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional, Tuple, TypedDict, Union, cast, TYPE_CHECKING

# 設定のインポート
import sys
from pathlib import Path
sys.path.append(str(Path(__file__).parent.parent.parent))
from config import DEFAULT_AVATAR

import discord
from discord import (
    app_commands,
    Attachment,
    File,
    Interaction,
    Member,
    Message,
    TextChannel,
    Thread,
    User,
    ui,
)
from discord.ext import commands

# 型チェック用のインポート
if TYPE_CHECKING:
    from bot import Bot

# ロガーの設定
logger = logging.getLogger(__name__)

# 型定義
class PostData(TypedDict, total=False):
    """投稿データを表す型定義"""
    user_id: int
    content: str
    category: str
    image_url: Optional[str]
    is_anonymous: bool
    is_private: bool
    display_name: str

# 定数
MAX_CONTENT_LENGTH = 2000
MAX_CATEGORY_LENGTH = 50
DEFAULT_CATEGORY = 'その他'
DEFAULT_AVATAR = 'https://cdn.discordapp.com/embed/avatars/0.png'  # 仮のデフォルトアバター

class Post(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self._init_db()
        logger.info("Post cog が初期化されました")
        
        # コマンドを手動で登録
        self.bot.tree.add_command(self.post)
    """投稿機能を提供するCog。
    
    ユーザーがメッセージを投稿し、データベースに保存する機能を提供します。
    匿名投稿や非公開投稿、カテゴリ分けなどの機能があります。
    """
    
    def __init__(self, bot: commands.Bot) -> None:
        """Post Cogを初期化します。
        
        Args:
            bot: Discord Bot インスタンス
        """
        self.bot: commands.Bot = bot
        self._init_db()
        logger.info("Post cog が初期化されました")
    
    def _init_db(self) -> None:
        """データベースを初期化します。"""
        with self._get_db_connection() as conn:
            with self._get_cursor(conn) as cursor:
                # パフォーマンス向上のためのPRAGMA設定
                cursor.execute('''
                    PRAGMA journal_mode=WAL;
                    PRAGMA synchronous=NORMAL;
                    PRAGMA foreign_keys=ON;
                ''')
                
                # テーブルが存在しない場合は作成
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS thoughts (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        user_id INTEGER NOT NULL,
                        content TEXT NOT NULL,
                        category TEXT,
                        image_url TEXT,
                        is_anonymous BOOLEAN DEFAULT 0,
                        is_private BOOLEAN DEFAULT 0,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        display_name TEXT
                    )
                ''')
                
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS message_references (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        channel_id TEXT NOT NULL,
                        message_id TEXT NOT NULL UNIQUE,
                        post_id INTEGER NOT NULL,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        FOREIGN KEY (post_id) REFERENCES thoughts (id) ON DELETE CASCADE
                    )
                ''')
                
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS attachments (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        post_id INTEGER NOT NULL,
                        url TEXT NOT NULL,
                        FOREIGN KEY (post_id) REFERENCES thoughts (id) ON DELETE CASCADE
                    )
                ''')
                
                # インデックスを作成
                cursor.execute('''
                    CREATE INDEX IF NOT EXISTS idx_thoughts_user_id 
                    ON thoughts(user_id);
                ''')
                
                cursor.execute('''
                    CREATE INDEX IF NOT EXISTS idx_message_references_post_id 
                    ON message_references(post_id);
                ''')
                
                cursor.execute('''
                    CREATE INDEX IF NOT EXISTS idx_message_references_message_id 
                    ON message_references(message_id);
                ''')
                
                cursor.execute('''
                    CREATE INDEX IF NOT EXISTS idx_attachments_post_id 
                    ON attachments(post_id);
                ''')
                
                conn.commit()
                logger.info("データベーステーブルの初期化が完了しました")
    
    @contextlib.contextmanager
    def _get_db_connection(self) -> sqlite3.Connection:
        """データベース接続を取得するコンテキストマネージャー
        
        Yields:
            sqlite3.Connection: データベース接続オブジェクト
            
        Raises:
            sqlite3.Error: データベース接続に失敗した場合
        """
        conn = None
        try:
            conn = sqlite3.connect(self.bot.db_path)
            conn.row_factory = sqlite3.Row
            yield conn
        except sqlite3.Error as e:
            logger.error(f"データベース接続エラー: {e}", exc_info=True)
            raise
        finally:
            if conn is not None:
                conn.close()
    
    @contextlib.contextmanager
    def _get_cursor(self, conn: sqlite3.Connection) -> sqlite3.Cursor:
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

    class PostModal(ui.Modal, title='メッセージを投稿'):
        """投稿用のモーダルフォーム。
        
        ユーザーがメッセージを入力するためのフォームを提供します。
        メッセージの内容、カテゴリ、画像URL、表示設定などを入力できます。
        """
        
        def __init__(self, bot: commands.Bot, *args: Any, **kwargs: Any) -> None:
            """モーダルを初期化します。
            
            Args:
                bot: Bot インスタンス
                *args: 親クラスに渡す引数
                **kwargs: 親クラスに渡すキーワード引数
            """
            super().__init__(*args, **kwargs)
            self.bot: commands.Bot = bot
            
            # メッセージ入力
            self.content: ui.TextInput[Any] = ui.TextInput(
                label=f'メッセージ (最大{MAX_CONTENT_LENGTH}文字)',
                style=discord.TextStyle.long,
                placeholder='メッセージを入力してください...',
                required=True,
                max_length=MAX_CONTENT_LENGTH,
                min_length=1
            )
            self.add_item(self.content)
            
            # カテゴリー入力
            self.category: ui.TextInput[Any] = ui.TextInput(
                label='カテゴリー',
                placeholder='例: 独り言, 愚痴, 悩み, アイデア など',
                required=False,
                max_length=MAX_CATEGORY_LENGTH
            )
            self.add_item(self.category)
            
            # 画像URL入力
            self.image_url: ui.TextInput[Any] = ui.TextInput(
                label='画像URL (任意)',
                placeholder='画像のURLを入力...',
                required=False
            )
            self.add_item(self.image_url)
            
            # 匿名設定
            self.is_anonymous: ui.TextInput[Any] = ui.TextInput(
                label='表示名',
                placeholder='名前を表示する場合は「表示」、匿名の場合は「匿名」と入力',
                default='表示',
                required=True,
                max_length=2
            )
            self.add_item(self.is_anonymous)
            
            # 公開設定
            self.is_private: ui.TextInput[Any] = ui.TextInput(
                label='公開設定',
                placeholder='公開する場合は「公開」、非公開の場合は「非公開」と入力',
                default='公開',
                required=True,
                max_length=3
            )
            self.add_item(self.is_private)
            
            logger.debug("PostModal が初期化されました")
        
        async def _validate_inputs(self) -> Tuple[str, str, Optional[str], bool, bool]:
            """入力値を検証し、整形して返します。
            
            Returns:
                Tuple[str, str, Optional[str], bool, bool]: 
                    (content, category, image_url, is_anonymous, is_private)
                    
            Raises:
                ValueError: 入力値が無効な場合
            """
            # メッセージの検証
            content = self.content.value.strip()
            if not content:
                raise ValueError('メッセージを入力してください。')
            
            if len(content) > MAX_CONTENT_LENGTH:
                raise ValueError(f'メッセージは{MAX_CONTENT_LENGTH}文字以内で入力してください。')
            
            # カテゴリの検証とデフォルト値設定
            category = (
                self.category.value.strip() 
                if self.category.value and self.category.value.strip() 
                else DEFAULT_CATEGORY
            )
            
            # 画像URLの検証（存在する場合は有効なURLか確認）
            image_url = None
            if self.image_url.value and self.image_url.value.strip():
                image_url = self.image_url.value.strip()
                if not image_url.startswith(('http://', 'https://')):
                    raise ValueError('画像URLは http:// または https:// で始まる必要があります。')
            
            # 表示設定の検証
            is_anonymous = self.is_anonymous.value.strip() == '匿名'
            is_private = self.is_private.value.strip() == '非公開'
            
            return content, category, image_url, is_anonymous, is_private
        
        async def _save_post_to_db(
            self, 
            user: Union[User, Member],
            content: str,
            category: str,
            image_url: Optional[str],
            is_anonymous: bool,
            is_private: bool
        ) -> int:
            """投稿をデータベースに保存します。
            
            Args:
                user: 投稿者のユーザーオブジェクト
                content: 投稿内容
                category: カテゴリ
                image_url: 画像URL（オプション）
                is_anonymous: 匿名設定
                is_private: 非公開設定
                
            Returns:
                int: 保存された投稿のID
                
            Raises:
                sqlite3.Error: データベース操作に失敗した場合
            """
            # 表示名を設定
            display_name = '匿名' if is_anonymous else user.display_name
            
            # 現在の日時を取得
            now = datetime.now().isoformat()
            
            # データベースに保存
            with self.bot.get_cog('Post')._get_db_connection() as conn:
                with conn:
                    with self.bot.get_cog('Post')._get_cursor(conn) as cursor:
                        cursor.execute('''
                            INSERT INTO thoughts (
                                user_id, content, category, image_url, 
                                is_anonymous, is_private, created_at, updated_at,
                                display_name
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        ''', (
                            user.id,
                            content,
                            category,
                            image_url,
                            is_anonymous,
                            is_private,
                            now,
                            now,
                            display_name
                        ))
                        
                        # 挿入された投稿のIDを取得
                        post_id = cursor.lastrowid
                        
                        # 画像URLが指定されている場合は添付ファイルとして保存
                        if image_url:
                            cursor.execute('''
                                INSERT INTO attachments (post_id, url)
                                VALUES (?, ?)
                            ''', (post_id, image_url))
                        
                        logger.info(f"投稿が保存されました: post_id={post_id}, user_id={user.id}")
                        return post_id
        
        async def on_submit(self, interaction: Interaction) -> None:
            """フォームが送信されたときに呼び出されます。
            
            Args:
                interaction: インタラクションオブジェクト
                
            Raises:
                Exception: 予期せぬエラーが発生した場合
            """
            # 既に応答済みの場合は何もしない
            if interaction.response.is_done():
                return
            
            try:
                # 即座に応答して処理中であることを伝える
                await interaction.response.defer(ephemeral=True)
                logger.debug("モーダルの送信を受信しました")
                
                # 入力値の検証
                try:
                    content, category, image_url, is_anonymous, is_private = \
                        await self._validate_inputs()
                except ValueError as e:
                    await interaction.followup.send(
                        f"❌ {str(e)}",
                        ephemeral=True
                    )
                    return
                
                # 投稿をデータベースに保存
                try:
                    post_id = await self._save_post_to_db(
                        user=interaction.user,
                        content=content,
                        category=category,
                        image_url=image_url,
                        is_anonymous=is_anonymous,
                        is_private=is_private
                    )
                except sqlite3.Error as e:
                    logger.error(f"データベースの保存中にエラーが発生しました: {e}", exc_info=True)
                    await interaction.followup.send(
                        "❌ 投稿の保存中にエラーが発生しました。しばらくしてからもう一度お試しください。",
                        ephemeral=True
                    )
                    return
                
                # 成功メッセージを送信
                try:
                    # 投稿内容のプレビューを作成
                    embed = self._create_post_embed(
                        content=content,
                        category=category,
                        image_url=image_url,
                        is_anonymous=is_anonymous,
                        post_id=post_id,
                        user=interaction.user
                    )
                    
                    # メッセージを送信
                    await interaction.followup.send(
                        "✅ 投稿が完了しました！",
                        embed=embed,
                        ephemeral=True
                    )
                    
                    logger.info(f"投稿が完了しました: post_id={post_id}, user_id={interaction.user.id}")
                    
                except Exception as e:
                    logger.error(f"メッセージ送信中にエラーが発生しました: {e}", exc_info=True)
                    await interaction.followup.send(
                        "✅ 投稿は保存されましたが、メッセージの送信中にエラーが発生しました。",
                        ephemeral=True
                    )
            
            except Exception as e:
                logger.critical("予期せぬエラーが発生しました", exc_info=True)
                try:
                    if not interaction.response.is_done():
                        await interaction.response.send_message(
                            "⚠️ 予期せぬエラーが発生しました。しばらくしてからもう一度お試しください。",
                            ephemeral=True
                        )
                    else:
                        await interaction.followup.send(
                            "⚠️ 予期せぬエラーが発生しました。しばらくしてからもう一度お試しください。",
                            ephemeral=True
                        )
                except Exception as e:
                    logger.error("エラーメッセージの送信中にエラーが発生しました", exc_info=True)
    
    def _create_post_embed(
        self,
        content: str,
        category: str,
        image_url: Optional[str],
        is_anonymous: bool,
        post_id: int,
        user: Union[User, Member]
    ) -> discord.Embed:
        """投稿用の埋め込みメッセージを作成します。
        
        Args:
            content: 投稿内容
            category: カテゴリ
            image_url: 画像URL（オプション）
            is_anonymous: 匿名設定
            post_id: 投稿ID
            user: 投稿者のユーザーオブジェクト
            
        Returns:
            discord.Embed: 作成された埋め込みメッセージ
        """
        # 埋め込みメッセージの作成
        embed = discord.Embed(
            description=content,
            color=discord.Color.blue(),
            timestamp=datetime.now()
        )
        
        # 投稿者情報を設定
        if is_anonymous:
            embed.set_author(name="匿名ユーザー", icon_url=DEFAULT_AVATAR)
        else:
            embed.set_author(
                name=user.display_name,
                icon_url=user.display_avatar.url if user.display_avatar else DEFAULT_AVATAR
            )
        
        # カテゴリーを追加
        embed.add_field(name="カテゴリー", value=category, inline=True)
        
        # 画像が指定されている場合は追加
        if image_url:
            embed.set_image(url=image_url)
        
        # フッターに投稿IDを設定
        embed.set_footer(text=f"ID: {post_id}")
        
        return embed

    class PostModal(ui.Modal, title='メッセージを投稿'):
        """投稿用のモーダルフォーム"""
        
        def __init__(self, bot: commands.Bot, *args: Any, **kwargs: Any) -> None:
            super().__init__(*args, **kwargs)
            self.bot = bot
            
            # メッセージ入力
            self.content = ui.TextInput(
                label=f'メッセージ (最大{MAX_CONTENT_LENGTH}文字)',
                style=discord.TextStyle.long,
                placeholder='メッセージを入力してください...',
                required=True,
                max_length=MAX_CONTENT_LENGTH,
                min_length=1
            )
            self.add_item(self.content)
            
            # カテゴリー入力
            self.category = ui.TextInput(
                label='カテゴリー',
                placeholder='例: 独り言, 愚痴, 悩み, アイデア など',
                required=False,
                max_length=MAX_CATEGORY_LENGTH
            )
            self.add_item(self.category)
            
            # 画像URL入力
            self.image_url = ui.TextInput(
                label='画像URL (任意)',
                placeholder='画像のURLを入力...',
                required=False
            )
            self.add_item(self.image_url)
            
            # 匿名設定
            self.is_anonymous = ui.TextInput(
                label='表示名',
                placeholder='名前を表示する場合は「表示」、匿名の場合は「匿名」と入力',
                default='表示',
                required=True,
                max_length=2
            )
            self.add_item(self.is_anonymous)
            
            # 公開設定
            self.is_private = ui.TextInput(
                label='公開設定',
                placeholder='公開する場合は「公開」、非公開の場合は「非公開」と入力',
                default='公開',
                required=True,
                max_length=3
            )
            self.add_item(self.is_private)
        
        async def on_submit(self, interaction: discord.Interaction) -> None:
            """フォームが送信されたときの処理"""
            # 入力値の検証
            try:
                content = self.content.value.strip()
                category = self.category.value.strip() if self.category.value else DEFAULT_CATEGORY
                image_url = self.image_url.value.strip() if self.image_url.value else None
                is_anonymous = self.is_anonymous.value.strip() == '匿名'
                # 公開設定を取得
                is_private = self.is_private.value.strip() == '非公開'
                
                # コンテンツの検証
                if not content:
                    await interaction.response.send_message(
                        "❌ メッセージを入力してください。",
                        ephemeral=True
                    )
                    return
                
                # 画像URLの検証
                if image_url and not image_url.startswith(('http://', 'https://')):
                    await interaction.response.send_message(
                        "❌ 画像URLは http:// または https:// で始まる必要があります。",
                        ephemeral=True
                    )
                    return
                
                # 投稿をデータベースに保存
                try:
                    post_id = await self.bot.get_cog('Post')._save_post_to_db(
                        user=interaction.user,
                        content=content,
                        category=category,
                        image_url=image_url,
                        is_anonymous=is_anonymous,
                        is_private=is_private
                    )
                    
                    # 投稿用の埋め込みメッセージを作成
                    embed = self._create_post_embed(
                        content=content,
                        category=category,
                        image_url=image_url,
                        is_anonymous=is_anonymous,
                        post_id=post_id,
                        user=interaction.user
                    )
                    
                    # 投稿を適切なチャンネルに送信
                    try:
                        # チャンネルを取得
                        target_channel_id = CHANNELS['private' if is_private else 'public']
                        target_channel = interaction.guild.get_channel(target_channel_id)
                        
                        if not target_channel:
                            raise ValueError(f"{'非公開' if is_private else '公開'}用のチャンネルが見つかりません")
                        
                        # チャンネルに投稿
                        await target_channel.send(embed=embed)
                        
                        # ユーザーに確認メッセージを送信
                        confirm_embed = discord.Embed(
                            title='✅ 投稿が完了しました',
                            description=f"{'非公開' if is_private else '公開'}チャンネルに投稿されました。",
                            color=discord.Color.green()
                        )
                        confirm_embed.add_field(name='投稿ID', value=str(post_id), inline=True)
                        confirm_embed.add_field(name='カテゴリー', value=category, inline=True)
                        confirm_embed.add_field(name='表示名', value='匿名' if is_anonymous else '表示', inline=True)
                        confirm_embed.add_field(name='公開設定', value='非公開 🔒' if is_private else '公開 🌐', inline=True)
                        confirm_embed.add_field(name='投稿先チャンネル', value=target_channel.mention, inline=False)
                        
                        await interaction.response.send_message(embed=confirm_embed, ephemeral=True)
                        
                    except Exception as e:
                        logger.error(f"チャンネルへの投稿中にエラーが発生しました: {e}", exc_info=True)
                        await interaction.response.send_message(
                            "✅ 投稿は保存されましたが、チャンネルへの投稿中にエラーが発生しました。",
                            ephemeral=True
                        )
                    
                except Exception as e:
                    logger.error(f"投稿の保存中にエラーが発生しました: {e}", exc_info=True)
                    await interaction.response.send_message(
                        "❌ 投稿の保存中にエラーが発生しました。しばらくしてからもう一度お試しください。",
                        ephemeral=True
                    )
            
            except Exception as e:
                logger.error(f"予期せぬエラーが発生しました: {e}", exc_info=True)
                await interaction.response.send_message(
                    "❌ 予期せぬエラーが発生しました。しばらくしてからもう一度お試しください。",
                    ephemeral=True
                )

    @app_commands.command(name="post", description="新しい投稿を作成します")
    @app_commands.describe()
    async def post(self, interaction: discord.Interaction):
        """新しい投稿を作成します"""
        # DMの場合は無効化
        if isinstance(interaction.channel, discord.DMChannel):
            await interaction.response.send_message(
                "❌ このコマンドはDMでは使用できません。サーバー内でお試しください。",
                ephemeral=True
            )
            return
            
        # モーダルを表示
        modal = self.PostModal(bot=self.bot)
        await interaction.response.send_modal(modal)


async def setup(bot):
    cog = Post(bot)
    await bot.add_cog(cog)
    print(f"[Post] Registered commands: {[cmd.name for cmd in cog.get_app_commands()]}")
