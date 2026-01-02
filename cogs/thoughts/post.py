import discord
from discord import app_commands
from discord.ext import commands
from datetime import datetime

class Post(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.db = bot.db

    class PostModal(discord.ui.Modal, title='メッセージを投稿'):
        def __init__(self, bot, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.bot = bot
            
            # メッセージ入力
            self.content = discord.ui.TextInput(
                label='メッセージ',
                style=discord.TextStyle.paragraph,
                placeholder='メッセージを入力してください...',
                required=True,
                max_length=1000
            )
            self.add_item(self.content)
            
            # カテゴリー入力
            self.category = discord.ui.TextInput(
                label='カテゴリー',
                placeholder='例: 独り言, 愚痴, 悩み, アイデア など',
                required=False,
                max_length=50
            )
            self.add_item(self.category)
            
            # 画像URL入力
            self.image_url = discord.ui.TextInput(
                label='画像URL (任意)',
                placeholder='画像のURLを入力...',
                required=False
            )
            self.add_item(self.image_url)
            
            # 匿名設定
            self.is_anonymous = discord.ui.TextInput(
                label='表示名',
                placeholder='名前を表示する場合は「表示」、匿名の場合は「匿名」と入力',
                default='表示',
                required=True,
                max_length=2
            )
            self.add_item(self.is_anonymous)
            
            # 公開設定
            self.is_private = discord.ui.TextInput(
                label='公開設定',
                placeholder='公開する場合は「公開」、非公開の場合は「非公開」と入力',
                default='公開',
                required=True,
                max_length=3
            )
            self.add_item(self.is_private)


        async def on_submit(self, interaction: discord.Interaction):
            try:
                # 即座に応答して処理中であることを伝える
                await interaction.response.defer(ephemeral=True)
                
                # モーダルの入力を取得
                content = self.content.value
                category = self.category.value if self.category.value else 'その他'
                image_url = self.image_url.value if self.image_url.value else None
                is_anonymous = self.is_anonymous.value.strip() == '匿名'
                is_private = self.is_private.value.strip() == '非公開'
                
                # 入力バリデーション
                if not content or len(content.strip()) == 0:
                    raise ValueError('メッセージを入力してください。')
                    
                if len(content) > 1000:
                    raise ValueError('メッセージは1000文字以内で入力してください。')
                
                # データベーストランザクション開始
                cursor = self.bot.db.cursor()
                try:
                    cursor.execute('''
                        INSERT INTO thoughts (
                            user_id, content, category, image_url, 
                            is_anonymous, is_private, created_at, updated_at,
                            display_name
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ''', (
                        interaction.user.id,
                        content,
                        category,
                        image_url,
                        is_anonymous,  # 匿名設定
                        is_private,  # 公開設定
                        datetime.now().isoformat(),
                        datetime.now().isoformat(),
                        None if is_anonymous else interaction.user.display_name  # 表示名を保存
                    ))
                    
                    # 投稿完了メッセージを表示
                    embed = discord.Embed(
                        title='📝 投稿が完了しました',
                        description=content,
                        color=discord.Color.green(),
                        timestamp=datetime.now()
                    )
                    
                    # 投稿者情報を設定
                    if not is_anonymous:
                        embed.set_author(
                            name=interaction.user.display_name,
                            icon_url=str(interaction.user.display_avatar.url)
                        )
                    else:
                        embed.set_author(name='匿名')
                    
                    # カテゴリーと表示設定を追加
                    embed.add_field(name='カテゴリー', value=category, inline=True)
                    embed.add_field(name='表示名', value='匿名' if is_anonymous else '表示', inline=True)
                    embed.add_field(name='公開設定', value='非公開 🔒' if is_private else '公開 🌐', inline=True)
                    
                    # 画像がある場合は追加
                    if image_url:
                        embed.set_image(url=image_url)
                    
                    # データベースの変更を確定
                    self.bot.db.commit()
                    
                    # 投稿IDを取得
                    post_id = cursor.lastrowid
                    
                    # チャンネルまたはDMに投稿
                    try:
                        if is_private:
                            # 非公開の場合はDMに送信
                            dm_channel = await interaction.user.create_dm()
                            message = await dm_channel.send(embed=discord.Embed(
                                title='🔒 非公開メッセージ',
                                description=content,
                                color=discord.Color.blue(),
                                timestamp=datetime.now()
                            ).set_footer(text=f'カテゴリー: {category} | ID: {post_id}'))
                            
                            # 確認メッセージを更新
                            embed.add_field(name='配信先', value='DMに送信されました', inline=False)
                            
                        else:
                            # 公開の場合はチャンネルに投稿
                            channel_embed = discord.Embed(
                                description=content,
                                color=discord.Color.blue(),
                                timestamp=datetime.now()
                            )
                            
                            # 投稿者情報を設定
                            if not is_anonymous:
                                channel_embed.set_author(
                                    name=interaction.user.display_name,
                                    icon_url=str(interaction.user.display_avatar.url)
                                )
                            else:
                                channel_embed.set_author(name='匿名')
                            
                            # フッターにカテゴリーと投稿IDを表示
                            channel_embed.set_footer(text=f'カテゴリー: {category} | ID: {post_id}')
                            
                            # 画像がある場合は追加
                            if image_url:
                                channel_embed.set_image(url=image_url)
                            
                            # チャンネルに投稿
                            message = await interaction.channel.send(embed=channel_embed)
                            
                            # 確認メッセージを更新
                            embed.add_field(name='チャンネル', value=f'[投稿を表示]({message.jump_url})', inline=False)
                            
                    except Exception as e:
                        # DM送信に失敗した場合のエラーハンドリング
                        error_msg = f"メッセージの送信中にエラーが発生しました: {str(e)}"
                        if "Cannot send messages to this user" in str(e):
                            error_msg = "DMを送信できませんでした。DMの設定を確認してください。"
                        embed.add_field(name='エラー', value=error_msg, inline=False)
                    
                    # ユーザーに確認メッセージを送信
                    await interaction.followup.send(embed=embed, ephemeral=True)
                    
                except Exception as e:
                    self.bot.db.rollback()
                    raise e
                    
            except Exception as e:
                error_embed = discord.Embed(
                    title='❌ エラー',
                    description=f'投稿中にエラーが発生しました: {str(e)}',
                    color=discord.Color.red()
                )
                try:
                    # インタラクションがまだ有効か確認
                    if not interaction.response.is_done():
                        await interaction.response.send_message(embed=error_embed, ephemeral=True)
                    else:
                        await interaction.followup.send(embed=error_embed, ephemeral=True)
                except:
                    # すべてのエラーをキャッチしてログに記録
                    import traceback
                    traceback.print_exc()
                    
                    # ユーザーにエラーを通知（DMで送信）
                    try:
                        await interaction.user.send(embed=error_embed)
                    except:
                        pass  # DMがブロックされている場合は無視

    @app_commands.command(name="post", description="新しいメッセージを投稿します")
    async def post(self, interaction: discord.Interaction):
        """新しいメッセージを投稿します"""
        modal = self.PostModal(bot=self.bot)
        await interaction.response.send_modal(modal)

async def setup(bot):
    await bot.add_cog(Post(bot))
