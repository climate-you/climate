# Runbook: Public VM Deployment (Caddy + systemd)

This runbook documents the V1 deployment path locked in `docs/plans/public-server-deployment-plan.md`.

## Scope

- Cloud provider: any Linux VM provider (`GCP`, `Hetzner`, `AWS`, `Azure`, others)
- VM type: provider-specific baseline (start with `2 vCPU`, `4-8 GB RAM`, `40-80 GB` SSD)
- Proxy: `Caddy`
- Frontend runtime: `Next.js server mode`
- Backend runtime: `FastAPI` (Uvicorn)
- Process supervision: `systemd`

## 0) Prerequisites and Dependency Installation

Install these on your local machine first:

- `git`
- `ssh` + an SSH keypair
- optional: `terraform` (>= 1.6) if you provision infrastructure via IaC

Recommended checks:

```bash
ssh -V
git --version
terraform version
```

Prepare your SSH public key for VM access:

```bash
cat ~/.ssh/id_ed25519.pub
```

Provisioning can be done from provider UI, provider CLI, or Terraform. This runbook assumes you have a reachable Linux VM with a public IP.

The VM-level dependencies (Python/Node/Caddy/fail2ban/ufw) are installed automatically by `scripts/deploy/bootstrap_vm.sh`.

## Repository Artifacts

- Systemd units: `deploy/systemd/*.service`
- Caddy config: `deploy/proxy/Caddyfile`
- Env templates: `deploy/env/*.env.example`
- Deploy scripts: `scripts/deploy/*.sh`
- GCP Terraform example: `infra/terraform/gcp/*`

## 1) Provision VM

Run from your local workstation.

Minimum VM properties for this runbook:

- public IPv4 address
- SSH access enabled
- inbound ports open for `22/tcp`, `80/tcp`, `443/tcp`
- Ubuntu/Debian-like OS with `systemd` and `sudo`
- enough disk for cloned source and data artifacts (typically tens of GB)

