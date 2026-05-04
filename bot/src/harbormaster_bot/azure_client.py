from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from typing import Iterable

from azure.identity.aio import DefaultAzureCredential
from azure.mgmt.compute.aio import ComputeManagementClient
from azure.mgmt.compute.models import RunCommandInput

from .config import BotConfig

# Allowlist for things we splice into PowerShell command lines.
_SAFE_WRAPPER_NAME = re.compile(r"^[A-Za-z0-9_.-]{1,80}\.ps1$")
_SAFE_SERVICE_NAME = re.compile(r"^[A-Za-z0-9_.-]{1,80}$")


@dataclass
class RunResult:
    succeeded: bool
    stdout: str
    stderr: str

    @property
    def best_text(self) -> str:
        """Concatenated stdout + stderr, labeled if both have content.

        Used for surfacing Run Command output. Failures often have empty
        stdout and the real error in stderr; we want both. URLs that
        could leak credentials (Discord webhooks, Healthchecks pings) are
        redacted before this is shown to users.
        """
        out = _redact(self.stdout or "").strip()
        err = _redact(self.stderr or "").strip()
        if out and err:
            return f"[stdout]\n{out}\n[stderr]\n{err}"
        return out or err


# Patterns that may appear in PowerShell stdout/stderr if a wrapper script
# error-prints a Discord webhook URL or Healthchecks ping URL. Both are
# treated as bearer-credential equivalents and redacted before any output
# is sent back to Discord.
_REDACT_PATTERNS = [
    re.compile(r"https://discord\.com/api/webhooks/\S+"),
    re.compile(r"https://hc-ping\.com/\S+"),
    # Defensive: any Bearer token, basic-auth header, or SAS-looking query.
    re.compile(r"(?i)Bearer\s+[A-Za-z0-9._\-]+"),
    re.compile(r"(?i)sig=[A-Za-z0-9%+/=_\-]+"),
]


def _redact(text: str) -> str:
    if not text:
        return text
    for pat in _REDACT_PATTERNS:
        text = pat.sub("[REDACTED]", text)
    return text


@dataclass
class VmStatus:
    power_state: str
    provisioning_state: str
    agent_status: str  # e.g. "Ready", "Unresponsive", "Unknown"
    os_name: str | None
    os_version: str | None


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

    async def vm_status(self) -> VmStatus:
        """Detailed instance view for `/server status`."""
        view = await self._compute.virtual_machines.instance_view(
            self._config.azure.resource_group, self._config.azure.vm_name
        )
        power = "unknown"
        prov = "unknown"
        for s in view.statuses or []:
            if not s.code:
                continue
            if s.code.startswith("PowerState/"):
                power = s.code.split("/", 1)[1]
            elif s.code.startswith("ProvisioningState/"):
                prov = s.code.split("/", 1)[1]
        agent = "unknown"
        va = getattr(view, "vm_agent", None)
        if va is not None:
            for s in va.statuses or []:
                if s.display_status:
                    agent = s.display_status
                    break
        return VmStatus(
            power_state=power,
            provisioning_state=prov,
            agent_status=agent,
            os_name=getattr(view, "os_name", None),
            os_version=getattr(view, "os_version", None),
        )

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

    async def invoke_wrapper(
        self, wrapper_filename: str, args: str = "", timeout_sec: int = 900
    ) -> RunResult:
        """Run one of the per-game PowerShell wrapper scripts on the VM.

        SECURITY NOTE: `args` is interpolated into a PowerShell command line
        as-is. Callers MUST sanitize any user-supplied values (allowlist
        regex on labels, app_commands.Range for ints, hard-coded choices for
        categories, etc.) before they reach this method.
        """
        # Enforce allowlist on the wrapper filename to prevent path traversal.
        if not _SAFE_WRAPPER_NAME.match(wrapper_filename):
            return RunResult(False, "", f"refusing wrapper name: {wrapper_filename!r}")
        path = f"{self._config.game.script_dir}\\{wrapper_filename}"
        return await self.run_powershell(
            [f'& "{path}" {args}'.rstrip()], timeout_sec=timeout_sec
        )

    async def get_service_status(self, service_name: str) -> str:
        """Return the Status of an NSSM-wrapped Windows service via Run Command."""
        if not _SAFE_SERVICE_NAME.match(service_name):
            return "invalid"
        result = await self.run_powershell(
            [
                f"$svc = Get-Service -Name '{service_name}' -ErrorAction SilentlyContinue;"
                "if ($null -eq $svc) { 'NotFound' } else { $svc.Status.ToString() }",
            ],
            timeout_sec=60,
        )
        text = (result.stdout or "").strip().splitlines()
        return text[-1].strip() if text else "Unknown"
