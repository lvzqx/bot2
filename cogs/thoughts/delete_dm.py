import asyncio
import discord
import os
from discord.ext import commands
import sqlite3
import re
import traceback
from typing import Tuple, Optional

class DeleteDM(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        print("DeleteDM cog が読み込まれました")
    
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

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        try:
            print(f"[DEBUG] 受信メッセージ: {message.content}")
            
            # サーバー内のメッセージは無視
            if not isinstance(message.channel, discord.DMChannel):
                print("[DEBUG] DMチャンネルではないためスキップ")
                return
                
            # ボットのメッセージは無視
            if message.author == self.bot.user:
                print("[DEBUG] ボットのメッセージのためスキップ")
                return
                
            # メッセージIDを抽出
            content = message.content.strip()
            print(f"[DEBUG] 処理対象のコンテンツ: {content}")
            
            # メッセージIDを数値に変換
            try:
                message_id = int(content)
                print(f"[DEBUG] 抽出したメッセージID: {message_id}")
            except ValueError:
                # 数値でない場合は無視
                print("[DEBUG] 数値に変換できないためスキップ")
                return
            
            # 削除処理を実行
            print("[DEBUG] delete_message_by_idを呼び出し")
            success, result = await self.delete_message_by_id(message, message_id, message.author.id)
            print(f"[DEBUG] 削除結果 - 成功: {success}, 結果: {result}")
            
            # 削除結果を送信
            embed = discord.Embed(
                description=result,
                color=discord.Color.green() if success else discord.Color.red()
            )
            
            # 結果メッセージを送信（5秒後に削除）
            print("[DEBUG] 結果メッセージを送信")
            response = await message.channel.send(embed=embed, delete_after=5.0)
            print("[DEBUG] 結果メッセージを送信完了")
            # 元のメッセージを削除
            try:
                await message.delete()
            except:
                pass
            
            # 成功した場合は5秒後に結果メッセージも削除
            if success:
                await asyncio.sleep(5)
                try:
                    await response.delete()
                except:
                    pass
                    
        except Exception as e:
            print(f"[ERROR] メッセージ送信中にエラー: {e}")
    
    async def delete_message_by_id(self, interaction_or_message, message_id: int, user_id: int) -> Tuple[bool, str]:
        """DMでメッセージIDを指定して削除する
        
        Args:
            interaction_or_message: discord.Interaction または discord.Message オブジェクト
            message_id: 削除するメッセージID
            user_id: 削除を試みるユーザーID
        """
        print(f"[DEBUG] delete_message_by_id 開始: message_id={message_id}, user_id={user_id}")
        
        try:
            # チャンネルを取得
            if isinstance(interaction_or_message, discord.Interaction):
                channel = interaction_or_message.channel
                print(f"[DEBUG] Interactionからチャンネルを取得: {channel}")
            else:
                channel = interaction_or_message.channel
                print(f"[DEBUG] Messageからチャンネルを取得: {channel}")
            
            # メッセージIDを文字列に変換
            message_id_str = str(int(message_id))
            print(f"[DEBUG] 検索対象のメッセージID: {message_id_str}")
            
            # データベース接続を取得
            db = self.get_db_connection()
            cursor = db.cursor()
            
            # 存在するテーブルを確認
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
            tables = [row[0] for row in cursor.fetchall()]
            print(f"[DEBUG] 利用可能なテーブル: {tables}")
            
            # メッセージIDで検索
            try:
                print("[DEBUG] データベース接続情報:")
                print(f"[DEBUG] - データベースファイル: {os.path.abspath('thoughts.db')}")
                print(f"[DEBUG] - メッセージID: {message_id_str}")
                print(f"[DEBUG] - ユーザーID: {user_id}")
                
                # メッセージと投稿情報を結合して検索
                print("[DEBUG] メッセージを検索中...")
                
                # まずはmessagesテーブルの内容を全て表示
                cursor.execute("SELECT * FROM messages")
                all_messages = cursor.fetchall()
                print(f"[DEBUG] messagesテーブルの全レコード: {all_messages}")
                
                # thoughtsテーブルの内容も確認
                cursor.execute("SELECT id, user_id FROM thoughts")
                all_thoughts = cursor.fetchall()
                print(f"[DEBUG] thoughtsテーブルの全レコード: {all_thoughts}")
                
                # メッセージを検索
                cursor.execute('''
                    SELECT m.channel_id, m.message_id, m.post_id, t.user_id
                    FROM messages m
                    JOIN thoughts t ON m.post_id = t.id
                    WHERE m.message_id = ?
                ''', (message_id_str,))
                
                message_data = cursor.fetchone()
                print(f"[DEBUG] 検索結果: {message_data}")
                
                # 見つからない場合は、message_idを数値としても検索してみる
                if not message_data and message_id_str.isdigit():
                    print("[DEBUG] 文字列IDで見つからなかったため、数値IDで再検索します")
                    cursor.execute('''
                        SELECT m.channel_id, m.message_id, m.post_id, t.user_id
                        FROM messages m
                        JOIN thoughts t ON m.post_id = t.id
                        WHERE CAST(m.message_id AS INTEGER) = ?
                    ''', (int(message_id_str),))
                    message_data = cursor.fetchone()
                    print(f"[DEBUG] 数値IDでの検索結果: {message_data}")
                
                if not message_data:
                    return False, "メッセージが見つかりませんでした。メッセージIDまたはリンクが正しいか確認してください。"
                
                # 投稿者を確認
                if message_data['user_id'] != user_id:
                    return False, "このメッセージを削除する権限がありません。"
                
                # メッセージを削除
                try:
                    # データベースからメッセージ情報を取得
                    cursor.execute('''
                        SELECT m.channel_id, m.message_id, m.post_id, t.content, t.is_private
                        FROM messages m
                        JOIN thoughts t ON m.post_id = t.id
                        WHERE m.message_id = ? AND t.user_id = ?
                    ''', (message_id_str, user_id))
                    
                    message_info = cursor.fetchone()
                    if not message_info:
                        return False, "メッセージが見つからないか、削除する権限がありません。"
                    
                    # データベースから削除
                    cursor.execute('DELETE FROM messages WHERE message_id = ?', (message_id_str,))
                    cursor.execute('DELETE FROM thoughts WHERE id = ?', (message_info['post_id'],))
                    db.commit()
                    
                    # 実際のメッセージを削除（可能な場合）
                    try:
                        if message_info['is_private']:
                            # DMのメッセージを削除
                            user = await self.bot.fetch_user(user_id)
                            if user:
                                channel = user.dm_channel or await user.create_dm()
                                try:
                                    msg = await channel.fetch_message(int(message_id_str))
                                    if msg:
                                        await msg.delete()
                                except (discord.NotFound, discord.Forbidden):
                                    # メッセージが既に削除されているか、削除権限がない場合は無視
                                    pass
                        else:
                            # パブリックチャンネルのメッセージを削除
                            channel = self.bot.get_channel(int(message_info['channel_id']))
                            if channel:
                                try:
                                    msg = await channel.fetch_message(int(message_id_str))
                                    if msg:
                                        await msg.delete()
                                except (discord.NotFound, discord.Forbidden):
                                    # メッセージが既に削除されているか、削除権限がない場合は無視
                                    pass
                    except Exception as e:
                        print(f"[WARNING] メッセージ削除に失敗しましたが、データベースからは削除しました: {e}")
                    
                    return True, "メッセージを削除しました。"
                    
                except sqlite3.Error as e:
                    db.rollback()
                    print(f"[ERROR] データベースエラー: {e}")
                    return False, "データベースエラーが発生しました。しばらくしてから再度お試しください。"
                    
                except Exception as e:
                    print(f"[ERROR] メッセージ削除エラー: {e}")
                    return False, f"メッセージの削除中にエラーが発生しました: {str(e)}"
                
            except sqlite3.OperationalError as e:
                error_msg = f"[ERROR] データベース操作エラー: {e}"
                print(error_msg)
                print("[DEBUG] データベースファイルの存在確認:")
                print(f"[DEBUG] - 存在するか: {os.path.exists('thoughts.db')}")
                traceback.print_exc()
                return False, "❌ データベースに接続できませんでした。管理者に連絡してください。"
            except Exception as e:
                error_msg = f"[ERROR] 予期せぬエラー: {e}"
                print(error_msg)
                traceback.print_exc()
                return False, "❌ 予期せぬエラーが発生しました。しばらくしてからもう一度お試しください。"
            
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

async def setup(bot):
    await bot.add_cog(DeleteDM(bot))
