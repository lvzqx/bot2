from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import sqlite3
import sys
from typing import Optional, List, Dict, Any, Union

import discord
from discord.ext import commands
from discord import app_commands
from dotenv import load_dotenv

# ロギングの設定
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('bot.log', encoding='utf-8')
    ]
)
logger = logging.getLogger(__name__)

# 環境変数の読み込み
load_dotenv()

# インテントの設定
intents = discord.Intents.default()
intents.message_content = True
intents.members = True

class DatabaseMixin:
    """データベース操作のミックスインクラス"""
    
    def __init__(self):
        # 環境変数からデータベースパスを取得、なければデフォルト値を使用
        self.db_path = os.getenv('DB_PATH', 'thoughts.db')
        self._init_db()
    
    def _init_db(self):
        """データベースの初期化"""
        with self._get_db_connection() as conn:
            cursor = conn.cursor()
            
            # テーブル作成
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS thoughts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    content TEXT NOT NULL,
                    category TEXT,
                    image_url TEXT,
                    is_anonymous BOOLEAN DEFAULT 0,
                    is_private BOOLEAN DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    user_id INTEGER NOT NULL,
                    display_name TEXT
                )
            ''')
            
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS message_references (
                    post_id INTEGER PRIMARY KEY,
                    message_id TEXT NOT NULL,
                    channel_id TEXT NOT NULL,
                    FOREIGN KEY (post_id) REFERENCES thoughts (id) ON DELETE CASCADE
                )
            ''')
            
            # インデックス作成
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_thoughts_user_id ON thoughts (user_id)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_thoughts_created_at ON thoughts (created_at)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_thoughts_category ON thoughts (category)')
            
            # パフォーマンス最適化
            cursor.execute('PRAGMA journal_mode=WAL')
            cursor.execute('PRAGMA synchronous=NORMAL')
            cursor.execute('PRAGMA cache_size=-2000')
            
            conn.commit()
    
    @contextlib.contextmanager
    def _get_db_connection(self):
        """データベース接続を取得するコンテキストマネージャ"""
        conn = sqlite3.connect(
            self.db_path,
            isolation_level=None,
            timeout=30.0,
            detect_types=sqlite3.PARSE_DECLTYPES | sqlite3.PARSE_COLNAMES
        )
        conn.row_factory = sqlite3.Row
        
        try:
            yield conn
        except sqlite3.Error as e:
            logger.error(f"データベースエラー: {e}")
            conn.rollback()
            raise
        finally:
            conn.close()
    
    @contextlib.contextmanager
    def _get_cursor(self, conn):
        """カーソルを取得するコンテキストマネージャ"""
        cursor = conn.cursor()
        try:
            yield cursor
        except Exception as e:
            logger.error(f"カーソルエラー: {e}")
            raise
        finally:
            cursor.close()

