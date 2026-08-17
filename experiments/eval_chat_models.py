#!/usr/bin/env python3
"""Compare chat models by running sample questions through the real ChatOrchestrator.

This drives climate_api.chat.orchestrator.ChatOrchestrator — the exact
production system prompt, tool schemas, and dispatch — with one single-model
tier per candidate, so differences in tool-call quality are attributable to
the model alone. It replaced an earlier standalone proof-of-concept harness
that carried its own copy of the agentic loop and had drifted out of sync
with production.

Usage:
    export GROQ_API_KEY_FREE=$(cat ~/.groq_api_key_free)   # or rely on the file fallback
    python experiments/eval_chat_models.py
    python experiments/eval_chat_models.py --models openai/gpt-oss-120b openai/gpt-oss-20b
    python experiments/eval_chat_models.py --questions "How hot is Rome?" --sleep 0

Writes a JSON transcript and a side-by-side Markdown report.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from climate_api.chat.orchestrator import ChatOrchestrator, ProviderTier
from climate_api.store.location_index import LocationIndex
from climate_api.store.tile_data_store import TileDataStore

DEFAULT_MODELS = [
    "openai/gpt-oss-120b",  # prod primary (Tiers 1-2)
    "openai/gpt-oss-20b",  # prod degraded fallback (Tier 3) and dev default
    "qwen/qwen3.6-27b",  # alternative small model, available as a dev override
]

# Mix of question-tree questions (global/city/local scopes, all datasets) and
# free-form ones exercising seasonal filters, comparisons, and the newly
# exposed monthly min/max metrics.
DEFAULT_QUESTIONS = [
    "How has air temperature changed globally?",
    "Which continent is warming the fastest?",
    "How have global sea surface temperatures changed?",
    "What is the hottest capital city in the world?",
    "What capital city sees the least rain?",
    "How has the temperature changed in Paris?",
    "How have winters changed in Stockholm?",
    "Compare temperatures in London and Madrid.",
    "Which capital city has recorded the highest temperature ever?",
    "How cold do winter nights get in Winnipeg?",
]


def _load_api_key() -> str:
    import os

    key = os.environ.get("GROQ_API_KEY_FREE") or os.environ.get("GROQ_API_KEY")
    if key:
        return key.strip()
    key_file = Path.home() / ".groq_api_key_free"
    if key_file.exists():
        return key_file.read_text(encoding="utf-8").strip()
    print(
        "ERROR: set GROQ_API_KEY_FREE (or GROQ_API_KEY), or create ~/.groq_api_key_free",
        file=sys.stderr,
    )
    raise SystemExit(1)


def _build_orchestrator(model: str, api_key: str, release: str) -> ChatOrchestrator:
    from groq import Groq

    tier = ProviderTier(
        name=model,
        client=Groq(api_key=api_key),
        model=model,
        is_degraded=False,
        max_request_tokens=None,
    )
    series_root = REPO_ROOT / "data" / "releases" / release / "series"
    tile_store = TileDataStore.discover(
        series_root, metrics_path=REPO_ROOT / "registry" / "metrics.json"
    )
    location_index = LocationIndex(
        REPO_ROOT / "data" / "locations" / "locations.index.csv"
    )
    country_names = json.loads(
        (REPO_ROOT / "data" / "locations" / "country_names.json").read_text(
            encoding="utf-8"
        )
    )
    return ChatOrchestrator(
        tiers=[tier],
        tile_store=tile_store,
        location_index=location_index,
        country_names=country_names,
    )


def _run_question(orchestrator: ChatOrchestrator, question: str) -> dict:
    tool_calls: list[dict] = []
    errors: list[str] = []
    answer_parts: list[str] = []
    done: dict = {}
    t0 = time.monotonic()
    try:
        for event in orchestrator.run(question):
            etype = event.get("type")
            if etype == "tool_call":
                tool_calls.append(
                    {"step": event["step"], "name": event["name"], "args": event["args"]}
                )
            elif etype == "answer":
                answer_parts.append(event.get("text", ""))
            elif etype == "error":
                errors.append(event.get("detail") or event.get("message", ""))
            elif etype == "done":
                done = event
    except Exception as exc:  # provider/network failures shouldn't kill the suite
        errors.append(f"{type(exc).__name__}: {exc}")
    return {
        "question": question,
        "answer": "\n".join(p for p in answer_parts if p),
        "tool_calls": tool_calls,
        "errors": errors,
        "step_count": done.get("step_count"),
        "total_ms": done.get("total_ms", round((time.monotonic() - t0) * 1000)),
        "charts": [c.get("title", "") for c in done.get("charts") or []],
        "locations": done.get("locations") or [],
    }


def _fmt_tool_call(tc: dict) -> str:
    args = ", ".join(f"{k}={v!r}" for k, v in tc["args"].items())
    return f"step {tc['step']}: {tc['name']}({args})"


def _write_markdown(path: Path, models: list[str], results: dict, questions: list[str]) -> None:
    lines = [
        "# Chat model comparison",
        "",
        f"Generated: {datetime.now(timezone.utc).isoformat(timespec='seconds')}",
        f"Models: {', '.join(models)}",
        "",
        "## Summary",
        "",
        "| Model | Answered | Errors | Avg steps | Avg time (s) | Avg tool calls |",
        "|---|---|---|---|---|---|",
    ]
    for model in models:
        runs = results[model]
        answered = sum(1 for r in runs if r["answer"] and not r["errors"])
        errs = sum(len(r["errors"]) for r in runs)
        steps = [r["step_count"] for r in runs if r["step_count"]]
        times = [r["total_ms"] for r in runs if r["total_ms"]]
        ncalls = [len(r["tool_calls"]) for r in runs]
        avg_steps = f"{sum(steps)/len(steps):.1f}" if steps else "-"
        avg_time = f"{sum(times)/len(times)/1000:.1f}" if times else "-"
        avg_calls = f"{sum(ncalls)/len(ncalls):.1f}" if ncalls else "-"
        lines.append(
            f"| {model} | {answered}/{len(runs)} | {errs} | {avg_steps} | {avg_time} | {avg_calls} |"
        )
    lines.append("")
    for qi, question in enumerate(questions):
        lines += [f"## Q{qi + 1}: {question}", ""]
        for model in models:
            r = results[model][qi]
            secs = f"{r['total_ms'] / 1000:.1f}s" if r["total_ms"] else "?"
            lines += [f"### {model} — {r['step_count'] or '?'} steps, {secs}", ""]
            if r["tool_calls"]:
                lines += ["```"] + [_fmt_tool_call(tc) for tc in r["tool_calls"]] + ["```", ""]
            else:
                lines += ["_No tool calls._", ""]
            if r["errors"]:
                lines += ["**Errors:**"] + [f"- {e}" for e in r["errors"]] + [""]
            if r["charts"]:
                lines += [f"**Charts:** {', '.join(r['charts'])}", ""]
            lines += [r["answer"] or "_No answer._", ""]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--models", nargs="+", default=DEFAULT_MODELS, metavar="MODEL_ID")
    ap.add_argument("--questions", nargs="+", default=DEFAULT_QUESTIONS)
    ap.add_argument("--release", default="dev")
    ap.add_argument("--sleep", type=float, default=3.0, help="Pause between questions (s)")
    ap.add_argument(
        "--out-dir",
        type=Path,
        default=REPO_ROOT / "experiments" / "output",
        help="Directory for the JSON transcript and Markdown report",
    )
    args = ap.parse_args()

    api_key = _load_api_key()
    args.out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")

    results: dict[str, list[dict]] = {}
    for model in args.models:
        print(f"=== {model} ===")
        orchestrator = _build_orchestrator(model, api_key, args.release)
        runs: list[dict] = []
        for question in args.questions:
            print(f"  {question} ...", end="", flush=True)
            r = _run_question(orchestrator, question)
            status = "ERROR" if r["errors"] else "ok"
            print(
                f" {status} ({r['step_count']} steps, {len(r['tool_calls'])} calls, "
                f"{(r['total_ms'] or 0) / 1000:.1f}s)"
            )
            runs.append(r)
            time.sleep(args.sleep)
        results[model] = runs

    json_path = args.out_dir / f"chat-model-eval-{stamp}.json"
    md_path = args.out_dir / f"chat-model-eval-{stamp}.md"
    json_path.write_text(
        json.dumps({"models": args.models, "results": results}, indent=2),
        encoding="utf-8",
    )
    _write_markdown(md_path, args.models, results, args.questions)
    print(f"\nTranscript: {json_path}\nReport:     {md_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
