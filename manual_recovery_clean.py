import sqlite3
import discord
from discord.ext import commands
import os

# 手動データ復元スクリプト
async def manual_data_recovery(bot):
    """手動でデータベースを復元する"""
    
    # データベース接続
    conn = sqlite3.connect('thoughts.db')
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
            user_id INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS message_references (
            post_id INTEGER PRIMARY KEY,
            message_id TEXT NOT NULL,
            channel_id TEXT NOT NULL
        )
    ''')
    
    recovered_count = 0
    
    # チャンネルIDを直接指定
    channel_configs = [
        ('public', 1457611087561101332),
        ('private', 1457611128225009666)
    ]
    
    # 各チャンネルをスキャン
    for channel_type, channel_id in channel_configs:
        channel = bot.get_channel(channel_id)
        if not channel:
            print(f"チャンネル {channel_id} が見つかりません")
            continue
        
        print(f"{channel.name} をスキャン中...")
        
        # メッセージ履歴を取得
        async for message in channel.history(limit=None):
            if message.author.bot and message.embeds:
                embed = message.embeds[0]
                
                # 投稿内容を取得
                content = embed.description
                if not content:
                    continue
                
                # フッターから情報を抽出
                footer_text = embed.footer.text if embed.footer else ""
                post_id = None
                category = None
                
                # 投稿IDを抽出
                if "ID:" in footer_text:
                    try:
                        post_id = int(footer_text.split("ID:")[1].strip())
                    except (ValueError, IndexError):
                        pass
                
                # カテゴリーを抽出
                if "カテゴリ:" in footer_text:
                    try:
                        category = footer_text.split("カテゴリ:")[1].split("|")[0].strip()
                        if category == "未設定":
                            category = None
                    except (IndexError, AttributeError):
                        pass
                
                # 匿名設定を判定
                is_anonymous = embed.author.name == "匿名ユーザー"
                
                # 非公開設定を判定
                is_private = channel_type == 'private'
                
                # データベースに存在しないことを確認
                if post_id:
                    cursor.execute('SELECT id FROM thoughts WHERE id = ?', (post_id,))
                    if not cursor.fetchone():
                        # データベースに挿入
                        cursor.execute('''
                            INSERT INTO thoughts (id, content, category, is_anonymous, is_private, user_id, created_at)
                            VALUES (?, ?, ?, ?, ?, ?, ?)
                        ''', (
                            post_id,
                            content,
                            category,
                            is_anonymous,
                            is_private,
                            bot.user.id,  # ボットのIDを仮設定
                            message.created_at
                        ))
                        
                        # メッセージ参照を追加
                        cursor.execute('''
                            INSERT INTO message_references (post_id, message_id, channel_id)
                            VALUES (?, ?, ?)
                        ''', (post_id, str(message.id), str(channel.id)))
                        
                        recovered_count += 1
                        print(f"復元: ID {post_id} - {content[:50]}...")
    
    conn.commit()
    conn.close()
    
    print(f"復元完了: {recovered_count}件")
    return recovered_count

# 使用方法
if __name__ == "__main__":
    import asyncio
    
    # トークンを設定
    TOKEN = os.getenv('DISCORD_TOKEN')
    if not TOKEN:
        print("DISCORD_TOKENが設定されていません")
        exit(1)
    
    # ボットを準備
    intents = discord.Intents.default()
    intents.message_content = True
    intents.guilds = True
    
    bot = commands.Bot(command_prefix='!', intents=intents)
    
    @bot.event
    async def on_ready():
        print(f"ログイン: {bot.user}")
        
        # データ復元を実行
        count = await manual_data_recovery(bot)
        print(f"データ復元が完了しました: {count}件")
        
        # ボットを終了
        await bot.close()
    
    # ボットを実行
    asyncio.run(bot.start(TOKEN))
