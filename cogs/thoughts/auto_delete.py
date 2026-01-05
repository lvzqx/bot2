from __future__ import annotations

import asyncio
import logging
import re
from typing import List, Optional, Pattern, Match, Any, TYPE_CHECKING

import discord
from discord import Message, TextChannel, DMChannel, Embed, NotFound, Forbidden, HTTPException
from discord.ext import commands

# 型チェック用のインポート
if TYPE_CHECKING:
    from bot import Bot

# ロガーの設定
logger = logging.getLogger(__name__)

# 削除対象のキーワード（必要に応じて追加・変更可能）
DEFAULT_KEYWORDS = [
    "削除して",
    "消して",
    "delete",
    "消えろ",
    "消えなさい"
]

class AutoDelete(commands.Cog):
    """自動削除機能を提供するCog。
    
    特定のキーワードを含むメッセージに反応して、指定されたメッセージを削除します。
    また、埋め込みメッセージの場合はデータベースからも削除します。
    """
    
    def __init__(self, bot: commands.Bot) -> None:
        """AutoDelete Cogを初期化します。
        
        Args:
            bot: Discord Bot インスタンス
        """
        self.bot: commands.Bot = bot
        self.keywords: List[str] = DEFAULT_KEYWORDS
        self.message_id_pattern: Pattern[str] = re.compile(r'\b(\d{17,20})\b')
        self.delete_delay: float = 5.0  # 確認メッセージの表示時間（秒）
        
        logger.info("AutoDelete cog が初期化されました")

    async def _extract_post_id(self, embed: Embed) -> Optional[int]:
        """埋め込みメッセージから投稿IDを抽出します。
        
        Args:
            embed: 埋め込みメッセージオブジェクト
            
        Returns:
            Optional[int]: 抽出された投稿ID、見つからない場合はNone
        """
        try:
            if embed.footer and 'ID:' in embed.footer.text:
                return int(embed.footer.text.split('ID:')[-1].strip())
        except (ValueError, AttributeError, IndexError) as e:
            logger.warning(f"投稿IDの抽出に失敗しました: {e}")
        return None
    
    async def _delete_from_database(self, post_id: int, user_id: int) -> bool:
        """データベースから投稿を削除します。
        
        Args:
            post_id: 削除する投稿のID
            user_id: 投稿者のユーザーID
            
        Returns:
            bool: 削除に成功した場合はTrue、失敗した場合はFalse
        """
        try:
            # Post コグを取得
            post_cog = self.bot.get_cog('Post')
            if not post_cog or not hasattr(post_cog, 'db'):
                logger.warning("Post コグが見つからないか、データベースにアクセスできません")
                return False
                
            # データベースから削除
            with post_cog._get_db_connection() as conn:
                with conn:
                    with post_cog._get_cursor(conn) as cursor:
                        # ユーザーが所有する投稿のみ削除
                        cursor.execute('''
                            DELETE FROM thoughts 
                            WHERE id = ? AND user_id = ?
                        ''', (post_id, user_id))
                        
                        # メッセージ参照も削除
                        cursor.execute('''
                            DELETE FROM message_references 
                            WHERE post_id = ?
                        ''', (post_id,))
                        
                        return cursor.rowcount > 0
                        
        except Exception as e:
            logger.error(f"データベースからの削除中にエラーが発生しました: {e}", exc_info=True)
            return False
    
    async def _delete_message_with_confirmation(
        self, 
        channel: TextChannel, 
        message: Message, 
        target_message: Message
    ) -> None:
        """メッセージを削除し、確認メッセージを表示します。
        
        Args:
            channel: メッセージが存在するチャンネル
            message: 削除対象のメッセージ
            target_message: 削除をリクエストしたメッセージ
        """
        try:
            # メッセージを削除
            await message.delete()
            
            # 確認メッセージを送信
            confirm_msg = await channel.send(
                "✅ メッセージを削除しました", 
                delete_after=self.delete_delay
            )
            
            # リクエストメッセージを削除
            try:
                await target_message.delete()
            except (NotFound, Forbidden, HTTPException) as e:
                logger.warning(f"リクエストメッセージの削除に失敗しました: {e}")
            
            # 確認メッセージを指定時間表示
            await asyncio.sleep(self.delete_delay)
            
        except (NotFound, Forbidden, HTTPException) as e:
            logger.error(f"メッセージの削除に失敗しました: {e}", exc_info=True)
            raise
    
    @commands.Cog.listener()
    async def on_message(self, message: Message) -> None:
        """メッセージを受信したときに呼び出されます。
        
        特定のキーワードを含むメッセージに反応し、指定されたメッセージを削除します。
        
        Args:
            message: 受信したメッセージ
        """
        # ボット自身のメッセージまたはDMは無視
        if message.author == self.bot.user or isinstance(message.channel, DMChannel):
            return
        
        # メッセージ内容を取得
        content = message.content.strip()
        
        # キーワードが含まれているかチェック
        if not any(keyword in content for keyword in self.keywords):
            return
        
        # メッセージIDを抽出
        match = self.message_id_pattern.search(content)
        if not match:
            return
        
        message_id = int(match.group(1))
        
        try:
            # メッセージを検索
            target_msg = None
            async for msg in message.channel.history(limit=100):
                if msg.id == message_id and msg.author == self.bot.user:
                    target_msg = msg
                    break
            
            if not target_msg:
                # メッセージが見つからない場合
                not_found_msg = await message.channel.send(
                    "❌ 削除対象のメッセージが見つかりませんでした。",
                    delete_after=self.delete_delay
                )
                await asyncio.sleep(self.delete_delay)
                
                try:
                    await message.delete()
                    await not_found_msg.delete()
                except (NotFound, Forbidden, HTTPException) as e:
                    logger.warning(f"メッセージの削除に失敗しました: {e}")
                return
            
            # 埋め込みメッセージの場合はデータベースからも削除
            if target_msg.embeds:
                for embed in target_msg.embeds:
                    post_id = await self._extract_post_id(embed)
                    if post_id:
                        await self._delete_from_database(post_id, message.author.id)
            
            # メッセージを削除
            await self._delete_message_with_confirmation(
                message.channel,
                target_msg,
                message
            )
            
        except Exception as e:
            logger.error(f"メッセージ削除中にエラーが発生しました: {e}", exc_info=True)
            
            try:
                error_msg = await message.channel.send(
                    "⚠️ エラーが発生しました。もう一度お試しください。",
                    delete_after=self.delete_delay
                )
                await asyncio.sleep(self.delete_delay)
                await message.delete()
                await error_msg.delete()
            except Exception as e:
                logger.error(f"エラーメッセージの送信中にエラーが発生しました: {e}", exc_info=True)

async def setup(bot):
    await bot.add_cog(AutoDelete(bot))
