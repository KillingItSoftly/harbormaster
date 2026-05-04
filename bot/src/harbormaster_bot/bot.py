from __future__ import annotations

import logging
import os
import traceback

import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv

from .audit import audit
from .azure_client import AzureClient
from .config import BotConfig, load_config
from .state import RuntimeState

log = logging.getLogger("harbormaster")


class HarbormasterBot(commands.Bot):
    config: BotConfig
    azure: AzureClient
    state: RuntimeState

    def __init__(self) -> None:
        intents = discord.Intents.default()  # no privileged intents needed
        # command_prefix is unused (slash-commands only). An empty iterable
        # tells discord.py not to parse messages for prefixes, which silences
        # the "message_content intent is missing" warning.
        super().__init__(command_prefix=(), intents=intents, help_command=None)
        self.config = load_config()
        self.azure = AzureClient(self.config)
        self.state = RuntimeState()

    async def setup_hook(self) -> None:
        for cog in (
            "server",
            "backup",
            "snapshot",
            "update",
            "health",
            "maintenance",
            "restore",
            "players",
            "help",
        ):
            await self.load_extension(f"harbormaster_bot.cogs.{cog}")

        # Global slash-command error handler. Replaces discord.py's default
        # behavior of swallowing the exception with only a stderr trace,
        # which would leave Discord users staring at "interaction failed".
        self.tree.on_error = self._on_app_command_error

        guild = discord.Object(id=self.config.discord.guild_id)
        self.tree.copy_global_to(guild=guild)
        synced = await self.tree.sync(guild=guild)
        log.info("Synced %d slash commands to guild %s", len(synced), guild.id)

    async def _on_app_command_error(
        self,
        interaction: discord.Interaction,
        error: app_commands.AppCommandError,
    ) -> None:
        # Permission/cooldown checks already replied to the interaction;
        # nothing useful to add here.
        if isinstance(error, app_commands.CheckFailure):
            return

        # Log the full trace for ops review.
        cmd = interaction.command.qualified_name if interaction.command else "?"
        log.exception(
            "Unhandled error in /%s by %s: %s",
            cmd, interaction.user, error,
        )

        # Reply to the user without leaking traceback contents.
        msg = (
            ":x: Something went wrong handling that command. "
            "An admin has been notified — please try again later."
        )
        try:
            if interaction.response.is_done():
                await interaction.followup.send(msg, ephemeral=True)
            else:
                await interaction.response.send_message(msg, ephemeral=True)
        except discord.HTTPException:
            pass

        # Audit the failure with a short trace so admins can investigate.
        try:
            tb = "".join(
                traceback.format_exception_only(type(error), error)
            ).strip()
            await audit(
                self,
                interaction,
                f"command error: /{cmd}",
                success=False,
                detail=tb[-1024:],
            )
        except Exception:  # noqa: BLE001
            log.exception("audit() failed inside global error handler")

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
