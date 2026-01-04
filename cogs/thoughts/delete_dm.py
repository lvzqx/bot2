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
            
        # メッセージリンクまたはメッセージIDを抽出
        content = message.content.strip()
        
        # メッセージリンクからメッセージIDを抽出
        if 'discord.com/channels/' in content:
            try:
                # メッセージIDを抽出
                message_id = int(content.split('/')[-1])
            except (ValueError, IndexError):
                await message.channel.send("❌ 無効なメッセージリンクです。削除したいメッセージのIDまたはリンクを送信してください。")
                return
        else:
            # メッセージIDとして処理
            try:
                message_id = int(content)
            except ValueError:
                # メッセージIDでもリンクでもない場合は無視
                return
        
        # 削除処理を実行
        success, result = await self.delete_message_by_id(message_id, message.author.id, message.channel)
        
        # 削除結果を送信
        embed = discord.Embed(
            description=result,
            color=discord.Color.blue() if success else discord.Color.red()
        )
        await message.channel.send(embed=embed)
        
        # 元のメッセージを削除
        try:
            await message.delete()
        except:
            pass  # メッセージ削除に失敗しても無視
    
    async def delete_message_by_id(self, message_id: int, user_id: int, channel: discord.DMChannel) -> Tuple[bool, str]:
        """メッセージIDで削除する"""
        try:
            # データベースからメッセージ情報を取得
            db = self.get_db_connection()
            cursor = db.cursor()
            
            cursor.execute('''
                SELECT channel_id, message_id, post_id 
                FROM message_references 
                WHERE message_id = ?
            ''', (str(message_id),))
            
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
                channel = self.bot.get_channel(int(channel_id))
                if channel:
                    msg = await channel.fetch_message(int(message_id))
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
            return False, f"❌ エラーが発生しました: {str(e)}"

async def setup(bot):
    await bot.add_cog(DeleteDM(bot))
