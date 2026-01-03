import asyncio
import discord
from discord import app_commands
from discord.ext import commands

class Delete(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.db = bot.db

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        # ボット自身のメッセージは無視
        if message.author == self.bot.user:
            return
            
        # DMの場合の処理
        if isinstance(message.channel, discord.DMChannel):
            await self.handle_dm_command(message)
    
    async def handle_dm_command(self, message: discord.Message):
        content = message.content.strip().lower()
        
        # メッセージ削除コマンド
        if content in ['削除', 'delete', 'さくじょ']:
            await self.delete_bot_messages(message)
        # 投稿IDを指定した削除コマンド（例: /delete 123）
        elif content.startswith('/delete '):
            await self.delete_private_post(message)
    
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
            # 投稿IDを取得
            post_id = message.content.split()[-1].strip()
            if not post_id.isdigit():
                await message.channel.send("❌ 正しい投稿IDを指定してください。例: `/delete 123`", delete_after=10)
                return
                
            post_id = int(post_id)
            user_id = message.author.id
            
            # メッセージ参照を取得
            cursor = self.bot.db.cursor()
            cursor.execute('''
                SELECT message_id, channel_id FROM message_references 
                WHERE post_id = ?
            ''', (post_id,))
            
            msg_ref = cursor.fetchone()
            
            # 投稿の存在確認と削除
            cursor.execute('''
                DELETE FROM thoughts 
                WHERE id = ? AND user_id = ? AND is_private = 1
                RETURNING id
            ''', (post_id, user_id))
            
            if cursor.fetchone():
                # メッセージ参照を削除
                cursor.execute('DELETE FROM message_references WHERE post_id = ?', (post_id,))
                self.bot.db.commit()
                
                # 埋め込みメッセージを削除
                if msg_ref:
                    message_id, channel_id = msg_ref
                    try:
                        channel = self.bot.get_channel(int(channel_id))
                        if channel and isinstance(channel, discord.DMChannel):
                            msg = await channel.fetch_message(int(message_id))
                            if msg:
                                await msg.delete()
                    except Exception as e:
                        print(f"メッセージ削除エラー: {e}")
                
                await message.channel.send(f"✅ 非公開投稿 (ID: {post_id}) を削除しました")
            else:
                await message.channel.send("❌ 削除できる非公開投稿が見つかりませんでした", delete_after=10)
                
        except Exception as e:
            print(f"非公開投稿削除エラー: {e}")
            await message.channel.send("❌ 投稿の削除中にエラーが発生しました", delete_after=10)

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
