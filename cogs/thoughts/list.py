from __future__ import annotations

import logging
from typing import List, Dict, Any, Optional, Tuple, Union
from datetime import datetime

import discord
from discord import app_commands, ui, Interaction, Embed, File
from discord.ext import commands

# ロガーの設定
logger = logging.getLogger(__name__)

# 型定義
PostData = Dict[str, Any]  # 投稿データの型

class List(commands.Cog):
    """投稿一覧を表示するためのCog"""
    
    def __init__(self, bot: commands.Bot) -> None:
        """List Cogを初期化します。
        
        Args:
            bot: Discord Bot インスタンス
        """
        self.bot: commands.Bot = bot
        logger.info("List cog が初期化されました")
    
    async def _fetch_user_posts(self, user_id: int, limit: int) -> List[PostData]:
        """ユーザーの投稿をデータベースから取得します。
        
        Args:
            user_id: ユーザーID
            limit: 取得する投稿の最大数
            
        Returns:
            List[PostData]: 投稿データのリスト
            
        Raises:
            sqlite3.Error: データベース操作に失敗した場合
        """
        try:
            # Post コグを取得
            post_cog = self.bot.get_cog('Post')
            if not post_cog or not hasattr(post_cog, '_get_db_connection'):
                logger.error("Post コグが見つからないか、データベースにアクセスできません")
                return []
                
            with post_cog._get_db_connection() as conn:
                with post_cog._get_cursor(conn) as cursor:
                    # 必要なデータを一度のクエリで取得（サブクエリを使用）
                    cursor.execute('''
                        SELECT 
                            t.id, 
                            t.content, 
                            t.category, 
                            t.created_at, 
                            t.is_private, 
                            t.display_name,
                            (SELECT GROUP_CONCAT(a.url, '|') 
                             FROM attachments a 
                             WHERE a.post_id = t.id 
                             AND a.url IS NOT NULL 
                             AND a.url != '') as attachment_urls
                        FROM thoughts t
                        WHERE t.user_id = ?
                        ORDER BY t.created_at DESC
                        LIMIT ?
                    ''', (user_id, limit))
                    
                    # 結果を辞書のリストとして取得
                    columns = [column[0] for column in cursor.description]
                    return [dict(zip(columns, row)) for row in cursor.fetchall()]
                    
        except sqlite3.Error as e:
            logger.error(f"投稿の取得中にエラーが発生しました: {e}", exc_info=True)
            raise

    @app_commands.command(name="list", description="自分の投稿一覧を表示します")
    @app_commands.describe(limit="表示する件数 (デフォルト: 10, 最大: 25)")
    async def list_posts(self, interaction: discord.Interaction, limit: int = 10) -> None:
        """自分の投稿一覧を表示します
        
        Args:
            interaction: Discord インタラクションオブジェクト
            limit: 表示する投稿の最大数 (1〜25)
            
        Raises:
            Exception: 予期せぬエラーが発生した場合
        """
        # DMの場合は無効化
        if isinstance(interaction.channel, discord.DMChannel):
            await interaction.response.send_message(
                "❌ このコマンドはDMでは使用できません。サーバー内でお試しください。", 
                ephemeral=True
            )
            return
            
        try:
            # 即座に応答して処理中であることを伝える
            await interaction.response.defer(ephemeral=True)
            logger.info(f"投稿一覧の取得を開始: user_id={interaction.user.id}, limit={limit}")
            
            # 入力バリデーション
            limit = max(1, min(25, limit))  # 1〜25件に制限
            
            # データベースから投稿を取得
            try:
                posts = await self._fetch_user_posts(interaction.user.id, limit)
                
                if not posts:
                    embed = discord.Embed(
                        title="📭 投稿がありません",
                        description="まだ投稿がありません。`/post` コマンドで新しい投稿を作成しましょう！",
                        color=discord.Color.blue()
                    )
                    return await interaction.followup.send(embed=embed, ephemeral=True)
                
                # ページネーションの設定
                items_per_page = 3  # 1ページあたりの表示数
                pages = []
                
                for i in range(0, len(posts), items_per_page):
                    embed = discord.Embed(
                        title=f"📋 {interaction.user.display_name} さんの投稿一覧",
                        color=discord.Color.blue()
                    )
                    
                    for post in posts[i:i + items_per_page]:
                        try:
                            post_id = post['id']
                            content = post['content'] or "（内容なし）"
                            category = post['category'] or "（カテゴリーなし）"
                            is_private = post['is_private']
                            display_name = post['display_name'] or interaction.user.display_name
                            
                            # 内容が長すぎる場合は省略
                            display_content = content[:100] + '...' if len(content) > 100 else content
                            
                            # 投稿情報を追加
                            field_value = f"{display_content}\n"
                            field_value += f"カテゴリー: {category}\n"
                            if is_private:
                                field_value += "🔒 非公開\n"
                            
                            # 添付ファイル情報を処理
                            if post.get('attachment_urls'):
                                attachments = [url for url in post['attachment_urls'].split('|') if url]
                                # 画像URLを抽出
                                image_urls = [
                                    url for url in attachments 
                                    if url.lower().endswith(('.png', '.jpg', '.jpeg', '.gif', '.webp'))
                                ]
                                
                                if image_urls:
                                    field_value += "\n🖼️ 画像が添付されています"
                                    if len(image_urls) > 1:
                                        field_value += f" ({len(image_urls)}枚)"
                                    
                                    # 最初の画像をサムネイルとして設定
                                    if not embed.thumbnail and len(embed.fields) == 0:
                                        # 最初の投稿の最初の画像のみをサムネイルに設定
                                        embed.set_thumbnail(url=image_urls[0])
                            
                            # 投稿をフィールドとして追加
                            embed.add_field(
                                name=f"ID: {post_id} | {display_name} | {post['created_at'].split(' ')[0]}",
                                value=field_value,
                                inline=False
                            )
                            
                        except Exception as e:
                            logger.error(f"投稿の処理中にエラーが発生しました (post_id: {post.get('id', 'unknown')}): {e}", 
                                       exc_info=True)
                            # エラーが発生した投稿はスキップ
                            continue
                    
                    # 1ページ分の埋め込みを追加
                    if embed.fields:  # フィールドが空でない場合のみ追加
                        pages.append(embed)
                
                if not pages:
                    error_embed = discord.Embed(
                        title="❌ エラー",
                        description="表示可能な投稿が見つかりませんでした。",
                        color=discord.Color.red()
                    )
                    return await interaction.followup.send(embed=error_embed, ephemeral=True)
                
                try:
                    # ページネーションのビューを作成
                    view = PaginationView(pages, 0, interaction.user.id)
                    
                    # 最初のページを表示
                    message = await interaction.followup.send(embed=pages[0], view=view, 
                                                           wait=True, ephemeral=True)
                    
                    # ビューにメッセージを設定
                    view.message = message
                    
                except discord.HTTPException as e:
                    logger.error(f"メッセージの送信中にエラーが発生しました: {e}", exc_info=True)
                    error_embed = discord.Embed(
                        title="❌ エラー",
                        description="メッセージの送信中にエラーが発生しました。もう一度お試しください。",
                        color=discord.Color.red()
                    )
                    await interaction.followup.send(embed=error_embed, ephemeral=True)
                
            except sqlite3.Error as e:
                logger.error(f"データベースエラーが発生しました: {e}", exc_info=True)
                error_embed = discord.Embed(
                    title="❌ データベースエラー",
                    description="投稿の読み込み中にエラーが発生しました。しばらくしてから再度お試しください。",
                    color=discord.Color.red()
                )
                await interaction.followup.send(embed=error_embed, ephemeral=True)
                
        except Exception as e:
            logger.critical(f"予期せぬエラーが発生しました: {e}", exc_info=True)
            try:
                error_embed = discord.Embed(
                    title="❌ エラー",
                    description="予期せぬエラーが発生しました。しばらくしてから再度お試しください。",
                    color=discord.Color.red()
                )
                await interaction.followup.send(embed=error_embed, ephemeral=True)
            except Exception as e:
                logger.error(f"エラーメッセージの送信中にエラーが発生しました: {e}", exc_info=True)

