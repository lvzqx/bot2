import discord
from discord import app_commands
from discord.ext import commands
import sqlite3
import traceback
from typing import Tuple
import re

class Delete(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        print("Delete cog が読み込まれました")
        
    def get_db_connection(self):
        """データベース接続を取得する"""
        if not hasattr(self.bot, 'db'):
            self.bot.db = sqlite3.connect('thoughts.db')
            self.bot.db.row_factory = sqlite3.Row
        return self.bot.db

    async def delete_message_by_id(self, interaction: discord.Interaction, message_id: int) -> Tuple[bool, str]:
        """メッセージIDで削除する"""
        try:
            # メッセージを取得
            try:
                message = await interaction.channel.fetch_message(message_id)
            except discord.NotFound:
                return False, "❌ メッセージが見つかりませんでした"
            except discord.Forbidden:
                return False, "❌ メッセージを削除する権限がありません"
                
            # ボットのメッセージか確認
            if message.author != self.bot.user:
                return False, "❌ ボットのメッセージのみ削除できます"
                
            # 埋め込みメッセージか確認
            if not message.embeds or not message.embeds[0].footer:
                return False, "❌ 投稿メッセージを削除できません"
                
            # フッターから投稿IDを取得
            footer_text = message.embeds[0].footer.text
            if not footer_text:
                return False, "❌ 投稿情報が見つかりません"
                
            # 投稿IDを抽出
            match = re.search(r'ID: (\d+)', footer_text)
            if not match:
                return False, "❌ 投稿IDを取得できませんでした"
                
            post_id = int(match.group(1))
            user_id = interaction.user.id
            
            # データベースから削除
            db = self.get_db_connection()
            cursor = db.cursor()
            
            try:
                cursor.execute('BEGIN TRANSACTION')
                
                # 投稿の存在確認と所有者チェック
                cursor.execute('''
                    SELECT id, user_id FROM thoughts 
                    WHERE id = ?
                ''', (post_id,))
                
                post = cursor.fetchone()
                if not post:
                    return False, "❌ 投稿が見つかりません"
                    
                # 投稿の所有者とコマンド実行者が一致するか確認
                if post['user_id'] != user_id:
                    return False, "❌ 自分の投稿のみ削除できます"
                
                # 投稿を削除
                cursor.execute('''
                    DELETE FROM thoughts 
                    WHERE id = ? AND user_id = ?
                ''', (post_id, user_id))
                
                # メッセージ参照を削除
                cursor.execute('''
                    DELETE FROM message_references 
                    WHERE post_id = ?
                ''', (post_id,))
                
                # 変更をコミット
                db.commit()
                
                # メッセージを削除
                await message.delete()
                return True, f"✅ 投稿 (ID: {post_id}) を削除しました"
                
            except Exception as e:
                db.rollback()
                raise
                
        except Exception as e:
            error_msg = f"❌ エラーが発生しました: {type(e).__name__}: {str(e)}"
            print(f"[ERROR] {error_msg}")
            traceback.print_exc()
            return False, error_msg

    @app_commands.command(name="delete", description="メッセージIDまたはメッセージリンクで投稿を削除します")
    @app_commands.describe(message_reference="削除するメッセージのIDまたはメッセージリンク")
    async def delete(self, interaction: discord.Interaction, message_reference: str):
        """メッセージIDまたはメッセージリンクで投稿を削除します（DMでも使用可能）"""
        
        # DMの場合は通常のメッセージとして処理
        if isinstance(interaction.channel, discord.DMChannel):
            success, result = await self.delete_message_by_id(
                int(message_reference) if message_reference.isdigit() else message_reference,
                interaction.user.id,
                interaction.channel
            )
            await interaction.response.send_message(result, ephemeral=True)
            return
            
        await interaction.response.defer(ephemeral=True)
        
        # メッセージリンクからメッセージIDを抽出
        if 'discord.com/channels/' in message_reference:
            try:
                # メッセージIDを抽出
                message_id = int(message_reference.split('/')[-1])
            except (ValueError, IndexError):
                await interaction.followup.send("❌ 無効なメッセージリンクです。", ephemeral=True)
                return
        else:
            # メッセージIDとして処理
            try:
                message_id = int(message_reference)
            except ValueError:
                await interaction.followup.send("❌ 無効なメッセージIDです。数値またはメッセージリンクを指定してください。", ephemeral=True)
                return
        
        # メッセージIDで削除を試みる
        success, result = await self.delete_message_by_id(interaction, message_id)
        await interaction.followup.send(result, ephemeral=True)

async def setup(bot):
    await bot.add_cog(Delete(bot))
