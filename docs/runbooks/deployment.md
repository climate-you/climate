# Runbook: Public VM Deployment (GCP + Caddy + systemd)

This runbook documents the V1 deployment path locked in `docs/plans/public-server-deployment-plan.md`.

## Scope

- Cloud provider: `GCP`
- VM type: `e2-standard-2` (initial baseline)
- Proxy: `Caddy`
- Frontend runtime: `Next.js server mode`
- Backend runtime: `FastAPI` (Uvicorn)
- Process supervision: `systemd`

## 0) Prerequisites and Dependency Installation

Install these on your local machine first:

- `terraform` (>= 1.6)
- `gcloud` CLI (authenticated to your GCP project)
- `git`
- `ssh` + an SSH keypair

Recommended checks:

```bash
terraform version
gcloud auth list
gcloud config get-value project
ssh -V
```

Prepare your SSH public key for Terraform:

```bash
cat ~/.ssh/id_ed25519.pub
```

The VM-level dependencies (Python/Node/Caddy/fail2ban/ufw) are installed automatically by `scripts/deploy/bootstrap_vm.sh`.

## Repository Artifacts

- Terraform: `infra/terraform/gcp/*`
- Systemd units: `deploy/systemd/*.service`
- Caddy config: `deploy/proxy/Caddyfile`
- Env templates: `deploy/env/*.env.example`
- Deploy scripts: `scripts/deploy/*.sh`

## 1) Provision GCP VM

Run from your local workstation.

```bash
cd infra/terraform/gcp
cp terraform.tfvars.example terraform.tfvars
# edit terraform.tfvars
terraform init
terraform plan
terraform apply
```

Capture the `public_ip` output.

Before `terraform apply`, edit these local files:

- `infra/terraform/gcp/terraform.tfvars`
- `infra/terraform/gcp/variables.tf` only if changing defaults structurally

## 2) First Bring-Up Without Domain (IP-only)

At first, test using public IP over HTTP (no TLS yet):

- in `deploy/proxy/Caddyfile`, use `:80 { ... }` as the site label
- set web/backend public URLs to `http://<PUBLIC_IP>`

This avoids domain/certificate setup while validating deployment.

## 3) First SSH Into VM (GCP)

From your workstation:

```bash
gcloud compute ssh <vm-name> --zone <zone>
```

This is preferred over raw `ssh` for initial access because `gcloud` handles project/instance context and key propagation.

## 4) Configure GitHub Access From VM

Inside the VM, generate a dedicated SSH key for Git operations:

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

## 6) Bootstrap VM

SSH into VM and run the bootstrap script from a checkout of this repo:

```bash
sudo ./scripts/deploy/bootstrap_vm.sh \
  --domain <PUBLIC_IP> \
  --repo-url <git-url> \
  --repo-branch main
```

What bootstrap does:

- installs OS dependencies (Python, Node, Caddy, fail2ban, ufw)
- creates service user and directories
- installs backend dependencies and frontend production build
- installs systemd units, env files, and Caddy config
- enables firewall rules (22,80,443)
- starts services and runs smoke checks

Bootstrap env behavior:

- bootstrap copies template files from the repo:
  - `deploy/env/backend.env.example` -> `/etc/climate/backend.env`
  - `deploy/env/web.env.example` -> `/etc/climate/web.env`
- then it replaces `https://example.com` with the provided `--domain` (or `http://<ip>` for IP input)

## 7) Configure Environment Values

Edit:

- `/etc/climate/backend.env`
- `/etc/climate/web.env`

Run this step on the VM after bootstrap.

Set production values for:

- `CORS_ALLOW_ORIGINS`
- `NEXT_PUBLIC_CLIMATE_API_BASE`
- `NEXT_PUBLIC_MAP_ASSET_BASE`
- release/data paths if custom

For IP-only testing, use:

- `NEXT_PUBLIC_CLIMATE_API_BASE=http://<PUBLIC_IP>`
- `NEXT_PUBLIC_MAP_ASSET_BASE=http://<PUBLIC_IP>`
- `CORS_ALLOW_ORIGINS=http://<PUBLIC_IP>`

Then reload services:

```bash
sudo systemctl restart climate-backend climate-web caddy
```

## 8) Verify IP-based Runtime

From your local machine:

```bash
curl -fsS http://<PUBLIC_IP>/healthz
curl -fsS http://<PUBLIC_IP>/api/v/latest/release
```

If both pass, open `http://<PUBLIC_IP>` in browser and validate web + API integration.

## 9) Deploy Updates

On the VM:

```bash
sudo ./scripts/deploy/deploy_app.sh --ref main
```

This script updates source, rebuilds backend/web assets, restarts services, and runs smoke checks.

## 10) Verify Services (VM-local)

```bash
systemctl is-active climate-backend
systemctl is-active climate-web
systemctl is-active caddy
curl -fsS http://127.0.0.1:8001/healthz
curl -fsS http://127.0.0.1:8001/api/v/latest/release
```

## 11) Add Domain and TLS Later

Once domain is chosen:

- map DNS `A` record to the VM public IP
- update Caddy site label from `:80` to `your-domain.example`
- update env URLs and CORS to `https://your-domain.example`
- restart `caddy`, `climate-backend`, `climate-web`

## 12) Basic Monitoring Setup

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

## 13) Security Baseline Checklist

- SSH keys only, root login disabled
- CORS restricted to your production domain(s)
- API exposed only through Caddy
- backend and web running as non-root `climate` user
- unattended upgrades enabled
- fail2ban + ufw active

## Notes

- API rate limiting is enabled in backend middleware by default via:
  - `RATE_LIMIT_ENABLED=1`
  - `RATE_LIMIT_SUSTAINED_RPS=5`
  - `RATE_LIMIT_BURST=20`
  - `RATE_LIMIT_WINDOW_S=10`
- For multi-instance deployments, replace local in-process rate limiting with shared-state limits (e.g., Redis + gateway/WAF policy).

## Automation Strategy (Recommendation)

Current recommendation:

- keep Terraform for reproducible infra provisioning (VM, IP, firewall)
- keep GitHub key registration manual in V1 (one-off bootstrap, low repetition)
- optionally automate GitHub key registration in V2 via `gh` CLI + PAT or GitHub App credentials

Rationale:

- Terraform prevents drift and makes rebuild/migration deterministic
- GitHub SSH key setup is sensitive and account-scoped; full automation adds secret-management complexity early
