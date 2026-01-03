import os
import discord
from discord.ext import commands
from dotenv import load_dotenv
import sqlite3
import datetime

# 環境変数の読み込み
load_dotenv()

# インテントの設定
intents = discord.Intents.default()
intents.message_content = True
intents.members = True

# ボットの設定
class ThoughtBot(commands.Bot):
    def __init__(self):
        super().__init__(
            command_prefix=commands.when_mentioned_or('!'),
            intents=intents,
            activity=discord.Game(name="/help")
        )
        self.initial_extensions = [
            'cogs.thoughts.post',
            'cogs.thoughts.list',
            'cogs.thoughts.search',
            'cogs.thoughts.delete',
            'cogs.thoughts.delete_dm',  # DM用の削除コマンド
            'cogs.thoughts.edit',
            'cogs.thoughts.cleanup',
            'cogs.thoughts.auto_delete',  # 自動削除機能
        ]
        self.db = None

    async def setup_hook(self):
        # データベースの初期化
        self.db = sqlite3.connect('thoughts.db')
        self.init_db()
        
        # コグの読み込み
        for ext in self.initial_extensions:
            try:
                await self.load_extension(ext)
                print(f'✅ Loaded extension: {ext}')
            except Exception as e:
                print(f'❌ Failed to load extension {ext}: {e}')
        
        # コマンドツリーの同期
        await self.tree.sync()
        print('✅ コマンドツリーを同期しました')

    def init_db(self):
        cursor = self.db.cursor()
        
        # テーブルが存在しない場合は作成
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
        
        # インデックスの作成
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_thoughts_user_id 
            ON thoughts (user_id)
        ''')
        
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_thoughts_created_at 
            ON thoughts (created_at)
        ''')
        
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_thoughts_category 
            ON thoughts (category)
        ''')
        
        # WALモードと最適化設定
        cursor.execute('PRAGMA journal_mode=WAL')
        cursor.execute('PRAGMA synchronous=NORMAL')
        cursor.execute('PRAGMA cache_size=-2000')
        
        self.db.commit()
        
        # 定期的な最適化
        cursor.execute('VACUUM')
        self.db.commit()
        cursor = self.db.cursor()
        # メインの投稿テーブル
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS thoughts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            content TEXT NOT NULL,
            category TEXT,
            image_url TEXT,
            is_anonymous BOOLEAN DEFAULT 0,
            is_private BOOLEAN DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        ''')
        
        # メッセージ参照テーブル（メッセージ削除用）
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS message_references (
            post_id INTEGER PRIMARY KEY,
            message_id TEXT NOT NULL,
            channel_id TEXT NOT NULL,
            FOREIGN KEY (post_id) REFERENCES thoughts (id) ON DELETE CASCADE
        )
        ''')
        self.db.commit()

    async def close(self):
        if self.db:
            self.db.close()
        await super().close()

    async def on_ready(self):
        print(f'Logged in as {self.user} (ID: {self.user.id})')
        print('------')

    async def on_error(self, event_method: str, *args, **kwargs) -> None:
        import traceback
        error = traceback.format_exc()
        print(f'Error in {event_method}: {error}')
        
        # エラーを開発者に通知
        owner = await self.fetch_user(self.owner_id) if hasattr(self, 'owner_id') else None
        if owner:
            error_msg = f'```py\n{error[:1900]}\n```'
            await owner.send(f'**Error in {event_method}**\n{error_msg}')

# データベーストランザクション用デコレータ
def with_transaction(func):
    async def wrapper(*args, **kwargs):
        self = args[0] if args else None
        if not hasattr(self, 'db') or not self.db:
            return await func(*args, **kwargs)
            
        try:
            result = await func(*args, **kwargs)
            self.db.commit()
            return result
        except Exception as e:
            self.db.rollback()
            raise e
    return wrapper

# ボットの起動
bot = ThoughtBot()

@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandNotFound):
        return
    elif isinstance(error, commands.MissingRequiredArgument):
        await ctx.send('必要な引数が不足しています。コマンドを確認してください。')
    elif isinstance(error, commands.MissingPermissions):
        await ctx.send('このコマンドを実行する権限がありません。')
    else:
        error_msg = f'エラーが発生しました: {error}'
        print(error_msg)
        await ctx.send('エラーが発生しました。後でもう一度お試しください。')
        # エラーログを開発者に送信
        owner = await bot.fetch_user(bot.owner_id) if hasattr(bot, 'owner_id') and bot.owner_id else None
        if owner:
            await owner.send(f'エラーが発生しました: {error}')

# 同期用コマンド
@bot.command()
@commands.is_owner()
async def sync(ctx):
    try:
        await bot.tree.sync()
        await ctx.send("✅ コマンドを同期しました")
    except Exception as e:
        await ctx.send(f"❌ エラー: {e}")

# ヘルプコマンド（スラッシュコマンドのみ）
@bot.tree.command(name='help', description='利用可能なコマンドを表示します')
async def help_command(interaction: discord.Interaction):
    try:
        # シンプルな応答を即座に返す
        embed = discord.Embed(
            title='📚 利用可能なコマンド',
            description='以下のコマンドが利用できます。',
            color=discord.Color.blue()
        )
        
        # コマンドの説明を追加
        commands_list = [
            ('📝 投稿関連', '''
            `/post` - 新しい投稿を作成
            `/list [件数]` - 自分の投稿を一覧表示（デフォルト10件）
            `/search [キーワード]` - 投稿を検索
            `/delete [ID]` - 投稿を削除
            `/edit [ID]` - 投稿を編集
            ''')
        ]
        
        for name, value in commands_list:
            embed.add_field(name=name, value=value, inline=False)
        
        # 一度の応答で送信
        await interaction.response.send_message(embed=embed, ephemeral=True)
        
    except Exception as e:
        print(f"Help command error: {e}")
        try:
            await interaction.response.send_message("ヘルプの表示中にエラーが発生しました。", ephemeral=True)
        except:
            pass
    return

# ボットを実行
async def main():
    async with bot:
        await bot.start(os.getenv('DISCORD_TOKEN'))

if __name__ == '__main__':
    token = os.getenv('DISCORD_TOKEN')
    if not token:
        print('エラー: DISCORD_TOKENが設定されていません。.envファイルを確認してください。')
    else:
        try:
            import asyncio
            asyncio.run(main())
        except discord.LoginFailure:
            print('ログインに失敗しました。トークンが正しいか確認してください。')
        except Exception as e:
            print(f'予期せぬエラーが発生しました: {e}')
