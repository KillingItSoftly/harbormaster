# Harbormaster Discord Bot

A Discord bot that lets trusted Discord users control a Harbormaster-managed
game server VM without giving them Azure access. It calls Azure ARM directly
for VM lifecycle ops, and uses **VM Run Command** to invoke the existing
PowerShell wrapper scripts on the VM (so backups, snapshots, updates and
health checks all reuse `core/scripts/`).

## Why a separate process

The bot can't live on the game VM itself — the VM is off most of the time,
and friends need to be able to `/server start` it from Discord. So the bot
runs as a tiny always-on Azure Container App and reaches *into* the VM
when needed.

## Commands

| Command | Tier | What it does |
|---|---|---|
| `/server status` | Player | VM power state |
| `/server start` | Player | Start the VM |
| `/server logs lines:<n>` | Player | Tail the server log |
| `/snapshot list` | Player | List milestones in blob storage |
| `/update check` | Player | Check Steam for an update |
| `/health` | Player | Run the on-VM health check |
| `/server stop` | Admin | Deallocate the VM (with confirm) |
| `/server restart-service` | Admin | Restart the NSSM service |
| `/backup now` | Admin | Trigger an on-demand backup |
| `/snapshot create` | Admin | Labeled milestone snapshot |
| `/update apply` | Admin | Snapshot then apply Steam update (with confirm) |
| `/help` | Anyone | Show commands + your tier |

Tiers are mapped to Discord role IDs in `config.yaml`. Per-user, per-command
rate limiting (default 30s) is applied to everyone.

## Architecture

```
Discord
   |  slash commands
   v
Container App (this bot)
   |  azure-mgmt-compute (managed identity)
   v
Game VM
   |  VM Run Command -> PowerShell
   v
games/<slug>/Backup-<Game>.ps1, Manage-<Game>Milestones.ps1, etc.
```

The bot calls the same wrapper scripts the scheduled tasks call — so behavior
is identical whether a backup is triggered by cron or by `/backup now`.

## VM-side prerequisites

1. Clone this repo on the VM at the path you put in
   `config.yaml -> game.script_dir` (e.g. `C:\Scripts\harbormaster\`).
2. Confirm the per-game `config.ps1` is filled in (storage account, etc.).
3. Make sure the VM's system-assigned managed identity has
   **Storage Blob Data Contributor** on the backup storage account
   (already required by the existing scripts — see
   [core/docs/azure-vm-setup.md](../core/docs/azure-vm-setup.md)).

The bot identity needs **Virtual Machine Contributor** on the VM — the
Bicep template grants this automatically.

## Local development

```bash
cd bot
python -m venv .venv && source .venv/bin/activate
pip install -e .

cp config.example.yaml config.yaml      # fill in real IDs
cp .env.example .env                    # paste DISCORD_BOT_TOKEN

# Auth to Azure as yourself; needs VM Contributor on the target VM.
az login

python -m harbormaster_bot
```

Slash commands sync to the configured guild on startup; they appear in the
Discord client within a few seconds.

## Build and push the image

```bash
ACR=<your-acr-name>
az acr login --name "$ACR"
docker build -t "$ACR.azurecr.io/harbormaster-bot:latest" .
docker push   "$ACR.azurecr.io/harbormaster-bot:latest"
```

If you don't have an ACR yet:

```bash
az acr create -g <rg> -n <acr-name> --sku Basic --admin-enabled false
```

## Deploy to Azure Container Apps

The Bicep at [infra/bot.bicep](infra/bot.bicep) creates:

- User-assigned managed identity
- Log Analytics workspace
- Container Apps managed environment
- Container App (1 replica, pinned)
- `AcrPull` on the ACR for the identity
- `Virtual Machine Contributor` on the target VM for the identity

```bash
cp infra/main.parameters.example.json infra/main.parameters.json
# Edit main.parameters.json: ACR name, VM name, Discord token, full config YAML

az deployment group create \
  -g <your-rg> \
  -f infra/bot.bicep \
  -p @infra/main.parameters.json
```

The `configYaml` parameter takes the **entire `config.yaml` file as a string**.
It's stored as a Container App secret and exposed inside the container as
`HARBORMASTER_CONFIG_YAML`. The bot prefers this over a file on disk if it's
set, so no volume mount is needed.

After the first deploy, rotate the token or config with:

```bash
az containerapp secret set \
  -g <rg> -n harbormaster-bot \
  --secrets discord-bot-token=<new-token> \
            harbormaster-config="$(cat config.yaml)"

az containerapp revision restart -g <rg> -n harbormaster-bot
```

## Discord bot setup

1. <https://discord.com/developers/applications> → New Application.
2. Bot tab → Reset Token → copy it (this goes into `DISCORD_BOT_TOKEN`).
3. Bot tab → Privileged intents: **none required**.
4. OAuth2 → URL Generator → scopes: `bot`, `applications.commands`.
5. Bot permissions: `Send Messages`, `Embed Links`, `Use Slash Commands`.
6. Open the generated URL, invite to your server.
7. Create two roles in Discord — `harbormaster-player`, `harbormaster-admin`
   (names up to you) — and copy the role IDs into `config.yaml`. Enable
   Developer Mode in Discord settings to right-click → Copy ID.

## Cost rough math

- Container App, 0.25 vCPU / 0.5 GiB, 1 replica pinned, 24/7 ≈ **$5–7/mo**
  (consumption plan; the always-on replica is the price floor)
- Log Analytics minimum ingestion: a few cents/mo at this scale
- ACR Basic: $5/mo flat
- VM Run Command itself: free

So roughly **$10–12/mo** added on top of the existing VM and storage.

## Security notes

- The bot identity has `Virtual Machine Contributor` on **one VM**, not the
  whole subscription. That gives it start, stop, run-command — but not the
  ability to delete the VM, mess with the NSG, or read other resources.
- Discord role IDs are the only access-control surface. Be careful who you
  hand the admin role to. Removing the role is instant; the bot re-checks
  on every command.
- Run Command output is captured and posted to Discord (truncated to 1.8 KB).
  Don't put secrets in scripts that the bot can call.
- The `configYaml` Bicep parameter is `@secure()` — Azure Resource Manager
  redacts it from logs and the portal, but anyone with `Reader` on the
  Container App can still read its env-var secret values. Don't share the
  RG with people you don't trust.
