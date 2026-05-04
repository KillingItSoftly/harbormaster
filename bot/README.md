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

## Build and push the image (manual)

The CI pipeline (below) is the recommended path. For one-off local pushes:

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

## Secrets live in Key Vault

The Container App **does not** receive the Discord token or config YAML as
deployment parameters. Instead they are stored in an Azure Key Vault, and
the Container App's user-assigned managed identity reads them at startup
(via the native Container Apps Key Vault secret reference).

This means:

- Pipeline runners never see the token.
- ARM deployment history doesn't contain the token.
- Rotating a secret is `az keyvault secret set` — no Bicep redeploy needed.
- Picking up the rotated value is a one-shot `az containerapp revision restart`.

### One-time: provision the Key Vault and seed secrets

```bash
RG=<your-rg>
KV=<your-keyvault-name>   # globally unique, 3-24 chars

az deployment group create \
  -g "$RG" \
  -f infra/keyvault.bicep \
  -p keyVaultName="$KV"

# Grant *yourself* permission to write secrets (one-time, your user account).
ME=$(az ad signed-in-user show --query id -o tsv)
az role assignment create \
  --assignee-object-id "$ME" --assignee-principal-type User \
  --role "Key Vault Secrets Officer" \
  --scope "$(az keyvault show -n "$KV" --query id -o tsv)"

# Seed the two secrets the bot expects.
az keyvault secret set --vault-name "$KV" \
  --name discord-bot-token --value '<paste-discord-bot-token>'

az keyvault secret set --vault-name "$KV" \
  --name harbormaster-config --file ./config.yaml
```

The `harbormaster-config` secret is the **entire `config.yaml` file**. The
bot reads it from the `HARBORMASTER_CONFIG_YAML` env var, so no volume
mount is needed.

### Deploy the bot

The Bicep at [infra/bot.bicep](infra/bot.bicep) creates:

- User-assigned managed identity
- Log Analytics workspace
- Container Apps managed environment
- Container App (1 replica, pinned), with secrets referenced from Key Vault
- `AcrPull` on the ACR
- `Virtual Machine Contributor` on the target VM
- `Key Vault Secrets User` on the Key Vault

```bash
cp infra/main.parameters.example.json infra/main.parameters.json
# Edit: namePrefix, acrName, image, vmName, keyVaultName

az deployment group create \
  -g <your-rg> \
  -f infra/bot.bicep \
  -p @infra/main.parameters.json
```

### Rotate a secret

```bash
az keyvault secret set --vault-name "$KV" \
  --name discord-bot-token --value '<new-token>'

# Force a new revision so Container Apps re-fetches the latest version.
az containerapp revision restart -g <rg> -n harbormaster-bot \
  --revision $(az containerapp revision list -g <rg> -n harbormaster-bot \
                  --query "[?properties.active].name | [0]" -o tsv)
```

## CI/CD: GitHub Actions

The workflow at
[.github/workflows/bot-build-deploy.yml](../.github/workflows/bot-build-deploy.yml)
builds the image with **ACR Tasks** (no Docker daemon on the runner) and
rolls the Container App to the new tag. It authenticates with **GitHub
OIDC** — there is no service principal client secret in GitHub.

### One-time setup

1. **Create an Entra app registration** the workflow will impersonate:

   ```bash
   APP_ID=$(az ad app create --display-name harbormaster-bot-deploy \
              --query appId -o tsv)
   az ad sp create --id "$APP_ID"
   ```

2. **Add a federated credential** that trusts pushes to `main` of this repo:

   ```bash
   az ad app federated-credential create --id "$APP_ID" --parameters '{
     "name": "github-main",
     "issuer": "https://token.actions.githubusercontent.com",
     "subject": "repo:<owner>/<repo>:ref:refs/heads/main",
     "audiences": ["api://AzureADTokenExchange"]
   }'
   ```

3. **Grant least-privilege** roles on the resource group:

   ```bash
   SP_ID=$(az ad sp show --id "$APP_ID" --query id -o tsv)
   RG_ID=$(az group show -n <rg> --query id -o tsv)

   # Build & push to ACR
   az role assignment create --assignee-object-id "$SP_ID" \
     --assignee-principal-type ServicePrincipal \
     --role "AcrPush" --scope "$RG_ID"

   # Update the Container App revision
   az role assignment create --assignee-object-id "$SP_ID" \
     --assignee-principal-type ServicePrincipal \
     --role "Container Apps Contributor" --scope "$RG_ID"
   ```

   Note that this principal **does not** get any Key Vault role. The
   pipeline cannot read or modify secrets — only the Container App's
   runtime identity can.

4. **Wire up GitHub**, in the repo's *Settings → Secrets and variables → Actions*:

   | Type | Name | Value |
   |---|---|---|
   | Secret   | `AZURE_CLIENT_ID`       | `$APP_ID` |
   | Secret   | `AZURE_TENANT_ID`       | `az account show --query tenantId -o tsv` |
   | Secret   | `AZURE_SUBSCRIPTION_ID` | `az account show --query id -o tsv` |
   | Variable | `AZURE_RESOURCE_GROUP`  | your RG name |
   | Variable | `ACR_NAME`              | your ACR name (no `.azurecr.io`) |
   | Variable | `CONTAINER_APP_NAME`    | `harbormaster-bot` (or your override) |
   | Variable | `IMAGE_REPOSITORY`      | `harbormaster-bot` (or your override) |

The workflow runs on every push to `main` that touches `bot/**`, and tags
images with the 7-char commit SHA plus `latest`. You can also dispatch it
manually with a custom tag.

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
- Runtime secrets (Discord token, config YAML) live in Key Vault. The
  Container App's managed identity has `Key Vault Secrets User` (read
  only), and the CI pipeline's identity has **no** Key Vault role at all.
  Anyone with `Reader` on the Container App can still read the resolved
  env-var values from a running revision — don't share the RG with people
  you don't trust.
