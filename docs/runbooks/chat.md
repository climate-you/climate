# Runbook: Chat AI Assistant

This runbook covers setup, configuration, and operation of the LLM-powered chat assistant (`/api/chat`).

## Overview

The chat assistant answers questions about climate data using an agentic loop: it calls internal data tools, then synthesises a natural-language answer. It is powered by Groq-hosted LLMs with a local Ollama fallback option.

The feature is **disabled by default** and must be explicitly enabled via env vars.

---

## 1. Backend Environment Variables

All variables go in `/etc/climate/backend.env` (production) or your local shell / `.env` file.

| Variable | Default | Description |
|---|---|---|
| `CHAT_ENABLED` | `0` | Set to `1` to activate the `/api/chat` endpoint |
| `CHAT_DEV_MODE` | `1` (safe) | `1` = dev/8b chain; `0` = prod/70b chain. **Always set to `0` in production.** |
| `GROQ_API_KEY_FREE` | — | Groq free-tier API key. Required in both dev and prod chains. Also accepted as `GROQ_API_KEY` for backward compatibility. |
| `GROQ_API_KEY_PAID` | — | Groq paid API key. Optional; only used in prod chain as Tier 2. |
| `GROQ_MODEL_PRIMARY` | `llama-3.3-70b-versatile` | 70b model used in prod chain Tiers 1 and 2. |
| `GROQ_MODEL_FALLBACK` | `llama-3.1-8b-instant` | 8b model used as Tier 3 in prod chain and Tier 1 in dev chain. |
| `OLLAMA_BASE_URL` | `` (disabled) | Base URL of a local Ollama instance (e.g. `http://localhost:11434`). Dev chain only. |
| `OLLAMA_MODEL` | `qwen2.5:14b` | Model to use via Ollama. Dev chain only. |
| `CHAT_MAX_STEPS` | `5` | Maximum tool-calling iterations per question before giving up. |

---

## 2. Fallback Chain

### Production chain (`CHAT_DEV_MODE=0`)

| Tier | Model | Key used | Condition |
|---|---|---|---|
| 1 | `llama-3.3-70b-versatile` | Free | Default |
| 2 | `llama-3.3-70b-versatile` | Paid | Tier 1 hits daily token quota (TPD) |
| 3 | `llama-3.1-8b-instant` | Free | Tier 2 also exhausted; shows degraded-model disclaimer to user |
| — | Static message | — | All tiers exhausted |

When the 8b fallback (Tier 3) is used, the frontend displays an amber notice above the answer:
> "Daily allowance exceeded, degraded model is used, accuracy might be lower."

### Dev chain (`CHAT_DEV_MODE=1`, the default)

| Tier | Model | Key used | Condition |
|---|---|---|---|
| 1 | `llama-3.1-8b-instant` | Free | Default |
| 2 | `qwen2.5:14b` (Ollama) | — | 8b quota exhausted (only if `OLLAMA_BASE_URL` is set) |
| — | Static message | — | All tiers exhausted |

The paid key is never used in dev mode. The 70b free allowance is preserved for production.

---

## 3. Getting API Keys

