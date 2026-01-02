import discord
from discord import app_commands, ui
from discord.ext import commands
from .base import BaseCog

class DeleteThoughtModal(ui.Modal, title="つぶやきを削除"):
    thought_id = ui.TextInput(
        label="削除するつぶやきのID",
        placeholder="削除したいつぶやきのIDを入力",
        required=True
    )

    async def on_submit(self, interaction: discord.Interaction):
        try:
            thought_id = int(self.thought_id.value)
            
            # つぶやきの存在確認と権限チェック
            async with interaction.client.db.execute('''
                SELECT id FROM thoughts 
                WHERE id = ? AND user_id = ?
            ''', (thought_id, interaction.user.id)) as cursor:
                thought = await cursor.fetchone()
            
            if not thought:
                await interaction.response.send_message(
                    "つぶやきが見つからないか、削除する権限がありません。",
                    ephemeral=True
                )
                return
            
            # つぶやきを削除
            await interaction.client.db.execute('''
                DELETE FROM thoughts 
                WHERE id = ? AND user_id = ?
            ''', (thought_id, interaction.user.id))
            await interaction.client.db.commit()
            
            await interaction.response.send_message(
                f"✅ つぶやき #{thought_id} を削除しました。",
                ephemeral=True
            )
            
        except ValueError:
            await interaction.response.send_message(
                "正しいつぶやきIDを入力してください。",
                ephemeral=True
            )
        except Exception as e:
            await interaction.response.send_message(
                f"エラーが発生しました: {str(e)}",
                ephemeral=True
            )

class DeleteCog(BaseCog):
    def __init__(self, bot):
        super().__init__(bot)
    
    @app_commands.command(name="delete", description="つぶやきを削除します")
    async def delete_thought(self, interaction: discord.Interaction):
        """つぶやきを削除するモーダルを開きます"""
        if not await self.check_channel(interaction):
            return
            
        try:
            await interaction.response.send_modal(DeleteThoughtModal())
        except Exception as e:
            if not interaction.response.is_done():
                await interaction.response.send_message(
                    f"エラーが発生しました: {str(e)}",
                    ephemeral=True
                )
            else:
                await interaction.followup.send(
                    f"エラーが発生しました: {str(e)}",
                    ephemeral=True
                )
