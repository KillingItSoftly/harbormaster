from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Iterable

from azure.identity.aio import DefaultAzureCredential
from azure.mgmt.compute.aio import ComputeManagementClient
from azure.mgmt.compute.models import RunCommandInput

from .config import BotConfig


@dataclass
class RunResult:
    succeeded: bool
    stdout: str
    stderr: str

    @property
    def best_text(self) -> str:
        return (self.stdout or self.stderr).strip()


class AzureClient:
    """Thin async wrapper around the bits of Azure compute the bot needs."""

    def __init__(self, config: BotConfig) -> None:
        self._config = config
        self._cred = DefaultAzureCredential()
        self._compute = ComputeManagementClient(self._cred, config.azure.subscription_id)

    async def aclose(self) -> None:
        await self._compute.close()
        await self._cred.close()

    # -- VM lifecycle --

    async def power_state(self) -> str:
        view = await self._compute.virtual_machines.instance_view(
            self._config.azure.resource_group, self._config.azure.vm_name
        )
        for s in view.statuses or []:
            if s.code and s.code.startswith("PowerState/"):
                return s.code.split("/", 1)[1]
        return "unknown"

    async def start_vm(self) -> None:
        poller = await self._compute.virtual_machines.begin_start(
            self._config.azure.resource_group, self._config.azure.vm_name
        )
        await poller.result()

    async def deallocate_vm(self) -> None:
        poller = await self._compute.virtual_machines.begin_deallocate(
            self._config.azure.resource_group, self._config.azure.vm_name
        )
        await poller.result()

    # -- Run Command --

    async def run_powershell(
        self, script_lines: Iterable[str], timeout_sec: int = 900
    ) -> RunResult:
        """Execute a PowerShell script on the VM via Azure VM Run Command."""
        body = RunCommandInput(
            command_id="RunPowerShellScript",
            script=list(script_lines),
        )
        poller = await self._compute.virtual_machines.begin_run_command(
            self._config.azure.resource_group, self._config.azure.vm_name, body
        )
        try:
            result = await asyncio.wait_for(poller.result(), timeout=timeout_sec)
        except asyncio.TimeoutError:
            return RunResult(False, "", f"Run command timed out after {timeout_sec}s")

        stdout_parts: list[str] = []
        stderr_parts: list[str] = []
        succeeded = True
        for entry in (result.value or []):
            text = entry.message or ""
            code = entry.code or ""
            if code.endswith("/stdout"):
                stdout_parts.append(text)
            elif code.endswith("/stderr"):
                stderr_parts.append(text)
                if text.strip():
                    succeeded = False
        return RunResult(succeeded, "\n".join(stdout_parts), "\n".join(stderr_parts))

    async def invoke_wrapper(self, wrapper_filename: str, args: str = "") -> RunResult:
        """Run one of the per-game PowerShell wrapper scripts on the VM."""
        path = f"{self._config.game.script_dir}\\{wrapper_filename}"
        return await self.run_powershell([f'& "{path}" {args}'.rstrip()])
