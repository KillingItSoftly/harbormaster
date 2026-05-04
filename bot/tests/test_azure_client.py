"""Tests for harbormaster_bot.azure_client — _redact, RunResult.best_text, invoke_wrapper."""
from __future__ import annotations

import pytest

from harbormaster_bot.azure_client import RunResult, _redact


# ---------------------------------------------------------------------------
# _redact — credential scrubbing
# ---------------------------------------------------------------------------


def test_redact_empty_string():
    assert _redact("") == ""


def test_redact_plain_text_unchanged():
    text = "Server started successfully. Players online: 5."
    assert _redact(text) == text


def test_redact_discord_webhook():
    text = "Error posting to https://discord.com/api/webhooks/123456789/abcXYZ-token here"
    result = _redact(text)
    assert "discord.com/api/webhooks" not in result
    assert "[REDACTED]" in result


def test_redact_healthchecks_url():
    text = "Pinging https://hc-ping.com/uuid-1234-5678 failed"
    result = _redact(text)
    assert "hc-ping.com" not in result
    assert "[REDACTED]" in result


def test_redact_bearer_token():
    text = "Authorization: Bearer eyJhbGciOiJSUzI1NiJ9.payload.sig"
    result = _redact(text)
    assert "eyJhbGciOiJSUzI1NiJ9" not in result
    assert "[REDACTED]" in result


def test_redact_bearer_token_case_insensitive():
    text = "authorization: BEARER sometoken123"
    result = _redact(text)
    assert "sometoken123" not in result


def test_redact_sig_parameter():
    text = "URL: https://example.com/blob?sv=2020&sig=abcDEF123%2Bxyz&se=2024"
    result = _redact(text)
    assert "abcDEF123" not in result
    assert "[REDACTED]" in result


def test_redact_multiple_secrets_in_one_string():
    text = (
        "Webhook: https://discord.com/api/webhooks/111/abc-token "
        "Healthcheck: https://hc-ping.com/check-id "
        "Bearer reallySecretToken123"
    )
    result = _redact(text)
    assert "discord.com" not in result
    assert "hc-ping.com" not in result
    assert "reallySecretToken123" not in result


def test_redact_preserves_surrounding_text():
    text = "Error: webhook https://discord.com/api/webhooks/1/tok failed — retrying"
    result = _redact(text)
    assert result.startswith("Error: webhook")
    assert "failed" in result
    assert "retrying" in result


# ---------------------------------------------------------------------------
# RunResult.best_text
# ---------------------------------------------------------------------------


def test_best_text_only_stdout():
    rr = RunResult(succeeded=True, stdout="output line", stderr="")
    assert rr.best_text == "output line"


def test_best_text_only_stderr():
    rr = RunResult(succeeded=False, stdout="", stderr="error detail")
    assert rr.best_text == "error detail"


def test_best_text_both_labeled():
    rr = RunResult(succeeded=False, stdout="out", stderr="err")
    text = rr.best_text
    assert "[stdout]" in text
    assert "out" in text
    assert "[stderr]" in text
    assert "err" in text


def test_best_text_both_empty():
    rr = RunResult(succeeded=True, stdout="", stderr="")
    assert rr.best_text == ""


def test_best_text_redacts_webhook_in_stderr():
    rr = RunResult(
        succeeded=False,
        stdout="",
        stderr="Failed to post https://discord.com/api/webhooks/123/secret-tok",
    )
    assert "secret-tok" not in rr.best_text
    assert "[REDACTED]" in rr.best_text


def test_best_text_strips_whitespace():
    rr = RunResult(succeeded=True, stdout="  hello  ", stderr="")
    assert rr.best_text == "hello"


# ---------------------------------------------------------------------------
# invoke_wrapper — safety allowlist on wrapper filename
# ---------------------------------------------------------------------------

# We test the filename-rejection logic in isolation by calling invoke_wrapper
# with a mock that ensures run_powershell is never reached on bad inputs.

from unittest.mock import AsyncMock, MagicMock

from harbormaster_bot.azure_client import AzureClient, _SAFE_WRAPPER_NAME
from harbormaster_bot.config import AzureConfig, BotConfig, DiscordConfig, GameConfig


