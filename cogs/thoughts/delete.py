import discord
from discord.ext import commands
from discord import app_commands
import sqlite3
import logging
from typing import Optional
from bot import DatabaseMixin

logger = logging.getLogger(__name__)

class Delete(commands.Cog, DatabaseMixin):
    """投稿削除用Cog"""
    
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        DatabaseMixin.__init__(self)
    
    @app_commands.command(name="delete", description="投稿を削除します")
    @app_commands.describe(message_id="削除する投稿のメッセージID")
    async def delete_post(self, interaction: discord.Interaction, message_id: str) -> None:
        """メッセージIDで投稿を削除します"""
        logger.info(f"delete コマンドが呼び出されました。ユーザー: {interaction.user}, メッセージID: {message_id}")
        
        # 応答を遅延
        await interaction.response.defer(ephemeral=True)
        
        try:
            # メッセージIDで投稿を検索
            with self._get_db_connection() as conn:
                with self._get_cursor(conn) as cursor:
                    cursor.execute('''
                        SELECT mr.post_id, mr.channel_id, t.user_id, t.is_private
                        FROM message_references mr
                        JOIN thoughts t ON mr.post_id = t.id
                        WHERE mr.message_id = ?
                    ''', (message_id,))
                    
                    row = cursor.fetchone()
                    if not row:
                        await interaction.followup.send(
                            "❌ 指定されたメッセージIDの投稿が見つかりません。",
                            ephemeral=True
                        )
                        return
                    
                    post_id, channel_id, post_user_id, is_private = row
                    logger.info(f"投稿を検出: post_id={post_id}, channel_id={channel_id}")
                    
                    # 権限チェック
                    is_admin = interaction.user.guild_permissions.administrator
                    if str(post_user_id) != str(interaction.user.id) and not is_admin:
                        await interaction.followup.send(
                            "❌ この投稿を削除する権限がありません。",
                            ephemeral=True
                        )
                        return
                    
                    # メッセージを削除
                    try:
                        channel = await interaction.guild.fetch_channel(int(channel_id))
                        message = await channel.fetch_message(int(message_id))
                        await message.delete()
                        logger.info(f"メッセージ {message_id} を削除しました")
                    except discord.NotFound:
                        logger.warning(f"メッセージが見つかりません: {message_id}")
                    except discord.Forbidden:
                        logger.warning(f"メッセージの削除権限がありません: {message_id}")
                    except Exception as e:
                        logger.error(f"メッセージ削除中にエラー: {e}")
                    
                    # データベースから投稿を削除
                    try:
                        # メッセージ参照を先に削除
                        cursor.execute('DELETE FROM message_references WHERE post_id = ?', (post_id,))
                        # 投稿を削除
                        cursor.execute('DELETE FROM thoughts WHERE id = ?', (post_id,))
                        conn.commit()
                        logger.info(f"投稿ID {post_id} をデータベースから削除しました")
                    except Exception as e:
                        logger.error(f"データベース削除中にエラー: {e}")
                        conn.rollback()
                        await interaction.followup.send(
                            "❌ データベースの削除に失敗しました。",
                            ephemeral=True
                        )
                        return
                    
                    # 非公開投稿の場合、ロールを確認
                    if is_private:
                        try:
                            # 残りの非公開投稿数を確認
                            cursor.execute('''
                                SELECT COUNT(*) as count 
                                FROM thoughts 
                                WHERE user_id = ? AND is_public = 0
                            ''', (post_user_id,))
                            remaining_posts = cursor.fetchone()['count']
                            
                            if remaining_posts == 0:
                                # プライベートスレッドを削除
                                try:
                                    private_channel = interaction.guild.get_channel(1278762436569415772)  # 非公開チャンネルID
                                    if private_channel:
                                        thread_prefix = f"非公開投稿 - {post_user_id} ("
                                        for thread in private_channel.threads:
                                            if thread.name.startswith(thread_prefix):
                                                # スレッドを完全に削除
                                                await thread.delete(reason="非公開投稿がなくなりました")
                                                logger.info(f"プライベートスレッド {thread.name} を削除しました")
                                                break
                                except Exception as e:
                                    logger.error(f"プライベートスレッドの削除中にエラーが発生しました: {e}")
                        except Exception as e:
                            logger.error(f"非公開投稿処理中にエラーが発生しました: {e}")
                    
                    await interaction.followup.send(
                        "✅ 投稿を削除しました。",
                        ephemeral=True
                    )
                    
        except Exception as e:
            logger.error(f"削除処理中にエラーが発生しました: {e}", exc_info=True)
            await interaction.followup.send(
                f"❌ 削除中にエラーが発生しました: {e}",
                ephemeral=True
            )

async def setup(bot: commands.Bot):
    await bot.add_cog(Delete(bot))
