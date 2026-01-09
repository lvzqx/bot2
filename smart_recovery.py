import sqlite3
import discord
from discord.ext import commands
import os
import re
from datetime import datetime
from config import CHANNELS, DEFAULT_AVATAR

class MessageAnalyzer:
    """Discordメッセージを解析してデータベースに復元するクラス"""
    
    def __init__(self, bot):
        self.bot = bot
        self.recovered_count = 0
        self.skipped_count = 0
        self.error_count = 0
    
    def extract_post_info_from_embed(self, embed):
        """埋め込みメッセージから投稿情報を抽出"""
        info = {
            'post_id': None,
            'content': None,
            'category': None,
            'is_anonymous': False,
            'image_url': None
        }
        
        # 投稿内容
        info['content'] = embed.description
        
        # 画像URL
        if embed.image:
            info['image_url'] = embed.image.url
        
        # 投稿者情報から匿名設定を判定
        if embed.author:
            info['is_anonymous'] = embed.author.name == "匿名ユーザー"
        
        # フッターから投稿IDとカテゴリーを抽出
        if embed.footer and embed.footer.text:
            footer_text = embed.footer.text
            
            # 投稿IDを抽出（複数のパターンに対応）
            id_patterns = [
                r'ID:\s*(\d+)',
                r'投稿ID:\s*(\d+)',
                r'ID\s*(\d+)'
            ]
            
            for pattern in id_patterns:
                match = re.search(pattern, footer_text)
                if match:
                    info['post_id'] = int(match.group(1))
                    break
            
            # カテゴリーを抽出
            category_patterns = [
                r'カテゴリ:\s*([^|]+)',
                r'カテゴリー:\s*([^|]+)',
                r'Category:\s*([^|]+)'
            ]
            
            for pattern in category_patterns:
                match = re.search(pattern, footer_text)
                if match:
                    category = match.group(1).strip()
                    if category and category != "未設定":
                        info['category'] = category
                    break
        
        return info
    
    def extract_post_info_from_content(self, content):
        """通常メッセージから投稿情報を抽出"""
        info = {
            'post_id': None,
            'content': content,
            'category': None,
            'is_anonymous': False,
            'image_url': None
        }
        
        # メッセージ内からIDを抽出
        id_patterns = [
            r'投稿ID[:\s]*(\d+)',
            r'ID[:\s]*(\d+)',
            r'#(\d+)',
            r'ID(\d+)'
        ]
        
        for pattern in id_patterns:
            match = re.search(pattern, content)
            if match:
                info['post_id'] = int(match.group(1))
                break
        
        # カテゴリーを抽出
        category_patterns = [
            r'カテゴリ[:\s*([^\n]+)',
            r'カテゴリー[:\s*([^\n]+)',
            r'Category[:\s*([^\n]+)'
        ]
        
        for pattern in category_patterns:
            match = re.search(pattern, content)
            if match:
                category = match.group(1).strip()
                if category and category != "未設定":
                    info['category'] = category
                break
        
        return info
    
    def is_bot_message(self, message):
        """ボットのメッセージかどうかを判定"""
        return message.author.bot
    
    def has_post_data(self, message):
        """メッセージに投稿データが含まれているか判定"""
        # 埋め込みメッセージをチェック
        if message.embeds:
            for embed in message.embeds:
                if embed.description:  # 内容がある
                    return True
        
        # 通常メッセージをチェック
        if message.content:
            # 投稿IDのパターンを検索
            id_patterns = [
                r'投稿ID[:\s]*\d+',
                r'ID[:\s]*\d+',
                r'#\d+'
            ]
            
            for pattern in id_patterns:
                if re.search(pattern, message.content):
                    return True
        
        return False
    
    async def analyze_and_recover_message(self, message, channel_type):
        """メッセージを解析してデータベースに復元"""
        try:
            post_info = None
            
            # 埋め込みメッセージから情報を抽出
            if message.embeds:
                for embed in message.embeds:
                    post_info = self.extract_post_info_from_embed(embed)
                    if post_info['content'] and post_info['post_id']:
                        break
            
            # 通常メッセージから情報を抽出
            elif message.content:
                post_info = self.extract_post_info_from_content(message.content)
            
            # 有効な投稿情報がない場合はスキップ
            if not post_info or not post_info['content'] or not post_info['post_id']:
                self.skipped_count += 1
                return False
            
            # データベースに既に存在するか確認
            conn = sqlite3.connect('thoughts.db')
            cursor = conn.cursor()
            
            cursor.execute('SELECT id FROM thoughts WHERE id = ?', (post_info['post_id'],))
            if cursor.fetchone():
                conn.close()
                self.skipped_count += 1
                return False
            
            # データベースに挿入
            cursor.execute('''
                INSERT INTO thoughts (id, content, category, image_url, is_anonymous, is_private, user_id, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                post_info['post_id'],
                post_info['content'],
                post_info['category'],
                post_info['image_url'],
                post_info['is_anonymous'],
                channel_type == 'private',
                message.author.id if not message.author.bot else self.bot.user.id,
                message.created_at
            ))
            
            # メッセージ参照を追加
            cursor.execute('''
                INSERT INTO message_references (post_id, message_id, channel_id)
                VALUES (?, ?, ?)
            ''', (post_info['post_id'], str(message.id), str(message.channel.id)))
            
            conn.commit()
            conn.close()
            
            self.recovered_count += 1
            print(f"✅ 復元: ID {post_info['post_id']} - {post_info['content'][:50]}...")
            return True
            
        except Exception as e:
            self.error_count += 1
            print(f"❌ エラー: {e}")
            return False
    
    async def scan_channel(self, channel, channel_type):
        """チャンネルをスキャンしてメッセージを解析"""
        print(f"\n📁 {channel.name} ({channel_type}) をスキャン中...")
        
        message_count = 0
        recovered_in_channel = 0
        
        try:
            # メッセージ履歴を取得
            async for message in channel.history(limit=None):
                message_count += 1
                
                # 進捗表示
                if message_count % 100 == 0:
                    print(f"  📊 {message_count}件のメッセージを処理中...")
                
                # ボットメッセージで投稿データを含むものを処理
                if self.is_bot_message(message) and self.has_post_data(message):
                    if await self.analyze_and_recover_message(message, channel_type):
                        recovered_in_channel += 1
                
                # 進捗表示
                if message_count % 500 == 0:
                    print(f"  📈 復元済み: {recovered_in_channel}件")
        
        except Exception as e:
            print(f"❌ チャンネル {channel.name} のスキャン中にエラー: {e}")
            self.error_count += 1
        
        print(f"  ✅ {channel.name}: {message_count}件中 {recovered_in_channel}件を復元")
        return recovered_in_channel
    
    async def recover_all_channels(self):
        """すべてのチャンネルをスキャンして復元"""
        print("🚀 Discordメッセージの解析と復元を開始します...")
        
        # データベース初期化
        conn = sqlite3.connect('thoughts.db')
        cursor = conn.cursor()
        
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
        
        conn.commit()
        conn.close()
        
        # 各チャンネルをスキャン
        total_recovered = 0
        channel_configs = [
            ('public', 1457611087561101332),
            ('private', 1457611128225009666)
        ]
        
        for channel_type, channel_id in channel_configs:
            channel = self.bot.get_channel(channel_id)
            if channel:
                recovered = await self.scan_channel(channel, channel_type)
                total_recovered += recovered
            else:
                print(f"❌ チャンネル {channel_id} が見つかりません")
        
        # 結果表示
        print(f"\n🎉 復元完了！")
        print(f"📊 復元した投稿: {self.recovered_count}件")
        print(f"📄 スキップしたメッセージ: {self.skipped_count}件")
        print(f"❌ エラー: {self.error_count}件")
        print(f"📈 合計処理メッセージ: {self.recovered_count + self.skipped_count + self.error_count}件")
        
        return self.recovered_count

# メイン処理
async def smart_message_recovery(bot):
    """スマートメッセージ復元を実行"""
    analyzer = MessageAnalyzer(bot)
    return await analyzer.recover_all_channels()

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
        print(f"🤖 ログイン: {bot.user}")
        print("=" * 50)
        
        # スマートメッセージ復元を実行
        count = await smart_message_recovery(bot)
        print("=" * 50)
        print(f"✅ スマート復元が完了しました: {count}件")
        
        # ボットを終了
        await bot.close()
    
    # ボットを実行
    asyncio.run(bot.start(TOKEN))
