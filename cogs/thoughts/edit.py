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
                label='内容',
                style=discord.TextStyle.paragraph,
                default=current_content,
                placeholder='投稿の内容を入力してください...',
                required=True,
                max_length=1000,
                min_length=1
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

    @app_commands.command(name="edit", description="投稿を編集します")
    @app_commands.describe(
        post_id="編集する投稿のID",
        field="編集する項目 (content, category) - 省略するとモーダルが開きます",
        new_value="新しい値 - フィールドを指定する場合は必須"
    )
    async def edit_post(
        self, 
        interaction: discord.Interaction, 
        post_id: int,
        field: str = None,
        new_value: str = None
    ):
        """投稿を編集します（モーダルまたはコマンド引数で）"""
        try:
            await interaction.response.defer(ephemeral=True)
            
            # 現在の投稿を取得
            cursor = self.bot.db.cursor()
            cursor.execute('''
                SELECT content, category, user_id, is_private, is_anonymous
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
            
            current_content, current_category, _, is_private, is_anonymous = post
            
            # モーダルで編集
            if field is None or new_value is None:
                modal = self.EditModal(
                    bot=self.bot,
                    post_id=post_id,
                    current_content=current_content,
                    current_category=current_category
                )
                
                # モーダルを表示
                await interaction.followup.send("📝 編集モーダルを開いています...", ephemeral=True, delete_after=1)
                await interaction.followup.send_modal(modal)
                return
            
            # コマンド引数で編集
            field = field.lower()
            if field not in ['content', 'category']:
                await interaction.followup.send("❌ 無効なフィールドです。'content' または 'category' を指定してください。")
                return
            
            if not new_value or not new_value.strip():
                await interaction.followup.send(f"❌ {field}の値を指定してください。")
                return
            
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
