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
            print(f"\n[DEBUG] メッセージ受信: {message.content}")
            print(f"[DEBUG] メッセージID: {message.id}")
            print(f"[DEBUG] 送信者: {message.author} (ID: {message.author.id})")
            print(f"[DEBUG] チャンネルタイプ: {type(message.channel).__name__}")
            
            # ボット自身のメッセージは無視
            if message.author == self.bot.user:
                print("[DEBUG] ボット自身のメッセージのため無視")
                return
                
            # DM以外は無視
            if not isinstance(message.channel, discord.DMChannel):
                print(f"[DEBUG] DM以外のチャンネル ({message.channel}) のため無視")
                return
                
            content = message.content.strip()
            print(f"[DEBUG] 処理開始 - メッセージ: {content}")
            
            # delete で始まるメッセージのみ処理
            if not content.lower().startswith(('delete ', '/delete ')):
                print("[DEBUG] 削除コマンドではないため無視")
                return
                
            try:
                # コマンドを解析
                parts = content.split()
                print(f"[DEBUG] コマンド解析 - パーツ: {parts}")
                print(f"[DEBUG] データベースパス: {self.bot.db}")
                print(f"[DEBUG] データベース接続状態: {'接続中' if self.bot.db else '未接続'}")
                
                if len(parts) < 2 or not parts[-1].isdigit():
                    help_msg = "```\n使い方:\n  delete [投稿ID]\n  \n例: delete 123\n```"
                    await message.channel.send(help_msg, delete_after=15)
                    return
                    
                post_id = int(parts[-1])
                user_id = message.author.id
                
                print(f"[DEBUG] DM削除リクエスト - ユーザーID: {user_id}, 投稿ID: {post_id}")
                
                # データベーストランザクション開始
                print("[DEBUG] データベーストランザクションを開始します")
                try:
                    # データベース接続を明示的に取得
                    db = self.bot.db
                    if not db:
                        print("[ERROR] データベース接続が確立されていません")
                        await message.channel.send("❌ データベースエラーが発生しました。", delete_after=10)
                        return
                        
                    cursor = db.cursor()
                    print("[DEBUG] データベース接続を取得しました")
                    
                    # 1. 投稿の存在確認
                    print(f"[DEBUG] 投稿を検索中: post_id={post_id}, user_id={user_id}")
                    try:
                        cursor.execute('''
                            SELECT id, is_private FROM thoughts 
                            WHERE id = ? AND user_id = ?
                        ''', (post_id, user_id))
                        post = cursor.fetchone()
                        print(f"[DEBUG] 投稿検索結果: {post}")
                        
                        if not post:
                            print("[DEBUG] 投稿が見つからないか、権限がありません")
                            await message.channel.send("❌ 投稿が見つからないか、削除する権限がありません。", delete_after=10)
                            return
                            
                        # 2. メッセージ参照を取得
                        print(f"[DEBUG] メッセージ参照を検索中: post_id={post_id}")
                        cursor.execute('''
                            SELECT message_id, channel_id FROM message_references 
                            WHERE post_id = ?
                        ''', (post_id,))
                        msg_ref = cursor.fetchone()
                        print(f"[DEBUG] メッセージ参照: {msg_ref}")
                        
                        # 3. 投稿を削除
                        print(f"[DEBUG] 投稿を削除中: post_id={post_id}")
                        cursor.execute('''
                            DELETE FROM thoughts 
                            WHERE id = ? AND user_id = ?
                        ''', (post_id, user_id))
                        
                        # メッセージ参照を削除
                        if msg_ref:
                            print(f"[DEBUG] メッセージ参照を削除中: post_id={post_id}")
                            cursor.execute('''
                                DELETE FROM message_references 
                                WHERE post_id = ?
                            ''', (post_id,))
                        
                        # 変更をコミット
                        db.commit()
                        print("[DEBUG] データベーストランザクションをコミットしました")
                        
                    except Exception as db_error:
                        db.rollback()
                        print(f"[ERROR] データベース操作中にエラーが発生: {db_error}")
                        raise
                        
                except Exception as e:
                    print(f"[ERROR] データベーストランザクション中にエラーが発生: {e}")
                    raise
                
                # 4. DM内の埋め込みメッセージを削除
                deleted = False
                try:
                    print("[DEBUG] 埋め込みメッセージの削除を開始します")
                    async for msg in message.channel.history(limit=100):
                        if msg.embeds and len(msg.embeds) > 0 and msg.embeds[0].footer:
                            footer_text = str(msg.embeds[0].footer.text)
                            print(f"[DEBUG] フッターテキスト: {footer_text}")
                            if f"ID: {post_id}" in footer_text:
                                print(f"[DEBUG] メッセージを削除: {msg.id}")
                                try:
                                    await msg.delete()
                                    deleted = True
                                    print("[DEBUG] メッセージを削除しました")
                                    break
                                except Exception as delete_error:
                                    print(f"[ERROR] メッセージ削除中にエラー: {delete_error}")
                                    raise
                    
                    # 5. 完了メッセージを送信
                    if deleted:
                        await message.channel.send(f"✅ 非公開投稿 (ID: {post_id}) を削除しました", delete_after=10)
                    else:
                        print("[WARN] 削除対象のメッセージが見つかりませんでした")
                        await message.channel.send(f"⚠️ 投稿は削除されましたが、メッセージが見つかりませんでした (ID: {post_id})", delete_after=10)
                        
                except Exception as e:
                    print(f"[ERROR] メッセージ削除処理中にエラーが発生: {e}")
                    await message.channel.send("❌ メッセージの削除中にエラーが発生しました。", delete_after=10)
                        
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
