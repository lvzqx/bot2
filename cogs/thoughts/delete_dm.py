import discord
from discord.ext import commands
import sqlite3
import re
from typing import Tuple, Optional

class DeleteDM(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        print("DeleteDM cog が読み込まれました")
    
    def get_db_connection(self):
        """データベース接続を取得する"""
        if not hasattr(self.bot, 'db'):
            self.bot.db = sqlite3.connect('thoughts.db')
            self.bot.db.row_factory = sqlite3.Row
        return self.bot.db

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        # サーバー内のメッセージは無視
        if not isinstance(message.channel, discord.DMChannel):
            return
            
        # ボットのメッセージは無視
        if message.author == self.bot.user:
            return
            
        # メッセージIDを抽出
        content = message.content.strip()
        
        # メッセージIDを数値に変換
        try:
            message_id = int(content)
        except ValueError:
            # 数値でない場合は無視
            return
        
        # 削除処理を実行
        success, result = await self.delete_message_by_id(message, message_id, message.author.id)
        
        # 削除結果を送信
        embed = discord.Embed(
            description=result,
            color=discord.Color.green() if success else discord.Color.red()
        )
        
        # 結果メッセージを送信（5秒後に削除）
        try:
            response = await message.channel.send(embed=embed, delete_after=5.0)
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
        if isinstance(interaction_or_message, discord.Interaction):
            channel = interaction_or_message.channel
        else:
            channel = interaction_or_message.channel
            
        try:
            # データベースからメッセージ情報を取得
            db = self.get_db_connection()
            cursor = db.cursor()
            
            # メッセージIDを文字列に変換
            message_id_str = str(int(message_id))
            print(f"[DEBUG] 検索対象のメッセージID: {message_id_str}")
            
            # 存在するテーブルを確認
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
            tables = cursor.fetchall()
            print(f"[DEBUG] 利用可能なテーブル: {tables}")
            
            # メッセージIDで検索
            cursor.execute('''
                SELECT channel_id, message_id, post_id 
                FROM messages 
                WHERE message_id = ?
            ''', (message_id_str,))
            
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