class PaginationView(discord.ui.View):
    def __init__(self, pages, current_page, user_id):
        super().__init__(timeout=300)  # 5分に延長
        self.pages = pages
        self.current_page = current_page
        self.user_id = user_id
        self.message = None
        self.update_buttons()
    
    def update_buttons(self):
        # すべてのボタンをクリア
        self.clear_items()
        
        # ボタンのスタイルを定義
        first_disabled = self.current_page == 0
        last_disabled = self.current_page >= len(self.pages) - 1
        
        # ボタンを追加
        buttons = [
            ('<<', 'first', first_disabled, discord.ButtonStyle.secondary),
            ('<', 'prev', first_disabled, discord.ButtonStyle.primary),
            (f'{self.current_page + 1}/{len(self.pages)}', 'page', True, discord.ButtonStyle.gray),
            ('>', 'next', last_disabled, discord.ButtonStyle.primary),
            ('>>', 'last', last_disabled, discord.ButtonStyle.secondary)
        ]
        
        for label, custom_id, disabled, style in buttons:
            button = discord.ui.Button(
                style=style,
                label=label,
                custom_id=custom_id,
                disabled=disabled
            )
            button.callback = self.button_callback
            self.add_item(button)
    
    async def button_callback(self, interaction: discord.Interaction):
        # ボタンを押したユーザーを確認
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("この操作は許可されていません。", ephemeral=True)
            return
            
        # ボタンIDに応じてページを更新
        custom_id = interaction.data['custom_id']
        
        try:
            if custom_id == 'first':
                self.current_page = 0
            elif custom_id == 'prev' and self.current_page > 0:
                self.current_page -= 1
            elif custom_id == 'next' and self.current_page < len(self.pages) - 1:
                self.current_page += 1
            elif custom_id == 'last':
                self.current_page = len(self.pages) - 1
            
            # ボタンの状態を更新
            self.update_buttons()
            
            # メッセージを編集
            await interaction.response.edit_message(
                embed=self.pages[self.current_page],
                view=self
            )
            
        except Exception as e:
            print(f"[ERROR] ページネーション処理中にエラーが発生しました: {e}")
            if not interaction.response.is_done():
                await interaction.response.send_message(
                    "ページの更新中にエラーが発生しました。",
                    ephemeral=True
                )
    
    async def on_timeout(self):
        # タイムアウト時にボタンを無効化
        for item in self.children:
            if isinstance(item, discord.ui.Button):
                item.disabled = True
        
        if self.message:
            try:
                await self.message.edit(view=self)
            except:
                pass

async def setup(bot):
    await bot.add_cog(List(bot))
