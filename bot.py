import os
import logging
import sqlite3
import asyncio
import contextlib
from typing import Optional

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
        self.db_path = 'thoughts.db'
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
            
            # パフォーマンス設定
            cursor.execute('PRAGMA journal_mode=WAL')
            cursor.execute('PRAGMA synchronous=NORMAL')
            cursor.execute('PRAGMA cache_size=-2000')
            
            conn.commit()
    
    @contextlib.contextmanager
    def _get_db_connection(self):
        """データベース接続を取得するコンテキストマネージャー"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()
    
    @contextlib.contextmanager
    def _get_cursor(self, conn):
        """カーソルを取得するコンテキストマネージャー"""
        cursor = conn.cursor()
        try:
            yield cursor
        finally:
            cursor.close()

class ThoughtBot(commands.Bot, DatabaseMixin):
    """メインボットクラス"""
    
    def __init__(self):
        super().__init__(
            command_prefix=commands.when_mentioned_or('!'),
            intents=intents,
            activity=discord.Game(name="/help")
        )
        
        # 拡張機能のリスト
        self.initial_extensions = [
            'cogs.thoughts.post',
            'cogs.thoughts.list',
            'cogs.thoughts.search',
            'cogs.thoughts.delete',
            'cogs.thoughts.edit',
            'cogs.thoughts.cleanup',
            'cogs.thoughts.auto_delete',
            'cogs.thoughts.help',
        ]
        
        # データベースの初期化
        DatabaseMixin.__init__(self)

    async def setup_hook(self):
        """起動時の初期化処理"""
        # コマンドツリーをクリア
        self.tree.clear_commands(guild=None)
        logger.info('🔄 コマンドツリーをクリアしました')
        
        # コグの読み込み
        loaded_extensions = []
        failed_extensions = []
        
        # 拡張機能をロード
        for ext in self.initial_extensions:
            try:
                await self.load_extension(ext)
                loaded_extensions.append(ext)
                logger.info(f'✅ 拡張機能を読み込みました: {ext}')
            except Exception as e:
                failed_extensions.append((ext, str(e)))
                logger.error(f'❌ 拡張機能の読み込みに失敗しました: {ext} - {e}', exc_info=True)
        
        # 読み込み結果をログに出力
        if loaded_extensions:
            logger.info(f'✅ 読み込みに成功した拡張機能 ({len(loaded_extensions)}/{len(self.initial_extensions)}):\n' + 
                      '\n'.join(f'  • {ext}' for ext in loaded_extensions))
        
        if failed_extensions:
            logger.warning('❌ 読み込みに失敗した拡張機能:')
            for ext, error in failed_extensions:
                logger.warning(f'  • {ext}: {error}')
        
        # 既存のコマンドを取得
        existing_commands = {cmd.name for cmd in self.tree.get_commands()}
        
        # コマンドを手動で登録（重複を避ける）
        for command in self.tree.walk_commands():
            if isinstance(command, app_commands.Command) and command.name not in existing_commands:
                try:
                    self.tree.add_command(command)
                    existing_commands.add(command.name)
                    logger.info(f'✅ コマンドを登録しました: /{command.name}')
                except Exception as e:
                    logger.error(f'❌ コマンドの登録に失敗しました: /{command.name} - {e}')
        
        # コマンドツリーを同期
        try:
            synced = await self.tree.sync()
            logger.info(f'✅ コマンドを同期しました: {len(synced)} 件')
            
            # 登録されているコマンドを確認
            registered_commands = self.tree.get_commands()
            logger.info(f'登録されているコマンド ({len(registered_commands)}件):')
            
            for cmd in registered_commands:
                cmd_info = f'  • /{cmd.name}'
                if hasattr(cmd, 'description'):
                    cmd_info += f' - {cmd.description}'
                logger.info(cmd_info)
                
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
        
        # 登録されているコマンドを確認
        commands = self.tree.get_commands()
        logger.info(f'現在登録されているコマンド数: {len(commands)}')
        
        # コマンドが登録されていない場合のみ再同期を試みる
        if not commands:
            logger.warning('⚠️ 登録されているコマンドがありません。再同期を試みます...')
            try:
                synced = await self.tree.sync()
                logger.info(f'✅ コマンドを同期しました: {len(synced)} 件')
                
                # 再度コマンドを確認
                commands = self.tree.get_commands()
                logger.info(f'再同期後の登録コマンド数: {len(commands)}')
                
            except Exception as e:
                logger.error(f'❌ コマンドの再同期に失敗しました: {e}', exc_info=True)
        
        # 登録されているコマンドをログに出力
        if commands:
            logger.info('現在のコマンド一覧:')
            for cmd in commands:
                cmd_info = f'  • /{cmd.name}'
                if hasattr(cmd, 'description'):
                    cmd_info += f' - {cmd.description}'
                logger.info(cmd_info)
            
            # 再試行
            try:
                synced = await self.tree.sync()
                logger.info(f'🔄 コマンドツリーを再同期しました: {len(synced)} コマンド')
            except Exception as e:
                logger.error(f'❌ コマンドツリーの再同期に失敗しました: {e}', exc_info=True)
    
    async def on_error(self, event_method: str, *args, **kwargs) -> None:
        """イベントハンドラでのエラーを処理"""
        logger.error(f'Error in {event_method}', exc_info=True)

    async def close(self):
        """ボットの終了処理"""
        await super().close()

def with_transaction(func):
    """データベーストランザクション用デコレータ"""
    async def wrapper(*args, **kwargs):
        self = args[0] if args else None
        if not hasattr(self, '_get_db_connection'):
            return await func(*args, **kwargs)
            
        with self._get_db_connection() as conn:
            try:
                result = await func(*args, **kwargs, conn=conn)
                conn.commit()
                return result
            except Exception as e:
                conn.rollback()
                logger.error(f'Transaction failed: {e}', exc_info=True)
                raise
    return wrapper

async def main():
    """メイン関数"""
    # ボットのインスタンスを作成
    bot = ThoughtBot()
    
    # エラーハンドラを設定
    @bot.event
    async def on_command_error(ctx, error):
        if isinstance(error, commands.CommandNotFound):
            return
            
        error_msg = None
        if isinstance(error, commands.MissingRequiredArgument):
            error_msg = '必要な引数が不足しています。コマンドを確認してください。'
        elif isinstance(error, commands.MissingPermissions):
            error_msg = 'このコマンドを実行する権限がありません。'
        else:
            error_msg = 'エラーが発生しました。後でもう一度お試しください。'
            logger.error(f'Command error: {error}', exc_info=True)
        
        if error_msg and not ctx.interaction.response.is_done():
            await ctx.send(error_msg, ephemeral=True)
    
    # 同期用コマンド
    @bot.command(name='sync')
    @commands.is_owner()
    async def sync_commands(ctx):
        """スラッシュコマンドを再同期します（Botオーナーのみ）"""
        try:
            # すべての拡張機能をリロード
            for ext in bot.initial_extensions:
                try:
                    await bot.reload_extension(ext)
                    logger.info(f'Reloaded extension: {ext}')
                except Exception as e:
                    logger.error(f'Failed to reload {ext}: {e}', exc_info=True)
            
            # コマンドを同期
            synced = await bot._sync_commands()
            
            if synced:
                commands_list = [f"• /{cmd.name}" for cmd in bot.tree.get_commands()]
                await ctx.send(
                    f'✅ {len(synced)}個のコマンドを同期しました。\n' +
                    '登録されているコマンド:\n' + 
                    '\n'.join(commands_list)
                )
        except Exception as e:
            await ctx.send(f'❌ 同期中にエラーが発生しました: {e}')
    
    # ヘルプコマンドは help.py に移動しました

    # ボットを起動
    try:
        token = os.getenv('DISCORD_TOKEN')
        if not token:
            raise ValueError('DISCORD_TOKEN が設定されていません。.envファイルを確認してください。')
            
        logger.info('Starting bot...')
        await bot.start(token)
    except KeyboardInterrupt:
        logger.info('Bot is shutting down...')
    except Exception as e:
        logger.error(f'Bot crashed: {e}', exc_info=True)
    finally:
        if not bot.is_closed():
            await bot.close()

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info('Bot has been stopped by user')
    except Exception as e:
        logger.critical(f'Fatal error: {e}', exc_info=True)
    finally:
        logger.info('Bot has been stopped')
