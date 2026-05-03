from __future__ import annotations

import logging
import os

import discord
from discord.ext import commands
from dotenv import load_dotenv

from .azure_client import AzureClient
from .config import BotConfig, load_config

log = logging.getLogger("harbormaster")


class HarbormasterBot(commands.Bot):
    config: BotConfig
    azure: AzureClient

    def __init__(self) -> None:
        intents = discord.Intents.default()  # no privileged intents needed
        super().__init__(command_prefix="!", intents=intents)
        self.config = load_config()
        self.azure = AzureClient(self.config)

    async def setup_hook(self) -> None:
        for cog in ("server", "backup", "snapshot", "update", "health", "help"):
            await self.load_extension(f"harbormaster_bot.cogs.{cog}")

        guild = discord.Object(id=self.config.discord.guild_id)
        self.tree.copy_global_to(guild=guild)
        synced = await self.tree.sync(guild=guild)
        log.info("Synced %d slash commands to guild %s", len(synced), guild.id)

    async def on_ready(self) -> None:
        log.info("Logged in as %s (game=%s, vm=%s)", self.user, self.config.game.name,
                 self.config.azure.vm_name)

    async def close(self) -> None:
        await self.azure.aclose()
        await super().close()


def main() -> None:
    load_dotenv()
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO"),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    token = os.environ.get("DISCORD_BOT_TOKEN")
    if not token:
        raise SystemExit("DISCORD_BOT_TOKEN env var is required")

    HarbormasterBot().run(token, log_handler=None)
