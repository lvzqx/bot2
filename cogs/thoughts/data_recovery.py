import discord
from discord.ext import commands
from discord import app_commands
import sqlite3
import logging
from typing import Optional
from bot import DatabaseMixin
from config import DEFAULT_AVATAR

logger = logging.getLogger(__name__)

class DataRecovery(commands.Cog, DatabaseMixin):
    """データ復元用Cog"""
    
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        DatabaseMixin.__init__(self)
    
    @app_commands.command(name="recover_from_messages", description="Discordメッセージからデータベースを復元します")
    @app_commands.default_permissions(administrator=True)
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.describe(channel_id="復元するチャンネルID（省略可）")
    async def recover_from_messages(self, interaction: discord.Interaction, channel_id: Optional[str] = None):
        """Discordメッセージからデータベースを復元します"""
        try:
            await interaction.response.defer(ephemeral=True)
            
            # 復元対象チャンネルを決定
            channels = []
            if channel_id:
                target_channel = interaction.guild.get_channel(int(channel_id))
                if not target_channel:
                    await interaction.followup.send("❌ 指定されたチャンネルが見つかりません。", ephemeral=True)
                    return
                channels.append(target_channel)
            else:
                # 公開チャンネルと非公開チャンネルの両方を確認
                from config import CHANNELS
                for channel_type, cid in CHANNELS.items():
                    ch = interaction.guild.get_channel(cid)
                    if ch:
                        channels.append(ch)
                
                if not channels:
                    await interaction.followup.send("❌ チャンネルが見つかりません。", ephemeral=True)
                    return
            
            recovered_count = 0
            
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                
                # テーブルが存在することを確認
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
                        post_id INTEGER,
                        message_id TEXT,
                        channel_id TEXT,
                        PRIMARY KEY (post_id)
                    )
                ''')
                
                target_channels = [target_channel] if channel_id else channels
                
                for channel in target_channels:
                    await interaction.followup.send(f"📁 {channel.name} のメッセージをスキャン中...", ephemeral=True)
                    
                    # チャンネルのメッセージを取得
                    async for message in channel.history(limit=None):
                        # ボットのメッセージのみを処理
                        if message.author.bot and message.embeds:
                            embed = message.embeds[0]
                            
                            # 投稿内容を取得
                            content = embed.description
                            if not content:
                                continue
                            
                            # フッターから投稿IDを抽出
                            footer_text = embed.footer.text if embed.footer else ""
                            post_id = None
                            
                            if "ID:" in footer_text:
                                try:
                                    post_id = int(footer_text.split("ID:")[1].strip())
                                except (ValueError, IndexError):
                                    pass
                            
                            # カテゴリーを抽出
                            category = None
                            if "カテゴリ:" in footer_text:
                                try:
                                    category = footer_text.split("カテゴリ:")[1].split("|")[0].strip()
                                    if category == "未設定":
                                        category = None
                                except (IndexError, AttributeError):
                                    pass
                            
                            # message_referencesからuser_idを取得
                            cursor.execute('''
                                SELECT user_id 
                                FROM message_references 
                                WHERE message_id = ?
                            ''', (message_id,))
                            user_ref = cursor.fetchone()
                            original_user_id = user_ref[0] if user_ref else None
                            
                            if original_user_id is None:
                                print(f"[DEBUG] 投稿ID {post_id}: message_referencesにuser_idが見つかりません")
                                continue
                            else:
                                print(f"[DEBUG] 投稿ID {post_id}: user_id={original_user_id} を検出、復元します")
                            
                            # 非公開設定を判定（チャンネルから判定）
                            is_private = not any(ch.id == channel.id for ch in channels if ch.name and "公開" in ch.name)
                            
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
                                        original_user_id,  # 匿名の場合はNULL、非匿名の場合は復元実行者のID（暫定）
                                        message.created_at
                                    ))
                                    
                                    # メッセージ参照を追加
                                    cursor.execute('''
                                        INSERT INTO message_references (post_id, message_id, channel_id)
                                        VALUES (?, ?, ?)
                                    ''', (post_id, str(message.id), str(channel.id)))
                                    
                                    recovered_count += 1
                                    
                                    if recovered_count % 10 == 0:
                                        await interaction.followup.send(
                                            f"🔄 {recovered_count}件を復元中...", 
                                            ephemeral=True
                                        )
                    
                    # スレッドもスキャン
                    if hasattr(channel, 'threads'):
                        for thread in channel.threads:
                            await interaction.followup.send(f"🧵 {thread.name} のメッセージをスキャン中...", ephemeral=True)
                            
                            async for message in thread.history(limit=None):
                                # ボットのメッセージのみを処理
                                if message.author.bot and message.embeds:
                                    embed = message.embeds[0]
                                    
                                    # 投稿内容を取得
                                    content = embed.description
                                    if not content:
                                        continue
                                    
                                    # フッターから投稿IDを抽出
                                    footer_text = embed.footer.text if embed.footer else ""
                                    post_id = None
                                    
                                    if "ID:" in footer_text:
                                        try:
                                            post_id = int(footer_text.split("ID:")[1].strip())
                                        except (ValueError, IndexError):
                                            pass
                                    
                                    # カテゴリーを抽出
                                    category = None
                                    if "カテゴリ:" in footer_text:
                                        try:
                                            category = footer_text.split("カテゴリ:")[1].split("|")[0].strip()
                                            if category == "未設定":
                                                category = None
                                        except (IndexError, AttributeError):
                                            pass
                                    
                                    # 匿名設定を判定
                                    is_anonymous = embed.author.name == "匿名ユーザー"
                                    print(f"[DEBUG] 復元時の匿名判定: author.name='{embed.author.name}', is_anonymous={is_anonymous}")
                                    
                                    # アイコンも確認
                                    if hasattr(embed.author, 'icon_url') and embed.author.icon_url:
                                        is_anonymous_by_icon = embed.author.icon_url == DEFAULT_AVATAR
                                        print(f"[DEBUG] アイコンによる匿名判定: icon_url='{embed.author.icon_url}', is_anonymous_by_icon={is_anonymous_by_icon}")
                                        # どちらか一方でも匿名なら匿名として扱う
                                        is_anonymous = is_anonymous or is_anonymous_by_icon
                                    
                                    # 非公開設定を判定（親チャンネルから判定）
                                    is_private = not any(ch.id == channel.id for ch in channels if ch.name and "公開" in ch.name)
                                    
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
                                                int(is_anonymous),  # 明示的にintに変換
                                                int(is_private),
                                                interaction.user.id,  # 復元実行者のID
                                                message.created_at
                                            ))
                                            print(f"[DEBUG] データベース挿入: post_id={post_id}, is_anonymous={int(is_anonymous)}, is_private={int(is_private)}")
                                            
                                            # メッセージ参照を追加
                                            cursor.execute('''
                                                INSERT INTO message_references (post_id, message_id, channel_id)
                                                VALUES (?, ?, ?)
                                            ''', (post_id, str(message.id), str(thread.id)))
                                            
                                            recovered_count += 1
                                            
                                            if recovered_count % 10 == 0:
                                                await interaction.followup.send(
                                                    f"🔄 {recovered_count}件を復元中...", 
                                                    ephemeral=True
                                                )
                
                conn.commit()
            
            await interaction.followup.send(
                f"✅ データベース復元が完了しました！\n"
                f"📊 復元件数: {recovered_count}件\n"
                f"💾 データベースをバックアップすることをお勧めします。",
                ephemeral=True
            )
            
            logger.info(f"データベース復元完了: {recovered_count}件")
            
        except Exception as e:
            logger.error(f"データ復元中にエラーが発生しました: {e}", exc_info=True)
            await interaction.followup.send(
                f"❌ エラーが発生しました: {e}",
                ephemeral=True
            )

async def setup(bot):
    await bot.add_cog(DataRecovery(bot))
