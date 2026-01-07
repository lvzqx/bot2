import sqlite3
import discord
from discord.ext import commands
from discord import app_commands
import logging
import os
from dotenv import load_dotenv
from datetime import datetime, timedelta
from typing import Optional

logger = logging.getLogger(__name__)

class MessageRestore(commands.Cog):
    """メッセージ復元用Cog"""
    
    def __init__(self, bot):
        self.bot = bot
        self.db_path = os.getenv('DB_PATH', 'thoughts.db')
    
    @app_commands.command(name="restore_messages", description="古いメッセージ参照を整理します")
    @app_commands.default_permissions(administrator=True)
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.describe(
        message_id="対象のメッセージID（省略可）",
        action="アクション（check/delete/resend、省略可）"
    )
    async def restore_messages(self, interaction: discord.Interaction, message_id: Optional[str] = None, action: Optional[str] = None):
        """古いメッセージ参照を整理します"""
        try:
            await interaction.response.defer(ephemeral=True)
            
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                
                if message_id and action:
                    # 特定のメッセージIDをチェック
                    cursor.execute("""
                        SELECT mr.post_id, mr.message_id, mr.channel_id, t.content, t.category, t.is_anonymous, t.is_private, t.user_id
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
                    
                    post_id, msg_id, channel_id, content, category, is_anonymous, is_private, user_id = ref
                    
                    if action == "check":
                        try:
                            # チャンネルを取得してメッセージが存在するか確認
                            channel = await interaction.guild.fetch_channel(int(channel_id))
                            message = await channel.fetch_message(int(msg_id))
                            await interaction.followup.send(
                                f"✅ メッセージID {message_id} は有効です。\n"
                                f"📝 内容: {content[:50]}{'...' if len(content) > 50 else ''}\n"
                                f"📁 チャンネル: {channel.name}\n"
                                f"🕐 作成時刻: {message.created_at.strftime('%Y-%m-%d %H:%M:%S')}",
                                ephemeral=True
                            )
                        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                            # メッセージが見つからない場合
                            await interaction.followup.send(
                                f"❌ メッセージID {message_id} は無効です。\n"
                                f"📝 投稿内容: {content[:100]}{'...' if len(content) > 100 else ''}\n"
                                f"🗑️ 参照を削除するには: /restore_messages {message_id} delete",
                                ephemeral=True
                            )
                        except Exception as e:
                            logger.warning(f"メッセージ確認中にエラー: {e}")
                            await interaction.followup.send(
                                f"⚠️ メッセージ確認中にエラーが発生しました: {e}",
                                ephemeral=True
                            )
                    
                    elif action == "delete":
                        # 参照を削除
                        cursor.execute("""
                            DELETE FROM message_references 
                            WHERE post_id = ?
                        """, (post_id,))
                        
                        conn.commit()
                        
                        await interaction.followup.send(
                            f"✅ メッセージID {message_id} の参照を削除しました。\n"
                            f"📝 投稿内容: {content[:100]}{'...' if len(content) > 100 else ''}\n"
                            f"🗑️ 投稿ID: {post_id}",
                            ephemeral=True
                        )
                        
                        logger.info(f"メッセージ参照を削除しました: {message_id}")
                    
                    elif action == "resend":
                        # メッセージを再送信
                        try:
                            # 投稿者情報を取得
                            member = await interaction.guild.fetch_member(user_id)
                            display_name = member.display_name if member else f"ユーザー{user_id}"
                            
                            # 埋め込みメッセージを作成
                            embed = discord.Embed(
                                description=content,
                                color=discord.Color.blue()
                            )
                            
                            # 表示名を設定
                            if is_anonymous:
                                embed.set_author(name='匿名')
                            else:
                                embed.set_author(
                                    name=display_name,
                                    icon_url=member.display_avatar.url if member else None
                                )
                            
                            # フッターにカテゴリーと投稿IDを表示
                            embed.set_footer(text=f'カテゴリー: {category or "未設定"} | ID: {post_id}')
                            
                            # チャンネルに送信
                            channel = await interaction.guild.fetch_channel(int(channel_id))
                            new_message = await channel.send(embed=embed)
                            
                            # 新しいメッセージ参照を更新
                            cursor.execute("""
                                UPDATE message_references 
                                SET message_id = ?
                                WHERE post_id = ?
                            """, (str(new_message.id), post_id))
                            
                            conn.commit()
                            
                            await interaction.followup.send(
                                f"✅ メッセージID {message_id} を再送信しました。\n"
                                f"🔗 新しいメッセージID: {new_message.id}\n"
                                f"📁 チャンネル: {channel.name}",
                                ephemeral=True
                            )
                            
                            logger.info(f"メッセージを再送信しました: {message_id} -> {new_message.id}")
                            
                        except Exception as e:
                            logger.error(f"メッセージ再送信中にエラーが発生しました: {e}", exc_info=True)
                            await interaction.followup.send(
                                f"❌ メッセージの再送信に失敗しました: {e}",
                                ephemeral=True
                            )
                    else:
                        await interaction.followup.send(
                            f"⚠️ 不正なアクションです。使用可能なアクション: check, delete, resend",
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
                            f"🗑️ 削除された参照: {len(invalid_refs)}件\n\n"
                            f"💡 個別に操作するには:\n"
                            f"/restore_messages <message_id> check - メッセージを確認\n"
                            f"/restore_messages <message_id> delete - 参照を削除\n"
                            f"/restore_messages <message_id> resend - メッセージを再送信",
                            ephemeral=True
                        )
                        
                        # 詳細を表示（最大10件）
                        if len(invalid_refs) <= 10:
                            details = "\n".join([f"• 投稿ID: {ref[0]} (チャンネル: {ref[2]})" for ref in invalid_refs[:10]])
                            await interaction.followup.send(f"削除された参照:\n{details}", ephemeral=True)
                    else:
                        await interaction.followup.send(
                            f"✅ すべてのメッセージ参照は有効です。（{len(valid_refs)}件）\n\n"
                            f"💡 個別に操作するには:\n"
                            f"/restore_messages <message_id> check - メッセージを確認\n"
                            f"/restore_messages <message_id> delete - 参照を削除\n"
                            f"/restore_messages <message_id> resend - メッセージを再送信",
                            ephemeral=True
                        )
                
        except Exception as e:
            logger.error(f"メッセージ整理中にエラーが発生しました: {e}", exc_info=True)
            await interaction.followup.send(
                f"❌ エラーが発生しました: {e}",
                ephemeral=True
            )

    @app_commands.command(name="backup_database", description="データベースをバックアップします")
    @app_commands.default_permissions(administrator=True)
    @app_commands.checks.has_permissions(administrator=True)
    async def backup_database(self, interaction: discord.Interaction):
        """データベースをバックアップします"""
        try:
            await interaction.response.defer(ephemeral=True)
            
            # バックアップファイル名を作成
            timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
            backup_path = f"backup/thoughts_backup_{timestamp}.db"
            
            # バックアップディレクトリを作成
            os.makedirs("backup", exist_ok=True)
            
            # データベースをコピー
            with sqlite3.connect(self.db_path) as source:
                with sqlite3.connect(backup_path) as backup:
                    source.backup(backup)
            
            # バックアップ情報を記録
            backup_info = {
                'timestamp': timestamp,
                'size': os.path.getsize(backup_path),
                'original_size': os.path.getsize(self.db_path),
                'readable_time': datetime.now().strftime("%Y年%m月%d日 %H:%M:%S")
            }
            
            await interaction.followup.send(
                f"✅ データベースをバックアップしました。\n"
                f"📁 バックアップファイル: {backup_path}\n"
                f"📊 サイズ: {backup_info['size']} bytes\n"
                f"🕐 作成時刻: {backup_info['readable_time']}",
                ephemeral=True
            )
            
            logger.info(f"データベースをバックアップしました: {backup_path}")
            
        except Exception as e:
            logger.error(f"バックアップ中にエラーが発生しました: {e}", exc_info=True)
            await interaction.followup.send(
                f"❌ バックアップに失敗しました: {e}",
                ephemeral=True
            )

    @app_commands.command(name="list_backups", description="バックアップ一覧を表示します")
    @app_commands.default_permissions(administrator=True)
    @app_commands.checks.has_permissions(administrator=True)
    async def list_backups(self, interaction: discord.Interaction):
        """バックアップ一覧を表示します"""
        try:
            await interaction.response.defer(ephemeral=True)
            
            if not os.path.exists("backup"):
                await interaction.followup.send(
                    "📁 バックアップはありません。",
                    ephemeral=True
                )
                return
            
            # バックアップファイル一覧を取得
            backup_files = []
            for filename in os.listdir("backup"):
                if filename.startswith("thoughts_backup_") and filename.endswith(".db"):
                    filepath = os.path.join("backup", filename)
                    stat = os.stat(filepath)
                    backup_files.append({
                        'filename': filename,
                        'size': stat.st_size,
                        'created': datetime.fromtimestamp(stat.st_ctime)
                    })
            
            if not backup_files:
                await interaction.followup.send(
                    "📁 バックアップはありません。",
                    ephemeral=True
                )
                return
            
            # 新しい順にソート
            backup_files.sort(key=lambda x: x['created'], reverse=True)
            
            # 埋め込みを作成
            embed = discord.Embed(
                title="📁 バックアップ一覧",
                color=discord.Color.blue()
            )
            
            for backup in backup_files[:10]:  # 最大10件表示
                created_str = backup['created'].strftime("%Y-%m-%d %H:%M:%S")
                size_mb = backup['size'] / (1024 * 1024)
                
                embed.add_field(
                    name=f"📄 {backup['filename']}",
                    value=f"作成: {created_str}\nサイズ: {size_mb:.2f} MB",
                    inline=False
                )
            
            if len(backup_files) > 10:
                embed.set_footer(text=f"他 {len(backup_files) - 10}件のバックアップがあります")
            
            await interaction.followup.send(embed=embed, ephemeral=True)
            
        except Exception as e:
            logger.error(f"バックアップ一覧取得中にエラーが発生しました: {e}", exc_info=True)
            await interaction.followup.send(
                f"❌ エラーが発生しました: {e}",
                ephemeral=True
            )

    @app_commands.command(name="restore_backup", description="バックアップから復元します")
    @app_commands.describe(backup_filename="復元するバックアップファイル名")
    @app_commands.default_permissions(administrator=True)
    @app_commands.checks.has_permissions(administrator=True)
    async def restore_backup(self, interaction: discord.Interaction, backup_filename: str):
        """バックアップから復元します"""
        try:
            await interaction.response.defer(ephemeral=True)
            
            backup_path = os.path.join("backup", backup_filename)
            
            if not os.path.exists(backup_path):
                await interaction.followup.send(
                    f"❌ バックアップファイルが見つかりません: {backup_filename}",
                    ephemeral=True
                )
                return
            
            # 現在のデータベースをバックアップ
            current_backup = f"backup/current_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db"
            os.makedirs("backup", exist_ok=True)
            
            with sqlite3.connect(self.db_path) as source:
                with sqlite3.connect(current_backup) as backup:
                    source.backup(backup)
            
            # バックアップから復元
            with sqlite3.connect(backup_path) as backup:
                with sqlite3.connect(self.db_path) as target:
                    backup.backup(target)
            
            await interaction.followup.send(
                f"✅ バックアップから復元しました。\n"
                f"📁 復元元: {backup_filename}\n"
                f"💾 現在のバックアップ: {os.path.basename(current_backup)}",
                ephemeral=True
            )
            
            logger.info(f"バックアップから復元しました: {backup_filename}")
            
        except Exception as e:
            logger.error(f"バックアップ復元中にエラーが発生しました: {e}", exc_info=True)
            await interaction.followup.send(
                f"❌ エラーが発生しました: {e}",
                ephemeral=True
            )

async def setup(bot):
    await bot.add_cog(MessageRestore(bot))