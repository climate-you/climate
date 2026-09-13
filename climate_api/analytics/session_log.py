"""Render a stored chat session as a plain-text log.

The admin UI shows one message at a time, which is the wrong shape for working
out why a late answer in a long conversation failed: the cause is usually
everything that came before it. This renders a whole session in the order it
happened, with the timings, tool calls and token counts that the per-message
view keeps folded away.
"""

from __future__ import annotations

import datetime
import json

_SEPARATOR = "=" * 78
_INDENT = "    "


def _utc(ts: int | float | None) -> str:
    if ts is None:
        return "unknown"
    return datetime.datetime.fromtimestamp(ts, datetime.timezone.utc).strftime(
        "%Y-%m-%d %H:%M:%S UTC"
    )


def _ms(value: int | None) -> str:
    if value is None:
        return "?"
    return f"{value / 1000:.1f}s" if value >= 1000 else f"{value}ms"


def _indent_block(text: str) -> str:
    """Indent a multi-line value so it cannot be mistaken for a log field."""
    if not text:
        return f"{_INDENT}(empty)"
    return "\n".join(f"{_INDENT}{line}" for line in text.splitlines())


def _steps_line(steps: list[dict]) -> list[str]:
    """One line per step: latency and, when recorded, the token counts."""
    lines = []
    for s in steps:
        parts = [f"step {s.get('step', '?')}", f"model {_ms(s.get('model_ms'))}"]
        if s.get("tools_ms") is not None:
            parts.append(f"tools {_ms(s.get('tools_ms'))}")
        prompt_tokens = s.get("prompt_tokens")
        completion_tokens = s.get("completion_tokens")
        if prompt_tokens is not None or completion_tokens is not None:
            parts.append(f"{prompt_tokens or 0}p + {completion_tokens or 0}c tokens")
        if s.get("error"):
            parts.append("ERROR")
        lines.append(f"{_INDENT}{'  '.join(parts)}")
    return lines


def _message_block(index: int, total: int, m: dict) -> list[str]:
    lines = [
        _SEPARATOR,
        f"[{index}/{total}] {_utc(m.get('ts'))}  message_id={m.get('message_id')}",
        "",
        "Q: " + (m.get("question") or "(empty)"),
        "",
    ]

    meta = [
        f"tier={m.get('tier')}",
        f"model={m.get('model')}",
        f"steps={m.get('step_count')}",
        f"total={_ms(m.get('total_ms'))}",
    ]
    if m.get("model_override"):
        meta.append(f"override={m['model_override']}")
    if m.get("rejected_tiers"):
        meta.append(f"rejected={','.join(m['rejected_tiers'])}")
    if m.get("feedback"):
        meta.append(f"feedback={m['feedback']}")
    if m.get("opt_out"):
        meta.append("opt_out=true")
    if m.get("question_id"):
        meta.append(f"question_id={m['question_id']}")
    lines.append(_INDENT + "  ".join(meta))

    steps = m.get("steps_timing") or []
    if steps:
        lines.append("")
        lines.append(f"{_INDENT}Timing:")
        lines.extend(_steps_line(steps))

    tool_calls = m.get("tool_calls_detail") or []
    if tool_calls:
        lines.append("")
        lines.append(f"{_INDENT}Tool calls:")
        for tc in tool_calls:
            args = json.dumps(tc.get("args", {}), sort_keys=True)
            lines.append(
                f"{_INDENT}  step {tc.get('step', '?')}  {tc.get('name')}({args})"
            )
    elif m.get("tools_called"):
        # Older rows recorded only the names, before args were stored.
        lines.append("")
        lines.append(f"{_INDENT}Tools called: {', '.join(m['tools_called'])}")

    if m.get("error"):
        lines.append("")
        lines.append(f"{_INDENT}ERROR: {m['error']}")

    lines.append("")
    lines.append("A:")
    lines.append(_indent_block(m.get("answer") or ""))
    lines.append("")
    return lines


def format_session_log(messages: list[dict], session_id: str = "") -> str:
    """Render one session's messages, oldest first, as a readable log."""
    now = _utc(datetime.datetime.now(datetime.timezone.utc).timestamp())
    if not messages:
        return f"No messages found for session '{session_id}'.\nExported {now}\n"

    session_ids = sorted({m.get("session_id", "") for m in messages})
    header = [
        "Climate assistant — session log",
        f"Session:  {', '.join(session_ids) or session_id}",
        f"Messages: {len(messages)}",
        f"First:    {_utc(messages[0].get('ts'))}",
        f"Last:     {_utc(messages[-1].get('ts'))}",
        f"Exported: {now}",
    ]
    if len(session_ids) > 1:
        header.append(
            f"NOTE: the id given matched {len(session_ids)} sessions; all are included."
        )
    header.append("")

    body: list[str] = []
    for i, m in enumerate(messages, start=1):
        body.extend(_message_block(i, len(messages), m))
    body.append(_SEPARATOR)
    return "\n".join(header + body) + "\n"


def session_log_filename(session_id: str) -> str:
    """`session_<first 8 chars>.log`, with anything path-unsafe dropped."""
    safe = "".join(c for c in session_id if c.isalnum() or c in "-_")[:8]
    return f"session_{safe or 'unknown'}.log"
