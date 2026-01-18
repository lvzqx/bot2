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
            target_channels = []
            if channel_id:
                try:
                    target_channel = interaction.guild.get_channel(int(channel_id))
                    if not target_channel:
                        await interaction.followup.send(f"❌ 指定されたチャンネルが見つかりません: {channel_id}", ephemeral=True)
                        return
                    target_channels.append(target_channel)
                    await interaction.followup.send(f"🔍 チャンネル `{target_channel.name}` から復元を開始します...", ephemeral=True)
                except ValueError:
                    await interaction.followup.send(f"❌ 無効なチャンネルIDです: {channel_id}", ephemeral=True)
                    return
            else:
                # 公開チャンネルと非公開チャンネルの両方を確認
                from config import CHANNELS
                for channel_type, cid in CHANNELS.items():
                    ch = interaction.guild.get_channel(cid)
                    if ch:
                        target_channels.append(ch)
                
                if not target_channels:
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
                
                # チャンネルリストを設定
                channel_list = [target_channel] if channel_id else target_channels
                
                for channel in channel_list:
                    await interaction.followup.send(f"📁 {channel.name} のメッセージをスキャン中...", ephemeral=True)
                    
                    message_count = 0
                    bot_message_count = 0
                    embed_count = 0
                    
                    # チャンネルのメッセージを取得
                    async for message in channel.history(limit=None):
                        message_count += 1
                        
                        # ボットのメッセージのみを処理
                        if message.author.bot:
                            bot_message_count += 1
                            
                            if message.embeds:
                                embed_count += 1
                                embed = message.embeds[0]
                                
                                # 投稿内容を取得
                                content = embed.description
                                if not content:
                                    continue
                            
                            # フッターから投稿IDを抽出
                            footer_text = embed.footer.text if embed.footer else ""
                            post_id = None
                            
                            if "投稿ID:" in footer_text:
                                try:
                                    post_id = int(footer_text.split("投稿ID:")[1].strip().split("|")[0].strip())
                                    print(f"[DEBUG] Footerから投稿IDを抽出: {post_id}")
                                except (ValueError, IndexError):
                                    print(f"[DEBUG] 投稿IDの解析に失敗: {footer_text}")
                                    pass
                            elif "ID:" in footer_text:
                                try:
                                    post_id = int(footer_text.split("ID:")[1].strip().split("|")[0].strip())
                                    print(f"[DEBUG] Footerから投稿IDを抽出（古い形式）: {post_id}")
                                except (ValueError, IndexError):
                                    print(f"[DEBUG] 投稿IDの解析に失敗（古い形式）: {footer_text}")
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
                            
                            # 投稿者IDを取得（ハッシュ化UIDから復元）
                            original_user_id = None
                            
                            # 方法1: ハッシュ化UIDから復元
                            import hashlib
                            has_uid = "UID:" in footer_text
                            if has_uid:
                                try:
                                    uid_hash = footer_text.split("UID:")[1].strip().split("|")[0].strip()
                                    print(f"[DEBUG] 投稿ID {post_id}: ハッシュ化UIDを検出: {uid_hash}")
                                    
                                    # サーバー内の全ユーザーのUIDをハッシュ化して比較
                                    for member in interaction.guild.members:
                                        member_hash = hashlib.sha256(str(member.id).encode()).hexdigest()[:8]
                                        if member_hash == uid_hash:
                                            original_user_id = member.id
                                            print(f"[DEBUG] 投稿ID {post_id}: ハッシュからユーザーを特定: {member.name} (ID: {original_user_id})")
                                            break
                                    
                                    if original_user_id is None:
                                        print(f"[DEBUG] 投稿ID {post_id}: ハッシュに一致するユーザーがいません")
                                        
                                except (ValueError, IndexError):
                                    print(f"[DEBUG] 投稿ID {post_id}: ハッシュ化UIDの解析に失敗しました")
                                    pass
                            
                            # 方法2: メッセージIDからmessage_referencesを検索（サーバー内部マッピング）
                            if original_user_id is None:
                                try:
                                    cursor.execute('''
                                        SELECT t.user_id 
                                        FROM thoughts t
                                        JOIN message_references mr ON t.id = mr.post_id
                                        WHERE mr.message_id = ?
                                    ''', (str(message.id),))
                                    ref_result = cursor.fetchone()
                                    if ref_result and ref_result[0]:
                                        original_user_id = ref_result[0]
                                        print(f"[DEBUG] 投稿ID {post_id}: MessageReferencesからuser_id={original_user_id} を検出")
                                except Exception as e:
                                    print(f"[DEBUG] 投稿ID {post_id}: MessageReferences検索エラー: {e}")
                            
                            # 方法3: Embed authorからユーザー名で特定
                            if original_user_id is None:
                                if embed.author and embed.author.name == "匿名ユーザー":
                                    # 匿名投稿の場合は復元実行者のIDを使用
                                    original_user_id = interaction.user.id
                                    print(f"[DEBUG] 投稿ID {post_id}: 匿名投稿として復元実行者のID={original_user_id} を使用")
                                elif embed.author and embed.author.name:
                                    # 非匿名投稿の場合、表示名からユーザーを検索
                                    display_name = embed.author.name
                                    print(f"[DEBUG] 投稿ID {post_id}: 表示名 '{display_name}' からユーザーを検索中...")
                                    
                                    # サーバー内で表示名が一致するユーザーを検索
                                    matching_members = []
                                    for member in interaction.guild.members:
                                        if member.display_name == display_name or member.name == display_name:
                                            matching_members.append(member)
                                    
                                    if len(matching_members) == 1:
                                        # 完全に一致するユーザーが1人だけの場合
                                        original_user_id = matching_members[0].id
                                        print(f"[DEBUG] 投稿ID {post_id}: 表示名からユーザーを特定: {matching_members[0].name} (ID: {original_user_id})")
                                    elif len(matching_members) > 1:
                                        # 複数一致する場合は不明としてマーク
                                        print(f"[DEBUG] 投稿ID {post_id}: 表示名 '{display_name}' に複数のユーザーが一致するため不明としてマーク")
                                        original_user_id = 0
                                    else:
                                        # 一致するユーザーがいない場合
                                        print(f"[DEBUG] 投稿ID {post_id}: 表示名 '{display_name}' に一致するユーザーがいないため不明としてマーク")
                                        original_user_id = 0
                                else:
                                    # author情報がない場合
                                    print(f"[DEBUG] 投稿ID {post_id}: author情報がないため不明としてマーク")
                                    original_user_id = 0
                            
                            # 匿名設定を判定
                            is_anonymous = embed.author.name == "匿名ユーザー"
                            
                            # 非公開設定を判定（チャンネルから判定）
                            is_private = not any(ch.id == channel.id for ch in channel_list if ch.name and "公開" in ch.name)
                            
                            # データベースに存在しないことを確認
                            if post_id:
                                cursor.execute('SELECT id FROM thoughts WHERE id = ?', (post_id,))
                                if not cursor.fetchone():
                                    # データベースに挿入
                                    cursor.execute('''
                                        INSERT INTO thoughts (content, category, is_anonymous, is_private, user_id, created_at)
                                        VALUES (?, ?, ?, ?, ?, ?)
                                    ''', (
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
                                    is_private = not any(ch.id == channel.id for ch in channel_list if ch.name and "公開" in ch.name)
                                    
                                    # データベースに存在しないことを確認
                                    if post_id:
                                        cursor.execute('SELECT id FROM thoughts WHERE id = ?', (post_id,))
                                        if not cursor.fetchone():
                                            # データベースに挿入
                                            cursor.execute('''
                                                INSERT INTO thoughts (content, category, is_anonymous, is_private, user_id, created_at)
                                                VALUES (?, ?, ?, ?, ?, ?)
                                            ''', (
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
                    f"📊 チャンネル `{channel.name}` のスキャン完了:\n"
                    f"• 総メッセージ数: {message_count}\n"
                    f"• ボットメッセージ数: {bot_message_count}\n"
                    f"• Embedメッセージ数: {embed_count}\n"
                    f"• 復元した投稿数: {recovered_count}", 
                    ephemeral=True
                )
            
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
