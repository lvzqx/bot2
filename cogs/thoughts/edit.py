import discord
from discord import app_commands
from discord.ext import commands
from datetime import datetime

class Edit(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.db = bot.db

    class EditModal(discord.ui.Modal):
        def __init__(self, bot, post_id, current_content, current_category, *args, **kwargs):
            self.bot = bot
            self.post_id = post_id
            super().__init__(title=f'投稿を編集 (ID: {post_id})', *args, **kwargs)
            
            # 内容入力フィールド
            self.content = discord.ui.TextInput(
                label='内容 (最大2000文字)',
                style=discord.TextStyle.paragraph,
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
        
        async def on_submit(self, interaction: discord.Interaction):
            try:
                # 入力バリデーション
                if not self.content.value.strip():
                    await interaction.response.send_message("❌ 内容を入力してください。", ephemeral=True)
                    return
                
                if not self.category.value.strip():
                    await interaction.response.send_message("❌ カテゴリーを入力してください。", ephemeral=True)
                    return
                
                await interaction.response.defer(ephemeral=True)
                
                # データベースを更新
                cursor = self.bot.db.cursor()
                cursor.execute('''
                    UPDATE thoughts 
                    SET content = ?, category = ?, updated_at = ?
                    WHERE id = ? AND user_id = ?
                    RETURNING image_url, is_private, is_anonymous
                ''', (
                    self.content.value.strip(),
                    self.category.value.strip(),
                    datetime.now().isoformat(),
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
                image_url, is_private, is_anonymous = result
                embed = discord.Embed(
                    title="✅ 投稿を更新しました",
                    description=f"`ID: {self.post_id}` の投稿を更新しました。",
                    color=discord.Color.green()
                )
                
                # 画像があれば表示
                if image_url:
                    embed.set_image(url=image_url)
                
                # 編集内容のプレビュー
                preview_content = self.content.value[:100] + ('...' if len(self.content.value) > 100 else '')
                embed.add_field(
                    name="更新内容",
                    value=f"**カテゴリー:** {self.category.value}\n"
                          f"**内容:** {preview_content}",
                    inline=False
                )
                
                # ステータスを表示
                status = []
                if is_private:
                    status.append("🔒 非公開")
                if is_anonymous:
                    status.append("👤 匿名")
                
                if status:
                    embed.add_field(
                        name="ステータス",
                        value=" | ".join(status),
                        inline=False
                    )
                
                # 編集ボタンを追加
                view = discord.ui.View(timeout=180)
                view.add_item(discord.ui.Button(
                    label="この投稿を表示",
                    style=discord.ButtonStyle.link,
                    url=f"https://discord.com/channels/{interaction.guild.id}/{interaction.channel.id}/{self.post_id}"
                ))
                
                await interaction.followup.send(embed=embed, view=view, ephemeral=True)
                
            except Exception as e:
                error_msg = f"エラーが発生しました: {str(e)}"
                print(f"Edit Error: {error_msg}")
                if not interaction.response.is_done():
                    await interaction.response.send_message("❌ エラーが発生しました。もう一度お試しください。", ephemeral=True)
                else:
                    await interaction.followup.send("❌ エラーが発生しました。もう一度お試しください。", ephemeral=True)

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
            await interaction.response.defer(ephemeral=True)
            post_id = int(self.values[0])
            
            # 選択された投稿を取得
            cursor = self.view.cog.bot.db.cursor()
            cursor.execute('''
                SELECT content, category, user_id, is_private, is_anonymous
                FROM thoughts 
                WHERE id = ? AND user_id = ?
            ''', (post_id, interaction.user.id))
            
            post = cursor.fetchone()
            
            if not post:
                await interaction.followup.send("❌ 投稿が見つからないか、編集権限がありません。", ephemeral=True)
                return
            
            current_content, current_category, _, _, _ = post
            
            # 編集モーダルを表示
            modal = self.view.cog.EditModal(
                bot=self.view.cog.bot,
                post_id=post_id,
                current_content=current_content,
                current_category=current_category
            )
            
            await interaction.followup.send("📝 編集モーダルを開いています...", ephemeral=True, delete_after=1)
            await interaction.followup.send_modal(modal)
    
    class PostSelectView(discord.ui.View):
        def __init__(self, cog, posts):
            super().__init__(timeout=60)
            self.cog = cog
            self.add_item(PostSelect(posts))
    
    @app_commands.command(name="edit", description="投稿を編集します")
    @app_commands.describe(
        post_id="編集する投稿のID（省略すると投稿一覧を表示）"
    )
    async def edit_post(
        self, 
        interaction: discord.Interaction, 
        post_id: int = None
    ):
        """投稿を編集します（モーダルで編集）"""
        try:
            await interaction.response.defer(ephemeral=True)
            
            # post_idが指定されている場合は直接編集
            if post_id is not None:
                # 現在の投稿を取得
                cursor = self.bot.db.cursor()
                cursor.execute('''
                    SELECT content, category, user_id
                    FROM thoughts 
                    WHERE id = ?
                ''', (post_id,))
                
                post = cursor.fetchone()
                
                if not post:
                    await interaction.followup.send("❌ 投稿が見つかりません。")
                    return
                    
                if post[2] != interaction.user.id:
                    await interaction.followup.send("❌ この投稿を編集する権限がありません。")
                    return
                
                current_content, current_category, _ = post
                
                # モーダルで編集
                modal = self.EditModal(
                    bot=self.bot,
                    post_id=post_id,
                    current_content=current_content,
                    current_category=current_category
                )
                
                await interaction.followup.send("📝 編集モーダルを開いています...", ephemeral=True, delete_after=1)
                await interaction.followup.send_modal(modal)
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
                await interaction.followup.send("❌ 編集可能な投稿が見つかりませんでした。", ephemeral=True)
                return
            
            # 投稿選択用のビューを表示
            view = self.PostSelectView(self, posts)
            await interaction.followup.send(
                "📝 編集する投稿を選択してください（最新25件）",
                view=view,
                ephemeral=True
            )
            
            # 更新処理
            cursor.execute(f'''
                UPDATE thoughts 
                SET {field} = ?, updated_at = ?
                WHERE id = ? AND user_id = ?
                RETURNING image_url
            ''', (
                new_value.strip(),
                datetime.now().isoformat(),
                post_id,
                interaction.user.id
            ))
            
            result = cursor.fetchone()
            
            if not result:
                await interaction.followup.send("❌ 投稿の更新に失敗しました。")
                return
                
            self.bot.db.commit()
            
            # 編集完了メッセージ
            image_url = result[0]
            embed = discord.Embed(
                title="✅ 投稿を更新しました",
                description=f"`ID: {post_id}` の投稿を更新しました。",
                color=discord.Color.green()
            )
            
            # 更新内容を表示
            updated_content = new_value if field == 'content' else current_content
            updated_category = new_value if field == 'category' else current_category
            
            preview_content = updated_content[:100] + ('...' if len(updated_content) > 100 else '')
            embed.add_field(
                name="更新内容",
                value=f"**カテゴリー:** {updated_category}\n"
                      f"**内容:** {preview_content}",
                inline=False
            )
            
            # 画像があれば表示
            if image_url:
                embed.set_image(url=image_url)
            
            # ステータスを表示
            status = []
            if is_private:
                status.append("🔒 非公開")
            if is_anonymous:
                status.append("👤 匿名")
            
            if status:
                embed.add_field(
                    name="ステータス",
                    value=" | ".join(status),
                    inline=False
                )
            
            # 編集ボタンを追加
            view = discord.ui.View(timeout=180)
            view.add_item(discord.ui.Button(
                label="この投稿を表示",
                style=discord.ButtonStyle.link,
                url=f"https://discord.com/channels/{interaction.guild.id}/{interaction.channel.id}/{post_id}"
            ))
            
            await interaction.followup.send(embed=embed, view=view, ephemeral=True)
                
        except Exception as e:
            error_msg = f"エラーが発生しました: {str(e)}"
            print(f"Edit Command Error: {error_msg}")
            if not interaction.response.is_done():
                await interaction.response.send_message("❌ エラーが発生しました。もう一度お試しください。", ephemeral=True)
            else:
                await interaction.followup.send("❌ エラーが発生しました。もう一度お試しください。", ephemeral=True)

async def setup(bot):
    await bot.add_cog(Edit(bot))
