# Public Server Deployment Plan (VM-first)

## Goal

Deploy the Climate backend + web demo on a public cloud VM with:

- always-on services with automatic restart
- basic observability for CPU/memory/errors and leak detection
- abuse controls (rate limiting, concurrency limits)
- baseline hardening against malicious traffic
- no filesystem browsing exposure
- reproducible provisioning that can move across VM types/providers

This is an implementation plan only. No implementation is included in this phase.

## Decision Locked (V1)

These decisions are confirmed and are the implementation baseline:

- Cloud provider: `GCP`
- Initial VM type: `e2-standard-2` (region chosen close to primary users)
- Reverse proxy: `Caddy`
- Frontend runtime: `Next.js server mode` (revisit static export in V2)
- Initial traffic assumption:
  - baseline concurrency: `1-5`
  - short peak concurrency: `20-30`
  - daily API requests: `~1,000-10,000`
- Initial API rate limit policy:
  - per-IP sustained: `5 req/s`
  - per-IP burst: `20 req/s`
  - endpoint-specific tighter limits for expensive routes if needed
- Alert channel for V1: `Email`

Implementation note:

- This section takes precedence over earlier open-question text below, which is retained as discussion history.

## Current Status

Last updated: 2026-02-26

Implemented in repository:

- Backend:
  - added `GET /healthz`
  - added env-driven production CORS controls
  - added API rate-limiting middleware defaults (`5 req/s` sustained, `20` burst)
- Deployment scaffolding:
  - `deploy/systemd/*.service`
  - `deploy/proxy/Caddyfile`
  - `deploy/env/*.env.example`
  - `scripts/deploy/bootstrap_vm.sh`
  - `scripts/deploy/deploy_app.sh`
  - `scripts/deploy/smoke_check.sh`
- GCP IaC scaffold:
  - `infra/terraform/gcp/*`
- Runbook:
  - `docs/runbooks/deployment.md`
  - added first-SSH (`gcloud compute ssh`) and GitHub key-based clone workflow
- Tests:
  - added/updated unit tests for config, `/healthz`, and rate limiting

Phase tracking:

- Phase 0 (Decisions): completed
- Phase 1 (VM/Network): in progress (Terraform + runbook prepared; VM not yet provisioned)
- Phase 2 (Runtime/systemd): in progress (units/scripts prepared; not yet validated on live VM)
- Phase 3 (Proxy/TLS/routing): in progress (Caddy template prepared; live validation pending)
- Phase 4 (Hardening/abuse controls): in progress (baseline implemented; live tuning pending)
- Phase 5 (Monitoring/alerting): not started
- Phase 6 (Cross-cloud reproducibility validation): not started

## Recommended Target Architecture (V1)

Single VM, reverse-proxied:

- `Caddy` or `Nginx` on `:80/:443` (TLS, routing, basic protection)
- `backend` FastAPI service on localhost (systemd-managed)
- `frontend` Next.js production service on localhost (systemd-managed) or static export served by proxy
- optional `Redis` for cache/rate-limit state
- host firewall + fail2ban + cloud security group

Routing:

- `/api/*` -> backend
- `/*` -> frontend

Why this first:

- low operational complexity
- cheap and quick to operate
- easy to lift-and-shift later to container/orchestrated setup

## Cloud VM Sizing Suggestions

Start with general-purpose burstable/entry medium and scale from metrics:

- AWS: `t4g.medium` (ARM) or `t3.medium` (x86)
- GCP: `e2-standard-2`
- Azure: `B2s` (cost-focused) or `D2as_v5` (steady workloads)

Recommended baseline:

- `2 vCPU`, `4-8 GB RAM`, `40-80 GB SSD`
- Ubuntu 24.04 LTS

Selection notes:

- pick x86 if dependency compatibility is uncertain
- pick ARM for cost/perf if Python/Node dependencies are confirmed compatible
- scale up when p95 latency and memory headroom indicate pressure, not preemptively

## Reliability: Keep Backend/Frontend Running

### Process management

Use `systemd` units:

- `climate-backend.service`
- `climate-web.service`

Unit behavior:

- `Restart=always`
- `RestartSec=3`
- startup dependency ordering (`After=network-online.target`)
- dedicated non-root service user
- explicit working directory and env files
- journald logging

### Service health

- reverse proxy health checks/upstream fail behavior
- backend `/healthz` endpoint (or equivalent lightweight endpoint)
- web readiness endpoint (or root route check)

