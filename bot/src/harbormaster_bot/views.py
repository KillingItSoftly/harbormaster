from __future__ import annotations

import discord


class ConfirmView(discord.ui.View):
    """Two-button confirm/cancel prompt. Only the original invoker can act."""

    def __init__(self, user_id: int, timeout: float = 30) -> None:
        super().__init__(timeout=timeout)
        self.user_id = user_id
        self.confirmed = False

    @discord.ui.button(label="Confirm", style=discord.ButtonStyle.danger)
    async def _confirm(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("Not your prompt.", ephemeral=True)
            return
        self.confirmed = True
        await interaction.response.defer()
        self.stop()

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def _cancel(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("Not your prompt.", ephemeral=True)
            return
        await interaction.response.defer()
        self.stop()
