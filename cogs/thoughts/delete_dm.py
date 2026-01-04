import discord
from discord.ext import commands
from typing import Optional

class DeleteDM(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        print("DeleteDM cog が読み込まれました")

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        try:
            print(f"[DEBUG] メッセージ受信: {message.content}")
            
            # ボット自身のメッセージは無視
            if message.author == self.bot.user:
                return
                
            # DM以外は無視
            if not isinstance(message.channel, discord.DMChannel):
                return
                
            content = message.content.strip()
            print(f"[DEBUG] DMメッセージ: {content}")
            
            # delete で始まるメッセージのみ処理
            if not content.lower().startswith(('delete ', '/delete ')):
                return
                
            try:
                # コマンドを解析
                parts = content.split()
                print(f"[DEBUG] コマンド解析 - パーツ: {parts}")
                
                if len(parts) < 2 or not parts[-1].isdigit():
                    help_msg = "```\n使い方:\n  delete [投稿ID]\n  \n例: delete 123\n```"
                    await message.channel.send(help_msg, delete_after=15)
                    return
                    
                post_id = int(parts[-1])
                user_id = message.author.id
                
                print(f"[DEBUG] DM削除リクエスト - ユーザーID: {user_id}, 投稿ID: {post_id}")
                
                # データベーストランザクション開始
                with self.bot.db:
                    cursor = self.bot.db.cursor()
                    
                    # 1. 投稿の存在確認
                    cursor.execute('''
                        SELECT id, is_private FROM thoughts 
                        WHERE id = ? AND user_id = ?
                    ''', (post_id, user_id))
                    
                    post = cursor.fetchone()
                    print(f"[DEBUG] 投稿検索結果: {post}")
                    
                    if not post:
                        await message.channel.send("❌ 投稿が見つからないか、削除する権限がありません。", delete_after=10)
                        return
                    
                    # 2. メッセージ参照を取得
                    cursor.execute('''
                        SELECT message_id, channel_id FROM message_references 
                        WHERE post_id = ?
                    ''', (post_id,))
                    msg_ref = cursor.fetchone()
                    print(f"[DEBUG] メッセージ参照: {msg_ref}")
                    
                    # 3. 投稿を削除
                    cursor.execute('''
                        DELETE FROM thoughts 
                        WHERE id = ? AND user_id = ?
                    ''', (post_id, user_id))
                    
                    # メッセージ参照を削除
                    if msg_ref:
                        cursor.execute('''
                            DELETE FROM message_references 
                            WHERE post_id = ?
                        ''', (post_id,))
                    
                    # 4. DM内の埋め込みメッセージを削除
                    deleted = False
                    try:
                        async for msg in message.channel.history(limit=100):
                            if msg.embeds and msg.embeds[0].footer:
                                footer_text = str(msg.embeds[0].footer.text)
                                print(f"[DEBUG] フッターテキスト: {footer_text}")
                                if f"ID: {post_id}" in footer_text:
                                    print(f"[DEBUG] メッセージを削除: {msg.id}")
                                    await msg.delete()
                                    deleted = True
                                    break
                    except Exception as e:
                        print(f"[WARN] DMメッセージ削除中にエラー: {e}")
                    
                    # 5. 完了メッセージを送信
                    if deleted:
                        await message.channel.send(f"✅ 非公開投稿 (ID: {post_id}) を削除しました", delete_after=10)
                    else:
                        await message.channel.send(f"⚠️ 投稿は削除されましたが、メッセージが見つかりませんでした (ID: {post_id})", delete_after=10)
                        
            except Exception as e:
                error_msg = f"[ERROR] 削除処理中にエラー: {type(e).__name__}: {e}"
                print(error_msg)
                import traceback
                traceback.print_exc()
                await message.channel.send("❌ 処理中にエラーが発生しました。もう一度お試しください。", delete_after=10)
                
        except Exception as e:
            print(f"[CRITICAL] 予期せぬエラー: {e}")
            import traceback
            traceback.print_exc()
            
            try:
                await message.channel.send("❌ エラーが発生しました。もう一度お試しください。", delete_after=10)
            except Exception as e2:
                print(f"[ERROR] エラーメッセージ送信に失敗: {type(e2).__name__}: {e2}")

async def setup(bot):
    await bot.add_cog(DeleteDM(bot))
