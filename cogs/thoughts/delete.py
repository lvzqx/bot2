import discord
from discord.ext import commands
import asyncio

class Delete(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.db = bot.db

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        # ボット自身のメッセージまたはDM以外は無視
        if message.author == self.bot.user or not isinstance(message.channel, discord.DMChannel):
            return
            
        content = message.content.strip()
        
        # メッセージ削除コマンド
        if content.lower() in ['削除', 'delete', 'さくじょ']:
            await self.delete_bot_messages(message)
        # 投稿IDを指定した削除コマンド（例: delete 123）
        elif content.lower().startswith(('delete ')):
            await self.delete_private_post(message)
        # ヘルプ表示
        elif content.lower() in ['help', 'ヘルプ']:
            await self.show_help(message.channel)
    
    async def show_help(self, channel):
        """ヘルプメッセージを表示"""
        help_embed = discord.Embed(
            title="📚 ヘルプ - 削除コマンド",
            description="DMで使用できるコマンド一覧です。",
            color=discord.Color.blue()
        )
        
        help_embed.add_field(
            name="📝 投稿を削除",
            value="`delete [投稿ID]`\n指定したIDの非公開投稿を削除します。",
            inline=False
        )
        
        help_embed.add_field(
            name="🗑️ メッセージを削除",
            value="`削除` または `delete` または `さくじょ`\nボットが送信したメッセージを削除します。",
            inline=False
        )
        
        help_embed.add_field(
            name="ℹ️ ヘルプ表示",
            value="`help` または `ヘルプ`\nこのヘルプを表示します。",
            inline=False
        )
        
        help_embed.set_footer(text="※ カギカッコ[]は実際に入力する際は不要です")
        
        try:
            await channel.send(embed=help_embed)
        except Exception as e:
            print(f"[ERROR] ヘルプメッセージ送信エラー: {e}")
            await channel.send("ヘルプメッセージの表示中にエラーが発生しました。")
    
    async def delete_bot_messages(self, message: discord.Message):
        """DM内のボットメッセージを削除"""
        try:
            # このスレッドのボットのメッセージを削除
            async for msg in message.channel.history(limit=100):
                if msg.author == self.bot.user:
                    try:
                        await msg.delete()
                        await asyncio.sleep(0.5)  # レート制限回避
                    except:
                        continue
            
            # 確認メッセージを送信（すぐに削除）
            confirm = await message.channel.send("✅ メッセージを削除しました")
            await asyncio.sleep(3)
            await confirm.delete()
            
        except Exception as e:
            print(f"DMメッセージ削除エラー: {e}")
            try:
                await message.channel.send("❌ メッセージの削除中にエラーが発生しました", delete_after=5)
            except:
                pass
    
    async def delete_private_post(self, message: discord.Message):
        """DMから非公開投稿を削除（埋め込みメッセージも削除）"""
        try:
            # 投稿IDを取得
            parts = message.content.split()
            if len(parts) != 2 or not parts[1].isdigit():
                await message.channel.send("❌ 正しい形式で入力してください。例: `delete 123`", delete_after=10)
                return
            
            post_id = int(parts[1])
            user_id = message.author.id
            
            # データベースから投稿を取得
            cursor = self.db.cursor()
            cursor.execute('''
                SELECT id, user_id FROM thoughts 
                WHERE id = ? AND is_private = 1
            ''', (post_id,))
            
            post = cursor.fetchone()
            
            if not post:
                await message.channel.send("❌ 削除できる非公開投稿が見つかりませんでした。", delete_after=10)
                return
                
            # 投稿者チェック
            if post[1] != user_id:
                await message.channel.send("❌ この投稿を削除する権限がありません。", delete_after=10)
                return
            
            # メッセージ参照を取得
            cursor.execute('''
                SELECT message_id, channel_id FROM message_references 
                WHERE post_id = ?
            ''', (post_id,))
            
            msg_ref = cursor.fetchone()
            
            # 投稿を削除
            cursor.execute('DELETE FROM thoughts WHERE id = ?', (post_id,))
            
            # メッセージ参照を削除
            if msg_ref:
                cursor.execute('DELETE FROM message_references WHERE post_id = ?', (post_id,))
                
                # メッセージを削除（DMのみ）
                message_id, channel_id = msg_ref
                try:
                    channel = self.bot.get_channel(int(channel_id))
                    if channel and isinstance(channel, discord.DMChannel):
                        message = await channel.fetch_message(int(message_id))
                        await message.delete()
                except:
                    pass  # メッセージが既に削除されている場合は無視
            
            self.db.commit()
            
            # 削除完了メッセージを送信
            await message.channel.send(f"✅ 投稿 (ID: {post_id}) を削除しました。")
            
        except Exception as e:
            print(f"[ERROR] 投稿削除エラー: {e}")
            await message.channel.send("❌ 投稿の削除中にエラーが発生しました。もう一度お試しください。")
    

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        # ボット自身のメッセージまたはDM以外は無視
        if message.author == self.bot.user or not isinstance(message.channel, discord.DMChannel):
            return
            
        content = message.content.strip()
        
        # メッセージ削除コマンド
        if content.lower() in ['削除', 'delete', 'さくじょ']:
            await self.delete_bot_messages(message)
        # 投稿IDを指定した削除コマンド（例: delete 123）
        elif content.lower().startswith(('delete ')):
            await self.delete_private_post(message)
        # ヘルプ表示
        elif content.lower() in ['help', 'ヘルプ']:
            await self.show_help(message.channel)
    
    async def show_help(self, channel):
        """ヘルプメッセージを表示"""
        help_embed = discord.Embed(
            title="📚 ヘルプ - 削除コマンド",
            description="DMで使用できるコマンド一覧です。",
            color=discord.Color.blue()
        )
        
        help_embed.add_field(
            name="📝 投稿を削除",
            value="`/delete [投稿ID]` または `delete [投稿ID]`\n指定したIDの非公開投稿を削除します。",
            inline=False
        )
        
        help_embed.add_field(
            name="🗑️ メッセージを削除",
            value="`削除` または `delete` または `さくじょ`\nボットが送信したメッセージを削除します。",
            inline=False
        )
        
        help_embed.add_field(
            name="ℹ️ ヘルプ表示",
            value="`/help` または `help` または `ヘルプ`\nこのヘルプを表示します。",
            inline=False
        )
        
        help_embed.set_footer(text="※ カギカッコ[]は実際に入力する際は不要です")
        
        try:
            await channel.send(embed=help_embed)
        except Exception as e:
            print(f"[ERROR] ヘルプメッセージ送信エラー: {e}")
            await channel.send("ヘルプメッセージの表示中にエラーが発生しました。")
    
    
    async def delete_bot_messages(self, message: discord.Message):
        """DM内のボットメッセージを削除"""
        try:
            # このスレッドのボットのメッセージを削除
            async for msg in message.channel.history(limit=100):
                if msg.author == self.bot.user:
                    try:
                        await msg.delete()
                    except:
                        continue
            
            # 確認メッセージを送信（すぐに削除）
            confirm = await message.channel.send("✅ メッセージを削除しました")
            await asyncio.sleep(3)
            await confirm.delete()
            
        except Exception as e:
            print(f"DMメッセージ削除エラー: {e}")
            try:
                await message.channel.send("❌ メッセージの削除中にエラーが発生しました", delete_after=5)
            except:
                pass
    
    async def delete_private_post(self, message: discord.Message):
        """DMから非公開投稿を削除（埋め込みメッセージも削除）"""
        try:
            print(f"[DEBUG] 削除コマンド受信: {message.content}")
            
            # 投稿IDを取得（コマンド形式: /delete 123 または delete 123）
            content = message.content.strip()
            parts = content.split()
            
            # コマンド形式をチェック
            if len(parts) != 2 or not parts[1].isdigit():
                print(f"[ERROR] 無効なコマンド形式: {content}")
                help_msg = "```\n使い方:\n  /delete [投稿ID]\n  \n例: /delete 123\n```"
                await message.channel.send(help_msg, delete_after=15)
                return
                
            post_id = int(parts[1])
            print(f"[DEBUG] 抽出した投稿ID: {post_id}")
            
            if not post_id.isdigit():
                print("[ERROR] 無効な投稿IDです")
                await message.channel.send("❌ 正しい投稿IDを指定してください。例: `/delete 123`", delete_after=10)
                return
                
            post_id = int(post_id)
            user_id = message.author.id
            print(f"[DEBUG] ユーザーID: {user_id}, 投稿ID: {post_id}")
            
            try:
                # メッセージ参照を取得
                cursor = self.bot.db.cursor()
                cursor.execute('''
                    SELECT message_id, channel_id FROM message_references 
                    WHERE post_id = ?
                ''', (post_id,))
                
                msg_ref = cursor.fetchone()
                print(f"[DEBUG] メッセージ参照: {msg_ref}")
                
                # 投稿の存在確認と削除
                cursor.execute('''
                    DELETE FROM thoughts 
                    WHERE id = ? AND user_id = ? AND is_private = 1
                    RETURNING id
                ''', (post_id, user_id))
                
                deleted = cursor.fetchone()
                print(f"[DEBUG] 削除されたレコード: {deleted}")
                
                if deleted:
                    # メッセージ参照を削除
                    cursor.execute('DELETE FROM message_references WHERE post_id = ?', (post_id,))
                    self.bot.db.commit()
                    print("[DEBUG] データベースから削除完了")
                    
                    # 埋め込みメッセージを削除
                    if msg_ref:
                        try:
                            message_id, channel_id = msg_ref
                            print(f"[DEBUG] メッセージ削除を試みます: message_id={message_id}, channel_id={channel_id}")
                            
                            channel = self.bot.get_channel(int(channel_id))
                            if channel:
                                print(f"[DEBUG] チャンネルを取得: {channel}")
                                msg = await channel.fetch_message(int(message_id))
                                if msg:
                                    print("[DEBUG] メッセージを削除します")
                                    await msg.delete()
                                    print("[DEBUG] メッセージ削除完了")
                        except discord.NotFound:
                            print("[DEBUG] メッセージは既に削除されています")
                        except Exception as e:
                            print(f"[ERROR] メッセージ削除エラー: {type(e).__name__}: {e}")
                    
                    print("[DEBUG] 完了メッセージを送信")
                    await message.channel.send(f"✅ 非公開投稿 (ID: {post_id}) を削除しました")
                else:
                    print("[DEBUG] 削除対象の投稿が見つかりませんでした")
                    await message.channel.send("❌ 削除できる非公開投稿が見つかりませんでした", delete_after=10)
                    
            except Exception as db_error:
                print(f"[ERROR] データベースエラー: {type(db_error).__name__}: {db_error}")
                self.bot.db.rollback()
                raise
                
        except Exception as e:
            error_msg = f"[ERROR] 予期せぬエラー: {type(e).__name__}: {e}"
            print(error_msg)
            import traceback
            traceback.print_exc()
            
            try:
                await message.channel.send("❌ エラーが発生しました。もう一度お試しください。", delete_after=10)
            except:
                print("[CRITICAL] エラーメッセージの送信に失敗しました")



async def setup(bot):
    await bot.add_cog(Delete(bot))
