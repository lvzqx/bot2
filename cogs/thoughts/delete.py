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
                
                # 4. メッセージを削除
                deleted_messages = 0
                
                # 非公開投稿の場合はDMからも削除
                if is_private:
                    try:
                        # 投稿者を取得
                        user = self.bot.get_user(post_user_id)
                        if user:
                            # DMチャンネルを取得または作成
                            dm_channel = user.dm_channel or await user.create_dm()
                            
                            # DM内のメッセージを検索して削除
                            async for dm_message in dm_channel.history(limit=100):
                                if dm_message.embeds and dm_message.embeds[0].footer:
                                    if f"ID: {post_id}" in str(dm_message.embeds[0].footer.text):
                                        await dm_message.delete()
                                        deleted_messages += 1
                                        break
                    except Exception as e:
                        print(f"[ERROR] DMメッセージ削除エラー: {e}")
                
                # 公開投稿の場合はチャンネルから削除
                for message_id, channel_id in msg_refs:
                    try:
                        channel = self.bot.get_channel(channel_id)
                        if channel:
                            message = await channel.fetch_message(message_id)
                            if message:
                                await message.delete()
                                deleted_messages += 1
                    except discord.NotFound:
                        print(f"[DEBUG] メッセージは既に削除されています - メッセージID: {message_id}")
                    except Exception as e:
                        print(f"[ERROR] メッセージ削除エラー: {e}")
                
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
            
            await interaction.followup.send(
                f"✅ 投稿 (ID: {post_id}) を削除しました\n"
                f"- 削除されたメッセージ: {deleted_messages}件",
                ephemeral=True
            )
            
        except Exception as e:
            error_msg = f"[ERROR] 削除処理中にエラー: {type(e).__name__}: {e}"
            print(error_msg)
            import traceback
            traceback.print_exc()
            
            try:
                self.bot.db.rollback()
            except:
                pass
                
            await interaction.followup.send(
                "❌ 投稿の削除中にエラーが発生しました。\n"
                "しばらくしてから再度お試しください。",
                ephemeral=True
            )

async def setup(bot):
    await bot.add_cog(Delete(bot))
