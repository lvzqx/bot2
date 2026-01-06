from __future__ import annotations

import logging
import sqlite3
from contextlib import contextmanager
from typing import Optional, Tuple

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

class Post(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        logger.info("Post cog が初期化されました")

class PostModal(ui.Modal, title='新規投稿'):
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
            
    def __init__(self) -> None:
        super().__init__(timeout=300)  # 明示的にタイムアウトを設定
        
        # メッセージ入力
        self.message = ui.TextInput(
            label='メッセージ',
            placeholder='投稿するメッセージを入力してください...',
            style=discord.TextStyle.paragraph,
            max_length=2000,
            required=True
        )
        
        # カテゴリ入力
        self.category = ui.TextInput(
            label='カテゴリ',
            placeholder='カテゴリを入力（例: 独り言, 愚痴, 考えごと など）',
            max_length=50,
            required=False
        )
        
        # 画像URL入力
        self.image_url = ui.TextInput(
            label='画像URL（任意）',
            placeholder='画像のURLを入力（https://...）',
            required=False
        )
        
        # 匿名設定
        self.anonymous = ui.TextInput(
            label='表示設定',
            placeholder='「匿名」で匿名投稿、「名義」で名前を表示',
            default='名義',
            required=True
        )
        
        # 公開/非公開選択
        self.visibility = ui.TextInput(
            label='公開設定',
            placeholder='「公開」または「非公開」と入力してください',
            default='公開',
            required=True
        )
        
        # UIコンポーネントを追加（指定された順序で）
        self.add_item(self.message)         # メッセージ入力
        self.add_item(self.category)        # カテゴリ入力
        self.add_item(self.image_url)       # 画像URL入力
        self.add_item(self.anonymous)       # 匿名設定
        self.add_item(self.visibility)      # 公開/非公開選択

    async def on_submit(self, interaction: discord.Interaction) -> None:
        """フォームが送信されたときの処理"""
        await interaction.response.defer(ephemeral=True)
        
        # モーダルから値を取得
        message = self.message.value
        category = self.category.value if self.category.value else None
        image_url = self.image_url.value if self.image_url.value else None
        is_public = self.visibility.value == '公開'
        is_anonymous = self.anonymous.value == '匿名'
        
        # データベースに保存
        try:
            post_cog = interaction.client.get_cog('Post')
            if not post_cog:
                await interaction.followup.send(
                    "❌ エラーが発生しました。もう一度お試しください。",
                    ephemeral=True
                )
                return
            
            # 投稿をデータベースに保存
            post_id = await post_cog._save_post_to_db(
                user_id=interaction.user.id,
                message=message,
                category=category,
                image_url=image_url,
                is_public=is_public,
                is_anonymous=is_anonymous
            )
            
            # 投稿先チャンネルを決定
            channel_id = CHANNELS['public'] if is_public else CHANNELS['private']
            channel = interaction.guild.get_channel(channel_id)
            
            if not channel:
                await interaction.followup.send(
                    "❌ 投稿先チャンネルが見つかりませんでした。",
                    ephemeral=True
                )
                return
            
            # 埋め込みメッセージを作成
            embed = discord.Embed(description=message)
            
            # 投稿者情報を追加
            if is_anonymous:
                embed.set_author(name="匿名", icon_url=DEFAULT_AVATAR)
            else:
                embed.set_author(
                    name=f"{interaction.author.name}",
                    icon_url=interaction.author.display_avatar.url
                )
            
            # 画像を追加（ある場合）
            if image_url:
                embed.set_image(url=image_url)
            
            # カテゴリを追加（ある場合）
            if category:
                embed.add_field(name="📁 カテゴリ", value=category, inline=False)
            
            # メッセージを送信
            if is_public:
                # 公開投稿は通常通りチャンネルにメッセージを送信
                sent_message = await channel.send(embed=embed)
            else:
                # 非公開投稿の場合のみスレッドを作成
                thread_name = f"非公開投稿 - {interaction.user.name}"
                if category:
                    thread_name += f" - {category}"
                
                try:
                    # スレッドを作成
                    thread = await channel.create_thread(
                        name=thread_name[:100],  # スレッド名は100文字まで
                        type=discord.ChannelType.private_thread,
                        reason=f"非公開投稿のスレッド作成 - {interaction.user.id}",
                        invitable=False  # 招待を無効化
                    )
                    
                    # 投稿者をスレッドに追加
                    await thread.add_user(interaction.user)
                    
                    # 「非公開」ロールを検索
                    private_role = discord.utils.get(interaction.guild.roles, name="非公開")
                    if private_role:
                        # ロールを持つメンバーをスレッドに追加
                        for member in private_role.members:
                            if member != interaction.user:  # 投稿者は既に追加済み
                                try:
                                    await thread.add_user(member)
                                    logger.info(f"ユーザー {member} をスレッドに追加しました")
                                except Exception as e:
                                    logger.warning(f"ユーザー {member} をスレッドに追加できませんでした: {e}")
                    else:
                        logger.warning("「非公開」ロールが見つかりませんでした")
                    
                except Exception as e:
                    logger.error(f"スレッド作成中にエラーが発生しました: {e}")
                    await interaction.followup.send(
                        "❌ 非公開スレッドの作成に失敗しました。しばらくしてからもう一度お試しください。",
                        ephemeral=True
                    )
                    return
                
                # スレッドにメッセージを送信
                sent_message = await thread.send(embed=embed)
                
                # スレッドのチャンネルIDを取得
                channel = thread
            
            # メッセージ参照を保存
            with post_cog._get_db_connection() as conn:
                with post_cog._get_cursor(conn) as cursor:
                    cursor.execute('''
                        INSERT INTO message_references (
                            channel_id, message_id, post_id
                        ) VALUES (?, ?, ?)
                    ''', (
                        str(channel.id),
                        str(sent_message.id),
                        post_id
                    ))
                    conn.commit()
            
            # 完了メッセージを送信
            embed = discord.Embed(
                title="✅ 投稿が完了しました！",
                description=f"[メッセージにジャンプ]({sent_message.jump_url})",
                color=discord.Color.green()
            )
            embed.add_field(name="ID", value=f"`{post_id}`", inline=True)
            if category:
                embed.add_field(name="カテゴリ", value=f"`{category}`", inline=True)
            embed.add_field(name="表示名", value=f"`{'匿名' if is_anonymous else '名義'}`", inline=True)
            
            await interaction.followup.send(embed=embed, ephemeral=True)
            
        except Exception as e:
            logger.error(f"投稿中にエラーが発生しました: {e}", exc_info=True)
            await interaction.followup.send(
                "❌ 投稿中にエラーが発生しました。しばらくしてからもう一度お試しください。",
                ephemeral=True
            )

class Post(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        logger.info("Post cog が初期化されました")

    @app_commands.command(name="post", description="新しい投稿を作成します")
    @app_commands.guild_only()
    async def post(self, interaction: discord.Interaction) -> None:
        """新しい投稿を作成します"""
        try:
            logger.info(f"post コマンドが呼び出されました。ユーザー: {interaction.user}")
            
            # モーダルのインスタンスを作成
            try:
                modal = PostModal()
                logger.info("モーダルのインスタンス化に成功しました")
            except Exception as e:
                logger.error(f"モーダルのインスタンス化に失敗しました: {e}", exc_info=True)
                if not interaction.response.is_done():
                    await interaction.response.send_message(
                        f"エラー: モーダルの作成に失敗しました。\n```{str(e)}```",
                        ephemeral=True
                    )
                return
            
            # モーダルを表示
            try:
                await interaction.response.send_modal(modal)
                logger.info("モーダルを表示しました")
            except Exception as e:
                logger.error(f"モーダルの表示中にエラーが発生しました: {e}", exc_info=True)
                if not interaction.response.is_done():
                    await interaction.response.send_message(
                        f"エラー: モーダルの表示に失敗しました。\n```{str(e)}```",
                        ephemeral=True
                    )
        except Exception as e:
            logger.error(f"予期しないエラーが発生しました: {e}", exc_info=True)
            if not interaction.response.is_done():
                await interaction.response.send_message(
                    f"予期しないエラーが発生しました: {str(e)}",
                    ephemeral=True
                )

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
        def __init__(self) -> None:
            super().__init__(timeout=300)  # 明示的にタイムアウトを設定
            self.is_public = True  # デフォルトは公開
            
            # メッセージ入力
            self.message = ui.TextInput(
                label='メッセージ',
                placeholder='投稿するメッセージを入力してください...',
                style=discord.TextStyle.paragraph,
                max_length=2000,
                required=True
            )
            
            # カテゴリ入力
            self.category = ui.TextInput(
                label='カテゴリ',
                placeholder='カテゴリを入力（例: 独り言, 愚痴, 考えごと など）',
                max_length=50,
                required=False
            )
            
            # 画像URL入力
            self.image_url = ui.TextInput(
                label='画像URL（任意）',
                placeholder='画像のURLを入力（https://...）',
                required=False
            )
            
            # 匿名設定
            self.anonymous = ui.TextInput(
                label='表示名（任意）',
                placeholder='「匿名」と入力すると匿名で投稿します',
                required=False
            )
            
            # UIコンポーネントを追加
            self.add_item(self.message)
            self.add_item(self.category)
            self.add_item(self.image_url)
            self.add_item(self.anonymous)
            
            # 公開/非公開選択（ビューとして追加）
            self.visibility_select = Post.VisibilitySelect()
            self.visibility_view = ui.View(timeout=300)
            self.visibility_view.add_item(self.visibility_select)

        async def on_submit(self, interaction: discord.Interaction) -> None:
            """フォームが送信されたときの処理"""
            await interaction.response.defer(ephemeral=True)
            
            # モーダルから値を取得
            message = self.message.value
            category = self.category.value if self.category.value else None
            image_url = self.image_url.value if self.image_url.value else None
            is_public = self.visibility_select.value == 'public'
            is_anonymous = self.anonymous.value.lower() == '匿名'
            
            # データベースに保存
            try:
                post_cog = interaction.client.get_cog('Post')
                if not post_cog:
                    await interaction.followup.send(
                        "❌ エラーが発生しました。もう一度お試しください。",
                        ephemeral=True
                    )
                    return
                
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
                    embed = discord.Embed(
                        description=message,
                        color=discord.Color.blue()
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
                
                # メッセージ参照を保存
                with post_cog._get_db_connection() as conn:
                    with post_cog._get_cursor(conn) as cursor:
                        cursor.execute('''
                            INSERT INTO message_references (
                                channel_id, message_id, post_id
                            ) VALUES (?, ?, ?)
                        ''', (
                            str(channel.id),
                            str(sent_message.id),
                            post_id
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

async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Post(bot))
    logger.info("Post cog が読み込まれました")
