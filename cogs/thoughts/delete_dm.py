import discord
from discord.ext import commands
from discord import app_commands
import sqlite3
import traceback
from typing import Tuple, Optional

class DeleteDM(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        print("DeleteDM cog が読み込まれました")
    
    @app_commands.command(name="dm_delete", description="DMで送信したメッセージを削除します")
    @app_commands.describe(message_id="削除するメッセージのID")
    async def dm_delete(self, interaction: discord.Interaction, message_id: str):
        """DMで送信したメッセージを削除します"""
        # DMでのみ実行可能
        if not isinstance(interaction.channel, discord.DMChannel):
            await interaction.response.send_message(
                "このコマンドはDMでのみ使用できます。",
                ephemeral=True
            )
            return
        
        try:
            # メッセージIDを数値に変換
            message_id_int = int(message_id)
        except ValueError:
            await interaction.response.send_message(
                "無効なメッセージIDです。",
                ephemeral=True
            )
            return
        
        # メッセージ削除を実行
        success, message = await self.delete_message_by_id(
            interaction,
            message_id_int,
            interaction.user.id
        )
        
        # 結果をユーザーに通知
        if interaction.response.is_done():
            await interaction.followup.send(message, ephemeral=True)
        else:
            await interaction.response.send_message(message, ephemeral=True)
    
    
    def get_db_connection(self):
        """データベース接続を取得する（シンプル版）"""
        try:
            # データベースファイルのパスを取得（bot.pyと同じディレクトリを想定）
            db_path = 'thoughts.db'
            
            # データベースに接続（ファイルがなければ作成される）
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            
            # テーブルが存在するか確認し、なければ作成
            cursor = conn.cursor()
            
            # thoughts テーブル
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
            
            # attachments テーブル（必要な場合）
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS attachments (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    post_id INTEGER NOT NULL,
                    url TEXT NOT NULL,
                    FOREIGN KEY (post_id) REFERENCES thoughts (id) ON DELETE CASCADE
                )
            ''')
            
            conn.commit()
            return conn
            
        except Exception as e:
            print(f"[ERROR] データベース接続エラー: {e}")
            traceback.print_exc()
            # エラーが発生した場合は新しい接続を試みる
            try:
                conn = sqlite3.connect(':memory:')
                print("[WARNING] メモリ内データベースにフォールバックしました")
                return conn
            except:
                print("[CRITICAL] データベース接続に失敗しました")
                raise

    async def delete_message_by_id(self, interaction: discord.Interaction, message_id: int, user_id: int) -> Tuple[bool, str]:
        """DMでメッセージIDを指定して削除する
        
        Args:
            ctx: commands.Context オブジェクト
            message_id: 削除するメッセージID（整数）
            user_id: 削除を試みるユーザーID
        """
        print(f"[DEBUG] delete_message_by_id 開始: message_id={message_id}, user_id={user_id}")
        
        db = None
        try:
            # DMかどうか確認
            if not isinstance(interaction.channel, discord.DMChannel):
                return False, "このコマンドはDMでのみ使用できます。"
            
            print(f"[DEBUG] 検索対象のメッセージID: {message_id}")
            
            # データベースからメッセージ情報を取得
            db = self.get_db_connection()
            cursor = db.cursor()
            
            # メッセージを検索（ユーザーIDも確認）
            cursor.execute('''
                SELECT m.message_id, t.id as post_id, t.user_id
                FROM messages m
                JOIN thoughts t ON m.post_id = t.id
                WHERE m.message_id = ? AND t.user_id = ?
            ''', (str(message_id), user_id))
            
            message_info = cursor.fetchone()
            
            if not message_info:
                return False, "メッセージが見つからないか、削除する権限がありません。"
            
            # メッセージを削除
            try:
                message = await interaction.channel.fetch_message(message_id)
                if message:
                    await message.delete()
                
                # データベースからも削除
                cursor.execute('DELETE FROM messages WHERE message_id = ?', (str(message_id),))
                cursor.execute('DELETE FROM thoughts WHERE id = ?', (message_info['post_id'],))
                db.commit()
                
                return True, "メッセージを削除しました。"
                
            except discord.NotFound:
                # メッセージが既に削除されている場合はデータベースから削除
                cursor.execute('DELETE FROM messages WHERE message_id = ?', (str(message_id),))
                cursor.execute('DELETE FROM thoughts WHERE id = ?', (message_info['post_id'],))
                db.commit()
                return True, "メッセージは既に削除されています。"
                
            except discord.Forbidden:
                return False, "メッセージを削除する権限がありません。"
            
            # データベース接続を取得
            db = self.get_db_connection()
            cursor = db.cursor()
            
            # 存在するテーブルを確認
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
            message_data = cursor.fetchone()
            if not message_data:
                return False, "❌ メッセージが見つかりませんでした。メッセージIDまたはリンクが正しいか確認してください。"
            
            channel_id = message_data['channel_id']
            post_id = message_data['post_id']
            
            # 投稿の所有権を確認
            cursor.execute('''
                SELECT id FROM thoughts 
                WHERE id = ? AND user_id = ?
            ''', (post_id, user_id))
            
            if not cursor.fetchone():
                return False, "❌ この投稿を削除する権限がありません。自分の投稿のみ削除できます。"
            
            # メッセージを削除
            try:
                target_channel = self.bot.get_channel(int(channel_id))
                if target_channel:
                    msg = await target_channel.fetch_message(int(message_id))
                    if msg:
                        await msg.delete()
            except (discord.NotFound, discord.Forbidden):
                pass  # メッセージが既に削除されているか、権限がない場合は無視
            
            # データベースから削除
            try:
                cursor.execute('BEGIN TRANSACTION')
                
                # メッセージ参照を削除
                cursor.execute('''
                    DELETE FROM message_references 
                    WHERE message_id = ?
                ''', (str(message_id),))
                
                # 添付ファイルを削除（存在する場合）
                cursor.execute('''
                    DELETE FROM attachments 
                    WHERE thought_id = ?
                ''', (post_id,))
                
                # 他のメッセージ参照がなければ投稿も削除
                cursor.execute('''
                    SELECT COUNT(*) as count 
                    FROM message_references 
                    WHERE post_id = ?
                ''', (post_id,))
                
                if cursor.fetchone()['count'] == 0:
                    cursor.execute('''
                        DELETE FROM thoughts 
                        WHERE id = ?
                    ''', (post_id,))
                
                db.commit()
                return True, f"✅ 投稿 (ID: {post_id}) を削除しました"
                
            except Exception as e:
                db.rollback()
                raise
                
        except Exception as e:
            error_msg = f"❌ エラーが発生しました: {type(e).__name__}: {str(e)}"
            print(f"[ERROR] {error_msg}")
            traceback.print_exc()
            return False, error_msg

    @commands.hybrid_command(
        name="delete_private",
        description="DMで非公開投稿を削除します"
    )
    async def delete_private(self, interaction: discord.Interaction, message_id: str):
        """DMで非公開投稿を削除します"""
        # DMでのみ実行可能
        if not isinstance(interaction.channel, discord.DMChannel):
            await interaction.response.send_message(
                "このコマンドはDMでのみ利用可能です",
                ephemeral=True
            )
            return
        
        db = None
        try:
            # メッセージIDを数値に変換
            message_id_int = int(message_id)
            
            # データベース接続
            db = self.get_db_connection()
            cursor = db.cursor()
            
            # 外部キー制約を有効化
            cursor.execute("PRAGMA foreign_keys = ON")
            
            # トランザクション開始
            cursor.execute("BEGIN TRANSACTION")
            
            # メッセージ情報を取得（投稿者も確認）
            cursor.execute('''
                SELECT m.message_id, t.id as post_id, t.user_id
                FROM messages m
                JOIN thoughts t ON m.post_id = t.id
                WHERE m.message_id = ? AND t.user_id = ?
            ''', (str(message_id_int), interaction.user.id))
            
            message_info = cursor.fetchone()
            
            if not message_info:
                await interaction.response.send_message(
                    "メッセージが見つからないか、削除する権限がありません。",
                    ephemeral=True
                )
                db.rollback()
                return
            
            # データベースから削除（CASCADEにより関連するレコードも削除）
            cursor.execute('DELETE FROM messages WHERE message_id = ?', (str(message_id_int),))
            
            # コミット
            db.commit()
            
            # メッセージを削除（可能な場合）
            try:
                message = await interaction.channel.fetch_message(message_id_int)
                if message:
                    await message.delete()
            except (discord.NotFound, discord.Forbidden):
                # メッセージが既に削除されている場合は無視
                print(f"[INFO] メッセージ {message_id_int} は既に削除されています")
            
            await interaction.response.send_message(
                "メッセージを削除しました。",
                ephemeral=True
            )
            
        except ValueError:
            if db:
                db.rollback()
            await interaction.response.send_message(
                "無効なメッセージIDです。数値で指定してください。",
                ephemeral=True
            )
        except Exception as e:
            if db:
                db.rollback()
            error_msg = f"[ERROR] 削除コマンドエラー: {type(e).__name__}: {str(e)}"
            print(error_msg)
            traceback.print_exc()
            
            if not interaction.response.is_done():
                await interaction.response.send_message(
                    "エラーが発生しました。もう一度お試しください。",
                    ephemeral=True
                )

async def setup(bot):
    await bot.add_cog(DeleteDM(bot))
    print("DeleteDM cog が読み込まれました")
