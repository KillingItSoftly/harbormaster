from __future__ import annotations

import asyncio
import time
from contextlib import asynccontextmanager
from typing import AsyncIterator

import discord
from discord.ext import commands

from .azure_client import AzureClient
from .state import BusyError


async def _reply(interaction: discord.Interaction, msg: str) -> None:
    if interaction.response.is_done():
        await interaction.followup.send(msg, ephemeral=True)
    else:
        await interaction.response.send_message(msg, ephemeral=True)


_RUNNABLE = {"running"}
_TRANSITIONAL = {"starting", "stopping", "deallocating"}


async def ensure_vm_running(
    interaction: discord.Interaction, azure: AzureClient
) -> bool:
    """Returns True iff the VM is in `running` state, else replies and returns False."""
    state = await azure.power_state()
    if state in _RUNNABLE:
        return True
    if state in _TRANSITIONAL:
        await _reply(
            interaction,
            f":hourglass: VM is `{state}`. Wait ~30s and try again.",
        )
        return False
    await _reply(
        interaction,
        f":no_entry: VM is `{state}`. Start it first with `/server start`, then retry.",
    )
    return False


async def ensure_service_running(
    interaction: discord.Interaction,
    azure: AzureClient,
    service_name: str,
) -> bool:
    """Verifies the NSSM-wrapped game service is Running. Costs one Run Command call."""
    status = await azure.get_service_status(service_name)
    if status.lower() == "running":
        return True
    await _reply(
        interaction,
        f":no_entry: Service `{service_name}` is `{status}`. "
        "Use `/server restart-service` first.",
    )
    return False


@asynccontextmanager
async def run_slot(
    bot: commands.Bot,
    interaction: discord.Interaction,
    holder: str,
) -> AsyncIterator[bool]:
    """Acquire the global Run-Command lock for `holder`.

    Yields True if acquired and the caller may proceed; yields False if
    another op is in progress (after replying to the interaction).
    Caller pattern:

        async with run_slot(bot, interaction, "update apply") as ok:
            if not ok:
                return
            ...do work...
    """
    state = bot.state  # type: ignore[attr-defined]
    try:
        cm = state.acquire_run(holder)
        await cm.__aenter__()
    except BusyError as exc:
        await _reply(
            interaction,
            f":hourglass: Another operation is in progress (`{exc.holder}`). "
            "Try again in a moment.",
        )
        yield False
        return
    try:
        yield True
    finally:
        await cm.__aexit__(None, None, None)


@asynccontextmanager
async def progress_heartbeat(
    interaction: discord.Interaction,
    base_text: str,
    *,
    interval_sec: int = 45,
) -> AsyncIterator[None]:
    """Background task that edits an ephemeral followup with elapsed time.

    Use as `async with progress_heartbeat(interaction, "Applying update"): ...`
    The heartbeat is cancelled when the block exits.
    """
    started = time.monotonic()
    try:
        sent = await interaction.followup.send(
            f":hourglass: {base_text} (0m elapsed)",
            ephemeral=True,
        )
    except Exception:  # noqa: BLE001
        sent = None

    async def _tick() -> None:
        while True:
            await asyncio.sleep(interval_sec)
            if sent is None:
                return
            elapsed = int((time.monotonic() - started) / 60)
            try:
                await sent.edit(
                    content=f":hourglass: {base_text} ({elapsed}m elapsed)"
                )
            except Exception:  # noqa: BLE001
                return

    task = asyncio.create_task(_tick())
    try:
        yield
    finally:
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):  # noqa: BLE001
            pass
