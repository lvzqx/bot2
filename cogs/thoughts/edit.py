from __future__ import annotations

import logging
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from typing import Any, Dict, Iterator, List, Literal, Optional, Tuple, TypedDict, Union, cast
from urllib.parse import urlparse
from config import CHANNELS, DEFAULT_AVATAR

import discord
from discord import app_commands, ui, Interaction, Embed, ButtonStyle
from discord.ext import commands
from bot import DatabaseMixin  # Added DatabaseMixin import

# ロガーの設定
logger = logging.getLogger(__name__)

# 定数
MAX_CONTENT_LENGTH = 2000  # Discordのメッセージ最大文字数
MAX_CATEGORY_LENGTH = 100  # カテゴリーの最大文字数

# 型定義
class PostData(TypedDict):
    """投稿データの型定義"""
    id: int
    content: str
    category: str
    image_url: Optional[str]
    is_anonymous: bool
    is_private: bool
    user_id: int
    display_name: Optional[str]
    created_at: Optional[str]
    updated_at: Optional[str]

class Edit(commands.Cog, DatabaseMixin):
    """投稿編集機能を提供するCog
    
    Attributes:
        bot: Discord Bot インスタンス
    """
    
    def __init__(self, bot: commands.Bot) -> None:
        """Edit Cog を初期化します。
        
        Args:
            bot: Discord Bot インスタンス
        """
        self.bot: commands.Bot = bot
        DatabaseMixin.__init__(self)
        logger.info("Edit cog が初期化されました")
    
    @contextmanager
    def _get_db_connection(self) -> Iterator[sqlite3.Connection]:
        """データベース接続を取得します。
        
        Yields:
            sqlite3.Connection: データベース接続
        """
        try:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA foreign_keys = ON")
            yield conn
        except sqlite3.Error as e:
            logger.error(f"データベース接続エラー: {e}", exc_info=True)
            raise
        finally:
            if 'conn' in locals():
                conn.close()
    
    @contextmanager
    def _get_cursor(self, conn: sqlite3.Connection) -> Iterator[sqlite3.Cursor]:
        """データベースカーソルを取得します。
        
        Args:
            conn: データベース接続
            
        Yields:
            sqlite3.Cursor: データベースカーソル
        """
        try:
            cursor = conn.cursor()
            yield cursor
        except sqlite3.Error as e:
            logger.error(f"カーソル操作エラー: {e}", exc_info=True)
            raise
        finally:
            if 'cursor' in locals():
                cursor.close()
    
    class EditModal(ui.Modal):
        """投稿編集用のモーダル
        
        Attributes:
            bot: Discord Bot インスタンス
            post_id: 編集する投稿のID
            _interaction: インタラクションオブジェクト
            _is_anonymous: 匿名設定
            _is_private: 非公開設定
        """
        
        def __init__(
            self, 
            bot: commands.Bot,
            post_id: int, 
            current_content: str, 
            current_category: str, 
            current_image_url: Optional[str] = None, 
            current_is_anonymous: bool = False, 
            current_is_private: bool = False,
            *args: Any, 
            **kwargs: Any
        ) -> None:
            """EditModal を初期化します。
            
            Args:
                bot: Discord Bot インスタンス
                post_id: 編集する投稿のID
                current_content: 現在の投稿内容
                current_category: 現在のカテゴリ
                current_image_url: 現在の画像URL（オプション）
                current_is_anonymous: 現在の匿名設定
                current_is_private: 現在の公開設定
            """
            super().__init__(title=f"投稿を編集 (ID: {post_id})", timeout=600)  # 10分でタイムアウト
            
            self.bot: commands.Bot = bot
            self.post_id: int = post_id
            self._interaction: Optional[discord.Interaction] = None
            
            # 状態管理
            self._is_anonymous: bool = bool(current_is_anonymous)
            self._is_private: bool = bool(current_is_private)
            
            # デバッグログ
            print(f"[DEBUG] EditModal初期化: is_anonymous={self._is_anonymous}, is_private={self._is_private}")
            print(f"[DEBUG] 受け取った値: current_is_anonymous={current_is_anonymous}, current_is_private={current_is_private}")
            
            # コンポーネントの作成
            self.content = self.content_input = ui.TextInput(
                label="投稿内容",
                style=discord.TextStyle.paragraph,
                placeholder="投稿内容を入力してください...",
                default=current_content,
                max_length=MAX_CONTENT_LENGTH,
                required=True
            )
            
            self.category = self.category_input = ui.TextInput(
                label="カテゴリー（任意）",
                style=discord.TextStyle.short,
                placeholder="例: 独り言, 愚痴, 考えごと など",
                default=current_category or "",
                max_length=MAX_CATEGORY_LENGTH,
                required=False
            )
            
            self.image_url = self.image_url_input = ui.TextInput(
                label="画像URL（任意）",
                style=discord.TextStyle.short,
                placeholder="https://example.com/image.jpg",
                default=current_image_url or "",
                required=False
            )
            
            # コンポーネントを追加
            self.add_item(self.content_input)
            self.add_item(self.category_input)
            self.add_item(self.image_url_input)
        
        @contextmanager
        def _get_db_connection(self) -> Iterator[sqlite3.Connection]:
            """データベース接続を取得します。
            
            Yields:
                sqlite3.Connection: データベース接続
            """
            try:
                conn = sqlite3.connect(self.bot.db_path)
                conn.row_factory = sqlite3.Row
                conn.execute("PRAGMA foreign_keys = ON")
                yield conn
            except sqlite3.Error as e:
                logger.error(f"データベース接続エラー: {e}", exc_info=True)
                raise
            finally:
                if 'conn' in locals():
                    conn.close()

        def _ensure_thoughts_display_name_column(self, cursor: sqlite3.Cursor) -> None:
            try:
                cursor.execute("PRAGMA table_info(thoughts)")
                cols = {row[1] for row in cursor.fetchall()}
                if 'display_name' not in cols:
                    cursor.execute("ALTER TABLE thoughts ADD COLUMN display_name TEXT")
            except sqlite3.Error as e:
                logger.error(f"display_name カラム確認/追加に失敗しました: {e}", exc_info=True)
        
        @contextmanager
        def _get_cursor(self, conn: sqlite3.Connection) -> Iterator[sqlite3.Cursor]:
            """データベースカーソルを取得します。
            
            Args:
                conn: データベース接続
                
            Yields:
                sqlite3.Cursor: データベースカーソル
            """
            try:
                cursor = conn.cursor()
                yield cursor
            except sqlite3.Error as e:
                logger.error(f"カーソル操作エラー: {e}", exc_info=True)
                raise
            finally:
                if 'cursor' in locals():
                    cursor.close()
        
        
        async def on_submit(self, interaction: discord.Interaction) -> None:
            """フォームの送信を処理します。
            
            Args:
                interaction: インタラクションオブジェクト
            """
            print(f"[DEBUG] on_submit が呼び出されました: post_id={self.post_id}")
            print(f"[DEBUG] on_submit時の匿名状態: is_anonymous={self._is_anonymous}")
            self._interaction = interaction
            
            # 入力値のバリデーション
            content = self.content_input.value.strip()
            category = self.category_input.value.strip() if self.category_input.value else None
            image_url = self.image_url_input.value.strip() if self.image_url_input.value else None
            display_name = None  # 表示名はDBから取得するため入力しない
            
            if not content:
                await interaction.response.send_message(
                    "投稿内容を入力してください。",
                    ephemeral=True
                )
                return
            
            # 画像URLのバリデーション
            if image_url and not self._is_valid_url(image_url):
                await interaction.response.send_message(
                    "無効な画像URLです。正しいURLを入力してください。",
                    ephemeral=True
                )
                return
            
            # 編集処理を実行
            await self._edit_post(interaction, content, category, image_url, display_name)
        
        def _is_valid_url(self, url: str) -> bool:
            """URLが有効かどうかを検証します。
            
            Args:
                url: 検証するURL
                
            Returns:
                bool: URLが有効な場合はTrue、それ以外はFalse
            """
            try:
                result = urlparse(url)
                return all([result.scheme, result.netloc])
            except ValueError:
                return False
        
        async def _edit_post(
            self, 
            interaction: discord.Interaction, 
            content: str, 
            category: Optional[str], 
            image_url: Optional[str],
            display_name: Optional[str]
        ) -> None:
            """投稿を編集します。
            
            Args:
                interaction: インタラクションオブジェクト
                content: 投稿内容
                category: カテゴリー
                image_url: 画像URL
                display_name: 表示名（任意）
            """
            try:
                # データベース接続を取得
                with self._get_db_connection() as conn:
                    with self._get_cursor(conn) as cursor:
                        self._ensure_thoughts_display_name_column(cursor)
                        # 投稿を更新
                        print(f"[DEBUG] データベース更新前: is_anonymous={self._is_anonymous}, is_private={self._is_private}")
                        cursor.execute("""
                            UPDATE thoughts 
                            SET content = ?, 
                                category = ?, 
                                image_url = ?, 
                                is_anonymous = ?, 
                                is_private = ?,
                                updated_at = CURRENT_TIMESTAMP
                            WHERE id = ?
                        """, (
                            content,
                            category,
                            image_url,
                            int(self._is_anonymous),
                            int(self._is_private),
                            self.post_id
                        ))
                        print(f"[DEBUG] データベース更新完了: rowcount={cursor.rowcount}")
                        
                        if cursor.rowcount == 0:
                            await interaction.response.send_message(
                                "投稿の更新に失敗しました。投稿が見つかりません。",
                                ephemeral=True
                            )
                            return
                        
                        conn.commit()
                
                # Discordメッセージを更新（エラーが無視されるように）
                print(f"[DEBUG] Discordメッセージ更新を開始します: post_id={self.post_id}")
                message_update_error: Optional[str] = None
                try:
                    print(f"[DEBUG] _update_discord_message を呼び出します")
                    await self._update_discord_message(interaction, content, category, image_url)
                    print(f"[DEBUG] Discordメッセージ更新が完了しました")
                except Exception as e:
                    logger.warning(f"Discordメッセージの更新に失敗しましたが、データベースは更新されています: {e}", exc_info=True)
                    print(f"[DEBUG] Discordメッセージ更新エラー: {e}")
                    # NOTE: Modal interaction では response 前の followup が失敗することがあるため、
                    # ここでは followup を送らず、最終レスポンスに必ず含める。
                    message_update_error = str(e)
                print(f"[DEBUG] Discordメッセージ更新処理を終了します")
                
                # 成功メッセージを送信
                if message_update_error:
                    await interaction.response.send_message(
                        f"⚠️ 投稿内容はデータベースに保存されましたが、Discordメッセージの編集に失敗しました。\n"
                        f"投稿ID: {self.post_id}\n"
                        f"理由: {message_update_error}",
                        ephemeral=True
                    )
                else:
                    await interaction.response.send_message(
                        f"✅ 投稿を更新しました！ (ID: {self.post_id})",
                        ephemeral=True
                    )
                
                logger.info(f"投稿を更新しました: id={self.post_id}")
                
            except sqlite3.Error as e:
                logger.error(f"データベースエラーが発生しました: {e}", exc_info=True)
                if not interaction.response.is_done():
                    await interaction.response.send_message(
                        "投稿の更新中にデータベースエラーが発生しました。",
                        ephemeral=True
                    )
            except Exception as e:
                logger.error(f"投稿の更新中にエラーが発生しました: {e}", exc_info=True)
                if not interaction.response.is_done():
                    await interaction.response.send_message(
                        "投稿の更新中にエラーが発生しました。",
                        ephemeral=True
                    )
        
        async def _update_discord_message(
            self, 
            interaction: discord.Interaction, 
            content: str, 
            category: Optional[str], 
            image_url: Optional[str]
        ) -> None:
            """Discordのメッセージを更新します。
            
            Args:
                interaction: インタラクションオブジェクト
                content: 投稿内容
                category: カテゴリー
                image_url: 画像URL
            """
            try:
                with self._get_db_connection() as conn:
                    with self._get_cursor(conn) as cursor:
                        self._ensure_thoughts_display_name_column(cursor)
                        cursor.execute("""
                            SELECT message_id, channel_id 
                            FROM message_references 
                            WHERE post_id = ?
                        """, (self.post_id,))
                        
                        message_ref = cursor.fetchone()
                        if not message_ref:
                            print(f"[DEBUG] Post {self.post_id} のメッセージ参照が見つかりません")
                            logger.warning(f"Post {self.post_id} のメッセージ参照が見つかりません")
                            logger.info(f"現在のメッセージ参照を確認します...")
                            cursor.execute('SELECT post_id, message_id, channel_id FROM message_references LIMIT 5')
                            refs = cursor.fetchall()
                            print(f"[DEBUG] メッセージ参照一覧: {refs}")
                            logger.info(f"メッセージ参照一覧: {refs}")
                            raise RuntimeError(f"message_references が見つかりません (post_id={self.post_id})")
                            
                        message_id, channel_id = message_ref
                        print(f"[DEBUG] メッセージ更新を試行: post_id={self.post_id}, message_id={message_id}, channel_id={channel_id}")
                        logger.info(f"メッセージ更新を試行: post_id={self.post_id}, message_id={message_id}, channel_id={channel_id}")
                        
                        # チャンネルを取得（キャッシュから取得できない場合はfetch）
                        channel = self.bot.get_channel(int(channel_id))
                        if not channel:
                            try:
                                channel = await self.bot.fetch_channel(int(channel_id))
                            except Exception as e:
                                raise RuntimeError(f"チャンネル取得に失敗しました (channel_id={channel_id}): {e}")
                        
                        if not channel:
                            raise RuntimeError(f"チャンネルが見つかりません (channel_id={channel_id})")
                            
                        try:
                            message = await channel.fetch_message(int(message_id))
                        except discord.NotFound:
                            raise RuntimeError(f"メッセージが見つかりません (message_id={message_id})")
                        except discord.Forbidden:
                            raise RuntimeError(f"メッセージへのアクセス権限がありません (message_id={message_id})")
                        
                        # 埋め込みメッセージを作成
                        embed = discord.Embed(
                            description=content,
                            color=discord.Color.blue()
                        )
                        
                        # 表示名を設定
                        print(f"[DEBUG] メッセージ更新時: is_anonymous={self._is_anonymous}")

                        # DBから投稿者情報を取得（管理者編集でも投稿者情報を維持する）
                        cursor.execute(
                            'SELECT user_id, is_anonymous, display_name FROM thoughts WHERE id = ?',
                            (self.post_id,)
                        )
                        row = cursor.fetchone()
                        if not row:
                            raise RuntimeError(f"投稿が見つかりません (post_id={self.post_id})")

                        post_user_id, db_is_anonymous, db_display_name = row
                        current_db_anonymous = bool(db_is_anonymous)
                        print(f"[DEBUG] データベース現在値: is_anonymous={current_db_anonymous}, display_name={db_display_name}, user_id={post_user_id}")

                        if current_db_anonymous:
                            embed.set_author(name='匿名ユーザー', icon_url=DEFAULT_AVATAR)
                            print(f"[DEBUG] データベース値で匿名ユーザー: {DEFAULT_AVATAR}")
                        else:
                            author_user = self.bot.get_user(int(post_user_id))
                            if author_user is None:
                                try:
                                    author_user = await self.bot.fetch_user(int(post_user_id))
                                except Exception:
                                    author_user = None

                            author_name = (db_display_name or None)
                            if not author_name:
                                author_name = str(author_user) if author_user else f"User {post_user_id}"

                            author_icon = None
                            if author_user:
                                try:
                                    author_icon = author_user.display_avatar.url
                                except Exception:
                                    author_icon = None

                            if author_icon:
                                embed.set_author(name=author_name, icon_url=author_icon)
                            else:
                                embed.set_author(name=author_name)
                            print(f"[DEBUG] データベース値で通常ユーザー: {author_name}")
                        
                        # フッターにカテゴリーと投稿IDを表示
                        # フッター設定（カテゴリーがない場合はIDのみ）
                        # UIDを取得してfooterに含める
                        cursor.execute('SELECT user_id FROM thoughts WHERE id = ?', (self.post_id,))
                        user_id_row = cursor.fetchone()
                        user_id = user_id_row[0] if user_id_row else interaction.user.id
                        
                        if category:
                            embed.set_footer(text=f'カテゴリー: {category} | 投稿ID: {self.post_id} | UID: {user_id}')
                        else:
                            embed.set_footer(text=f'投稿ID: {self.post_id} | UID: {user_id}')
                        
                        # 画像があれば追加
                        if image_url:
                            embed.set_image(url=image_url)
                        
                        await message.edit(embed=embed)
                        print(f"[DEBUG] メッセージを更新しました: post_id={self.post_id}, message_id={message_id}")
                        logger.info(f"メッセージを更新しました: post_id={self.post_id}, message_id={message_id}")
                        
                        # 非公開投稿の場合はスレッドの最初のメッセージも更新
                        # if self._is_private:
                        #     try:
                        #         # スレッドの場合はスレッド自体の名前も更新
                        #         if hasattr(channel, 'thread') and channel.thread:
                        #             thread = channel.thread
                        #         elif isinstance(channel, discord.Thread):
                        #             thread = channel
                        #         else:
                        #             thread = None
                        #         
                        #         if thread:
                        #             preview = content[:50] + ('...' if len(content) > 50 else '')
                        #             await thread.edit(name=f"非公開投稿 - ID: {self.post_id} - {preview}")
                        #             logger.info(f"スレッド名を更新しました: post_id={self.post_id}")
                        #     except Exception as e:
                        #         logger.warning(f"スレッド名の更新に失敗しました: {e}")
                        
            except Exception as e:
                logger.error(f"Discordメッセージの更新中にエラーが発生しました: {e}", exc_info=True)
        
        async def on_error(self, interaction: discord.Interaction, error: Exception) -> None:
            """エラーが発生した際に呼び出されます。
            
            Args:
                interaction: インタラクションオブジェクト
                error: 発生した例外
            """
            logger.error(f"モーダル処理中にエラーが発生しました: {error}", exc_info=True)
            if not interaction.response.is_done():
                await interaction.response.send_message(
                    f"エラーが発生しました: {type(error).__name__}: {error}",
                    ephemeral=True
                )
            
            # discord.ui.Modal の既定の on_error も呼び出す
            await super().on_error(interaction, error)
        
        async def _update_post_in_database(
            self, 
            conn: sqlite3.Connection, 
            post_id: int, 
            user_id: int, 
            content: str, 
            category: str, 
            image_url: Optional[str], 
            is_anonymous: bool, 
            is_private: bool,
            display_name: Optional[str]
        ) -> Optional[Dict[str, Any]]:
            """データベースの投稿を更新します。
            
            Returns:
                Optional[Dict[str, Any]]: 更新された投稿データ、失敗時はNone
            """
            try:
                with self._get_cursor(conn) as cursor:
                    cursor.execute('''
                        UPDATE thoughts 
                        SET content = ?, 
                            category = ?, 
                            image_url = ?,
                            is_anonymous = ?,
                            is_private = ?,
                            updated_at = ?,
                            display_name = ?
                        WHERE id = ? AND user_id = ?
                        RETURNING *
                    ''', (
                        content,
                        category,
                        image_url,
                        is_anonymous,
                        is_private,
                        datetime.now().isoformat(),
                        None if is_anonymous else display_name,
                        post_id,
                        user_id
                    ))
                    
                    result = cursor.fetchone()
                    if result:
                        return dict(result)
                    return None
                    
            except sqlite3.Error as e:
                logger.error(f"Failed to update post {post_id}: {e}", exc_info=True)
                return None
        
    class PostSelect(discord.ui.Select):
        def __init__(self, posts):
            options = []
            for post in posts[:25]:  # Discordの制限で最大25個まで
                post_id, content, category = post
                # プレビューテキストを短く整形
                preview = f"{content[:30]}{'...' if len(content) > 30 else ''}"
                options.append(discord.SelectOption(
                    label=f"ID: {post_id} - {category}",
                    description=preview,
                    value=str(post_id)
                ))
            
            super().__init__(
                placeholder="編集する投稿を選択...",
                min_values=1,
                max_values=1,
                options=options
            )
        
        async def callback(self, interaction: discord.Interaction):
            post_id = int(self.values[0])
            
            # 選択された投稿を取得
            with self.view.cog._get_db_connection() as conn:
                with self.view.cog._get_cursor(conn) as cursor:
                    cursor.execute('''
                        SELECT content, category, image_url, is_anonymous, is_private, user_id
                        FROM thoughts 
                        WHERE id = ? AND user_id = ?
                    ''', (post_id, interaction.user.id))
                    post = cursor.fetchone()
            
            if not post:
                if not interaction.response.is_done():
                    await interaction.response.send_message("❌ 投稿が見つからないか、編集権限がありません。", ephemeral=True)
                else:
                    await interaction.followup.send("❌ 投稿が見つからないか、編集権限がありません。", ephemeral=True)
                return
            
            current_content, current_category, current_image_url, current_is_anonymous, current_is_private, _ = post
            
            # 編集モーダルを表示
            view = self.view.cog.EditSetupView(
                cog=self.view.cog,
                post_id=post_id,
                current_content=current_content,
                current_category=current_category,
                current_image_url=current_image_url,
                current_is_anonymous=bool(current_is_anonymous),
                current_is_private=bool(current_is_private)
            )
            if not interaction.response.is_done():
                await interaction.response.send_message("設定を確認してから『編集を開く』を押してください。", view=view, ephemeral=True)
            else:
                await interaction.followup.send("設定を確認してから『編集を開く』を押してください。", view=view, ephemeral=True)
    
    class PostSelectView(discord.ui.View):
        def __init__(self, cog, posts):
            super().__init__(timeout=60)
            self.cog = cog
            self.add_item(PostSelect(posts))

    class EditSetupView(discord.ui.View):
        def __init__(
            self,
            cog: 'Edit',
            post_id: int,
            current_content: str,
            current_category: str,
            current_image_url: Optional[str],
            current_is_anonymous: bool,
            current_is_private: bool,
        ):
            super().__init__(timeout=300)
            self.cog = cog
            self.post_id = post_id
            self.current_content = current_content
            self.current_category = current_category
            self.current_image_url = current_image_url
            self.is_anonymous = bool(current_is_anonymous)
            self.is_private = bool(current_is_private)

            self.anonymous_button = ui.Button(
                style=discord.ButtonStyle.secondary,
                label=f"匿名: {'ON' if self.is_anonymous else 'OFF'}"
            )
            self.anonymous_button.callback = self._toggle_anonymous
            self.add_item(self.anonymous_button)

            self.private_button = ui.Button(
                style=discord.ButtonStyle.secondary,
                label=f"非公開: {'ON' if self.is_private else 'OFF'}"
            )
            self.private_button.callback = self._toggle_private
            self.add_item(self.private_button)

            self.open_button = ui.Button(
                style=discord.ButtonStyle.primary,
                label="編集を開く"
            )
            self.open_button.callback = self._open_modal
            self.add_item(self.open_button)

        async def _toggle_anonymous(self, interaction: discord.Interaction):
            self.is_anonymous = not self.is_anonymous
            self.anonymous_button.label = f"匿名: {'ON' if self.is_anonymous else 'OFF'}"
            await interaction.response.edit_message(view=self)

        async def _toggle_private(self, interaction: discord.Interaction):
            self.is_private = not self.is_private
            self.private_button.label = f"非公開: {'ON' if self.is_private else 'OFF'}"
            await interaction.response.edit_message(view=self)

        async def _open_modal(self, interaction: discord.Interaction):
            modal = self.cog.EditModal(
                bot=self.cog.bot,
                post_id=self.post_id,
                current_content=self.current_content,
                current_category=self.current_category,
                current_image_url=self.current_image_url,
                current_is_anonymous=self.is_anonymous,
                current_is_private=self.is_private,
            )
            await interaction.response.send_modal(modal)
    
    @app_commands.command(name="edit", description="投稿を編集します")
    @app_commands.describe(post_id="編集する投稿のID（省略可）")
    async def edit_post(
        self, 
        interaction: discord.Interaction, 
        post_id: Optional[int] = None
    ):
        """投稿を編集します（モーダルで編集）"""
        try:
            # post_idが指定されている場合は直接編集モーダルを表示
            if post_id is not None:
                # データベースから投稿を取得
                with self._get_db_connection() as conn:
                    with self._get_cursor(conn) as cursor:
                        cursor.execute('''
                            SELECT content, category, image_url, is_anonymous, is_private, user_id
                            FROM thoughts 
                            WHERE id = ?
                        ''', (post_id,))
                        post = cursor.fetchone()
                
                if not post:
                    await interaction.response.send_message("❌ 指定された投稿が見つかりません。", ephemeral=True)
                    return
                
                current_content, current_category, current_image_url, current_is_anonymous, current_is_private, post_user_id = post
                
                # デバッグログ
                print(f"[DEBUG] データベースから取得: is_anonymous={current_is_anonymous}, type={type(current_is_anonymous)}")
                print(f"[DEBUG] bool変換後: {bool(current_is_anonymous)}")
                
                # 権限チェック（投稿者本人または管理者のみ編集可能）
                is_owner = post_user_id == interaction.user.id
                is_admin = interaction.user.guild_permissions.administrator if interaction.guild else False
                
                if not (is_owner or is_admin):
                    await interaction.response.send_message("❌ この投稿を編集する権限がありません。", ephemeral=True)
                    return
                
                # モーダルを表示
                view = self.EditSetupView(
                    cog=self,
                    post_id=post_id,
                    current_content=current_content,
                    current_category=current_category,
                    current_image_url=current_image_url,
                    current_is_anonymous=bool(current_is_anonymous),
                    current_is_private=bool(current_is_private)
                )
                await interaction.response.send_message("設定を確認してから『編集を開く』を押してください。", view=view, ephemeral=True)
                return
                
            # post_idが指定されていない場合は投稿一覧を表示
            with self._get_db_connection() as conn:
                with self._get_cursor(conn) as cursor:
                    cursor.execute('''
                        SELECT id, content, category
                        FROM thoughts 
                        WHERE user_id = ?
                        ORDER BY created_at DESC
                        LIMIT 25
                    ''', (interaction.user.id,))
                    posts = cursor.fetchall()
            
            if not posts:
                await interaction.response.send_message("❌ 編集可能な投稿が見つかりませんでした。", ephemeral=True)
                return
            
            # 投稿選択用のビューを表示
            view = self.PostSelectView(self, posts)
            await interaction.response.send_message(
                "📝 編集する投稿を選択してください（最新25件）",
                view=view,
                ephemeral=True
            )
            
        except Exception as e:
            error_msg = f"コマンド実行中にエラーが発生しました: {str(e)}\n```{type(e).__name__}```"
            print(f"Command Error in edit_post: {error_msg}")
            if not interaction.response.is_done():
                await interaction.response.send_message("❌ エラーが発生しました。もう一度お試しください。", ephemeral=True)
            else:
                await interaction.followup.send("❌ エラーが発生しました。もう一度お試しください。", ephemeral=True)

async def setup(bot):
    await bot.add_cog(Edit(bot))
