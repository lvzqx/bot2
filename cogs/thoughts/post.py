import discord
from discord import app_commands
from discord.ext import commands
from datetime import datetime
import os
import traceback
import sys
import sqlite3

# Add the project root to the Python path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import DEFAULT_AVATAR

class Post(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.db = bot.db

    class PostModal(discord.ui.Modal, title='メッセージを投稿'):
        def __init__(self, bot, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.bot = bot
            
            # メッセージ入力
            self.content = discord.ui.TextInput(
                label='メッセージ (最大2000文字)',
                style=discord.TextStyle.long,
                placeholder='メッセージを入力してください...',
                required=True,
                max_length=2000,
                min_length=1
            )
            self.add_item(self.content)
            
            # カテゴリー入力
            self.category = discord.ui.TextInput(
                label='カテゴリー',
                placeholder='例: 独り言, 愚痴, 悩み, アイデア など',
                required=False,
                max_length=50
            )
            self.add_item(self.category)
            
            # 画像URL入力
            self.image_url = discord.ui.TextInput(
                label='画像URL (任意)',
                placeholder='画像のURLを入力...',
                required=False
            )
            self.add_item(self.image_url)
            
            # 匿名設定
            self.is_anonymous = discord.ui.TextInput(
                label='表示名',
                placeholder='名前を表示する場合は「表示」、匿名の場合は「匿名」と入力',
                default='表示',
                required=True,
                max_length=2
            )
            self.add_item(self.is_anonymous)
            
            # 公開設定
            self.is_private = discord.ui.TextInput(
                label='公開設定',
                placeholder='公開する場合は「公開」、非公開の場合は「非公開」と入力',
                default='公開',
                required=True,
                max_length=3
            )
            self.add_item(self.is_private)


        async def on_submit(self, interaction: discord.Interaction):
            try:
                # 即座に応答して処理中であることを伝える
                await interaction.response.defer(ephemeral=True)
                
                # モーダルの入力を取得
                content = self.content.value
                category = self.category.value if self.category.value else 'その他'
                image_url = self.image_url.value if self.image_url.value else None
                is_anonymous = self.is_anonymous.value.strip() == '匿名'
                is_private = self.is_private.value.strip() == '非公開'
                
                # 入力バリデーション
                if not content or len(content.strip()) == 0:
                    raise ValueError('メッセージを入力してください。')
                    
                if len(content) > 2000:
                    raise ValueError('メッセージは2000文字以内で入力してください。')
                
                # データベース接続を確立
                try:
                    # データベースファイルのパス（bot.pyと同じディレクトリ）
                    db_path = 'thoughts.db'
                    print(f"[DEBUG] データベースファイルのパス: {os.path.abspath(db_path)}")
                    
                    # ディレクトリが存在するか確認し、なければ作成
                    os.makedirs(os.path.dirname(os.path.abspath(db_path)) or '.', exist_ok=True)
                    
                    # データベースに接続（ファイルがなければ作成される）
                    conn = sqlite3.connect(db_path)
                    conn.row_factory = sqlite3.Row
                    cursor = conn.cursor()
                    
                    # 外部キー制約を有効化
                    cursor.execute('PRAGMA foreign_keys = ON')
                    
                    # トランザクション開始
                    cursor.execute('BEGIN TRANSACTION')
                    
                    try:
                        # テーブルが存在するか確認し、なければ作成
                        cursor.execute('''
                            CREATE TABLE IF NOT EXISTS thoughts (
                                id INTEGER PRIMARY KEY AUTOINCREMENT,
                                user_id INTEGER NOT NULL,
                                content TEXT NOT NULL,
                                category TEXT,
                                image_url TEXT,
                                is_anonymous BOOLEAN DEFAULT 0,
                                is_private BOOLEAN DEFAULT 0,
                                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                                display_name TEXT
                            )
                        ''')
                        
                        # messages テーブル
                        cursor.execute('''
                            CREATE TABLE IF NOT EXISTS messages (
                                id INTEGER PRIMARY KEY AUTOINCREMENT,
                                channel_id TEXT NOT NULL,
                                message_id TEXT NOT NULL UNIQUE,
                                post_id INTEGER NOT NULL,
                                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                                FOREIGN KEY (post_id) REFERENCES thoughts (id) ON DELETE CASCADE
                            )
                        ''')
                        
                        # attachments テーブル
                        cursor.execute('''
                            CREATE TABLE IF NOT EXISTS attachments (
                                id INTEGER PRIMARY KEY AUTOINCREMENT,
                                post_id INTEGER NOT NULL,
                                url TEXT NOT NULL,
                                FOREIGN KEY (post_id) REFERENCES thoughts (id) ON DELETE CASCADE
                            )
                        ''')
                        
                        conn.commit()
                        print("[DEBUG] テーブルの作成/確認が完了しました")
                        
                    except Exception as e:
                        conn.rollback()
                        print(f"[ERROR] テーブル作成エラー: {e}")
                        raise
                    
                    print("[DEBUG] データベース接続が確立されました")
                    
                except sqlite3.Error as e:
                    error_msg = f"[ERROR] データベースエラー: {e}"
                    print(error_msg)
                    print(f"[DEBUG] データベースファイルの存在: {os.path.exists(db_path) if 'db_path' in locals() else '不明'}")
                    print(f"[DEBUG] カレントディレクトリ: {os.getcwd()}")
                    import traceback
                    traceback.print_exc()
                    if interaction.response.is_done():
                        await interaction.followup.send("❌ データベースエラーが発生しました。詳細は管理者に問い合わせてください。", ephemeral=True)
                    else:
                        await interaction.response.send_message("❌ データベースエラーが発生しました。詳細は管理者に問い合わせてください。", ephemeral=True)
                    return
                    
                except Exception as e:
                    error_msg = f"[ERROR] 予期せぬエラー: {e}"
                    print(error_msg)
                    import traceback
                    traceback.print_exc()
                    if interaction.response.is_done():
                        await interaction.followup.send("❌ 予期せぬエラーが発生しました。しばらくしてからもう一度お試しください。", ephemeral=True)
                    else:
                        await interaction.response.send_message("❌ 予期せぬエラーが発生しました。しばらくしてからもう一度お試しください。", ephemeral=True)
                    return
                    
                    # 現在の日時を取得
                    now = datetime.now().isoformat()
                    
                    # 投稿を挿入
                    cursor.execute('''
                        INSERT INTO thoughts (
                            user_id, content, category, image_url, 
                            is_anonymous, is_private, created_at, updated_at,
                            display_name
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ''', (
                        interaction.user.id,
                        content,
                        category,
                        image_url,
                        is_anonymous,  # 匿名設定
                        is_private,  # 公開設定
                        now,
                        now,
                        None if is_anonymous else interaction.user.display_name  # 表示名を保存
                    ))
                    
                    # 投稿完了メッセージを表示
                    embed = discord.Embed(
                        title='✅ 投稿が完了しました',
                        description=content,
                        color=discord.Color.green()
                    )
                    
                    # 投稿者情報を設定
                    if not is_anonymous:
                        embed.set_author(
                            name=interaction.user.display_name,
                            icon_url=str(interaction.user.display_avatar.url)
                        )
                    else:
                        embed.set_author(name='匿名')
                    
                    # カテゴリーと表示設定を追加
                    embed.add_field(name='カテゴリー', value=category, inline=True)
                    embed.add_field(name='表示名', value='匿名' if is_anonymous else '表示', inline=True)
                    embed.add_field(name='公開設定', value='非公開 🔒' if is_private else '公開 🌐', inline=True)
                    
                    # 画像がある場合は追加
                    if image_url:
                        embed.set_image(url=image_url)
                    
                    # データベースの変更を確定
                    self.bot.db.commit()
                    
                    # 投稿IDを取得
                    post_id = cursor.lastrowid
                    
                    # チャンネルまたはDMに投稿
                    try:
                        if is_private:
                            try:
                                # 投稿者にDMを送信
                                dm_embed = discord.Embed(
                                    description=content,
                                    color=discord.Color.blue()
                                )
                                
                                # 表示名を設定
                                if is_anonymous:
                                    dm_embed.set_author(name='匿名', icon_url=DEFAULT_AVATAR)
                                else:
                                    dm_embed.set_author(
                                        name=interaction.user.display_name,
                                        icon_url=str(interaction.user.display_avatar.url)
                                    )
                                
                                # フッターにカテゴリーと投稿IDを表示
                                footer_text = f'カテゴリー: {category} | ID: {post_id}'
                                dm_embed.set_footer(text=footer_text)
                                
                                # 画像があれば追加
                                if image_url:
                                    dm_embed.set_image(url=image_url)
                                
                                # 送信先のユーザーを取得
                                user = interaction.user
                                if user:
                                    dm_channel = user.dm_channel or await user.create_dm()
                                    await dm_channel.send(embed=dm_embed)
                            except Exception as e:
                                print(f"DM送信エラー: {e}")
                                await interaction.followup.send("❌ 非公開メッセージの送信中にエラーが発生しました。", ephemeral=True)
                            
                            # 確認メッセージを更新
                            embed.add_field(name='配信先', value='DMに送信されました', inline=False)
                            
                        else:
                            # チャンネルに投稿するための埋め込みメッセージを作成
                            channel_embed = discord.Embed(
                                description=content,
                                color=discord.Color.blue()
                            )
                            
                            # 投稿者情報を設定
                            if not is_anonymous:
                                channel_embed.set_author(
                                    name=interaction.user.display_name,
                                    icon_url=str(interaction.user.display_avatar.url)
                                )
                            else:
                                channel_embed.set_author(name='匿名', icon_url=DEFAULT_AVATAR)
                            
                            # フッターにカテゴリーと投稿IDを表示（時間は表示しない）
                            footer_text = f'カテゴリー: {category} | ID: {post_id}'
                            channel_embed.set_footer(text=footer_text)
                            
                            # 画像がある場合は追加
                            if image_url:
                                channel_embed.set_image(url=image_url)
                            
                            # チャンネルに投稿
                            message = await interaction.channel.send(embed=channel_embed)
                            
                            # メッセージ参照をデータベースに保存
                            try:
                                cursor.execute('''
                                    INSERT INTO message_references (post_id, message_id, channel_id)
                                    VALUES (?, ?, ?)
                                ''', (post_id, message.id, message.channel.id))
                                self.bot.db.commit()
                            except Exception as e:
                                print(f"メッセージ参照の保存中にエラーが発生しました: {e}")
                            
                            # 確認メッセージを更新
                            embed.add_field(name='チャンネル', value=f'[投稿を表示]({message.jump_url})', inline=False)
                            
                    except Exception as e:
                        # DM送信に失敗した場合のエラーハンドリング
                        error_msg = f"メッセージの送信中にエラーが発生しました: {str(e)}"
                        if "Cannot send messages to this user" in str(e):
                            error_msg = "DMを送信できませんでした。DMの設定を確認してください。"
                        embed.add_field(name='エラー', value=error_msg, inline=False)
                    
                    # ユーザーに確認メッセージを送信
                    await interaction.followup.send(embed=embed, ephemeral=True)
                    
                except Exception as e:
                    self.bot.db.rollback()
                    raise e
                    
            except Exception as e:
                error_msg = str(e)
                print(f"[ERROR] 投稿エラー: {error_msg}")
                
                # エラーメッセージを適切に整形
                if "UNIQUE constraint failed" in error_msg:
                    error_msg = "このメッセージは既に投稿されています。"
                elif "no such table" in error_msg.lower():
                    error_msg = "データベースの初期化に失敗しました。管理者に連絡してください。"
                elif "no such column" in error_msg.lower():
                    error_msg = "データベースの構造に問題があります。管理者に連絡してください。"
                
                error_embed = discord.Embed(
                    title='❌ エラー',
                    description=f'投稿中にエラーが発生しました: {error_msg}',
                    color=discord.Color.red()
                )
                
                try:
                    # インタラクションがまだ有効か確認
                    if not interaction.response.is_done():
                        await interaction.response.send_message(embed=error_embed, ephemeral=True)
                    else:
                        await interaction.followup.send(embed=error_embed, ephemeral=True)
                except:
                    # すべてのエラーをキャッチしてログに記録
                    import traceback
                    traceback.print_exc()
                    
                    # ユーザーにエラーを通知（DMで送信）
                    try:
                        # await interaction.user.send(embed=error_embed)
                        pass
                    except:
                        pass  # DMがブロックされている場合は無視

    @app_commands.command(name="post", description="新しい投稿を作成します")
    async def post(self, interaction: discord.Interaction):
        """新しい投稿を作成します"""
        # DMの場合は無効化
        if isinstance(interaction.channel, discord.DMChannel):
            await interaction.response.send_message("❌ このコマンドはDMでは使用できません。サーバー内でお試しください。", ephemeral=True)
            return
            
        # モーダルを表示
        modal = self.PostModal(bot=self.bot)
        await interaction.response.send_modal(modal)

async def setup(bot):
    await bot.add_cog(Post(bot))