### Restart/deploy strategy

- rolling service restart by unit (`systemctl restart ...`) after artifact update
- `ExecStartPre` smoke checks where applicable
- optional blue/green later (out of V1 scope)

## Monitoring and Leak Detection

### Metrics and logs (V1 minimal)

- node_exporter + Prometheus + Grafana (or cloud-native equivalent)
- journald forwarding (or Loki/Promtail if desired)

Track at minimum:

- VM CPU %, load average
- VM memory used/free, swap usage
- process RSS for backend/web
- request rate, error rate (4xx/5xx), latency p50/p95/p99
- restart counts for both services

### Alerts

- CPU > 85% for 10m
- memory > 85% for 10m
- swap usage > threshold
- service restart bursts (e.g., >3 in 10m)
- sustained 5xx above baseline

### Leak validation workflow

- baseline RSS after boot
- observe RSS trend over 24-72h under representative traffic
- run synthetic load test and compare pre/post RSS and GC behavior
- define acceptable growth budget; fail if exceeded

## Abuse Prevention (Overload by One User)

Apply controls at reverse proxy and app layers.

### Edge/proxy rate limiting

- IP-based request rate limits on `/api/*`
- burst + sustained windows (example: `30 req/s` burst, `5-10 req/s` sustained)
- connection/request timeout caps
- max request body size

### Backend safeguards

- strict per-endpoint timeouts
- bounded worker/concurrency settings
- cache hot expensive responses where safe
- reject malformed/oversized query params early

### Optional stronger controls

- API key gating for non-public/high-cost endpoints
- Redis-backed distributed rate limits (if scaling beyond one VM)

## Malicious Usage Mitigation

Defense-in-depth baseline:

- TLS everywhere (Let’s Encrypt via proxy)
- security headers (HSTS, X-Frame-Options, etc.)
- WAF/CDN in front later if abuse increases (Cloudflare/AWS WAF)
- fail2ban for repeated hostile patterns
- regular OS security updates (`unattended-upgrades`)
- strict SSH policy:
  - key-only auth
  - disable root SSH login
  - non-default user + sudo
  - optional allowlist on admin IPs

Application hardening:

- input validation for all query/path parameters
- CORS restricted to expected domain(s)
- no debug mode in production
- sanitized error responses (no stack traces to clients)

## Prevent Filesystem Browsing

- serve only explicit frontend assets and API routes
- disable directory listing in reverse proxy
- never mount repository path as static root except intended built assets
- run backend/web under non-root service user with minimal permissions
- isolate secrets in env files with tight file modes
- disable shell execution paths from user input (audit endpoint code)

## Reproducible Setup Across Clouds

## Provisioning strategy

Use Infrastructure as Code + idempotent bootstrap:

- Terraform for VM/network/security-group primitives
- Ansible (or shell bootstrap) for instance configuration
- versioned env template and systemd unit templates in repo

Repository additions planned:

- `infra/terraform/<provider>/...`
- `infra/ansible/...` or `scripts/deploy/bootstrap_vm.sh`
- `deploy/systemd/*.service`
- `deploy/proxy/{Caddyfile|nginx.conf}`
- `deploy/env/*.env.example`
- `docs/runbooks/deployment.md`

Reproducibility requirements:

- pin OS family/version
- pin major runtime versions (Python, Node)
- deterministic install steps
- one-command bootstrap + one-command deploy
- post-provision smoke tests

## Phased Implementation Plan

### Phase 0: Decisions and Baseline

- choose first provider + region
- choose proxy (`Caddy` recommended for simpler TLS)
- choose runtime mode for web:
  - Next.js server mode (simpler parity)
  - static export + proxy (lower runtime overhead)
- define expected traffic envelope for rate-limit tuning

Deliverables:

- finalized architecture decision record
- initial VM sizing decision

### Phase 1: VM and Network Foundation

- provision VM, static IP, DNS record
- configure cloud firewall/security group (allow 22,80,443 only)
- harden SSH and OS baseline packages

Deliverables:

- reachable hardened VM
- DNS resolving to VM

### Phase 2: Runtime and Service Supervision

- install pinned Python/Node runtime stack
- configure backend and web as systemd services
- configure env files and working directories
- verify autorestart behavior with crash simulation

Deliverables:

- both services start on boot
- crash-restart validated

### Phase 3: Reverse Proxy, TLS, and Routing

