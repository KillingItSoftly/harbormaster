from __future__ import annotations

import logging
from datetime import datetime, timezone

import discord
from discord.ext import commands

log = logging.getLogger("harbormaster.audit")


async def audit(
    bot: commands.Bot,
    interaction: discord.Interaction,
    action: str,
    *,
    success: bool = True,
    detail: str = "",
) -> None:
    """Post a one-line audit entry to the configured audit channel.

    No-op if no audit_channel_id is configured. Failures here never
    propagate — auditing must not break the user-facing command.
    """
    cfg = bot.config  # type: ignore[attr-defined]
    cid = cfg.discord.audit_channel_id
    if cid is None:
        return
    chan = bot.get_channel(cid)
    if chan is None:
        return
    color = 0x2ECC71 if success else 0xE74C3C
    embed = discord.Embed(
        title=action,
        color=color,
        timestamp=datetime.now(timezone.utc),
    )
    embed.add_field(
        name="User",
        value=f"{interaction.user} (`{interaction.user.id}`)",
        inline=False,
    )
    if interaction.guild_id is not None:
        embed.add_field(name="Guild", value=str(interaction.guild_id), inline=True)
    embed.add_field(name="Status", value="success" if success else "failed", inline=True)
    if detail:
        embed.add_field(name="Detail", value=detail[:1024], inline=False)
    try:
        await chan.send(embed=embed)
    except Exception:  # noqa: BLE001
        log.exception("Failed to write audit entry: %s", action)
