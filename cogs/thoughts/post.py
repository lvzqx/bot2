from __future__ import annotations

import logging
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple, Union

import discord
from discord import app_commands, ui
from discord.ext import commands

# 設定をインポート
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import CHANNELS, DEFAULT_AVATAR

# ロガーの設定
logger = logging.getLogger(__name__)

# 最大文字数制限
MAX_CONTENT_LENGTH = 2000
MAX_CATEGORY_LENGTH = 50
DEFAULT_CATEGORY = 'その他'

class Post(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
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
                
                conn.commit()
                logger.info("データベースの初期化が完了しました")

    @contextmanager
    def _get_db_connection(self) -> sqlite3.Connection:
        """データベース接続を取得するコンテキストマネージャ"""
        conn = sqlite3.connect(self.bot.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        except sqlite3.Error as e:
            logger.error(f"データベースエラー: {e}")
            conn.rollback()
            raise
        finally:
            conn.close()

    @contextmanager
    def _get_cursor(self, conn: sqlite3.Connection) -> sqlite3.Cursor:
        """カーソルを取得するコンテキストマネージャ"""
        cursor = conn.cursor()
        try:
            yield cursor
        finally:
            cursor.close()

    async def _save_post_to_db(self, user_id: int, message: str, category: Optional[str] = None, 
                            image_url: Optional[str] = None, is_public: bool = True, 
                            is_anonymous: bool = False) -> int:
        """投稿をデータベースに保存し、投稿IDを返します"""
        try:
            with self._get_db_connection() as conn:
                with self._get_cursor(conn) as cursor:
                    cursor.execute(''' 
                        INSERT INTO thoughts (
                            user_id, content, category, image_url, 
                            is_anonymous, is_private, created_at, updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?, datetime('now'), datetime('now'))
                    ''', (user_id, message, category, image_url, 1 if is_anonymous else 0, 1 if not is_public else 0))
                    conn.commit()
                    return cursor.lastrowid
        except sqlite3.Error as e:
            logger.error(f"データベースへの投稿保存中にエラーが発生しました: {e}")
            raise

    class VisibilitySelect(ui.Select):
        def __init__(self):
            options = [
                discord.SelectOption(label='公開', value='public', description='誰でも見ることができます', emoji='👥'),
                discord.SelectOption(label='非公開', value='private', description='自分と管理者のみが削除できます', emoji='🔒')
            ]
            super().__init__(
                placeholder='公開設定を選択...',
                min_values=1,
                max_values=1,
                options=options
            )
            self.value = 'public'  # デフォルト値
            
        async def callback(self, interaction: discord.Interaction):
            self.value = self.values[0]
            await interaction.response.defer()
    
    class PostModal(ui.Modal, title='新規投稿'):
        def __init__(self, bot: commands.Bot) -> None:
            super().__init__(timeout=300)
            self.bot = bot
            self.is_public = True  # デフォルトは公開
            
            # メッセージ入力
            self.message = ui.TextInput(
                label='メッセージ',
                placeholder='投稿するメッセージを入力してください...',
                style=discord.TextStyle.paragraph,
                max_length=1000,
                required=True
            )
            self.add_item(self.message)
            
            # カテゴリ入力
            self.category = ui.TextInput(
                label='カテゴリ',
                placeholder='カテゴリを入力（例: 独り言, 愚痴, 考えごと など）',
                max_length=50,
                required=False
            )
            self.add_item(self.category)
            
            # 画像URL入力
            self.image_url = ui.TextInput(
                label='画像URL（任意）',
                placeholder='画像のURLを入力（https://...）',
                required=False
            )
            self.add_item(self.image_url)
            
            # 公開/非公開選択（ビューとして追加）
            self.visibility_select = self.VisibilitySelect()
            self.visibility_view = ui.View(timeout=300)
            self.visibility_view.add_item(self.visibility_select)
            
            # 匿名設定
            self.anonymous = ui.TextInput(
                label='表示名（任意）',
                placeholder='「匿名」と入力すると匿名で投稿します',
                required=False
            )
            self.add_item(self.anonymous)

        async def on_submit(self, interaction: discord.Interaction) -> None:
            await interaction.response.defer(ephemeral=True)
            
            try:
                # 入力値の検証
                message = self.message.value.strip()
                if not message:
                    await interaction.followup.send(
                        "❌ メッセージを入力してください。",
                        ephemeral=True
                    )
                    return
                
                category = self.category.value.strip() if self.category.value else None
                image_url = self.image_url.value.strip() if self.image_url.value else None
                is_public = self.visibility_select.value == 'public'
                is_anonymous = self.anonymous.value.strip().lower() == '匿名' if self.anonymous.value else False
                
                # 画像URLの検証
                if image_url and not image_url.startswith(('http://', 'https://')):
                    await interaction.followup.send(
                        "❌ 画像URLは http:// または https:// で始まる必要があります。",
                        ephemeral=True
                    )
                    return
                
                # データベースに保存
                post_cog = self.bot.get_cog('Post')
                if not post_cog:
                    raise ValueError("Postコグが見つかりません")
                    
                is_anonymous = self.anonymous.value.strip().lower() == '匿名' if self.anonymous.value else False
                
                post_id = await post_cog._save_post_to_db(
                    interaction.user.id,
                    message,
                    category,
                    image_url,
                    is_public,
                    is_anonymous
                )
                
                # 公開/非公開でチャンネルを分ける
                if is_public:
                    # 公開チャンネルに投稿
                    channel = interaction.guild.get_channel(CHANNELS['public'])
                    if not channel:
                        raise ValueError("公開用の投稿チャンネルが見つかりません")
                    
                    # 埋め込みメッセージを作成
                    embed = await post_cog._create_post_embed(
                        post_id,
                        interaction.user.id,
                        message,
                        category,
                        image_url,
                        is_public,
                        is_anonymous
                    )
                    
                    # メッセージを送信
                    sent_message = await channel.send(embed=embed)
                else:
                    # 非公開チャンネルを取得
                    private_channel = interaction.guild.get_channel(CHANNELS['private'])
                    if not private_channel:
                        raise ValueError("非公開用の投稿チャンネルが見つかりません")
                    
                    # 非公開チャンネルに投稿
                    embed = discord.Embed(
                        description=message,
                        color=discord.Color.dark_grey()
                    )
                    
                    # 投稿者情報を追加（匿名設定に応じて表示を変更）
                    if is_anonymous:
                        embed.set_author(name="匿名ユーザー", icon_url=DEFAULT_AVATAR)
                    else:
                        embed.set_author(name=str(interaction.user), icon_url=interaction.user.display_avatar.url)
                    
                    # カテゴリを追加
                    if category:
                        embed.add_field(name="カテゴリ", value=category, inline=True)
                    
                    # 投稿IDを追加
                    embed.add_field(name="投稿ID", value=f"`{post_id}`", inline=True)
                    
                    # 画像を追加（ある場合）
                    if image_url:
                        embed.set_image(url=image_url)
                    
                    # 非公開チャンネルに送信
                    sent_message = await private_channel.send(embed=embed)
                    
                    # 投稿者には通常の完了メッセージを送信
                    embed = discord.Embed(
                        title="✅ 非公開で投稿が完了しました！",
                        description=f"この投稿は管理者のみが閲覧できます。",
                        color=discord.Color.green()
                    )
                    embed.add_field(name="ID", value=f"`{post_id}`", inline=True)
                    if category:
                        embed.add_field(name="カテゴリ", value=f"`{category}`", inline=True)
                    
                    await interaction.followup.send(embed=embed, ephemeral=False)
                    
                    # データベースには通常のチャンネルIDを保存
                    channel = private_channel
                    
                    # データベースには通常のチャンネルIDを保存（実際の投稿先は非公開チャンネル）
                    channel = private_channel
                
                # メッセージ参照を保存
                with post_cog._get_db_connection() as conn:
                    with post_cog._get_cursor(conn) as cursor:
                        cursor.execute('''
                            INSERT INTO message_references (
                                channel_id, message_id, post_id, is_public
                            ) VALUES (?, ?, ?, ?)
                        ''', (
                            str(channel.id),
                            str(sent_message.id),
                            post_id,
                            1 if is_public else 0
                        ))
                        conn.commit()
                
                # 公開投稿の場合のみ完了メッセージを送信（非公開は既に送信済み）
                if is_public:
                    embed = discord.Embed(
                        title="✅ 投稿が完了しました！",
                        description=f"[メッセージにジャンプ]({sent_message.jump_url})",
                        color=discord.Color.green()
                    )
                    embed.add_field(name="ID", value=f"`{post_id}`", inline=True)
                    if category:
                        embed.add_field(name="カテゴリ", value=f"`{category}`", inline=True)
                    embed.add_field(name="表示名", value=f"`{'匿名' if is_anonymous else '表示'}`", inline=True)
                    
                    await interaction.followup.send(embed=embed, ephemeral=True)
                
            except Exception as e:
                logger.error(f"投稿中にエラーが発生しました: {e}", exc_info=True)
                await interaction.followup.send(
                    "❌ 投稿中にエラーが発生しました。しばらくしてからもう一度お試しください。",
                    ephemeral=True
                )

    @app_commands.command(name="post", description="新しい投稿を作成します")
    @app_commands.guild_only()
    async def post(self, interaction: discord.Interaction) -> None:
        """新しい投稿を作成します"""
        logger.info(f"post コマンドが呼び出されました。ユーザー: {interaction.user}")
        # モーダルを表示
        await interaction.response.send_modal(self.PostModal(self.bot))

async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Post(bot))
    logger.info("Post cog が読み込まれました")
