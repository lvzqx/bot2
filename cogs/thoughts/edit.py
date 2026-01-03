import discord
from discord import app_commands
from discord.ext import commands
from datetime import datetime

class Edit(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.db = bot.db

    class EditModal(discord.ui.Modal):
        def __init__(self, bot, post_id, current_content, current_category, current_image_url=None, current_is_anonymous=False, current_is_private=False, *args, **kwargs):
            self.bot = bot
            self.post_id = post_id
            super().__init__(title=f'投稿を編集 (ID: {post_id})', *args, **kwargs)
            
            # 内容入力フィールド
            self.content = discord.ui.TextInput(
                label='内容 (最大2000文字)',
                default=current_content,
                placeholder='投稿の内容を入力してください...',
                required=True,
                max_length=2000,
                min_length=1,
                style=discord.TextStyle.long
            )
            self.add_item(self.content)
            
            # カテゴリー入力フィールド
            self.category = discord.ui.TextInput(
                label='カテゴリー',
                default=current_category,
                placeholder='カテゴリーを入力してください...',
                required=True,
                max_length=50,
                min_length=1
            )
            self.add_item(self.category)
            
            # 画像URL入力フィールド
            self.image_url = discord.ui.TextInput(
                label='画像URL (削除する場合は空欄)',
                default=current_image_url or '',
                placeholder='画像のURLを入力...',
                required=False
            )
            self.add_item(self.image_url)
            
            # 表示名設定
            self.is_anonymous = discord.ui.TextInput(
                label='表示名',
                placeholder='名前を表示する場合は「表示」、匿名の場合は「匿名」と入力',
                default='匿名' if current_is_anonymous else '表示',
                required=True,
                max_length=2
            )
            self.add_item(self.is_anonymous)
            
            # 公開設定
            self.is_private = discord.ui.TextInput(
                label='公開設定',
                placeholder='公開する場合は「公開」、非公開の場合は「非公開」と入力',
                default='非公開' if current_is_private else '公開',
                required=True,
                max_length=3
            )
            self.add_item(self.is_private)
        
        async def on_submit(self, interaction: discord.Interaction):
            try:
                # 入力バリデーション
                if not self.content.value.strip():
                    await interaction.response.send_message("❌ 内容を入力してください。", ephemeral=True)
                    return
                
                if not self.category.value.strip():
                    await interaction.response.send_message("❌ カテゴリーを入力してください。", ephemeral=True)
                    return
                    
                # 表示名と公開設定のバリデーション
                display_option = self.is_anonymous.value.strip()
                if display_option not in ['表示', '匿名']:
                    await interaction.response.send_message("❌ 表示名は「表示」または「匿名」で入力してください。", ephemeral=True)
                    return

                privacy_option = self.is_private.value.strip()
                if privacy_option not in ['公開', '非公開']:
                    await interaction.response.send_message("❌ 公開設定は「公開」または「非公開」で入力してください。", ephemeral=True)
                    return

                is_anonymous = display_option == '匿名'
                is_private = privacy_option == '非公開'
                image_url = self.image_url.value.strip() or None
                
                await interaction.response.defer(ephemeral=True)
                
                try:
                    # データベースを更新
                    cursor = self.bot.db.cursor()
                    cursor.execute('''
                        UPDATE thoughts 
                        SET content = ?, 
                            category = ?, 
                            image_url = ?,
                            is_anonymous = ?,
                            is_private = ?,
                            updated_at = ?,
                            display_name = ?
                        WHERE id = ? AND user_id = ?
                        RETURNING *
                    ''', (
                        self.content.value.strip(),
                        self.category.value.strip(),
                        image_url,
                        is_anonymous,
                        is_private,
                        datetime.now().isoformat(),
                        None if is_anonymous else interaction.user.display_name,
                        self.post_id,
                        interaction.user.id
                    ))
                    
                    result = cursor.fetchone()
                    
                    if not result:
                        # 投稿が見つからないか権限がない場合
                        cursor.execute('SELECT id FROM thoughts WHERE id = ?', (self.post_id,))
                        if not cursor.fetchone():
                            await interaction.followup.send("❌ 投稿が見つかりません。既に削除されている可能性があります。", ephemeral=True)
                        else:
                            await interaction.followup.send("❌ 編集に失敗しました。自分の投稿のみ編集できます。", ephemeral=True)
                        return
                        
                    self.bot.db.commit()
                    
                    # 編集完了メッセージ
                    _, _, _, content, category, image_url, is_anonymous, is_private, created_at, updated_at, user_id, display_name = result
                    
                    embed = discord.Embed(
                        title="✅ 投稿を更新しました",
                        description=f"`ID: {self.post_id}` の投稿を更新しました。",
                        color=discord.Color.green()
                    )
                    
                    # 画像があれば表示
                    if image_url:
                        embed.set_image(url=image_url)
                    
                    # 編集内容のプレビュー
                    preview_content = content[:100] + ('...' if len(content) > 100 else '')
                    embed.add_field(
                        name="更新内容",
                        value=f"**カテゴリー:** {category}\n"
                              f"**表示名:** {'匿名' if is_anonymous else '表示'}\n"
                              f"**公開設定:** {'非公開 🔒' if is_private else '公開 🌐'}\n"
                              f"**内容:** {preview_content}",
                        inline=False
                    )
                    
                    # メッセージ参照を更新
                    if not is_private:
                        cursor.execute('''
                            SELECT message_id, channel_id 
                            FROM message_references 
                            WHERE post_id = ?
                        ''', (self.post_id,))
                        
                        message_ref = cursor.fetchone()
                        if message_ref:
                            message_id, channel_id = message_ref
                            try:
                                channel = self.bot.get_channel(int(channel_id))
                                if channel:
                                    message = await channel.fetch_message(int(message_id))
                                    
                                    # 埋め込みメッセージを更新
                                    new_embed = discord.Embed(
                                        description=content,
                                        color=discord.Color.blue()
                                    )
                                    
                                    # 表示名を設定
                                    if is_anonymous:
                                        new_embed.set_author(name='匿名')
                                    else:
                                        new_embed.set_author(
                                            name=display_name or interaction.user.display_name,
                                            icon_url=str(interaction.user.display_avatar.url)
                                        )
                                    
                                    # フッターにカテゴリーと投稿IDを表示
                                    footer_text = f'カテゴリー: {category} | ID: {self.post_id}'
                                    new_embed.set_footer(text=footer_text)
                                    
                                    # 画像があれば追加
                                    if image_url:
                                        new_embed.set_image(url=image_url)
                                    
                                    await message.edit(embed=new_embed)
                            except Exception as e:
                                print(f"メッセージ更新エラー: {e}")
                    
                    await interaction.followup.send(embed=embed, ephemeral=True)
                    
                except Exception as db_error:
                    self.bot.db.rollback()
                    error_msg = f"データベースエラー: {str(db_error)}"
                    print(f"Database Error in EditModal: {error_msg}")
                    await interaction.followup.send(f"❌ データの更新中にエラーが発生しました: {str(db_error)}", ephemeral=True)
                
            except Exception as e:
                error_msg = f"予期せぬエラーが発生しました: {str(e)}\n```{type(e).__name__}```"
                print(f"Unexpected Error in EditModal: {error_msg}")
                if not interaction.response.is_done():
                    await interaction.response.send_message(f"❌ エラーが発生しました: {str(e)}\nタイプ: {type(e).__name__}", ephemeral=True)
                else:
                    await interaction.followup.send(f"❌ エラーが発生しました: {str(e)}\nタイプ: {type(e).__name__}", ephemeral=True)

    class PostSelect(discord.ui.Select):
        def __init__(self, posts):
            options = []
            for post in posts[:25]:  # Discordの制限で最大25個まで
                post_id, content, category = post
                # プレビューテキストを短く整形
                preview = f"{content[:30]}{'...' if len(content) > 30 else ''}"
                options.append(discord.SelectOption(
                    label=f"ID: {post_id} - {category}",
                    description=preview,
                    value=str(post_id)
                ))
            
            super().__init__(
                placeholder="編集する投稿を選択...",
                min_values=1,
                max_values=1,
                options=options
            )
        
        async def callback(self, interaction: discord.Interaction):
            post_id = int(self.values[0])
            
            # 選択された投稿を取得
            cursor = self.view.cog.bot.db.cursor()
            cursor.execute('''
                SELECT content, category, image_url, is_anonymous, is_private, user_id
                FROM thoughts 
                WHERE id = ? AND user_id = ?
            ''', (post_id, interaction.user.id))
            
            post = cursor.fetchone()
            
            if not post:
                if not interaction.response.is_done():
                    await interaction.response.send_message("❌ 投稿が見つからないか、編集権限がありません。", ephemeral=True)
                else:
                    await interaction.followup.send("❌ 投稿が見つからないか、編集権限がありません。", ephemeral=True)
                return
            
            current_content, current_category, current_image_url, current_is_anonymous, current_is_private, _ = post
            
            # 編集モーダルを表示
            modal = self.view.cog.EditModal(
                bot=self.view.cog.bot,
                post_id=post_id,
                current_content=current_content,
                current_category=current_category,
                current_image_url=current_image_url,
                current_is_anonymous=bool(current_is_anonymous),
                current_is_private=bool(current_is_private)
            )
            
            # モーダルを直接表示
            try:
                await interaction.response.send_modal(modal)
            except discord.InteractionResponded:
                # 既にレスポンスが送信されている場合は、フォローアップとして送信
                await interaction.followup.send("❌ エラーが発生しました。もう一度お試しください。", ephemeral=True)
    
    class PostSelectView(discord.ui.View):
        def __init__(self, cog, posts):
            super().__init__(timeout=60)
            self.cog = cog
            self.add_item(PostSelect(posts))
    
    @app_commands.command(name="edit", description="投稿を編集します")
    @app_commands.describe(post_id="編集する投稿のID（省略可）")
    async def edit_post(
        self, 
        interaction: discord.Interaction, 
        post_id: int = None
    ):
        """投稿を編集します（モーダルで編集）"""
        try:
            # post_idが指定されている場合は直接編集モーダルを表示
            if post_id is not None:
                # データベースから投稿を取得
                cursor = self.bot.db.cursor()
                cursor.execute('''
                    SELECT content, category, user_id 
                    FROM thoughts 
                    WHERE id = ?
                ''', (post_id,))
                
                post = cursor.fetchone()
                
                if not post:
                    await interaction.response.send_message("❌ 指定された投稿が見つかりません。", ephemeral=True)
                    return
                
                current_content, current_category, post_user_id = post
                
                # 権限チェック（投稿者本人または管理者のみ編集可能）
                is_owner = post_user_id == interaction.user.id
                is_admin = interaction.user.guild_permissions.administrator if interaction.guild else False
                
                if not (is_owner or is_admin):
                    await interaction.response.send_message("❌ この投稿を編集する権限がありません。", ephemeral=True)
                    return
                
                # モーダルを表示
                modal = self.EditModal(
                    bot=self.bot,
                    post_id=post_id,
                    current_content=current_content,
                    current_category=current_category,
                    current_image_url=current_image_url,
                    current_is_anonymous=bool(current_is_anonymous),
                    current_is_private=bool(current_is_private)
                )
                await interaction.response.send_modal(modal)
                return
                
            # post_idが指定されていない場合は投稿一覧を表示
            cursor = self.bot.db.cursor()
            cursor.execute('''
                SELECT id, content, category
                FROM thoughts 
                WHERE user_id = ?
                ORDER BY created_at DESC
                LIMIT 25
            ''', (interaction.user.id,))
            
            posts = cursor.fetchall()
            
            if not posts:
                await interaction.response.send_message("❌ 編集可能な投稿が見つかりませんでした。", ephemeral=True)
                return
            
            # 投稿選択用のビューを表示
            view = self.PostSelectView(self, posts)
            await interaction.response.send_message(
                "📝 編集する投稿を選択してください（最新25件）",
                view=view,
                ephemeral=True
            )
            
        except Exception as e:
            error_msg = f"コマンド実行中にエラーが発生しました: {str(e)}\n```{type(e).__name__}```"
            print(f"Command Error in edit_post: {error_msg}")
            if not interaction.response.is_done():
                await interaction.response.send_message("❌ エラーが発生しました。もう一度お試しください。", ephemeral=True)
            else:
                await interaction.followup.send("❌ エラーが発生しました。もう一度お試しください。", ephemeral=True)

async def setup(bot):
    await bot.add_cog(Edit(bot))