1. Create a free account at [console.groq.com](https://console.groq.com)
2. Generate a key under **API Keys** → **Create API key**
3. Set it as `GROQ_API_KEY_FREE` in your env file

For the paid key (Tier 2 prod fallback), add a payment method and generate a second key (`GROQ_API_KEY_PAID`). It is only billed when the free daily quota is exhausted.

---

## 4. Local Development Setup

```bash
# Minimum to run chat locally (dev chain, 8b model)
export CHAT_ENABLED=1
# CHAT_DEV_MODE defaults to 1, no need to set it
export GROQ_API_KEY_FREE=<your-free-key>

uvicorn climate_api.main:app --reload
```

Then in the frontend, visit `http://localhost:3000?feature=chat_bot` to activate the feature flag in your browser. The chat button appears at the bottom-right of the map.

To use the local Ollama fallback (dev Tier 2):

```bash
# 1. Install Ollama (macOS/Linux)
curl -fsSL https://ollama.com/install.sh | sh

# 2. Pull the model (~9 GB download, requires at least 16 GB RAM)
ollama pull qwen2.5:14b

# 3. Start the Ollama server (runs on port 11434 by default)
ollama serve

# 4. Set the env var and restart the backend
export OLLAMA_BASE_URL=http://localhost:11434
```

Ollama starts automatically as a background service on macOS after installation; `ollama serve` is only needed if it isn't already running. Verify with `curl http://localhost:11434/api/tags`.

To test the production chain locally (uses 70b, burns free quota):

```bash
export CHAT_DEV_MODE=0
```

To see the dev model toggle in the chat UI, append `&debug=on` to the URL.

---

## 5. Activating the Feature for Users

The chat widget is hidden behind a localStorage feature flag. Users activate it by visiting the site with `?feature=chat_bot` in the URL:

```
https://your-domain.com?feature=chat_bot
```

The flag is written to `localStorage` and the param is stripped from the URL. The widget stays active until `localStorage` is cleared.

To deactivate for a specific user, they can clear their browser's localStorage for the site.

---

## 6. Production Deployment Checklist

- [ ] `CHAT_ENABLED=1` in `/etc/climate/backend.env`
- [ ] `CHAT_DEV_MODE=0` in `/etc/climate/backend.env`
- [ ] `GROQ_API_KEY_FREE` set to a valid Groq free key
- [ ] `GROQ_API_KEY_PAID` set (optional, but recommended to avoid the 8b fallback during busy periods)
- [ ] Backend restarted: `sudo systemctl restart climate-backend`
- [ ] Verify endpoint responds: `curl -s http://127.0.0.1:8001/api/chat` (should return 405, not 404)

---

## 7. Monitoring

Chat sessions are recorded in the analytics DB (`data/analytics/events.db`, table `chat_sessions`).

The `/admin` dashboard **Chat tab** exposes:
- Stats: total sessions, avg step count, avg response time, p95 response time, thumbs-up/down counts
- All sessions list: paginated log with tier, step count, response time, feedback; expandable to show tool calls and per-step timing breakdown
- Bad answers inbox: sessions marked "bad" by users, pending review (shown as a badge on the tab)

You can also query the DB directly:

```bash
sqlite3 data/analytics/events.db \
  "SELECT ts, question, tier, step_count, total_ms, feedback FROM chat_sessions ORDER BY ts DESC LIMIT 20;"
```

### Schema validation

At startup the backend calls `check_schema()` on the analytics DB. If required columns are missing (e.g. after an upgrade that added new columns), the backend will **refuse to start** with a clear error message including the exact sqlite3 command to wipe the stale tables:

```bash
sqlite3 data/analytics/events.db \
  "DROP TABLE IF EXISTS chat_sessions; DROP TABLE IF EXISTS click_events; DROP TABLE IF EXISTS session_events;"
```

After wiping, restart the backend — it will recreate all tables with the current schema.

---

## 8. Troubleshooting

**Chat button doesn't appear**
- Confirm the browser has the feature flag set: open DevTools → Application → Local Storage → check for `climate.chatBotEnabled = 1`
- If missing, revisit the URL with `?feature=chat_bot`

**`/api/chat` returns 404**
- `CHAT_ENABLED` is not set or not set to `1` — check backend env and restart

**All answers return the "budget exhausted" static message**
- The Groq free key's daily token quota is exhausted
- In prod: ensure `GROQ_API_KEY_PAID` is set so Tier 2 can take over
- In dev: wait for the quota to reset (resets at midnight UTC)

**Answers are slow or wrong (8b fallback in prod)**
- The free 70b quota is exhausted and the paid key isn't set
- Add `GROQ_API_KEY_PAID` or wait for the daily reset
- The amber notice in the UI will tell users accuracy may be lower

**Local Ollama fallback not activating**
- Check `OLLAMA_BASE_URL` is set and Ollama is running: `curl http://localhost:11434/api/tags`
- Check the model is pulled: `ollama list`