- install/configure proxy
- route `/api/*` to backend and `/` to frontend
- enable TLS certificate automation
- disable directory listing and set security headers

Deliverables:

- HTTPS public endpoint working
- direct backend port not publicly exposed

### Phase 4: Abuse Controls and Security Hardening

- apply rate limits and timeout ceilings
- add fail2ban and request-size controls
- tighten CORS and production flags
- validate no sensitive path exposure

Deliverables:

- documented anti-abuse settings
- security checklist pass

### Phase 5: Monitoring and Alerting

- deploy metrics/log pipeline (Prometheus/Grafana or cloud-native)
- add dashboards for host + process + HTTP metrics
- configure alert rules for CPU/memory/errors/restarts

Deliverables:

- dashboard links + alert channels
- leak-detection runbook

### Phase 6: Reproducible Deploy Automation

- codify provisioning with Terraform + Ansible/bootstrap
- create deployment script (build, sync artifact, restart units, smoke test)
- verify on a fresh VM type/provider variant

Deliverables:

- repeatable end-to-end deployment from clean VM
- documented migration steps between VM families/providers

## Validation Checklist Per Release

- `systemctl is-active climate-backend` == active
- `systemctl is-active climate-web` == active
- HTTPS certificate valid and auto-renew configured
- `/api/*` rate limit enforced
- p95 latency within target under smoke load
- memory trend stable after 24h
- no unintended filesystem path exposure
- reboot test: services auto-start and pass smoke checks

## Risks and Mitigations

- under-sized VM causes noisy throttling: start with 2 vCPU and monitor headroom
- rate limits too strict break UX: tune with real traffic and endpoint classes
- memory growth from data/cache paths: add capped caches and restart alarms
- single-VM SPOF: accept for V1, plan multi-instance + managed DB/cache in V2

## Open Questions for Next Review Round

1. Preferred cloud provider for V1 (AWS/GCP/Azure/other)?

- [Benoit] I'm more familiar with GCP so let's go with it at first, I can revisit if another provider is cheaper.
- [Codex] Acknowledged. We will target GCP for V1. Recommended starting point: `e2-standard-2` in a region close to your users, then right-size after 1-2 weeks of metrics.

2. Proxy preference: Caddy (simpler TLS) vs Nginx (more common/custom)?

- [Benoit] I would say simpler is better here, so let's go with Caddy.
- [Codex] Acknowledged. We will standardize on Caddy for V1 to reduce operational complexity (TLS automation, concise config, easy reverse proxy routing).

3. Web runtime preference: Next.js server mode vs static export?

- [Benoit] Current version runs as Next.js so I think we should keep it? I'm not sure I fully understand pros/cons and amount of work of a "static export", can you detail?
- [Codex] Recommendation: keep Next.js server mode for V1. It preserves current behavior and minimizes change risk during first deployment.
- [Codex] Summary of tradeoffs:
  - Next.js server mode: lowest migration effort; supports dynamic behavior without refactor; higher runtime footprint than static.
  - Static export: lower CPU/RAM and simpler serving, but only works if pages/features are compatible with static generation; usually requires code and routing adjustments.
- [Codex] Follow-up for next round: unless you want to optimize hosting cost immediately, I suggest we lock "Next.js server mode in V1" and revisit static export in V2.
- [Benoit] Let's lock "Next.js" and revisit static export in v2.

4. Expected initial traffic (requests/min and concurrent users) for rate-limit tuning?

- [Benoit] I expect low traffic at first:
  - a few beta testers testing the website several times over a week or two
  - later, more traffic as I post about the website publicly, but it's still a personal project with no marketing, etc. so I think we should expect low traffic, but I'm not sure how it translates into numbers.
- [Codex] Acknowledged. For V1 we can assume low traffic and start with conservative limits, then tune from logs.
- [Codex] Proposed initial planning envelope:
  - baseline: 1-5 concurrent users
  - short peaks: 20-30 concurrent users
  - request volume: roughly 1,000-10,000 API requests/day
- [Codex] Proposed initial limit policy (adjust after observation): per-IP sustained `5 req/s`, burst `20 req/s`, with tighter limits on heavy endpoints if needed.
- [Benoit] These numbers sound good.

5. Alert destination preference (email/Slack/other)?

- [Benoit] email is fine for now.
- [Codex] Acknowledged. We will use email alerts for V1 and keep the alerting pipeline compatible with later Slack/PagerDuty integration.