class ThoughtBot(commands.Bot, DatabaseMixin):
    """メインボットクラス"""
    
    def __init__(self):
        super().__init__(
            command_prefix=commands.when_mentioned_or('!'),
            intents=intents,
            application_id=os.getenv('APPLICATION_ID'),
            activity=discord.Game(name="/help でヘルプを表示")
        )
        DatabaseMixin.__init__(self)
    
    async def setup_hook(self):
        """起動時の初期化処理"""
        # コマンドツリーのクリアは行わない（各Cogのsetupで登録するため）
        logger.info('🔄 拡張機能の読み込みを開始します...')
        
        # コグの読み込み
        loaded_extensions = []
        failed_extensions = []
        
        # 必要な拡張機能の順序を定義（依存関係がある場合に備えて）
        required_extensions = [
            'cogs.thoughts.post',
            'cogs.thoughts.delete',
            'cogs.thoughts.list',
            'cogs.thoughts.search',
            'cogs.thoughts.edit',
            'cogs.thoughts.restore_messages',  # メッセージ整理用
            'cogs.thoughts.data_recovery',  # データ復元用
            'cogs.thoughts.user_fix',  # 投稿者情報修正用
            'cogs.thoughts.help',
        ]
        
        # 拡張機能をロード
        for ext in required_extensions:
            try:
                # 既に読み込まれている場合は一度アンロード
                if ext in self.extensions:
                    await self.unload_extension(ext)
                    logger.info(f'🔄 拡張機能をアンロードしました: {ext}')
                
                # 拡張機能をロード
                await self.load_extension(ext)
                loaded_extensions.append(ext)
                logger.info(f'✅ 拡張機能を読み込みました: {ext}')
                
            except Exception as e:
                failed_extensions.append((ext, str(e)))
                logger.error(f'❌ 拡張機能の読み込みに失敗しました: {ext} - {e}', exc_info=True)
        
        # 読み込み結果をログに出力
        if loaded_extensions:
            logger.info(f'✅ 読み込みに成功した拡張機能 ({len(loaded_extensions)}/{len(required_extensions)}):\n' + 
                      '\n'.join(f'  • {ext}' for ext in loaded_extensions))
        
        if failed_extensions:
            logger.warning('❌ 読み込みに失敗した拡張機能:')
            for ext, error in failed_extensions:
                logger.warning(f'  • {ext}: {error}')
        
        # コマンドツリーを同期
        try:
            # 同期前に登録されているコマンドを確認
            before_sync_commands = {cmd.name for cmd in self.tree.get_commands()}
            logger.info(f'同期前の登録コマンド数: {len(before_sync_commands)}')
            logger.info(f'同期前の登録コマンド: {before_sync_commands}')
            
            # post コマンドが登録されているか確認
            post_cog = self.get_cog('Post')
            if post_cog:
                logger.info('Post cog は正常に読み込まれています')
                logger.info(f'Post cog のメソッド: {[name for name, _ in post_cog.get_commands()]}')
            else:
                logger.warning('Post cog が読み込まれていません')
            
            # コマンドツリーを同期
            synced = await self.tree.sync()
            logger.info(f'✅ コマンドを同期しました: {len(synced)} 件')
            
            # 同期後のコマンドを確認
            registered_commands = self.tree.get_commands()
            logger.info(f'同期後の登録コマンド数: {len(registered_commands)}')
            
            # 登録されているコマンドをログに出力
            if registered_commands:
                logger.info('登録されているコマンド一覧:')
                for cmd in registered_commands:
                    cmd_info = f'  • /{cmd.name}'
                    if hasattr(cmd, 'description'):
                        cmd_info += f' - {cmd.description}'
                    logger.info(cmd_info)
            
            # 必要なコマンドがすべて登録されているか確認
            required_commands = {
                'post', 'delete', 'list', 'search', 'edit', 'help', 'restore_messages',
                'backup_database', 'list_backups', 'restore_backup', 'check_database', 'cleanup_orphaned',
                'recover_from_messages'
            }
            registered_command_names = {cmd.name for cmd in registered_commands}
            missing_commands = required_commands - registered_command_names
            
            if missing_commands:
                logger.warning(f'⚠️ 以下の必須コマンドが登録されていません: {missing_commands}')
                
                # 不足しているコマンドがある場合は、該当する拡張機能を再読み込み
                for cmd in missing_commands:
                    ext_name = f'cogs.thoughts.{cmd}'
                    try:
                        # 既存の拡張機能をアンロード
                        if ext_name in self.extensions:
                            await self.unload_extension(ext_name)
                            logger.info(f'✅ 拡張機能をアンロードしました: {ext_name}')
                            
                        # 拡張機能を再読み込み
                        await self.load_extension(ext_name)
                        logger.info(f'✅ 拡張機能を再読み込みしました: {ext_name}')
                        
                    except Exception as e:
                        logger.error(f'❌ 拡張機能の再読み込みに失敗しました: {ext_name} - {e}')
                
                # 再同期を試みる
                try:
                    synced = await self.tree.sync()
                    logger.info(f'✅ コマンドを再同期しました: {len(synced)} 件')
                    
                    # 再同期後のコマンドを確認
                    commands = self.tree.get_commands()
                    logger.info(f'再同期後の登録コマンド数: {len(commands)}')
                    
                    if commands:
                        logger.info('再登録後のコマンド一覧:')
                        for cmd in commands:
                            cmd_info = f'  • /{cmd.name}'
                            if hasattr(cmd, 'description'):
                                cmd_info += f' - {cmd.description}'
                            logger.info(cmd_info)
                    
                except Exception as e:
                    logger.error(f'❌ コマンドの再同期に失敗しました: {e}', exc_info=True)
            
        except Exception as e:
            logger.error(f'❌ コマンドの同期に失敗しました: {e}', exc_info=True)
            
            # 再試行
            try:
                synced = await self.tree.sync()
                logger.info(f'🔄 コマンドツリーを再同期しました: {len(synced)} コマンド')
            except Exception as e:
                logger.error(f'❌ コマンドツリーの再同期に失敗しました: {e}', exc_info=True)
    
    async def on_ready(self):
        """ボットの準備が完了したときに呼び出される"""
        logger.info(f'✅ ログインしました: {self.user} (ID: {self.user.id})')
        logger.info('------')

        # 拡張機能の読み込み状態を確認
        logger.info('読み込まれている拡張機能:')
        for ext in self.extensions:
            logger.info(f'  • {ext}')
            
        # 登録されているコマンドを確認
        commands = self.tree.get_commands()
        logger.info(f'現在登録されているコマンド数: {len(commands)}')
        
        # 登録されているコマンドを表示
        if commands:
            logger.info('登録されているコマンド一覧:')
            for cmd in commands:
                cmd_info = f'  • /{cmd.name}'
                if hasattr(cmd, 'description'):
                    cmd_info += f' - {cmd.description}'
                logger.info(cmd_info)

def main():
    # ボットのインスタンスを作成
    bot = ThoughtBot()
    
    # トークンの確認
    TOKEN = os.getenv('DISCORD_TOKEN')
    if not TOKEN:
        logger.error('❌ 環境変数 DISCORD_TOKEN が設定されていません')
        sys.exit(1)
    
    # ボットを起動
    try:
        bot.run(TOKEN)
    except discord.LoginFailure:
        logger.error('❌ ログインに失敗しました。トークンが無効です。')
        sys.exit(1)
    except Exception as e:
        logger.error(f'❌ ボットの起動中にエラーが発生しました: {e}')
        sys.exit(1)

if __name__ == '__main__':
    main()