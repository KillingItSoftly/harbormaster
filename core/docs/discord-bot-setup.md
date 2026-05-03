# Discord Bot Setup

Setting up the Harbormaster Discord bot end-to-end: Discord application, Azure Container Registry, Container App, identity, and config. The bot itself lives under [bot/](../../bot) — this doc is the operator's runbook for getting one running.

## Why a separate process

The bot can't live on the game VM. The VM is off most of the time (auto-shutdown), and one of the headline commands is `/server start` — chicken and egg. The bot needs to be always-on somewhere outside the VM, with permission to wake it up.

Azure Container Apps with one pinned replica is the cheapest reasonable way to get an always-on workload in Azure: roughly $5–7/mo for the bot itself, $5/mo flat for ACR Basic, ~$10–12/mo total on top of the existing VM and storage.

You could host it elsewhere (Fly.io, Railway, a Raspberry Pi at home), but the Bicep template assumes Container Apps and a managed identity for Azure auth. Other hosts work; you'll need to provide credentials some other way (service principal in env vars, typically).

## What the bot can do

Two permission tiers, mapped to Discord role IDs:

- **Player** — `/server status`, `/server start`, `/server logs`, `/snapshot list`, `/update check`, `/health`
- **Admin** — `/server stop`, `/server restart-service`, `/backup now`, `/snapshot create`, `/update apply`

Destructive admin ops (`/server stop`, `/update apply`) get a Confirm/Cancel prompt. All commands are rate-limited per user (30s default). Anyone in the guild without either role gets nothing.

## Architecture

```
Discord (slash commands)
   |
   v
Container App (this bot, always on)
   |   azure-mgmt-compute via user-assigned managed identity
   v
Game VM (Windows)
   |   Azure VM Run Command -> PowerShell
   v
games/<slug>/Backup-<Game>.ps1, Manage-<Game>Milestones.ps1, etc.
```

Two key choices to understand:

1. **Azure ARM for VM lifecycle.** Start/stop/deallocate go straight to the Azure compute API. The VM doesn't need to be on for those.
2. **Run Command for everything else.** Backups, snapshots, update checks — the bot doesn't reimplement them. It uses [VM Run Command](https://learn.microsoft.com/azure/virtual-machines/windows/run-command) to execute the existing wrapper scripts on the VM. Same code path as the scheduled tasks.

This keeps the bot small and means there's only one place where backup logic lives. The cost: Run Command requires the VM to be running. `/backup now` while the VM is deallocated will fail; the user needs to `/server start` first.

## Prerequisites

Before you start:

