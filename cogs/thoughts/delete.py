import asyncio
import discord
from discord import app_commands
from discord.ext import commands

class Delete(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.db = bot.db
        self.bot.tree.on_error = self.on_app_command_error
    
    async def on_app_command_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        """スラッシュコマンドのエラーハンドリング"""
        if isinstance(error, app_commands.CommandOnCooldown):
            await interaction.response.send_message(
                f"このコマンドは{error.retry_after:.1f}秒後に再度お試しください。",
                ephemeral=True
            )
        else:
            error_msg = f"コマンド実行中にエラーが発生しました: {str(error)}"
            print(f"[ERROR] {error_msg}")
            if not interaction.response.is_done():
                await interaction.response.send_message("❌ エラーが発生しました。もう一度お試しください。", ephemeral=True)
            else:
                await interaction.followup.send("❌ エラーが発生しました。もう一度お試しください。", ephemeral=True)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        # ボット自身のメッセージは無視
        if message.author == self.bot.user:
            return
            
        # DMの場合の処理
        if not isinstance(message.channel, discord.DMChannel):
            return
            
        content = message.content.strip()
        
        # 削除コマンドのみを処理
        if not content.lower().startswith(('delete ', '/delete ')):
            return
            
        try:
            # コマンドを解析
            parts = content.split()
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
                
                if not post:
                    await message.channel.send("❌ 投稿が見つからないか、削除する権限がありません。", delete_after=10)
                    return
                    
                if not post[1]:  # is_privateが0（公開投稿）の場合
                    await message.channel.send(
                        "❌ この投稿は公開されています。サーバーで `/delete" + 
                        f" {post_id}` を使用してください。", 
                        delete_after=15
                    )
                    return
                
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
                
                # メッセージ参照があれば削除
                if msg_ref:
                    cursor.execute('''
                        DELETE FROM message_references 
                        WHERE post_id = ?
                    ''', (post_id,))
                
                # 4. DM内のメッセージを削除
                async for msg in message.channel.history(limit=100):
                    if msg.embeds and msg.embeds[0].footer and f"ID: {post_id}" in str(msg.embeds[0].footer.text):
                        await msg.delete()
                        break
                
                # 5. 完了メッセージを送信
                await message.channel.send(f"✅ 非公開投稿 (ID: {post_id}) を削除しました", delete_after=10)
                
        except Exception as e:
            error_msg = f"[ERROR] DM削除処理中にエラー: {type(e).__name__}: {e}"
            print(error_msg)
            import traceback
            traceback.print_exc()
            
            try:
                await message.channel.send("❌ エラーが発生しました。もう一度お試しください。", delete_after=10)
            except Exception as e2:
                print(f"[ERROR] エラーメッセージ送信に失敗: {type(e2).__name__}: {e2}")

    @app_commands.command(name="delete", description="投稿を削除します")
    @app_commands.describe(post_id="削除する投稿のID")
    async def delete_post(self, interaction: discord.Interaction, post_id: int):
        """指定されたIDの投稿を削除します"""
        await interaction.response.defer(ephemeral=True)
        
        try:
            print(f"[DEBUG] 削除リクエスト受信 - ユーザーID: {interaction.user.id}, 投稿ID: {post_id}")
            
            # データベーストランザクション開始
            with self.bot.db:
                cursor = self.bot.db.cursor()
                
                # 1. 投稿の存在確認と情報取得
                cursor.execute('''
                    SELECT user_id, is_private, is_anonymous, content, category
                    FROM thoughts 
                    WHERE id = ?
                ''', (post_id,))
                
                post = cursor.fetchone()
                
                if not post:
                    print(f"[DEBUG] 投稿が見つかりません - 投稿ID: {post_id}")
                    await interaction.followup.send("❌ 指定された投稿が見つかりません。", ephemeral=True)
                    return
                
                post_user_id, is_private, is_anonymous, content, category = post
                
                # 2. 権限チェック（投稿者本人または管理者のみ削除可能）
                is_owner = post_user_id == interaction.user.id
                is_admin = interaction.user.guild_permissions.administrator if interaction.guild else False
                
                if not (is_owner or is_admin):
                    print(f"[DEBUG] 権限がありません - ユーザーID: {interaction.user.id}, 投稿者ID: {post_user_id}")
                    await interaction.followup.send("❌ この投稿を削除する権限がありません。", ephemeral=True)
                    return
                
                # 3. メッセージ参照を取得
                cursor.execute('''
                    SELECT message_id, channel_id 
                    FROM message_references 
                    WHERE post_id = ?
                ''', (post_id,))
                msg_refs = cursor.fetchall()
                print(f"[DEBUG] メッセージ参照を取得しました - 参照数: {len(msg_refs)}")
                
                # メッセージ参照が空の場合は、thoughtsテーブルから直接チャンネルIDを取得
                if not msg_refs:
                    print(f"[WARNING] メッセージ参照が存在しません - 投稿ID: {post_id}")
                    
                    # thoughtsテーブルからチャンネルIDを取得
                    cursor.execute('''
                        SELECT channel_id, is_private 
                        FROM thoughts 
                        WHERE id = ?
                    ''', (post_id,))
                    thought_data = cursor.fetchone()
                    
                    if thought_data:
                        channel_id, is_private_thought = thought_data
                        if not is_private_thought and channel_id:  # 公開投稿の場合
                            print(f"[DEBUG] thoughtsテーブルからチャンネルIDを取得しました: {channel_id}")
                            # メッセージIDが不明な場合は、チャンネルの履歴を検索
                            msg_refs = [(0, channel_id)]
                
                # デバッグ用に参照情報を表示
                for ref in msg_refs:
                    print(f"[DEBUG] メッセージ参照 - メッセージID: {ref[0]}, チャンネルID: {ref[1]}")
                
                # 4. メッセージを削除
                deleted_messages = 0
                max_retries = 3
                
                async def try_delete_message(channel, message_id, is_dm=False):
                    print(f"[DEBUG] メッセージ削除を試行します - チャンネルID: {channel.id}, メッセージID: {message_id}")
                    
                    for attempt in range(max_retries):
                        try:
                            print(f"[DEBUG] 試行 {attempt + 1}/{max_retries} - メッセージID: {message_id}")
                            
                            # メッセージを直接取得
                            try:
                                print(f"[DEBUG] メッセージを直接取得します - メッセージID: {message_id}")
                                message = await channel.fetch_message(message_id)
                                if message:
                                    print(f"[DEBUG] メッセージを削除します - メッセージID: {message_id}, コンテンツ: {message.content[:100]}...")
                                    await message.delete()
                                    print(f"[DEBUG] メッセージを削除しました (直接取得) - メッセージID: {message_id}")
                                    return True
                            except discord.NotFound:
                                print(f"[DEBUG] メッセージは既に削除されています - メッセージID: {message_id}")
                                return False
                            except discord.Forbidden as e:
                                print(f"[ERROR] メッセージ削除の権限がありません - メッセージID: {message_id}: {e}")
                                return False
                            except Exception as e:
                                print(f"[WARNING] メッセージの直接取得に失敗しました - メッセージID: {message_id}: {type(e).__name__}: {e}")
                            
                            # メッセージが削除されていないが、取得できない場合は履歴を検索
                            print(f"[DEBUG] チャンネルの履歴を検索します - チャンネルID: {channel.id}, メッセージID: {message_id}")
                            try:
                                async for msg in channel.history(limit=200):
                                    if msg.id == message_id:
                                        print(f"[DEBUG] 履歴からメッセージを削除します - メッセージID: {message_id}")
                                        await msg.delete()
                                        print(f"[DEBUG] 履歴からメッセージを削除しました - メッセージID: {message_id}")
                                        return True
                                
                                print(f"[WARNING] メッセージが見つかりませんでした - メッセージID: {message_id}")
                                return False
                                
                            except Exception as e:
                                print(f"[ERROR] 履歴検索中にエラーが発生しました - メッセージID: {message_id}: {type(e).__name__}: {e}")
                                if attempt < max_retries - 1:
                                    await asyncio.sleep(1)  # 1秒待機して再試行
                                continue
                            
                        except discord.Forbidden as e:
                            print(f"[ERROR] メッセージ削除の権限がありません - メッセージID: {message_id}: {e}")
                            return False
                        except Exception as e:
                            error_msg = f"[ERROR] メッセージ削除エラー (試行 {attempt + 1}/{max_retries}, メッセージID: {message_id}): {type(e).__name__}: {e}"
                            print(error_msg)
                            import traceback
                            traceback.print_exc()
                            
                            if attempt < max_retries - 1:
                                print(f"[DEBUG] 1秒待機して再試行します... (残り試行回数: {max_retries - attempt - 1})")
                                await asyncio.sleep(1)  # 1秒待機して再試行
                    
                    print(f"[ERROR] メッセージの削除に失敗しました - 最大試行回数に達しました: メッセージID: {message_id}")
                    return False
                
                # 非公開投稿の場合はDMからも削除
                if is_private:
                    print(f"[DEBUG] 非公開投稿の削除を開始します - 投稿ID: {post_id}, ユーザーID: {post_user_id}")
                    try:
                        # 投稿者を取得
                        user = self.bot.get_user(post_user_id)
                        if not user:
                            print(f"[ERROR] ユーザーが見つかりません - ユーザーID: {post_user_id}")
                        else:
                            print(f"[DEBUG] ユーザーを取得しました - ユーザーID: {user.id}, 名前: {user.name}")
                            try:
                                # DMチャンネルを取得または作成
                                try:
                                    dm_channel = user.dm_channel
                                    if not dm_channel:
                                        print("[DEBUG] DMチャンネルが存在しないため、作成します")
                                        dm_channel = await user.create_dm()
                                    
                                    print(f"[DEBUG] DMチャンネルを取得/作成しました - チャンネルID: {dm_channel.id}")
                                    
                                    # DM内のメッセージを検索して削除（より広範に検索）
                                    found = False
                                    print(f"[DEBUG] DMチャンネルの履歴を検索します - チャンネルID: {dm_channel.id}")
                                    
                                    try:
                                        async for dm_message in dm_channel.history(limit=200):
                                            try:
                                                # メッセージIDが一致するか、埋め込みメッセージのフッターに投稿IDが含まれているか確認
                                                message_matches = (
                                                    dm_message.id in [ref[0] for ref in msg_refs] or 
                                                    (dm_message.embeds and 
                                                     len(dm_message.embeds) > 0 and 
                                                     dm_message.embeds[0].footer and 
                                                     f"ID: {post_id}" in str(dm_message.embeds[0].footer.text))
                                                )
                                                
                                                if message_matches:
                                                    print(f"[DEBUG] 削除対象のDMメッセージを検出 - メッセージID: {dm_message.id}")
                                                    if await try_delete_message(dm_channel, dm_message.id, is_dm=True):
                                                        deleted_messages += 1
                                                        found = True
                                                        break
                                            except Exception as e:
                                                print(f"[ERROR] DMメッセージ処理中にエラー: {type(e).__name__}: {e}")
                                                continue
                                        
                                        if not found:
                                            print(f"[WARNING] DM内で削除対象のメッセージが見つかりませんでした - 投稿ID: {post_id}")
                                            
                                            # メッセージが見つからない場合、メッセージIDを直接指定して削除を試みる
                                            for msg_id, _ in msg_refs:
                                                if msg_id > 0:  # 有効なメッセージIDの場合
                                                    print(f"[DEBUG] メッセージIDを直接指定して削除を試みます - メッセージID: {msg_id}")
                                                    if await try_delete_message(dm_channel, msg_id, is_dm=True):
                                                        deleted_messages += 1
                                                        found = True
                                                        break
                                                                                    
                                    except Exception as e:
                                        print(f"[ERROR] DM履歴の取得中にエラーが発生しました: {type(e).__name__}: {e}")
                                        
                                except Exception as e:
                                    print(f"[ERROR] DMチャンネルの作成中にエラーが発生しました: {type(e).__name__}: {e}")
                                    
                            except Exception as e:
                                print(f"[ERROR] DMチャンネル処理中にエラーが発生しました: {type(e).__name__}: {e}")
                                import traceback
                                traceback.print_exc()
                    except Exception as e:
                        print(f"[ERROR] ユーザー取得中にエラーが発生しました: {type(e).__name__}: {e}")
                        import traceback
                        traceback.print_exc()
                
                # 公開投稿の場合はチャンネルから削除
                for message_id, channel_id in msg_refs:
                    try:
                        if channel_id == 0:  # チャンネルIDが無効な場合はスキップ
                            continue
                            
                        channel = self.bot.get_channel(channel_id)
                        if not channel:
                            print(f"[WARNING] チャンネルが見つかりません - チャンネルID: {channel_id}")
                            continue
                            
                        print(f"[DEBUG] チャンネルからメッセージを削除します - チャンネルID: {channel_id}, メッセージID: {message_id}")
                        
                        # メッセージIDが有効な場合
                        if message_id > 0:
                            if await try_delete_message(channel, message_id):
                                deleted_messages += 1
                                continue
                            else:
                                print(f"[WARNING] メッセージの削除に失敗しました - チャンネルID: {channel_id}, メッセージID: {message_id}")
                        
                        # メッセージIDが無効な場合や削除に失敗した場合は、チャンネルの履歴を検索
                        try:
                            print(f"[DEBUG] チャンネルの履歴を検索します - チャンネルID: {channel_id}")
                            found = False
                            async for message in channel.history(limit=200):
                                try:
                                    # メッセージIDが一致するか、埋め込みメッセージのフッターに投稿IDが含まれているか確認
                                    message_matches = (
                                        (message_id > 0 and message.id == message_id) or
                                        (message.embeds and 
                                         len(message.embeds) > 0 and 
                                         message.embeds[0].footer and 
                                         f"ID: {post_id}" in str(message.embeds[0].footer.text))
                                    )
                                    
                                    if message_matches:
                                        print(f"[DEBUG] 履歴からメッセージを削除します - メッセージID: {message.id}")
                                        await message.delete()
                                        deleted_messages += 1
                                        found = True
                                        print(f"[DEBUG] 履歴からメッセージを削除しました - メッセージID: {message.id}")
                                        break
                                except Exception as e:
                                    print(f"[ERROR] メッセージ処理中にエラー: {type(e).__name__}: {e}")
                                    continue
                                    
                            if not found:
                                print(f"[WARNING] メッセージが見つかりませんでした - チャンネルID: {channel_id}, 投稿ID: {post_id}")
                                
                        except Exception as e:
                            print(f"[ERROR] チャンネル履歴の検索中にエラー: {type(e).__name__}: {e}")
                            import traceback
                            traceback.print_exc()
                            
                    except Exception as e:
                        print(f"[ERROR] チャンネル処理中にエラー (チャンネルID: {channel_id}): {type(e).__name__}: {e}")
                        import traceback
                        traceback.print_exc()
                
                # 5. メッセージ参照を削除
                cursor.execute('''
                    DELETE FROM message_references 
                    WHERE post_id = ?
                ''', (post_id,))
                
                # 6. 投稿を削除
                cursor.execute('''
                    DELETE FROM thoughts 
                    WHERE id = ?
                ''', (post_id,))
                
                print(f"[DEBUG] 削除完了 - 投稿ID: {post_id}, 削除メッセージ数: {deleted_messages}")
            
            if deleted_messages > 0 or is_private:
                await interaction.followup.send(
                    f"✅ 投稿 (ID: {post_id}) を削除しました\n"
                    f"- 削除されたメッセージ: {deleted_messages}件",
                    ephemeral=True
                )
            else:
                await interaction.followup.send(
                    f"⚠️ 投稿 (ID: {post_id}) はデータベースから削除されましたが、\n"
                    "メッセージが見つからなかったか、既に削除されています。",
                    ephemeral=True
                )
            
        except Exception as e:
            error_msg = f"[ERROR] 削除処理中にエラー: {type(e).__name__}: {e}"
            print(error_msg)
            import traceback
            traceback.print_exc()
            
            try:
                self.bot.db.rollback()
                print("[DEBUG] データベーストランザクションをロールバックしました")
            except Exception as rollback_error:
                print(f"[ERROR] ロールバック中にエラーが発生: {type(rollback_error).__name__}: {rollback_error}")
                
            await interaction.followup.send(
                "❌ 投稿の削除中にエラーが発生しました。\n"
                "ボットのログを確認してください。",
                ephemeral=True
            )

async def setup(bot):
    await bot.add_cog(Delete(bot))
