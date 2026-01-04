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
        success, result_message = await self.delete_message_by_id(
            interaction,
            message_id_int,
            interaction.user.id
        )
        
        # 結果をユーザーに通知
        if interaction.response.is_done():
            await interaction.followup.send(result_message, ephemeral=True)
        else:
            await interaction.response.send_message(result_message, ephemeral=True)
    
    
    def get_db_connection(self):
        """データベース接続を取得する（シンプル版）"""
        try:
            # データベースファイルのパスを絶対パスで指定
            import os
            db_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'thoughts.db')
            print(f"[DEBUG] データベースパス: {db_path}")
            print(f"[DEBUG] ファイル存在確認: {os.path.exists(db_path)}")
            
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
            interaction: discord.Interaction オブジェクト
            message_id: 削除するメッセージID
            user_id: 削除を試みるユーザーID
        """
        print(f"[DEBUG] delete_message_by_id 開始: message_id={message_id} (型: {type(message_id)}), user_id={user_id}")
        
        # メッセージIDを文字列に変換
        message_id_str = str(message_id)
        print(f"[DEBUG] メッセージID (文字列): {message_id_str}")
        
        db = None
        try:
            # チャンネルを取得
            channel = interaction.channel
            
            print(f"[DEBUG] 検索対象のメッセージID: {message_id}")
            
            # データベースからメッセージ情報を取得
            db = self.get_db_connection()
            cursor = db.cursor()
            
            # データベースの全メッセージを表示（デバッグ用）
            print("[DEBUG] データベース内の全メッセージ:")
            cursor.execute('''
                SELECT m.id as db_id, m.message_id, t.user_id, m.channel_id, t.content, t.id as post_id
                FROM messages m
                JOIN thoughts t ON m.post_id = t.id
                WHERE t.user_id = ?
                ORDER BY m.id DESC
                LIMIT 10
            ''', (user_id,))
            db_messages = cursor.fetchall()
            print(f"[DEBUG] ユーザー {user_id} のメッセージ件数: {len(db_messages)}")
            for row in db_messages:
                msg_id = row['message_id']
                print(f"[DEBUG] メッセージ: db_id={row['db_id']}, msg_id='{msg_id}' (型: {type(msg_id)}), "
                      f"post_id={row['post_id']}, user_id={row['user_id']}, "
                      f"channel_id={row['channel_id']}, content='{row['content'][:30]}...'")
            
            # メッセージを検索（ユーザーIDも確認）
            print(f"[DEBUG] データベース検索: message_id={message_id}, user_id={user_id}")
            
            # メッセージIDとユーザーIDで検索（型を考慮）
            print(f"[DEBUG] データベース検索開始: message_id={message_id} (型: {type(message_id)}), user_id={user_id}")
            
            # DM専用の削除処理（チャンネルIDはチェックしない）
            print(f"[DEBUG] DM専用削除処理を開始: message_id={message_id}, user_id={user_id}")
            
            # メッセージIDの型に関わらず検索（文字列と数値の両方で試す）
            cursor.execute('''
                SELECT m.message_id, t.id as post_id, t.user_id, m.channel_id, t.content
                FROM messages m
                JOIN thoughts t ON m.post_id = t.id
                WHERE (m.message_id = ? OR m.message_id = ?) 
                AND t.user_id = ?
            ''', (str(message_id), int(message_id), user_id))
            
            # 検索結果を取得して表示（デバッグ用）
            message_info = cursor.fetchone()
            results = cursor.fetchall()  # 残りの結果をクリア
            
            if message_info:
                print(f"[DEBUG] 検索結果: message_id={message_info['message_id']} (型: {type(message_info['message_id'])}), post_id={message_info['post_id']}, user_id={message_info['user_id']}")
            else:
                print("[DEBUG] 検索結果: 該当するメッセージが見つかりませんでした")
            print(f"[DEBUG] データベース検索結果: {message_info}")
            
            if not message_info:
                print("[DEBUG] メッセージが見つからないか、削除する権限がありません")
                return False, "メッセージが見つからないか、削除する権限がありません。"
            
            # ボットが送信したメッセージを削除
            try:
                # メッセージIDを文字列に変換
                message_id_str = str(message_id)
                print(f"[DEBUG] 削除を試みるメッセージID: {message_id_str}")
                
                # DMでメッセージを取得して削除を試みる
                try:
                    print(f"[DEBUG] DMからメッセージを取得中: message_id={message_id_str}")
                    
                    # DMチャンネルからメッセージを取得
                    try:
                        message = await interaction.channel.fetch_message(int(message_id_str))
                        print(f"[DEBUG] メッセージ取得成功: {message.id} (author: {message.author}, content: {message.content[:50]}...)")
                        
                        # メッセージの送信者がボット自身であることを確認
                        if message.author.id != self.bot.user.id:
                            print("[DEBUG] エラー: ボットが送信したメッセージではありません")
                            return False, "ボットが送信したメッセージのみ削除できます。"
                            
                    except discord.NotFound:
                        print("[DEBUG] メッセージが見つかりませんでした")
                        # データベースからは削除を試みる
                        cursor.execute('DELETE FROM messages WHERE message_id = ?', (message_id_str,))
                        cursor.execute('DELETE FROM thoughts WHERE id = ?', (message_info['post_id'],))
                        db.commit()
                        return True, "メッセージは既に削除されています。"
                        
                    except Exception as e:
                        print(f"[DEBUG] メッセージ取得中にエラーが発生: {str(e)}")
                        return False, f"メッセージの取得中にエラーが発生しました: {str(e)}"
                    
                    # メッセージを削除
                    await message.delete()
                    print("[DEBUG] Discordメッセージを削除しました")
                    
                    # データベースからも削除
                    cursor.execute('DELETE FROM messages WHERE message_id = ?', (message_id_str,))
                    cursor.execute('DELETE FROM thoughts WHERE id = ?', (message_info['post_id'],))
                    db.commit()
                    print("[DEBUG] データベースから削除しました")
                    
                    return True, "メッセージを削除しました。"
                    
                except discord.NotFound:
                    print("[DEBUG] メッセージは既に削除されています")
                    # メッセージが既に削除されている場合でも、データベースからは削除する
                    cursor.execute('DELETE FROM messages WHERE message_id = ?', (message_id_str,))
                    cursor.execute('DELETE FROM thoughts WHERE id = ?', (message_info['post_id'],))
                    db.commit()
                    return True, "メッセージは既に削除されています。"
                    
                except discord.Forbidden:
                    print("[DEBUG] メッセージ削除の権限がありません")
                    return False, "メッセージを削除する権限がありません。"
                    
                except Exception as e:
                    print(f"[DEBUG] メッセージ削除中にエラーが発生: {e}")
                    return False, f"メッセージの削除中にエラーが発生しました: {str(e)}"
                    
            except Exception as e:
                db.rollback()
                error_msg = f"データベースの更新中にエラーが発生しました: {e}"
                print(f"[ERROR] {error_msg}")
                traceback.print_exc()
                return False, error_msg
            
        except Exception as e:
            error_msg = f"エラーが発生しました: {type(e).__name__}: {str(e)}"
            print(f"[ERROR] {error_msg}")
            traceback.print_exc()
            return False, error_msg
            
        finally:
            if db:
                db.close()

async def setup(bot):
    await bot.add_cog(DeleteDM(bot))
    print("DeleteDM cog が読み込まれました")