- An Azure subscription with the existing game VM and storage account (i.e. you've already followed [azure-vm-setup.md](azure-vm-setup.md)).
- The Harbormaster repo cloned **on the VM** at the path you'll put in `config.yaml -> game.script_dir`. The bot calls scripts at that path via Run Command — they have to actually exist there. Recommended: `C:\Scripts\harbormaster\`.
- A resource group (can be the same one as the VM).
- An [Azure Container Registry](https://learn.microsoft.com/azure/container-registry/) — the Bicep template assumes one already exists. Create with `az acr create -g <rg> -n <name> --sku Basic`.
- Docker installed locally for the image build.

## Step 1: Create the Discord application

This is the slowest step in real time but only takes a few minutes of clicks.

1. Go to <https://discord.com/developers/applications> → **New Application**. Name it whatever — "Harbormaster" is fine.
2. **Bot** tab → **Reset Token** → copy the token. This goes into `DISCORD_BOT_TOKEN` later. Treat it like a password; if it leaks, reset it from the same page.
3. **Privileged Gateway Intents**: leave all three off. The bot only uses slash commands and doesn't need to read message content or member presence.
4. **OAuth2 → URL Generator**:
   - Scopes: `bot`, `applications.commands`
   - Bot Permissions: `Send Messages`, `Embed Links`, `Use Slash Commands`
   - Copy the generated URL, open it, invite the bot to your guild.
5. In your guild, create two roles. Names don't matter to the bot — only the role IDs do. Recommended: `harbormaster-player` and `harbormaster-admin`. Assign yourself the admin role; you can hand out player roles later.
6. Enable **User Settings → Advanced → Developer Mode** in Discord. Right-click each role and "Copy ID". You'll also need the guild ID (right-click the server icon).

Save these for later:

- Bot token
- Guild ID
- Player role ID
- Admin role ID

## Step 2: Build and push the bot image

From the repo root:

```bash
cd bot
ACR=<your-acr-name>      # not the full hostname, just the registry name
az acr login --name "$ACR"

docker build -t "$ACR.azurecr.io/harbormaster-bot:latest" .
docker push   "$ACR.azurecr.io/harbormaster-bot:latest"
```

The image is small (~150 MB) and pure-Python — there's no native code, so a fresh build from a cold cache takes a minute or two.

If you're on an Apple Silicon Mac, force amd64 so the image runs on Container Apps' x86 nodes:

```bash
docker build --platform linux/amd64 -t "$ACR.azurecr.io/harbormaster-bot:latest" .
```

## Step 3: Fill in the config

The Bicep template stores the bot's entire `config.yaml` as a single Container App secret named `harbormaster-config`. The bot reads it from the `HARBORMASTER_CONFIG_YAML` env var if present, falling back to a file on disk for local dev.

Copy the template:

```bash
cp infra/main.parameters.example.json infra/main.parameters.json
```

Edit `infra/main.parameters.json`:

- `acrName`: the ACR you pushed to
- `vmName`: the existing game VM
- `discordBotToken`: the token from step 1
- `configYaml`: a YAML string with all your values. The example file has the right shape — just replace the IDs.

The `configYaml` string is YAML embedded in JSON, so newlines need to be `\n` and any literal backslashes (Windows paths) need to be doubled. The example shows this. If you'd rather edit a real YAML file and inline it at deploy time, see "Updating config later" below.

## Step 4: Deploy the infrastructure

```bash
az deployment group create \
  -g <your-rg> \
  -f infra/bot.bicep \
  -p @infra/main.parameters.json
```

The template creates:

- A user-assigned managed identity (`harbormaster-bot-id`)
- A Log Analytics workspace
- A Container Apps managed environment
- The Container App itself, pinned at `minReplicas: 1`, `maxReplicas: 1`
- An `AcrPull` role assignment on the registry (so the App can pull the image)
- A `Virtual Machine Contributor` role assignment on the target VM (so the bot identity can start, stop, and run commands on it)

Deployment takes 3–5 minutes. The Container Apps environment is the slow part — first-time provisioning of the underlying Log Analytics linkage takes a couple of minutes.

After it finishes, watch the bot come online:

```bash
az containerapp logs show \
  -g <your-rg> -n harbormaster-bot \
  --follow
```

You should see `Logged in as <BotName>#XXXX` and `Synced N slash commands to guild <id>` within a few seconds. Slash commands appear in Discord clients almost immediately — guild-scoped commands skip the global cache.

## Step 5: Smoke test

In your Discord guild, with the admin role:

```
/help
/server status
```

`/help` should show the command list and your role tier. `/server status` should hit Azure and return the current power state of the VM.

If the VM is currently running, also try:

```
/health
```

This invokes `Check-<Game>Health.ps1` via Run Command. Output is the script's own log — usually a few lines, possibly truncated to 1.8 KB to fit a Discord message.

## Updating config later

Two ways to rotate values without rebuilding the image:

**Single secret rotation** (fast, no Bicep needed):

```bash
az containerapp secret set \
  -g <rg> -n harbormaster-bot \
  --secrets discord-bot-token=<new-token>

az containerapp revision restart -g <rg> -n harbormaster-bot
```

**Re-upload the whole config YAML** when role IDs or game settings change:

```bash
az containerapp secret set \
  -g <rg> -n harbormaster-bot \
  --secrets harbormaster-config="$(cat config.yaml)"

az containerapp revision restart -g <rg> -n harbormaster-bot
```

Note that secret changes don't trigger a restart automatically. The `revision restart` is the line people forget.

## Updating the bot itself

Build, push, restart:

```bash
docker build --platform linux/amd64 -t "$ACR.azurecr.io/harbormaster-bot:latest" .
docker push                                "$ACR.azurecr.io/harbormaster-bot:latest"

az containerapp update \
  -g <rg> -n harbormaster-bot \
  --image "$ACR.azurecr.io/harbormaster-bot:latest"
```

Container Apps handles the rolling update; the bot disconnects from Discord, the new revision starts, reconnects within a few seconds. Slash commands re-sync on each startup so command additions/removals propagate without any extra step.

## Common pitfalls

### "Bot replied with: This interaction failed"

Almost always one of:

- The bot logged in but the slash command tree hasn't synced yet. Wait 5 seconds and retry.
- The user has neither role configured in `config.yaml`. Check role IDs — copy-paste typos are common because role IDs are 18-19 digit numbers.
- Run Command timed out (default 15 minutes). Check Container App logs.

### Run Command hangs or returns nothing

VM Run Command requires the VM to be running and the Azure VM Agent to be healthy. Symptoms of an unhealthy agent: commands appear to succeed but never return output, or hang indefinitely.

To check from the VM, RDP in and:

```powershell
Get-Service WindowsAzureGuestAgent
```

It should be `Running`. Restart it if not. If the service is missing entirely, the VM was created from an image without the agent — easier to recreate the VM than retrofit it.

### Bot can start the VM but can't run commands

The identity has `Virtual Machine Contributor` (granted by the Bicep template), which includes both. But Run Command also requires the VM to be **running** and the agent to be **healthy** — see above. If `/server start` works but `/backup now` immediately afterward fails, the agent probably hasn't finished initializing yet. Wait 30-60 seconds after the VM reports `running` before issuing Run Command operations.

### "AuthorizationFailed" on first deploy

The deploying user (you) needs `Owner` or `User Access Administrator` on the resource group, because the Bicep template creates role assignments. `Contributor` alone isn't enough — Contributor can create resources but can't grant roles. Easiest fix: add yourself as Owner of the RG temporarily, deploy, then optionally drop back to Contributor.

### Image won't pull (`UNAUTHORIZED` in Container App logs)

The `AcrPull` role assignment in the Bicep takes effect immediately, but if you pushed the image **after** the deployment, the App's pull might happen during a bad cache window. `az containerapp revision restart` fixes it.

### Slash commands not appearing

The bot does a guild-scoped sync at startup. If commands aren't showing up:

1. Confirm `discord.guild_id` in config is correct.
2. Confirm the bot is actually in that guild (Server Settings → Integrations).
3. Re-invite with the OAuth2 URL — the `applications.commands` scope is required and easy to forget.
4. As a last resort, **DM the bot a message** to wake the gateway, then refresh the Discord client. Guild syncs are usually instant but very rarely take a minute or two.

## Security model

Worth being clear about what the bot can and can't do, and who can do what.

**The bot identity** has `Virtual Machine Contributor` on **one VM**, scoped at the VM resource — not at the resource group, not at the subscription. That gives it:

- Start, stop, deallocate, restart the VM
- Read VM properties (power state, etc.)
- Invoke Run Command on the VM

It does *not* give it:

- Delete the VM
- Modify the NSG, public IP, or networking
- Read or modify other VMs in the same RG
- Touch the storage account (the VM's *own* identity does that, separately)

**Discord roles** are the only access control on the bot's commands. There's no per-user override, no audit log inside the bot, no two-factor for admin commands beyond the Confirm button. The threat model is "trusted friends with maybe-iffy security hygiene", not "hostile actor with a stolen Discord token". Adjust your role assignments accordingly.

**Run Command output** is captured and posted to Discord, truncated to about 1.8 KB. Don't put secrets in scripts the bot can call. The wrapper scripts in `games/<slug>/` don't echo any — they pass the per-game `config.ps1` to the core scripts and let those run — but worth keeping in mind if you add custom commands later.

**The config YAML secret** is marked `@secure()` in Bicep, so ARM redacts it from deployment logs and the portal. Anyone with `Reader` on the Container App can still call `secret list` and see the values, though. Don't share the RG with anyone you wouldn't share the Discord bot token with.

**Webhook URLs and Healthchecks ping URLs** stay on the VM, not in the bot. The bot doesn't need them — it triggers the scripts and lets the scripts do their own notification. This is by design: the bot leaves a smaller credential footprint.

## What's not in the bot (yet)

A few things that didn't make the first cut, in case you want to add them:

- **`/server players`** — The current implementation has the slot but no game-specific implementation. Most games expose a player count via a query port (e.g. Source Engine A2S, Minecraft SLP) — wiring that up requires a per-game adapter and a network path from the Container App to the VM's query port.
- **Status channel posting** — `discord.status_channel_id` is in the config schema but unused. The hook is "after every admin action, post a one-line summary to that channel" so non-Discord users can audit who did what.
- **Long output upload** — Run Command output > 1.8 KB gets cut. Could be uploaded as a `.txt` attachment instead. Trivial change to `cogs/server.py` and friends.
- **Scheduled commands from Discord** — "snooze auto-shutdown by 1 hour", "extend the VM uptime tonight". Possible but requires the bot to track its own state and re-trigger on a timer. Not in scope yet.

## Tear-down

If you ever want to remove the bot:

```bash
az group deployment delete -g <rg> -n bot
# or, more aggressively:
az containerapp delete -g <rg> -n harbormaster-bot --yes
az containerapp env delete -g <rg> -n harbormaster-bot-env --yes
az identity delete -g <rg> -n harbormaster-bot-id
```

The role assignments are scoped to the identity, so deleting the identity removes them. The VM is unaffected; everything continues running on its scheduled tasks.