For a GCP Terraform example, see [Appendix A](#appendix-a-gcp-specific-reference-optional).

## 2) First Bring-Up Without Domain (IP-only)

At first, test using public IP over HTTP (no TLS yet):

- keep `deploy/proxy/Caddyfile` site label as placeholder (`example.com`) initially
- run bootstrap with `--domain <PUBLIC_IP>` so the Caddy site label is rendered to that IP
- set web/backend public URLs to `http://<PUBLIC_IP>`

This avoids domain/certificate setup while validating deployment.

## 3) First SSH Into VM and User Model

From your workstation:

```bash
ssh root@<PUBLIC_IP>
# or, if your provider uses a regular user by default:
ssh <SSH_USER>@<PUBLIC_IP>
```

Provider defaults differ:

- some providers start with `root` SSH access
- others start with a non-root user

Recommended policy:

- if first login is `root`, create a regular sudo user and use it for ongoing Git/deploy operations
- reserve direct `root` SSH for exceptional recovery tasks

If you start as `root`, run:

```bash
adduser <SSH_USER>
usermod -aG sudo <SSH_USER>
mkdir -p /home/<SSH_USER>/.ssh
cp ~/.ssh/authorized_keys /home/<SSH_USER>/.ssh/authorized_keys
chown -R <SSH_USER>:<SSH_USER> /home/<SSH_USER>/.ssh
chmod 700 /home/<SSH_USER>/.ssh
chmod 600 /home/<SSH_USER>/.ssh/authorized_keys
```

Then reconnect as regular user:

```bash
ssh <SSH_USER>@<PUBLIC_IP>
```

## 4) Configure GitHub Access From VM

Inside the VM as the user who owns the deployment checkout (recommended: regular sudo user), generate a dedicated SSH key for Git operations:

```bash
ssh-keygen -t ed25519 -C "<email address>"
eval "$(ssh-agent -s)"
ssh-add ~/.ssh/id_ed25519
cat ~/.ssh/id_ed25519.pub
```

Then:

- copy the printed public key
- add it to GitHub (user key or deploy key)
- verify from VM:

```bash
ssh -T git@github.com
```

## 5) Clone Repository On VM

Inside the VM:

```bash
git clone git@github.com:<org-or-user>/<repo>.git
cd <repo>
```

Recommended: use `/opt/climate/source` as the single deployment checkout to avoid drift between multiple copies.

## 6) Copy Data Package Before First Bootstrap

Backend and web services depend on data assets under `<repo>/data` (release artifacts, location assets, masks, and related files). On a fresh VM, copy a prepared archive from your local machine before service validation.

From your local machine:

```bash
scp /path/to/archive.tar.gz <SSH_USER>@<PUBLIC_IP>:/opt/climate/source/
```

From inside the VM checkout:

```bash
cd /opt/climate/source
tar xvf archive.tar.gz
```

If your archive is compressed and `tar xvf` fails to unpack, use:

```bash
tar xzvf archive.tar.gz
```

Quick verification checklist:

- required folders exist under `/opt/climate/source/data/`
- expected release/data files are present for your configured backend paths
- API-required artifacts are available before running bootstrap health checks

## 7) Bootstrap VM

Run bootstrap from inside that checkout:

```bash
sudo ./scripts/deploy/bootstrap_vm.sh \
  --domain <PUBLIC_IP> \
  --repo-branch main
```

What bootstrap does:

- installs OS dependencies (Python, Node, Caddy, fail2ban, ufw)
- installs Python package with API extras (`.[api]`) so `uvicorn` and FastAPI runtime deps are present
- creates service user and directories
- installs backend dependencies and frontend production build
- installs systemd units, env files, and Caddy config
- enables firewall rules (22,80,443)
- starts services and runs smoke checks
- by default, it reuses/copies the current repo checkout and does not fetch/pull remotes
- pass `--sync-repo` if you explicitly want bootstrap to run `git fetch/checkout/pull`
- `--repo-url` is an optional fallback only when cloning is required

Bootstrap env behavior:

- bootstrap copies template files from the repo:
  - `deploy/env/backend.env.example` -> `/etc/climate/backend.env`
  - `deploy/env/web.env.example` -> `/etc/climate/web.env`
- then it replaces `https://example.com` with the provided `--domain` (or `http://<ip>` for IP input)

Important note about `sudo` + GitHub SSH:

- root GitHub SSH key requirements are avoided in the default flow
- recommended path is: clone manually as your normal user, then run bootstrap from that checkout
- only use remote sync during bootstrap when needed (`--sync-repo`)

## 8) Configure Environment Values

Edit:

- `/etc/climate/backend.env`
- `/etc/climate/web.env`

Run this step on the VM after bootstrap.

Set production values for:

- `CORS_ALLOW_ORIGINS`
- `SITE_URL`
- `NEXT_PUBLIC_CLIMATE_API_BASE`
- `NEXT_PUBLIC_MAP_ASSET_BASE`
- `GOATCOUNTER_ENDPOINT` (optional; leave unset to disable GoatCounter analytics)
- release/data paths if custom
- `ANALYTICS_ENABLED=1` to enable the analytics event recording (off by default)
- `ANALYTICS_DB_PATH` (defaults to `<REPO_ROOT>/data/analytics/events.db`; the directory is created automatically on first write)

For IP-only testing, use:

- `SITE_URL=http://<PUBLIC_IP>`
- `NEXT_PUBLIC_CLIMATE_API_BASE=http://<PUBLIC_IP>`
- `NEXT_PUBLIC_MAP_ASSET_BASE=http://<PUBLIC_IP>`
- `CORS_ALLOW_ORIGINS=http://<PUBLIC_IP>`

Then reload services:

```bash
sudo systemctl restart climate-backend climate-web caddy
```

## 8b) Set Admin Credentials (for `/admin` page)

The `/admin` analytics page and the `/api/admin/*` endpoints are protected by Caddy basic auth. The credentials are passed to Caddy as environment variables — they are **not** stored in the application env file.

Generate a bcrypt password hash (run on the VM or locally):

```bash
caddy hash-password
# enter your chosen password at the prompt; copy the printed hash
```

Set the variables in the Caddy environment. The safest approach is a systemd override:

```bash
sudo systemctl edit caddy
```

Add:

```ini
[Service]
Environment="ADMIN_USER=admin"
Environment="ADMIN_PASSWORD_HASH=$2a$14$..."
```

Then reload:

```bash
sudo systemctl daemon-reload
sudo systemctl restart caddy
```

Verify the gate works:

```bash
# should return 401
curl -fsS http://127.0.0.1/admin
# should return the page
curl -u admin:<your-password> http://127.0.0.1/admin
```

## 9) Verify IP-based Runtime

From your local machine:

```bash
curl -fsS http://<PUBLIC_IP>/healthz
curl -fsS http://<PUBLIC_IP>/api/v/latest/release
```

If both pass, open `http://<PUBLIC_IP>` in browser and validate web + API integration.

## 10) Deploy Updates

Recommended workflow on the VM:

```bash
cd /opt/climate/source
git fetch --tags
git checkout v1.0.0
sudo ./scripts/deploy/deploy_app.sh --skip-pull
```

Why this is recommended:

- `deploy_app.sh` runs as `root` when invoked with `sudo`.
- Git operations done by root use `/root/.ssh`, which usually does not have GitHub deploy keys configured.
- Doing `git fetch/checkout` as your normal VM user avoids root SSH key issues.

Optional workflow (only if root GitHub SSH auth is configured):

```bash
sudo ./scripts/deploy/deploy_app.sh --ref v1.0.0
# or
sudo ./scripts/deploy/deploy_app.sh --tag v1.0.0
```

All workflows rebuild backend/web assets, restart services, and run smoke checks.

Important:

- Next.js reads `NEXT_PUBLIC_*` at build time.
- Next.js metadata routes (`robots.ts`, `sitemap.ts`) and `metadataBase` use `SITE_URL` from `/etc/climate/web.env` at build time.
- `deploy_app.sh` now loads `/etc/climate/web.env` before `npm run build`.
- after changing `NEXT_PUBLIC_*`, `SITE_URL`, or `GOATCOUNTER_ENDPOINT`, run a new web build (through deploy script or manually) for changes to take effect.

## 11) Verify Services (VM-local)

```bash
systemctl is-active climate-backend
systemctl is-active climate-web
systemctl is-active caddy
curl -fsS http://127.0.0.1:8001/healthz
curl -fsS http://127.0.0.1:8001/api/v/latest/release
```

## 12) Troubleshooting

### 12.1 Service Status and Recent Logs

```bash
systemctl status climate-backend climate-web caddy
journalctl -u climate-backend -n 200 --no-pager
journalctl -u climate-web -n 200 --no-pager
journalctl -u caddy -n 200 --no-pager
```

### 12.2 Backend Startup Fails (Missing Data/Assets)

- inspect `climate-backend` logs for missing file/path errors
- verify configured paths in `/etc/climate/backend.env`
- verify extracted files exist in `<repo>/data`
- restart after fixing paths or missing files:

```bash
sudo systemctl restart climate-backend climate-web caddy
```

### 12.3 Cannot Connect to Backend/API

Check from VM first:

```bash
curl -fsS http://127.0.0.1:8001/healthz
```

Then check from local machine:

```bash
curl -fsS http://<PUBLIC_IP>/healthz
```

If VM-local succeeds but public endpoint fails:

- check Caddy status/logs and site routing
- verify provider firewall/security-group rules for ports `80/443`
- verify env values for public API base/CORS

### 12.4 Web Loads but API Calls Fail

- verify `NEXT_PUBLIC_CLIMATE_API_BASE` in `/etc/climate/web.env`
- verify `SITE_URL` in `/etc/climate/web.env`
- verify `CORS_ALLOW_ORIGINS` in `/etc/climate/backend.env`
- rebuild/redeploy web after `NEXT_PUBLIC_*`, `SITE_URL`, or `GOATCOUNTER_ENDPOINT` changes (build-time values)

### 12.5 Quick Triage Order

1. logs (`journalctl`)
2. VM-local backend health (`127.0.0.1`)
3. public health (`<PUBLIC_IP>`)
4. env mismatch (`/etc/climate/*.env`)
5. firewall/security-group exposure

### 12.6 `app_version=unknown` In `/api/v/latest/release`

Symptom:

- API response contains:
  - `"version": {"app_version": "unknown", "app_tag": null, "app_commit": null, ...}`
- backend startup log shows:
  - `Startup version info: app_version=unknown app_tag=None app_commit=None ...`

Typical cause:

- Git trust check blocks repository access for service context (`dubious ownership`).
- `climate-backend` runs with `ProtectHome=true`, so user-global Git config (`~/.gitconfig`) may not be visible to the service.

Immediate VM remediation:

```bash
sudo git config --system --add safe.directory /opt/climate/source
sudo systemctl restart climate-backend
```

Verification:

```bash
sudo journalctl -u climate-backend -n 50 --no-pager | grep "Startup version info"
curl -s http://127.0.0.1:8001/api/v/latest/release | python3 -m json.tool
```

Expected result:

- startup log includes a resolved tag or commit (for example `app_version=v0.1.1`)
- API `version.app_version` matches the deployed tag/commit, not `unknown`

## 13) Add Domain and TLS Later

Once domain is chosen:

- map DNS `A` record to the VM public IP
- update Caddy site label from `:80` to `your-domain.example`
- update env URLs and CORS to `https://your-domain.example`
- restart `caddy`, `climate-backend`, `climate-web`

## 14) Basic Monitoring Setup

Minimum checks to add in your monitoring stack:

- CPU/memory/swap utilization
- service restart counts
- backend 4xx/5xx rates
- p95 API latency

Alert thresholds (initial):

- CPU > 85% for 10m
- memory > 85% for 10m
- restart bursts > 3 in 10m
- sustained 5xx above baseline

## 15) Security Baseline Checklist

- SSH keys only, root login disabled
- CORS restricted to your production domain(s)
- API exposed only through Caddy
- backend and web running as non-root `climate` user
- unattended upgrades enabled
- fail2ban + ufw active
- `/admin` and `/api/admin/*` protected by Caddy basic auth (`ADMIN_USER` / `ADMIN_PASSWORD_HASH` set in Caddy environment)

## 16) Notes

- API rate limiting is enabled in backend middleware by default via:
  - `RATE_LIMIT_ENABLED=1`
  - `RATE_LIMIT_SUSTAINED_RPS=5`
  - `RATE_LIMIT_BURST=20`
  - `RATE_LIMIT_WINDOW_S=10`
- For multi-instance deployments, replace local in-process rate limiting with shared-state limits (e.g., Redis + gateway/WAF policy).

## 17) Automation Strategy (Recommendation)

Current recommendation:

- keep Terraform for reproducible infra provisioning (VM, IP, firewall)
- keep GitHub key registration manual in V1 (one-off bootstrap, low repetition)
- optionally automate GitHub key registration in V2 via `gh` CLI + PAT or GitHub App credentials

Rationale:

- Terraform prevents drift and makes rebuild/migration deterministic
- GitHub SSH key setup is sensitive and account-scoped; full automation adds secret-management complexity early

## Appendix A: GCP-specific reference (optional)

Use this appendix only if you are provisioning on GCP.

### A.1 GCP prerequisites

- `gcloud` CLI authenticated to your GCP project
- `terraform` (>= 1.6) if using Terraform

```bash
gcloud auth list
gcloud config get-value project
```

### A.2 GCP Terraform provisioning example

```bash
cd infra/terraform/gcp
cp terraform.tfvars.example terraform.tfvars
# edit terraform.tfvars
terraform init
terraform plan
terraform apply
```

Before `terraform apply`, edit:

- `infra/terraform/gcp/terraform.tfvars`
- `infra/terraform/gcp/variables.tf` only if changing defaults structurally

Capture the `public_ip` output for runbook steps.

### A.3 GCP SSH example

```bash
gcloud compute ssh <vm-name> --zone <zone>
```