def _minimal_config() -> BotConfig:
    return BotConfig(
        discord=DiscordConfig(
            guild_id=1,
            player_role_id=2,
            admin_role_id=3,
            status_channel_id=None,
        ),
        azure=AzureConfig(
            subscription_id="sub",
            resource_group="rg",
            vm_name="vm",
        ),
        game=GameConfig(
            name="TestGame",
            service_name="svc",
            script_dir=r"C:\Scripts",
            log_path=r"C:\Logs\game.log",
        ),
    )


def _make_azure_client() -> AzureClient:
    """Return an AzureClient with its external SDK attributes stubbed out."""
    client = object.__new__(AzureClient)
    client._config = _minimal_config()
    client._cred = MagicMock()
    client._compute = MagicMock()
    return client


@pytest.mark.parametrize(
    "safe_name",
    [
        "Backup-GameServer.ps1",
        "Check-SteamUpdate.ps1",
        "My-Wrapper_v2.ps1",
        "a.ps1",
    ],
)
def test_safe_wrapper_name_matches(safe_name):
    assert _SAFE_WRAPPER_NAME.match(safe_name)


@pytest.mark.parametrize(
    "bad_name",
    [
        "../../../evil.ps1",          # path traversal
        "evil; rm -rf /.ps1",         # semicolon injection
        "evil.bat",                   # wrong extension
        "",                           # empty
        "a" * 81 + ".ps1",            # too long
        "has space.ps1",              # space in name
        "evil\n.ps1",                 # newline
    ],
)
def test_unsafe_wrapper_name_rejected(bad_name):
    assert not _SAFE_WRAPPER_NAME.match(bad_name)


async def test_invoke_wrapper_refuses_bad_filename():
    client = _make_azure_client()
    # run_powershell should NOT be called for bad filenames.
    client.run_powershell = AsyncMock()

    result = await client.invoke_wrapper("../evil.ps1")

    assert result.succeeded is False
    assert "refusing" in result.stderr
    client.run_powershell.assert_not_awaited()


async def test_invoke_wrapper_calls_run_powershell_for_valid_name():
    client = _make_azure_client()
    fake_result = RunResult(True, "ok", "")
    client.run_powershell = AsyncMock(return_value=fake_result)

    result = await client.invoke_wrapper("Backup-Game.ps1")

    assert result is fake_result
    client.run_powershell.assert_awaited_once()
    # The script path should incorporate script_dir.
    script_arg = client.run_powershell.call_args[0][0]
    assert r"C:\Scripts" in script_arg[0]
    assert "Backup-Game.ps1" in script_arg[0]


async def test_invoke_wrapper_appends_args():
    client = _make_azure_client()
    client.run_powershell = AsyncMock(return_value=RunResult(True, "", ""))

    await client.invoke_wrapper("Check-GameUpdate.ps1", "-ApplyUpdate")

    call_args = client.run_powershell.call_args[0][0]
    assert "-ApplyUpdate" in call_args[0]


# ---------------------------------------------------------------------------
# get_service_status — safety allowlist
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "bad_name",
    [
        "bad'name",         # single quote injection
        "bad name",         # space
        "",                 # empty
        "X" * 81,           # too long
    ],
)
async def test_get_service_status_returns_invalid_for_bad_names(bad_name):
    client = _make_azure_client()
    client.run_powershell = AsyncMock()

    result = await client.get_service_status(bad_name)

    assert result == "invalid"
    client.run_powershell.assert_not_awaited()


async def test_get_service_status_returns_parsed_status():
    client = _make_azure_client()
    client.run_powershell = AsyncMock(
        return_value=RunResult(True, "Running\n", "")
    )

    status = await client.get_service_status("palworld-nssm")

    assert status == "Running"


async def test_get_service_status_returns_last_non_empty_line():
    """Azure noise before the actual status should be stripped."""
    client = _make_azure_client()
    client.run_powershell = AsyncMock(
        return_value=RunResult(True, "WARNING: some noise\nStopped\n", "")
    )

    status = await client.get_service_status("my-svc")

    assert status == "Stopped"


async def test_get_service_status_empty_stdout_returns_unknown():
    client = _make_azure_client()
    client.run_powershell = AsyncMock(return_value=RunResult(False, "", ""))

    status = await client.get_service_status("my-svc")

    assert status == "Unknown"
