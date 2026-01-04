import discord
from discord.ext import commands
import sqlite3
import traceback
from typing import Optional, Tuple, List, Dict, Any, Union

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

    async def delete_post(self, post_id: int, user_id: int, channel: discord.DMChannel) -> Tuple[bool, str]:
        """投稿を削除する"""
        db = self.get_db_connection()
        cursor = db.cursor()
        
        try:
            # トランザクション開始
            cursor.execute('BEGIN TRANSACTION')
            
            # 1. 投稿の存在確認
            cursor.execute('''
                SELECT id, is_private FROM thoughts 
                WHERE id = ? AND user_id = ?
            ''', (post_id, user_id))
            post = cursor.fetchone()
            
            if not post:
                return False, "投稿が見つからないか、削除する権限がありません"
            
            # 2. メッセージ参照を取得
            cursor.execute('''
                SELECT message_id, channel_id FROM message_references 
                WHERE post_id = ?
            ''', (post_id,))
            msg_ref = cursor.fetchone()
            
            # 3. 投稿を削除
            cursor.execute('''
                DELETE FROM thoughts 
                WHERE id = ? AND user_id = ?
            ''', (post_id, user_id))
            
            # 4. メッセージ参照を削除
            if msg_ref:
                cursor.execute('''
                    DELETE FROM message_references 
                    WHERE post_id = ?
                ''', (post_id,))
            
            # 変更をコミット
            db.commit()
            
            # 5. DM内の埋め込みメッセージを削除
            deleted = False
            async for msg in channel.history(limit=100):
                if msg.embeds and msg.embeds[0].footer and f"ID: {post_id}" in msg.embeds[0].footer.text:
                    await msg.delete()
                    deleted = True
                    break
            
            if deleted:
                return True, f"✅ 投稿 (ID: {post_id}) を削除しました"
            else:
                return True, f"⚠️ 投稿は削除されましたが、メッセージが見つかりませんでした (ID: {post_id})"
                
        except Exception as e:
            db.rollback()
            error_msg = f"エラーが発生しました: {type(e).__name__}: {str(e)}"
            print(f"[ERROR] {error_msg}")
            traceback.print_exc()
            return False, f"❌ {error_msg}"

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        # DM以外は無視
        if not isinstance(message.channel, discord.DMChannel):
            return
            
        # ボット自身のメッセージは無視
        if message.author == self.bot.user:
            return
                
        # メッセージを小文字に変換して処理
        content = message.content.strip().lower()
        
        # delete で始まるメッセージのみ処理
        if not content.startswith(('delete ', '/delete ')):
            return
            
        try:
            # コマンドを解析
            parts = content.split()
            
            # ヘルプ表示
            if len(parts) < 2 or not parts[-1].isdigit():
                help_msg = "```\n使い方:\n  delete [投稿ID]\n  \n例: delete 123\n```"
                await message.channel.send(help_msg, delete_after=15)
                return
                
            # 投稿IDを取得
            post_id = int(parts[-1])
            
            # 削除処理を実行
            success, result = await self.delete_post(
                post_id=post_id,
                user_id=message.author.id,
                channel=message.channel
            )
            
            # 結果を送信
            await message.channel.send(result, delete_after=15)
            
        except Exception as e:
            error_msg = f"❌ エラーが発生しました: {type(e).__name__}: {str(e)}"
            print(f"[ERROR] {error_msg}")
            traceback.print_exc()
            await message.channel.send(error_msg, delete_after=15)

async def setup(bot):
    await bot.add_cog(DeleteDM(bot))
