import sqlite3
import discord
from discord.ext import commands
from discord import app_commands
import logging
import os
from dotenv import load_dotenv
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

class MessageRestore(commands.Cog):
    """メッセージ復元用Cog"""
    
    def __init__(self, bot):
        self.bot = bot
        self.db_path = os.getenv('DB_PATH', 'thoughts.db')
    
    @app_commands.command(name="restore_messages", description="古いメッセージ参照を整理します")
    @app_commands.default_permissions(administrator=True)
    async def restore_messages(self, interaction: discord.Interaction, message_id: Optional[str] = None):
        """古いメッセージ参照を整理します"""
        try:
            await interaction.response.defer(ephemeral=True)
            
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                
                if message_id:
                    # 特定のメッセージIDをチェック
                    cursor.execute("""
                        SELECT mr.post_id, mr.message_id, mr.channel_id, t.created_at
                        FROM message_references mr
                        JOIN thoughts t ON mr.post_id = t.id
                        WHERE CAST(mr.message_id AS TEXT) = ?
                    """, (str(message_id),))
                    
                    ref = cursor.fetchone()
                    
                    if not ref:
                        await interaction.followup.send(
                            f"❌ メッセージID {message_id} の参照が見つかりません。",
                            ephemeral=True
                        )
                        return
                    
                    post_id, msg_id, channel_id, created_at = ref
                    
                    try:
                        # チャンネルを取得してメッセージが存在するか確認
                        channel = await interaction.guild.fetch_channel(int(channel_id))
                        await channel.fetch_message(int(msg_id))
                        await interaction.followup.send(
                            f"✅ メッセージID {message_id} は有効です。",
                            ephemeral=True
                        )
                    except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                        # メッセージが見つからない場合、参照を削除
                        cursor.execute("""
                            DELETE FROM message_references 
                            WHERE post_id = ?
                        """, (post_id,))
                        
                        conn.commit()
                        
                        await interaction.followup.send(
                            f"✅ メッセージID {message_id} の無効な参照を削除しました。\n"
                            f"投稿ID: {post_id}, チャンネルID: {channel_id}",
                            ephemeral=True
                        )
                    except Exception as e:
                        logger.warning(f"メッセージ確認中にエラー: {e}")
                        await interaction.followup.send(
                            f"⚠️ メッセージ確認中にエラーが発生しました: {e}",
                            ephemeral=True
                        )
                else:
                    # すべてのメッセージ参照をチェック
                    cursor.execute("""
                        SELECT mr.post_id, mr.message_id, mr.channel_id, t.created_at
                        FROM message_references mr
                        JOIN thoughts t ON mr.post_id = t.id
                        ORDER BY t.created_at DESC
                    """)
                    
                    all_refs = cursor.fetchall()
                    
                    if not all_refs:
                        await interaction.followup.send("✅ メッセージ参照はありません。")
                        return
                    
                    # 無効なメッセージ参照をチェック
                    invalid_refs = []
                    valid_refs = []
                    
                    for ref in all_refs:
                        post_id, message_id, channel_id, created_at = ref
                        
                        try:
                            # チャンネルを取得してメッセージが存在するか確認
                            channel = await interaction.guild.fetch_channel(int(channel_id))
                            await channel.fetch_message(int(message_id))
                            valid_refs.append(ref)
                        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                            # メッセージが見つからないかアクセスできない
                            invalid_refs.append(ref)
                        except Exception as e:
                            logger.warning(f"メッセージ確認中にエラー: {e}")
                            invalid_refs.append(ref)
                    
                    # 無効な参照を削除
                    if invalid_refs:
                        invalid_post_ids = [ref[0] for ref in invalid_refs]
                        cursor.execute("""
                            DELETE FROM message_references 
                            WHERE post_id IN ({','.join(['?'] * len(invalid_post_ids))})
                        """, invalid_post_ids)
                        
                        conn.commit()
                        
                        await interaction.followup.send(
                            f"✅ {len(invalid_refs)}件の無効なメッセージ参照を削除しました。\n"
                            f"📊 有効な参照: {len(valid_refs)}件\n"
                            f"🗑️ 削除された参照: {len(invalid_refs)}件",
                            ephemeral=True
                        )
                        
                        # 詳細を表示（最大10件）
                        if len(invalid_refs) <= 10:
                            details = "\n".join([f"• 投稿ID: {ref[0]} (チャンネル: {ref[2]})" for ref in invalid_refs[:10]])
                            await interaction.followup.send(f"削除された参照:\n{details}", ephemeral=True)
                    else:
                        await interaction.followup.send(
                            f"✅ すべてのメッセージ参照は有効です。（{len(valid_refs)}件）",
                            ephemeral=True
                        )
                
        except Exception as e:
            logger.error(f"メッセージ整理中にエラーが発生しました: {e}", exc_info=True)
            await interaction.followup.send(
                f"❌ エラーが発生しました: {e}",
                ephemeral=True
            )

async def setup(bot):
    await bot.add_cog(MessageRestore(bot))