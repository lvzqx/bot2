import os
import discord
from discord import app_commands
from discord.ext import commands
import aiosqlite
import datetime
from dotenv import load_dotenv
from typing import Optional

# Load environment variables
load_dotenv()

# Initialize bot with intents
intents = discord.Intents.default()
intents.messages = True
intents.message_content = True

class ThoughtBot(commands.Bot):    
    def __init__(self):
        super().__init__(
            command_prefix='!',
            intents=intents,
            activity=discord.Game(name="/post でつぶやきを投稿")
        )
        self.initial_extensions = [
    'cogs.thoughts.post',
    'cogs.thoughts.list',
    'cogs.thoughts.search',
    'cogs.thoughts.delete'
    ]
        self.db = None
        self.allowed_channel_id = int(os.getenv('ALLOWED_CHANNEL_ID', 0))  # 環境変数から許可するチャンネルIDを取得

    async def setup_hook(self):
        # Initialize database
        self.db = await aiosqlite.connect('thoughts.db')
        await self.create_tables()
        
        # Load cogs
        for ext in self.initial_extensions:
            try:
                await self.load_extension(ext)
                print(f'拡張機能を読み込みました: {ext}')
            except Exception as e:
                print(f'Failed to load extension {ext}: {e}')
        
        # Sync commands
        await self.tree.sync()
        print("コマンドを同期しました！")

    async def create_tables(self):
        await self.db.execute('''
        CREATE TABLE IF NOT EXISTS thoughts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            content TEXT NOT NULL,
            category TEXT NOT NULL,
            image_url TEXT,
            show_name BOOLEAN DEFAULT 1,
            is_private BOOLEAN DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        ''')
        await self.db.commit()

    async def close(self):
        if self.db:
            await self.db.close()
        await super().close()

# Initialize bot
bot = ThoughtBot()

@bot.event
async def on_ready():
    print(f'ログインしました: {bot.user} (ID: {bot.user.id})')
    print('----------------------------------')

# Run the bot
if __name__ == '__main__':
    TOKEN = os.getenv('DISCORD_TOKEN')
    if not TOKEN:
        raise ValueError("環境変数にDISCORD_TOKENが設定されていません")
    
    bot.run(TOKEN)
