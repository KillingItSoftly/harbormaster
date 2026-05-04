from __future__ import annotations

import discord


class ConfirmView(discord.ui.View):
    """Two-button confirm/cancel prompt.

    - Only the original invoker can interact.
    - The view stops on the first decision; subsequent button clicks
      (e.g. from a stale message) are rejected with an explanatory message
      so users can't double-fire destructive operations.
    """

    def __init__(self, user_id: int, timeout: float = 30) -> None:
        super().__init__(timeout=timeout)
        self.user_id = user_id
        self.confirmed = False
        self._decided = False

    async def _guard(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message(
                "Not your prompt.", ephemeral=True
            )
            return False
        if self._decided:
            await interaction.response.send_message(
                "This prompt has already been answered.", ephemeral=True
            )
            return False
        return True

    @discord.ui.button(label="Confirm", style=discord.ButtonStyle.danger)
    async def _confirm(
        self, interaction: discord.Interaction, _: discord.ui.Button
    ) -> None:
        if not await self._guard(interaction):
            return
        self._decided = True
        self.confirmed = True
        # Disable buttons so the original prompt visibly reflects the choice.
        for child in self.children:
            if isinstance(child, discord.ui.Button):
                child.disabled = True
        try:
            await interaction.response.edit_message(view=self)
        except discord.HTTPException:
            await interaction.response.defer()
        self.stop()

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def _cancel(
        self, interaction: discord.Interaction, _: discord.ui.Button
    ) -> None:
        if not await self._guard(interaction):
            return
        self._decided = True
        for child in self.children:
            if isinstance(child, discord.ui.Button):
                child.disabled = True
        try:
            await interaction.response.edit_message(view=self)
        except discord.HTTPException:
            await interaction.response.defer()
        self.stop()


def confirm_prompt(action: str, details: list[tuple[str, str]] | None = None) -> str:
    """Render a verbose confirm prompt body.

    `details` is a list of (label, value) shown below the action line so
    users can see exactly what will happen before clicking Confirm.
    """
    lines = [f":warning: **Confirm:** {action}"]
    for label, value in details or []:
        lines.append(f"• **{label}:** {value}")
    lines.append("")
    lines.append("This action cannot be undone via Discord.")
    return "\n".join(lines)
