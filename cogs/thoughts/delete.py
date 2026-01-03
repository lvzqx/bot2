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
        if isinstance(message.channel, discord.DMChannel):
            content = message.content.strip()
            
            # 削除コマンドのみを処理
            if content.lower().startswith(('delete ', '/delete ')):
                await self.delete_private_post(message)
    
    
    
    
    async def delete_private_post(self, message: discord.Message):
        """DMから非公開投稿を削除（埋め込みメッセージも削除）"""
        try:
            print(f"[DEBUG] 削除コマンド受信: {message.content}")
            
            # メッセージがDMか確認
            if not isinstance(message.channel, discord.DMChannel):
                print("[ERROR] このコマンドはDMでのみ使用できます")
                return
                
            # 投稿IDを取得（コマンド形式: /delete 123 または delete 123）
            content = message.content.strip()
            parts = content.split()
            
            # コマンド形式をチェック
            if len(parts) < 2 or not parts[-1].isdigit():
                print(f"[ERROR] 無効なコマンド形式: {content}")
                help_msg = "```\n使い方:\n  delete [投稿ID]\n  \n例: delete 123\n```"
                await message.channel.send(help_msg, delete_after=15)
                return
                
            post_id = int(parts[-1])  # 最後の引数を投稿IDとして使用
            user_id = message.author.id
            print(f"[DEBUG] ユーザーID: {user_id}, 削除対象投稿ID: {post_id}")
            
            try:
                cursor = self.bot.db.cursor()
                
                # 1. 投稿の存在確認
                cursor.execute('''
                    SELECT id, is_private FROM thoughts 
                    WHERE id = ? AND user_id = ?
                ''', (post_id, user_id))
                
                post = cursor.fetchone()
                print(f"[DEBUG] 投稿確認: {post}")
                
                if not post:
                    await message.channel.send("❌ 投稿が見つからないか、削除する権限がありません。", delete_after=10)
                    return
                    
                if not post[1]:  # is_privateが0（公開投稿）の場合
                    await message.channel.send("❌ この投稿は公開されています。サーバーで `/delete" + 
                                            f" {post_id}` を使用してください。", delete_after=15)
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
                
                # メッセージ参照があれば削除
                if msg_ref:
                    cursor.execute('DELETE FROM message_references WHERE post_id = ?', (post_id,))
                
                self.bot.db.commit()
                print("[DEBUG] データベースから削除完了")
                
                # 埋め込みメッセージを削除
                if msg_ref:
                    try:
                        message_id, channel_id = msg_ref
                        print(f"[DEBUG] メッセージ削除を試みます: message_id={message_id}, channel_id={channel_id}")
                        
                        # チャンネルを取得
                        channel = self.bot.get_channel(int(channel_id))
                        
                        # DMチャンネルの場合、ユーザーからDMチャンネルを取得
                        if not channel and isinstance(message.channel, discord.DMChannel):
                            print("[DEBUG] DMチャンネルを検出、ユーザーからDMチャンネルを取得")
                            channel = message.channel
                        
                        if channel:
                            print(f"[DEBUG] チャンネルを取得: {channel} (type: {type(channel)})")
                            
                            try:
                                # メッセージを取得して削除
                                msg = await channel.fetch_message(int(message_id))
                                if msg:
                                    print("[DEBUG] メッセージを削除します")
                                    await msg.delete()
                                    print("[DEBUG] メッセージ削除完了")
                            except discord.NotFound:
                                print("[DEBUG] メッセージは既に削除されています")
                                # メッセージが既に削除されている場合は、DMの履歴からも削除を試みる
                                if isinstance(channel, discord.DMChannel):
                                    print("[DEBUG] DMの履歴からメッセージを検索中...")
                                    async for msg in channel.history(limit=100):
                                        if msg.embeds and msg.embeds[0].footer and f"ID: {post_id}" in str(msg.embeds[0].footer.text):
                                            print("[DEBUG] 埋め込みメッセージを検出、削除します")
                                            await msg.delete()
                                            print("[DEBUG] DMの埋め込みメッセージを削除しました")
                                            break
                            except Exception as e:
                                print(f"[ERROR] メッセージ削除エラー: {type(e).__name__}: {e}")
                                # エラーが発生した場合も、DMの履歴から削除を試みる
                                if isinstance(channel, discord.DMChannel):
                                    try:
                                        async for msg in channel.history(limit=100):
                                            if msg.embeds and msg.embeds[0].footer and f"ID: {post_id}" in str(msg.embeds[0].footer.text):
                                                print("[DEBUG] エラー後のDMメッセージ削除を試みます")
                                                await msg.delete()
                                                print("[DEBUG] DMの埋め込みメッセージを削除しました")
                                                break
                                    except Exception as e2:
                                        print(f"[ERROR] 代替削除処理中にエラー: {type(e2).__name__}: {e2}")
                    except Exception as e:
                        error_msg = f"[ERROR] メッセージ削除処理中にエラー: {type(e).__name__}: {e}"
                        print(error_msg)
                        import traceback
                        traceback.print_exc()
                        
                        # エラーが発生した場合でも、DMの履歴から削除を試みる
                        if isinstance(message.channel, discord.DMChannel):
                            try:
                                print("[DEBUG] 例外発生時のDMメッセージ削除を試みます")
                                async for msg in message.channel.history(limit=100):
                                    if msg.embeds and msg.embeds[0].footer and f"ID: {post_id}" in str(msg.embeds[0].footer.text):
                                        print("[DEBUG] 埋め込みメッセージを検出、削除します")
                                        await msg.delete()
                                        print("[DEBUG] DMの埋め込みメッセージを削除しました")
                                        break
                            except Exception as e2:
                                print(f"[ERROR] 例外処理中のDMメッセージ削除エラー: {type(e2).__name__}: {e2}")
                
                print("[DEBUG] 完了メッセージを送信")
                await message.channel.send(f"✅ 非公開投稿 (ID: {post_id}) を削除しました")
                    
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

    @app_commands.command(name="delete", description="投稿を削除します")
    @app_commands.describe(post_id="削除する投稿のID")
    async def delete_post(self, interaction: discord.Interaction, post_id: int):
        """指定されたIDの投稿を削除します"""
        await interaction.response.defer(ephemeral=True)
        
        try:
            # 投稿の存在確認と情報取得
            cursor = self.bot.db.cursor()
            cursor.execute('''
                SELECT user_id, is_private, is_anonymous, content, category
                FROM thoughts 
                WHERE id = ?
            ''', (post_id,))
            
            post = cursor.fetchone()
            
            if not post:
                await interaction.followup.send("❌ 指定された投稿が見つかりません。", ephemeral=True)
                return
            
            post_user_id, is_private, is_anonymous, content, category = post
            
            # 権限チェック（投稿者本人または管理者のみ削除可能）
            is_owner = post_user_id == interaction.user.id
            is_admin = interaction.user.guild_permissions.administrator if interaction.guild else False
            
            if not (is_owner or is_admin):
                await interaction.followup.send("❌ この投稿を削除する権限がありません。", ephemeral=True)
                return
            
            # 非公開投稿の場合はDMからも削除
            if is_private:
                try:
                    # 投稿者を取得
                    user = self.bot.get_user(post_user_id)
                    if user:
                        # DMチャンネルを取得または作成
                        dm_channel = user.dm_channel or await user.create_dm()
                        
                        # DM内のメッセージを検索して削除
                        async for message in dm_channel.history(limit=100):
                            if message.author == self.bot.user and message.embeds:
                                embed = message.embeds[0]
                                footer = embed.footer.text if embed.footer else ""
                                if f"ID: {post_id}" in footer:
                                    await message.delete()
                                    break
                except Exception as e:
                    print(f"DMメッセージ削除エラー: {e}")
            else:
                # 公開投稿の場合はチャンネルから削除
                cursor.execute('''
                    SELECT message_id, channel_id 
                    FROM message_references 
                    WHERE post_id = ?
                ''', (post_id,))
                
                for message_id, channel_id in cursor.fetchall():
                    try:
                        channel = self.bot.get_channel(channel_id)
                        if channel:
                            message = await channel.fetch_message(message_id)
                            if message:
                                await message.delete()
                    except Exception as e:
                        print(f"メッセージ削除エラー: {e}")
            
            # メッセージ参照を削除
            cursor.execute('''
                DELETE FROM message_references 
                WHERE post_id = ?
            ''', (post_id,))
            
            # 投稿を削除
            cursor.execute('''
                DELETE FROM thoughts 
                WHERE id = ?
            ''', (post_id,))
            
            self.bot.db.commit()
            
            # 削除完了メッセージ
            await interaction.followup.send(f"✅ 投稿を削除しました (ID: {post_id})", ephemeral=True)
            
        except Exception as e:
            self.bot.db.rollback()
            error_msg = f"削除中にエラーが発生しました: {str(e)}"
            print(f"Delete Error: {error_msg}")
            await interaction.followup.send(f"❌ {error_msg}", ephemeral=True)

    @app_commands.command(name="delete", description="投稿を削除します")
    @app_commands.describe(post_id="削除する投稿のID")
    async def delete_post(self, interaction: discord.Interaction, post_id: int):
        """指定したIDの投稿を削除します"""
        await interaction.response.defer(ephemeral=True)
        
        try:
            # 投稿の存在確認と情報取得
            cursor = self.bot.db.cursor()
            cursor.execute('''
                SELECT t.user_id, t.is_private, t.id, t.content, 
                       m.message_id, m.channel_id
                FROM thoughts t
                LEFT JOIN message_references m ON t.id = m.post_id
                WHERE t.id = ?
            ''', (post_id,))
            
            post = cursor.fetchone()
            
            if not post:
                await interaction.followup.send("❌ 指定された投稿が見つかりません。")
                return
                
            post_user_id, is_private, post_id, content, message_id, channel_id = post
            
            # 権限チェック（投稿者本人または管理者のみ削除可能）
            is_owner = post_user_id == interaction.user.id
            is_admin = interaction.user.guild_permissions.administrator
            
            if not (is_owner or is_admin):
                await interaction.followup.send("❌ この投稿を削除する権限がありません。")
                return
            
            # 確認メッセージを送信
            confirm_embed = discord.Embed(
                title="⚠️ 本当に削除しますか？",
                description=f"以下の投稿を削除しようとしています。\n```{content[:100]}{'...' if len(content) > 100 else ''}```\n**この操作は元に戻せません。**",
                color=discord.Color.orange()
            )
            
            # 確認ボタンを追加
            class ConfirmDelete(discord.ui.View):
                def __init__(self, original_interaction):
                    super().__init__(timeout=30)
                    self.original_interaction = original_interaction
                    self.value = None
                
                @discord.ui.button(label='削除する', style=discord.ButtonStyle.danger)
                async def confirm(self, button_interaction: discord.Interaction, button: discord.ui.Button):
                    if button_interaction.user.id != self.original_interaction.user.id:
                        return
                    
                    try:
                        # データベースから削除
                        cursor = self.original_interaction.client.db.cursor()
                        cursor.execute('DELETE FROM thoughts WHERE id = ?', (post_id,))
                        
                        # メッセージ参照を削除
                        cursor.execute('DELETE FROM message_references WHERE post_id = ?', (post_id,))
                        self.original_interaction.client.db.commit()
                        
                        # メッセージ削除処理
                        try:
                            if message_id and channel_id:
                                # チャンネルIDを整数に変換
                                channel_id_int = int(channel_id)
                                
                                # 通常のチャンネルかDMチャンネルを取得
                                if is_private:
                                    # DMチャンネルの場合
                                    user = await self.original_interaction.client.fetch_user(post_user_id)
                                    if user:
                                        try:
                                            dm_channel = user.dm_channel or await user.create_dm()
                                            message = await dm_channel.fetch_message(int(message_id))
                                            await message.delete()
                                            print(f"DMメッセージを削除しました: {message_id} (User: {user.id})")
                                        except discord.NotFound:
                                            print(f"DMメッセージが見つかりません: {message_id}")
                                        except discord.Forbidden:
                                            print(f"DMメッセージの削除権限がありません: {message_id}")
                                        except Exception as e:
                                            print(f"DMメッセージ削除中にエラーが発生しました: {e}")
                                else:
                                    # 通常のチャンネルの場合
                                    channel = self.original_interaction.client.get_channel(channel_id_int)
                                    if channel:
                                        try:
                                            message = await channel.fetch_message(int(message_id))
                                            await message.delete()
                                            print(f"チャンネルメッセージを削除しました: {message_id} in {channel_id_int}")
                                        except discord.NotFound:
                                            print(f"チャンネルメッセージが見つかりません: {message_id}")
                                        except discord.Forbidden:
                                            print(f"チャンネルメッセージの削除権限がありません: {message_id}")
                                        except Exception as e:
                                            print(f"チャンネルメッセージ削除中にエラーが発生しました: {e}")
                        except Exception as e:
                            print(f"メッセージ削除処理中にエラーが発生しました: {e}")
                        
                        embed = discord.Embed(
                            title="🗑️ 投稿を削除しました",
                            description=f"投稿ID: `{post_id}` を削除しました。",
                            color=discord.Color.green()
                        )
                        await button_interaction.response.edit_message(embed=embed, view=None)
                        
                    except Exception as e:
                        print(f"削除エラー: {e}")
                        error_embed = discord.Embed(
                            title="❌ エラー",
                            description="投稿の削除中にエラーが発生しました。",
                            color=discord.Color.red()
                        )
                        await button_interaction.response.edit_message(embed=error_embed, view=None)
                
                @discord.ui.button(label='キャンセル', style=discord.ButtonStyle.secondary)
                async def cancel(self, button_interaction: discord.Interaction, button: discord.ui.Button):
                    if button_interaction.user.id == self.original_interaction.user.id:
                        embed = discord.Embed(
                            title="キャンセルされました",
                            description="投稿の削除をキャンセルしました。",
                            color=discord.Color.blue()
                        )
                        await button_interaction.response.edit_message(embed=embed, view=None)
                
                async def on_timeout(self):
                    # タイムアウト時にボタンを無効化
                    for item in self.children:
                        item.disabled = True
                    try:
                        await self.message.edit(view=self)
                    except:
                        pass
            
            view = ConfirmDelete(interaction)
            view.message = await interaction.followup.send(embed=confirm_embed, view=view, wait=True)
                
        except Exception as e:
            print(f"Error in delete command: {e}")
            await interaction.followup.send("❌ エラーが発生しました。もう一度お試しください。")

async def setup(bot):
    await bot.add_cog(Delete(bot))
