from __future__ import annotations

import contextlib
import logging
import sqlite3
import traceback
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, TypedDict, Union, cast, Iterator

import discord
from discord import app_commands, ui, abc, Interaction, Message, DMChannel
from discord.ext import commands

# ロガーの設定
logger = logging.getLogger(__name__)

# 型定義
@dataclass
class MessageData:
    """メッセージデータを表すデータクラス"""
    message_id: int
    channel_id: int
    post_id: int
    user_id: int
    content: str
    is_private: bool

@dataclass
class DeleteResult:
    """削除結果を表すデータクラス"""
    success: bool
    message: str
    
    def __bool__(self) -> bool:
        return self.success

class DeleteDM(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        """DeleteDM コグを初期化します。
        
        Args:
            bot: Discord Bot インスタンス
        """
        self.bot = bot
        self._init_db()
        logger.info("DeleteDM cog が初期化されました")
    
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
                
                # 必要なテーブルが存在するか確認
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
                    CREATE INDEX IF NOT EXISTS idx_message_references_post_id 
                    ON message_references(post_id);
                ''')
                
                cursor.execute('''
                    CREATE INDEX IF NOT EXISTS idx_message_references_message_id 
                    ON message_references(message_id);
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
            conn.execute("PRAGMA foreign_keys = ON")
            conn.execute("PRAGMA journal_mode = WAL")
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

    async def _get_message_data(self, message_id: int, user_id: int) -> Optional[MessageData]:
        """メッセージデータを取得します。
        
        Args:
            message_id: メッセージID
            user_id: ユーザーID（認証用）
            
        Returns:
            Optional[MessageData]: メッセージデータ、見つからない場合はNone
        """
        try:
            with self._get_db_connection() as conn:
                with self._get_cursor(conn) as cursor:
                    cursor.execute('''
                        SELECT 
                            m.message_id, 
                            m.channel_id, 
                            t.id as post_id, 
                            t.user_id, 
                            t.content, 
                            t.is_private
                        FROM message_references m
                        JOIN thoughts t ON m.post_id = t.id
                        WHERE (m.message_id = ? OR m.message_id = ?)
                        AND t.user_id = ?
                    ''', (str(message_id), str(int(message_id)), user_id))
                    
                    if row := cursor.fetchone():
                        return MessageData(
                            message_id=int(row['message_id']),
                            channel_id=int(row['channel_id']),
                            post_id=row['post_id'],
                            user_id=row['user_id'],
                            content=row['content'],
                            is_private=bool(row['is_private'])
                        )
                    return None
                    
        except sqlite3.Error as e:
            logger.error(f"Failed to get message data for ID {message_id}: {e}", exc_info=True)
            return None
    
    async def _delete_message_from_discord(
        self, 
        channel: discord.TextChannel | discord.DMChannel, 
        message_id: int
    ) -> bool:
        """Discordからメッセージを削除します。
        
        Args:
            channel: メッセージが存在するチャンネル
            message_id: 削除するメッセージのID
            
        Returns:
            bool: 削除に成功したかどうか
        """
        try:
            message = await channel.fetch_message(message_id)
            await message.delete()
            logger.info(f"Discordメッセージを削除しました: message_id={message_id}")
            return True
            
        except discord.NotFound:
            logger.warning(f"メッセージが見つかりませんでした: message_id={message_id}")
            return False
            
        except discord.Forbidden:
            logger.error(f"メッセージを削除する権限がありません: message_id={message_id}")
            return False
            
        except discord.HTTPException as e:
            logger.error(f"メッセージの削除中にエラーが発生しました: {e}", exc_info=True)
            return False
    
    async def _delete_message_from_db(self, message_id: int, post_id: int) -> bool:
        """データベースからメッセージ参照を削除します。
        
        Args:
            message_id: 削除するメッセージのID
            post_id: 関連する投稿のID
            
        Returns:
            bool: 削除に成功したかどうか
        """
        try:
            with self._get_db_connection() as conn:
                with conn:
                    with self._get_cursor(conn) as cursor:
                        # メッセージ参照を削除
                        cursor.execute('''
                            DELETE FROM message_references 
                            WHERE message_id = ?
                        ''', (str(message_id),))
                        
                        # 関連する投稿に他のメッセージ参照がなければ削除
                        cursor.execute('''
                            DELETE FROM thoughts 
                            WHERE id = ? AND NOT EXISTS (
                                SELECT 1 FROM message_references 
                                WHERE post_id = ?
                            )
                        ''', (post_id, post_id))
                        
                        return cursor.rowcount > 0
                        
        except sqlite3.Error as e:
            logger.error(f"Failed to delete message {message_id} from database: {e}", exc_info=True)
            return False
    
    async def delete_message_by_id(
        self, 
        interaction: discord.Interaction, 
        message_id: str, 
        user_id: int
    ) -> DeleteResult:
        """メッセージIDを指定してメッセージを削除します。
        
        Args:
            interaction: Discordインタラクション
            message_id: 削除するメッセージのID
            user_id: 削除をリクエストしたユーザーのID
            
        Returns:
            DeleteResult: 削除結果
        """
        try:
            # メッセージIDを数値に変換
            try:
                message_id_int = int(message_id)
            except ValueError:
                return DeleteResult(False, "❌ 無効なメッセージIDです。数値を入力してください。")
            
            # メッセージ情報を取得
            message_data = await self._get_message_data(message_id_int, user_id)
            if not message_data:
                return DeleteResult(False, "❌ メッセージが見つからないか、削除する権限がありません。")
            
            # 非公開メッセージは削除不可
            if message_data.is_private:
                return DeleteResult(False, "❌ 非公開のメッセージは削除できません。")
            
            # Discordからメッセージを削除
            channel = interaction.channel
            discord_deleted = await self._delete_message_from_discord(channel, message_id_int)
            
            # データベースから削除
            db_deleted = await self._delete_message_from_db(message_id_int, message_data.post_id)
            
            if discord_deleted and db_deleted:
                return DeleteResult(True, f"✅ メッセージ (ID: {message_id_int}) を削除しました。")
            elif not discord_deleted and db_deleted:
                return DeleteResult(True, "✅ メッセージは既に削除されています。")
            else:
                return DeleteResult(False, "❌ メッセージの削除中に問題が発生しました。")
                
        except Exception as e:
            error_msg = f"❌ エラーが発生しました: {type(e).__name__}: {str(e)}"
            logger.error(error_msg, exc_info=True)
            return DeleteResult(False, error_msg)
    
    @app_commands.command(name="dm_delete", description="DMで送信したメッセージを削除します")
    @app_commands.describe(message_id="削除するメッセージのID")
    async def dm_delete(self, interaction: discord.Interaction, message_id: str) -> None:
        """DMで送信したメッセージを削除します。
        
        Args:
            interaction: インタラクションオブジェクト
            message_id: 削除するメッセージのID
        """
        # DMでのみ実行可能
        if not isinstance(interaction.channel, discord.DMChannel):
            await interaction.response.send_message(
                "❌ このコマンドはDMでのみ使用できます。",
                ephemeral=True
            )
            return
        
        # 即時応答で処理中であることを伝える
        await interaction.response.defer(ephemeral=True)
        
        try:
            # メッセージ削除を実行
            result = await self.delete_message_by_id(
                interaction=interaction,
                message_id=message_id,
                user_id=interaction.user.id
            )
            
            # 結果をユーザーに通知
            await interaction.followup.send(result.message, ephemeral=True)
            
        except Exception as e:
            error_msg = f"❌ 予期せぬエラーが発生しました: {type(e).__name__}"
            logger.error(f"dm_delete コマンド実行中にエラー: {e}", exc_info=True)
            
            if not interaction.response.is_done():
                await interaction.response.send_message(error_msg, ephemeral=True)
            else:
                await interaction.followup.send(error_msg, ephemeral=True)
    
    
    @property
    def _db_path(self) -> Path:
        """データベースファイルのパスを取得する
        
        Returns:
            Path: データベースファイルのPathオブジェクト
        """
        return (
            Path(__file__).parent.parent.parent
            / 'data' 
            / 'thoughts.db'
        )

    def _ensure_db_directory_exists(self) -> None:
        """データベースディレクトリが存在することを確認し、なければ作成する"""
        self._db_path.parent.mkdir(parents=True, exist_ok=True)

    @contextlib.contextmanager
    def _get_db_connection(self) -> sqlite3.Connection:
        """データベース接続を取得するコンテキストマネージャー
        
        Yields:
            sqlite3.Connection: データベース接続オブジェクト
            
        Raises:
            sqlite3.Error: データベース接続に失敗した場合
        """
        self._ensure_db_directory_exists()
        conn = None
        
        try:
            conn = sqlite3.connect(
                str(self._db_path),
                timeout=10.0,
                isolation_level='IMMEDIATE'  # 明示的なトランザクション制御のため
            )
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA foreign_keys = ON")
            conn.execute("PRAGMA journal_mode = WAL")  # パフォーマンス向上のため
            yield conn
            
        except sqlite3.Error as e:
            self._log_error(f"データベース接続エラー: {e}")
            raise
            
        finally:
            if conn is not None:
                conn.close()

    def _log_error(self, message: str, exc_info: bool = True, **kwargs: Any) -> None:
        """エラーログを出力する
        
        Args:
            message: エラーメッセージ
            exc_info: 例外情報を出力するかどうか
            **kwargs: 追加のログ情報
        """
        extra = ""
        if kwargs:
            extra = " " + " ".join(f"{k}={v}" for k, v in kwargs.items())
            
        print(f"[ERROR] {message}{extra}")
        if exc_info:
            traceback.print_exc(limit=5)  # スタックトレースの深さを制限

    async def _get_message_info(self, message_id: int, user_id: int) -> Optional[MessageInfo]:
        """メッセージ情報をデータベースから取得する
        
        Args:
            message_id: 検索するメッセージID
            user_id: ユーザーID
            
        Returns:
            Optional[MessageInfo]: メッセージ情報（見つからない場合はNone）
            
        Raises:
            sqlite3.Error: データベースエラーが発生した場合
        """
        try:
            with self._get_db_connection() as conn:
                cursor = conn.cursor()
                
                # メッセージIDとユーザーIDで検索（文字列と数値の両方で検索）
                cursor.execute('''
                    SELECT 
                        m.message_id, 
                        t.id as post_id, 
                        t.user_id, 
                        m.channel_id, 
                        t.content, 
                        t.is_private
                    FROM messages m
                    JOIN thoughts t ON m.post_id = t.id
                    WHERE (m.message_id = ? OR m.message_id = ?)
                    AND t.user_id = ?
                ''', (str(message_id), str(int(message_id)), user_id))
                
                if row := cursor.fetchone():
                    return cast(MessageInfo, dict(row))
                return None
                
        except (sqlite3.Error, ValueError) as e:
            self._log_error(f"メッセージ情報の取得中にエラーが発生しました: {e}")
            if isinstance(e, sqlite3.Error):
                raise
            return None

    async def _delete_message_from_discord(self, channel: abc.Messageable, 
                                         message_id: int) -> bool:
        """Discordからメッセージを削除する
        
        Args:
            channel: メッセージが存在するチャンネル
            message_id: 削除するメッセージID
            
        Returns:
            bool: 削除に成功したかどうか
            
        Note:
            メッセージが既に削除されている場合はTrueを返します。
        """
        try:
            # メッセージの存在確認と削除を1回のAPIコールで行う
            try:
                message = await channel.fetch_message(message_id)
                await message.delete()
                self._log_info(f"メッセージ {message_id} を削除しました")
                return True
                
            except discord.NotFound:
                self._log_info(f"メッセージ {message_id} は既に削除されています")
                return True
                
        except discord.Forbidden as e:
            self._log_error(f"メッセージ {message_id} の削除権限がありません: {e}")
            return False
            
        except discord.HTTPException as e:
            self._log_error(f"メッセージ {message_id} の削除中にHTTPエラーが発生: {e}")
            return False
            
    async def _delete_message_from_db(self, message_id: int, post_id: int) -> bool:
        """データベースからメッセージを削除する
        
        Args:
            message_id: 削除するメッセージID
            post_id: 関連する投稿ID
            
        Returns:
            bool: 削除に成功したかどうか
            
        Raises:
            sqlite3.Error: データベースエラーが発生した場合
        """
        try:
            with self._get_db_connection() as conn:
                with conn:  # トランザクション開始
                    cursor = conn.cursor()
                    
                    # 外部キー制約を一時的に無効化（パフォーマンス向上のため）
                    cursor.execute('PRAGMA foreign_keys = OFF')
                    
                    try:
                        # メッセージを削除（外部キー制約により、関連する添付ファイルも削除される）
                        cursor.execute(
                            'DELETE FROM messages WHERE message_id = ?', 
                            (str(message_id),)
                        )
                        
                        # 関連する投稿を削除
                        cursor.execute(
                            'DELETE FROM thoughts WHERE id = ?', 
                            (post_id,)
                        )
                        
                        # 変更をコミット
                        conn.commit()
                        
                        # 外部キー制約を再度有効化
                        cursor.execute('PRAGMA foreign_keys = ON')
                        
                        deleted = cursor.rowcount > 0
                        if deleted:
                            self._log_info(f"データベースからメッセージ {message_id} を削除しました")
                        return deleted
                        
                    except sqlite3.Error:
                        # エラーが発生した場合はロールバック
                        conn.rollback()
                        cursor.execute('PRAGMA foreign_keys = ON')
                        raise
                    
        except sqlite3.Error as e:
            self._log_error(f"データベースからの削除中にエラーが発生しました: {e}")
            raise

    async def delete_message_by_id(self, 
                                 interaction: discord.Interaction,
                                 message_id: Union[str, int], 
                                 user_id: int) -> Tuple[bool, str]:
        """DMでメッセージIDを指定して削除する
        
        Args:
            interaction: discord.Interaction オブジェクト
            message_id: 削除するメッセージID（文字列または数値）
            user_id: 削除を試みるユーザーID
            
        Returns:
            Tuple[bool, str]: (成功可否, メッセージ)
        """
        self._log_info(f"メッセージ削除処理を開始: message_id={message_id}, user_id={user_id}")
        
        # メッセージIDの検証
        try:
            message_id_int = int(str(message_id).strip())
            if message_id_int <= 0:
                raise ValueError("メッセージIDは正の整数である必要があります")
                
        except (ValueError, TypeError) as e:
            self._log_error(f"無効なメッセージID: {e}")
            return False, "❌ 無効なメッセージIDです。正しいIDを入力してください。"
        
        # チャンネルの検証
        if not isinstance(interaction.channel, abc.Messageable):
            return False, "❌ このコマンドはメッセージを送信できるチャンネルでのみ使用できます。"
        
        try:
            # メッセージ情報を取得
            message_info = await self._get_message_info(message_id_int, user_id)
            if not message_info:
                return False, "❌ メッセージが見つからないか、削除する権限がありません。"
            
            # 非公開メッセージのチェック
            if message_info.get('is_private'):
                return False, "🔒 非公開のメッセージは削除できません。"
            
            # Discordからメッセージを削除
            discord_deleted = await self._delete_message_from_discord(
                interaction.channel, 
                message_id_int
            )
            
            # データベースから削除
            db_deleted = await self._delete_message_from_db(
                message_id_int, 
                message_info['post_id']
            )
            
            # 結果に基づいてメッセージを返す
            if db_deleted:
                if discord_deleted:
                    return True, "✅ メッセージを削除しました。"
                return True, "ℹ️ メッセージは既に削除されています。"
            
            return False, "❌ メッセージの削除中に問題が発生しました。"
            
        except discord.DiscordException as e:
            error_type = type(e).__name__
            self._log_error(f"Discord APIエラー ({error_type}): {e}")
            
            if isinstance(e, discord.HTTPException):
                if e.status == 429:  # レートリミット
                    retry_after = getattr(e, 'retry_after', 5)
                    return False, f"⏳ レートリミットに達しました。{retry_after:.1f}秒後にもう一度お試しください。"
                return False, f"❌ Discordサーバーでエラーが発生しました。しばらくしてから再試行してください。"
                
            return False, f"❌ メッセージの削除中にエラーが発生しました: {error_type}"
            
        except sqlite3.Error as e:
            self._log_error(f"データベースエラー: {e}")
            return False, "❌ データの処理中にエラーが発生しました。管理者にお問い合わせください。"
            
        except Exception as e:
            error_type = type(e).__name__
            self._log_error(f"予期しないエラー ({error_type}): {e}")
            return False, "❌ 予期しないエラーが発生しました。もう一度お試しください。"

async def setup(bot):
    await bot.add_cog(DeleteDM(bot))
    print("DeleteDM cog が読み込まれました")
