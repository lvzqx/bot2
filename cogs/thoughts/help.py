"""ヘルプコマンドを提供するCog"""

import discord
from discord import app_commands
from discord.ext import commands
from typing import Optional

class Help(commands.Cog):
    """ヘルプコマンドを提供するCog"""
    
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        
    @app_commands.command(name="help", description="利用可能なコマンドを表示します")
    async def help_command(self, interaction: discord.Interaction):
        """利用可能なコマンドを表示します"""
        try:
            # 埋め込みメッセージを作成
            embed = discord.Embed(
                title="🤖 利用可能なコマンド",
                description="以下のコマンドが利用できます。",
                color=discord.Color.blue()
            )
            
            # コマンド一覧を追加
            commands_list = []
            for cmd in self.bot.tree.get_commands():
                # コマンドがグループの場合はサブコマンドも表示
                if hasattr(cmd, 'commands'):
                    sub_commands = [f"`/{cmd.name} {sub.name}` - {sub.description}" 
                                  for sub in cmd.commands]
                    commands_list.append("\n".join(sub_commands))
                else:
                    commands_list.append(f"`/{cmd.name}` - {cmd.description}")
            
            if commands_list:
                embed.add_field(
                    name="📝 コマンド一覧",
                    value="\n".join(commands_list),
                    inline=False
                )
            
            # 使い方の例を追加
            embed.add_field(
                name="💡 使い方の例",
                value="""
                `/post` - 新しい投稿を作成します
                `/delete 1234567890` - 指定したIDの投稿を削除します
                `/search キーワード` - 投稿を検索します
                `/list` - 投稿の一覧を表示します
                `/edit 1234567890` - 指定したIDの投稿を編集します
                """,
                inline=False
            )
            
            # フッターを追加
            embed.set_footer(text="※ 各コマンドの詳細はスラッシュ(/)を入力して確認できます")
            
            await interaction.response.send_message(embed=embed, ephemeral=True)
            
        except Exception as e:
            self.bot.logger.error(f'Help command error: {e}', exc_info=True)
            if not interaction.response.is_done():
                await interaction.response.send_message(
                    "ヘルプの表示中にエラーが発生しました。", 
                    ephemeral=True
                )

async def setup(bot: commands.Bot) -> None:
    """Cogをボットに追加"""
    await bot.add_cog(Help(bot))
