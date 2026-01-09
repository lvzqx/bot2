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
                    # すべてのメッセージ参照をチェック（パフォーマンス対策）
                    cursor.execute("""
                        SELECT COUNT(*) FROM message_references
                    """)
                    total_refs = cursor.fetchone()[0]
                    
                    # 大量データの場合は警告
                    if total_refs > 1000:
                        await interaction.followup.send(
                            f"⚠️ {total_refs}件のメッセージ参照があります。\n"
                            f"処理に時間がかかる場合があります。\n"
                            f"個別に確認する場合は /restore_messages <message_id> check を使用してください。",
                            ephemeral=True
                        )
                        return
                    
                    cursor.execute("""
                        SELECT mr.post_id, mr.message_id, mr.channel_id, t.created_at
                        FROM message_references mr
                        JOIN thoughts t ON mr.post_id = t.id
                        ORDER BY t.created_at DESC
                        LIMIT 500
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
                        placeholders = ','.join(['?'] * len(invalid_post_ids))
                        cursor.execute(f"""
                            DELETE FROM message_references 
                            WHERE post_id IN ({placeholders})
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

    @app_commands.command(name="check_database", description="データベースの整合性をチェックします")
    @app_commands.default_permissions(administrator=True)
    @app_commands.checks.has_permissions(administrator=True)
    async def check_database(self, interaction: discord.Interaction):
        """データベースの整合性をチェックします"""
        try:
            await interaction.response.defer(ephemeral=True)
            
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                
                # データベースの基本情報を取得
                cursor.execute('SELECT COUNT(*) FROM thoughts')
                thoughts_count = cursor.fetchone()[0]
                
                cursor.execute('SELECT COUNT(*) FROM message_references')
                refs_count = cursor.fetchone()[0]
                
                # 孤立したメッセージ参照を検出
                cursor.execute("""
                    SELECT COUNT(*)
                    FROM message_references mr
                    LEFT JOIN thoughts t ON mr.post_id = t.id
                    WHERE t.id IS NULL
                """)
                orphaned_refs_count = cursor.fetchone()[0]
                
                # 参照されていない投稿を検出
                cursor.execute("""
                    SELECT COUNT(*)
                    FROM thoughts t
                    LEFT JOIN message_references mr ON t.id = mr.post_id
                    WHERE mr.post_id IS NULL
                """)
                orphaned_posts_count = cursor.fetchone()[0]
                
                # データベースファイルのサイズを取得
                db_size = os.path.getsize(self.db_path)
                db_size_mb = db_size / (1024 * 1024)
                
                # 埋め込みを作成
                embed = discord.Embed(
                    title="🔍 データベース整合性チェック",
                    color=discord.Color.blue()
                )
                
                embed.add_field(
                    name="📊 基本情報",
                    value=f"📝 投稿数: {thoughts_count}\n"
                          f"🔗 メッセージ参照数: {refs_count}\n"
                          f"💾 データベースサイズ: {db_size_mb:.2f} MB",
                    inline=False
                )
                
                # 問題の有無をチェック
                issues = []
                if orphaned_refs_count > 0:
                    issues.append(f"🗑️ 孤立したメッセージ参照: {orphaned_refs_count}件")
                
                if orphaned_posts_count > 0:
                    issues.append(f"📝 参照されていない投稿: {orphaned_posts_count}件")
                
                if issues:
                    embed.add_field(
                        name="⚠️ 検出された問題",
                        value="\n".join(issues),
                        inline=False
                    )
                    embed.color = discord.Color.orange()
                    
                    embed.add_field(
                        name="🔧 推奨されるアクション",
                        value="\n".join([
                            "• /cleanup_orphaned - 孤立したデータをクリーンアップ",
                            "• /backup_database - 現在の状態をバックアップ",
                            "• /restore_messages - メッセージ参照を整理"
                        ]),
                        inline=False
                    )
                else:
                    embed.add_field(
                        name="✅ 状態",
                        value="データベースは健全です。問題は検出されませんでした。",
                        inline=False
                    )
                    embed.color = discord.Color.green()
                
                await interaction.followup.send(embed=embed, ephemeral=True)
                
                logger.info(f"データベース整合性チェック完了: 投稿{thoughts_count}件, 参照{refs_count}件, 問題{len(issues)}件")
                
        except Exception as e:
            logger.error(f"データベースチェック中にエラーが発生しました: {e}", exc_info=True)
            await interaction.followup.send(
                f"❌ エラーが発生しました: {e}",
                ephemeral=True
            )

    @app_commands.command(name="cleanup_orphaned", description="孤立した参照をクリーンアップします")
    @app_commands.default_permissions(administrator=True)
    @app_commands.checks.has_permissions(administrator=True)
    async def cleanup_orphaned(self, interaction: discord.Interaction):
        """孤立した参照をクリーンアップします"""
        try:
            await interaction.response.defer(ephemeral=True)
            
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                
                # 孤立したメッセージ参照を検出
                cursor.execute("""
                    SELECT mr.post_id, mr.message_id, mr.channel_id
                    FROM message_references mr
                    LEFT JOIN thoughts t ON mr.post_id = t.id
                    WHERE t.id IS NULL
                """)
                orphaned_refs = cursor.fetchall()
                
                # 参照されていない投稿を検出
                cursor.execute("""
                    SELECT t.id, t.content, t.created_at
                    FROM thoughts t
                    LEFT JOIN message_references mr ON t.id = mr.post_id
                    WHERE mr.post_id IS NULL
                """)
                orphaned_posts = cursor.fetchall()
                
                cleanup_count = 0
                
                # 孤立したメッセージ参照を削除
                if orphaned_refs:
                    orphaned_post_ids = [ref[0] for ref in orphaned_refs]
                    placeholders = ','.join(['?'] * len(orphaned_post_ids))
                    cursor.execute(f"""
                        DELETE FROM message_references 
                        WHERE post_id IN ({placeholders})
                    """, orphaned_post_ids)
                    cleanup_count += len(orphaned_refs)
                    
                    await interaction.followup.send(
                        f"🗑️ {len(orphaned_refs)}件の孤立したメッセージ参照を削除しました。\n"
                        f"📊 削除された参照: {', '.join([str(ref[0]) for ref in orphaned_refs[:5]])}{'...' if len(orphaned_refs) > 5 else ''}",
                        ephemeral=True
                    )
                
                # 参照されていない投稿を削除
                if orphaned_posts:
                    orphaned_post_ids = [post[0] for post in orphaned_posts]
                    placeholders = ','.join(['?'] * len(orphaned_post_ids))
                    cursor.execute(f"""
                        DELETE FROM thoughts 
                        WHERE id IN ({placeholders})
                    """, orphaned_post_ids)
                    cleanup_count += len(orphaned_posts)
                    
                    await interaction.followup.send(
                        f"🗑️ {len(orphaned_posts)}件の参照されていない投稿を削除しました。\n"
                        f"📝 削除された投稿ID: {', '.join([str(post[0]) for post in orphaned_posts[:5]])}{'...' if len(orphaned_posts) > 5 else ''}",
                        ephemeral=True
                    )
                
                if not orphaned_refs and not orphaned_posts:
                    await interaction.followup.send(
                        "✅ 孤立したデータはありません。データベースはクリーンです。",
                        ephemeral=True
                    )
                
                if cleanup_count > 0:
                    conn.commit()
                    await interaction.followup.send(
                        f"✅ クリーンアップが完了しました。\n"
                        f"🧹 合計 {cleanup_count}件の不要なデータを削除しました。",
                        ephemeral=True
                    )
                    
                    logger.info(f"クリーンアップ完了: {cleanup_count}件の不要なデータを削除")
                
        except Exception as e:
            logger.error(f"クリーンアップ中にエラーが発生しました: {e}", exc_info=True)
            await interaction.followup.send(
                f"❌ エラーが発生しました: {e}",
                ephemeral=True
            )

async def setup(bot):
    await bot.add_cog(MessageRestore(bot))