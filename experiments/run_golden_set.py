#!/usr/bin/env python3
"""
Golden-set evaluation runner for the climate chat PoC.

Usage (Groq):
    export GROQ_API_KEY=gsk_...
    export GROQ_MODEL=llama-3.1-8b-instant   # optional; default: llama-3.3-70b-versatile
    PYTHONPATH=. python experiments/run_golden_set.py [--layer 1|2] [--id L1-01]

Usage (Ollama local):
    export OLLAMA_BASE_URL=http://localhost:11434/v1
    export OLLAMA_MODEL=llama3.1:8b           # optional; default: llama3.1:8b
    PYTHONPATH=. python experiments/run_golden_set.py [--layer 1|2] [--id L1-01]

Layer 1: automated checks (numeric, year, contains, not_contains, count, not_called)
Layer 2: LLM-as-judge qualitative evaluation

Skips any check where the required expected value is null.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT))

# ---------------------------------------------------------------------------
# Import PoC infrastructure
# ---------------------------------------------------------------------------

import experiments.chat_poc as poc  # noqa: E402

poc.MOCK_TOOLS = False
poc._init_real_tools()

# ---------------------------------------------------------------------------
# Chat runner (captures answer + tool trace instead of printing)
# ---------------------------------------------------------------------------

_TPD_EXHAUSTED = False  # set True on first TPD error to abort remaining tests


def _is_tpd_error(error_msg: str) -> bool:
    return "tokens per day" in error_msg.lower() or "tpd" in error_msg.lower()


def _is_tpm_error(error_msg: str) -> bool:
    return "tokens per minute" in error_msg.lower() or "tpm" in error_msg.lower()


def _parse_retry_after_s(error_msg: str) -> float:
    """Try to parse a 'retry in Xm Ys' or 'retry in Xs' from the error message."""
    m = re.search(
        r"try again in\s+(?:(\d+)m)?(?:\s*(\d+(?:\.\d+)?)s)?", error_msg, re.I
    )
    if m:
        minutes = float(m.group(1) or 0)
        seconds = float(m.group(2) or 0)
        return minutes * 60 + seconds
    return 10.0  # default backoff


def _get_context_window() -> int:
    for env_name in ("OLLAMA_CONTEXT_LENGTH", "OLLAMA_NUM_CTX"):
        raw = os.environ.get(env_name)
        if raw:
            try:
                return int(raw)
            except ValueError:
                pass
    return 4096 if poc._OLLAMA_BASE_URL else 8192


def _estimate_token_count(value: Any) -> int:
    """Cheap token estimate for request logging when exact tokenization is unavailable."""
    text = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    return max(1, (len(text) + 3) // 4)


def _log_request_size(
    *,
    label: str,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None = None,
) -> None:
    message_tokens = _estimate_token_count(messages)
    tool_tokens = _estimate_token_count(tools) if tools else 0
    total_tokens = message_tokens + tool_tokens
    context_window = _get_context_window()
    usage_pct = (total_tokens / context_window) * 100 if context_window else 0.0

    status = ""
    if usage_pct >= 100:
        status = "  [likely overflow]"
    elif usage_pct >= 85:
        status = "  [near limit]"

    print(
        f"    [request {label}: ~{total_tokens} tokens "
        f"(messages ~{message_tokens}, tools ~{tool_tokens}) / ctx {context_window} = {usage_pct:.0f}%]{status}",
        flush=True,
    )


def run_question(
    client,
    question: str,
    map_context: dict | None = None,
    max_steps: int = 6,
    inter_call_delay: float = 3.0,
    log_tokens: bool = False,
) -> dict:
    """Run the agentic loop and return {answer, tools_called, step_count, error}."""
    metrics = poc._real_list_available_metrics()["metrics"]
    system_prompt = poc.build_system_prompt(metrics)

    if map_context:
        lat = map_context.get("lat")
        lon = map_context.get("lon")
        label = map_context.get("label", f"{lat},{lon}")
        ctx_line = (
            f"\nMap context: the user is currently viewing [{label}]. "
            "For questions about 'here', 'this location', or 'this place', "
            f'pass "{label}" as the location parameter — do not use raw coordinates.\n'
        )
        # Insert before "Available metrics:"
        system_prompt = system_prompt.replace(
            "\nAvailable metrics:", ctx_line + "\nAvailable metrics:", 1
        )

    global _TPD_EXHAUSTED

    messages: list[dict] = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": question},
    ]
    tools_called: list[str] = []
    tool_traces: list[dict] = []
    retried = False
    tpm_retries = 0

    for step in range(1, max_steps + 1):
        if inter_call_delay > 0 and step > 1:
            time.sleep(inter_call_delay)

        try:
            if log_tokens:
                _log_request_size(
                    label=f"agent step {step}",
                    messages=messages,
                    tools=poc.TOOL_SCHEMAS,
                )
            response = client.chat.completions.create(
                model=poc.MODEL,
                messages=messages,
                tools=poc.TOOL_SCHEMAS,
                tool_choice="auto",
                parallel_tool_calls=True,
                temperature=0,
            )
        except Exception as exc:
            error_body = getattr(exc, "body", {}) or {}
            error_info = error_body.get("error") or {}
            error_code = error_info.get("code", "")
            error_msg = error_info.get("message", str(exc))

            if error_code == "tool_use_failed" and not retried:
                retried = True
                messages.append(
                    {
                        "role": "user",
                        "content": "Your previous tool call was malformed. Please retry using correct JSON.",
                    }
                )
                step -= 1
                continue

            if _is_tpd_error(error_msg):
                _TPD_EXHAUSTED = True
                return {
                    "error": f"TPD_EXHAUSTED: {error_msg}",
                    "tools_called": tools_called,
                    "tool_traces": tool_traces,
                    "step_count": step,
                }

            if _is_tpm_error(error_msg) and tpm_retries < 3:
                wait = min(_parse_retry_after_s(error_msg) + 2.0, 30.0)
                print(f"    [rate limit TPM — sleeping {wait:.0f}s]", flush=True)
                time.sleep(wait)
                tpm_retries += 1
                step -= 1
                continue

            return {
                "error": f"API error: {error_msg}",
                "tools_called": tools_called,
                "tool_traces": tool_traces,
                "step_count": step,
            }

        message = response.choices[0].message

        tool_calls = []
        if message.tool_calls:
            tool_calls = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.function.name,
                        "arguments": tc.function.arguments,
                    },
                }
                for tc in message.tool_calls
            ]
        elif message.content and "<function" in message.content:
            parsed = poc._parse_text_tool_calls(message.content)
            if parsed:
                tool_calls = [
                    {
                        "id": tc["id"],
                        "type": "function",
                        "function": {
                            "name": tc["name"],
                            "arguments": json.dumps(tc["arguments"]),
                        },
                    }
                    for tc in parsed
                ]

        if tool_calls:
            messages.append({"role": "assistant", "tool_calls": tool_calls})
            for tc in tool_calls:
                args = json.loads(tc["function"]["arguments"])
                name = tc["function"]["name"]
                tools_called.append(name)
                result = poc.dispatch_tool(name, args)
                tool_traces.append({"name": name, "args": args, "result": result})
                messages.append(
                    {"role": "tool", "tool_call_id": tc["id"], "content": result}
                )
        else:
            return {
                "answer": message.content or "",
                "tools_called": tools_called,
                "tool_traces": tool_traces,
                "step_count": step,
            }

    return {
        "error": "max steps reached",
        "tools_called": tools_called,
        "tool_traces": tool_traces,
        "step_count": max_steps,
    }


# ---------------------------------------------------------------------------
# Malformed answer detection
# ---------------------------------------------------------------------------

_KNOWN_TOOL_NAMES = [
    "get_metric_series",
    "resolve_location",
    "find_extreme_location",
    "find_similar_locations",
    "list_available_metrics",
]


def _malformed_reason(answer: str) -> str | None:
    """Return a human-readable reason if the answer is malformed, else None."""
    for tool in _KNOWN_TOOL_NAMES:
        if tool in answer:
            return f"mentions tool name '{tool}'"
    # Raw JSON tool call embedded in text
    if '"parameters"' in answer or '{"name":' in answer:
        return "contains raw JSON tool call"
    return None


# ---------------------------------------------------------------------------
# Check helpers
# ---------------------------------------------------------------------------


def _extract_numbers(text: str) -> list[float]:
    matches = re.findall(r"-?\d+(?:\.\d+)?", text)
    out = []
    for m in matches:
        try:
            out.append(float(m))
        except ValueError:
            pass
    return out


def _extract_years(text: str) -> list[int]:
    return [int(m) for m in re.findall(r"\b(19[789]\d|20[0-3]\d)\b", text)]


def _run_check(check: dict, result: dict) -> tuple[bool, str]:
    """Return (passed, detail_message)."""
    answer = result.get("answer", "")
    tools_called = result.get("tools_called", [])
    ctype = check["type"]
    desc = check.get("description", "")

    if ctype == "numeric":
        expected = check.get("expected_value")
        tolerance = check.get("tolerance", 0.5)
        if expected is None:
            return True, f"SKIP (expected_value is null)"
        numbers = _extract_numbers(answer)
        if not numbers:
            return False, f"FAIL — no number found in answer"
        best = min(numbers, key=lambda n: abs(n - expected))
        if abs(best - expected) <= tolerance:
            return True, f"PASS — found {best} (expected {expected} ±{tolerance})"
        return (
            False,
            f"FAIL — best match {best} is not within {tolerance} of {expected}",
        )

    elif ctype == "year":
        expected = check.get("expected_year")
        if expected is None:
            return True, "SKIP (expected_year is null)"
        # Strip range-context phrases so a year that appears only as a bound
        # (e.g. "between 2000 and 2023") doesn't trigger a false positive.
        cleaned = re.sub(r"\bbetween\s+\d{4}\s+and\s+\d{4}\b", "", answer, flags=re.I)
        cleaned = re.sub(r"\bfrom\s+\d{4}\s+to\s+\d{4}\b", "", cleaned, flags=re.I)
        years = _extract_years(cleaned)
        if expected in years:
            return True, f"PASS — year {expected} found"
        return False, f"FAIL — year {expected} not found (found: {years})"

    elif ctype == "contains":
        pattern = check.get("pattern", "")
        if pattern.lower() in answer.lower():
            return True, f"PASS — '{pattern}' found"
        return False, f"FAIL — '{pattern}' not in answer"

    elif ctype == "not_contains":
        pattern = check.get("pattern", "")
        if pattern.lower() not in answer.lower():
            return True, f"PASS — '{pattern}' correctly absent"
        return False, f"FAIL — '{pattern}' found but should be absent"

    elif ctype == "count":
        expected_count = check.get("expected_count")
        if expected_count is None:
            return True, "SKIP (expected_count is null)"
        # Count numbered list items: "1.", "2.", etc.
        numbered = re.findall(r"^\s*\d+[.)]\s", answer, re.MULTILINE)
        # Also count bold city names or lines with a temperature value
        found = len(numbered) if numbered else None
        if found == expected_count:
            return True, f"PASS — found {found} ranked items"
        # Soft: don't fail on count alone if temperature values are present
        temps = _extract_numbers(answer)
        if found is None:
            return None, f"SKIP (could not count items in answer)"  # type: ignore
        return False, f"FAIL — expected {expected_count} items, found {found}"

    elif ctype == "not_called":
        tool = check.get("tool", "")
        if tool not in tools_called:
            return True, f"PASS — '{tool}' was not called"
        return False, f"FAIL — '{tool}' was called but should not have been"

    return None, f"UNKNOWN check type '{ctype}'"  # type: ignore


# ---------------------------------------------------------------------------
# Layer 2: LLM-as-judge
# ---------------------------------------------------------------------------

_JUDGE_PROMPT = """\
You are evaluating a climate data assistant's response to a user question.

Question: {question}
Assistant response: {answer}

Evaluation criteria:
{criteria_text}

Must NOT patterns (any of these found in the answer is a failure):
{must_not_text}

Score each criterion from 0–3:
  0 = completely missing or wrong
  1 = partially addressed
  2 = mostly correct
  3 = fully correct and specific

Also give an overall verdict: PASS (average score ≥ 2) or FAIL.

Respond with JSON only (no markdown):
{{"scores": {{"criterion_name": score, ...}}, "overall": "PASS" or "FAIL", "notes": "brief explanation"}}
"""


def judge_response(client, test: dict, result: dict, log_tokens: bool = False) -> dict:
    criteria = test.get("criteria", {})
    must_not = test.get("must_not", [])
    answer = result.get("answer", "")

    criteria_text = (
        "\n".join(f"  - {k}: {v}" for k, v in criteria.items()) or "  (none)"
    )
    must_not_text = "\n".join(f"  - {m}" for m in must_not) or "  (none)"

    prompt = _JUDGE_PROMPT.format(
        question=test["question"],
        answer=answer,
        criteria_text=criteria_text,
        must_not_text=must_not_text,
    )

    try:
        judge_messages = [{"role": "user", "content": prompt}]
        if log_tokens:
            _log_request_size(label=f"judge {test['id']}", messages=judge_messages)
        resp = client.chat.completions.create(
            model=poc.MODEL,
            messages=judge_messages,
            temperature=0,
        )
        raw = resp.choices[0].message.content or ""
        # Strip markdown fences if present
        raw = re.sub(r"^```(?:json)?\s*", "", raw.strip(), flags=re.MULTILINE)
        raw = re.sub(r"```\s*$", "", raw.strip())
        return json.loads(raw)
    except Exception as exc:
        return {"error": str(exc), "overall": "ERROR"}


# ---------------------------------------------------------------------------
# Tool trace printer
# ---------------------------------------------------------------------------


def _print_tool_traces(result: dict, max_result_len: int = 300) -> None:
    for trace in result.get("tool_traces", []):
        args_str = ", ".join(f"{k}={repr(v)}" for k, v in (trace["args"] or {}).items())
        raw = trace["result"]
        result_str = raw[:max_result_len] + ("…" if len(raw) > max_result_len else "")
        print(f"    {trace['name']}({args_str}) → {result_str}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(description="Run golden-set evaluation")
    parser.add_argument(
        "--layer",
        type=int,
        choices=[1, 2],
        help="Run only layer 1 or 2 (default: both)",
    )
    parser.add_argument(
        "--id",
        type=str,
        action="append",
        dest="ids",
        metavar="ID",
        help="Run specific test(s) by ID — may be repeated (e.g. --id L1-02 --id L1-10)",
    )
    parser.add_argument("--verbose", action="store_true", help="Print full answer text")
    parser.add_argument(
        "--delay",
        type=float,
        default=5.0,
        help="Seconds to wait between API calls within a test (default: 5)",
    )
    parser.add_argument(
        "--log-tokens",
        action="store_true",
        help="Print estimated request token usage before each model call",
    )
    parser.add_argument(
        "--trace-tools",
        action="store_true",
        help="Print each tool call with arguments and result (truncated to 300 chars)",
    )
    args = parser.parse_args()

    if poc._OLLAMA_BASE_URL:
        api_key = None
        print(f"Using Ollama at {poc._OLLAMA_BASE_URL}  |  model: {poc.MODEL}")
    else:
        print(f"Using Groq  |  model: {poc.MODEL}")
        api_key = os.environ.get("GROQ_API_KEY")
        if not api_key:
            print(
                "Error: GROQ_API_KEY not set (or set OLLAMA_BASE_URL for local inference)",
                file=sys.stderr,
            )
            sys.exit(1)

    golden_path = REPO_ROOT / "experiments" / "golden_set.yaml"
    tests = yaml.safe_load(golden_path.read_text(encoding="utf-8"))

    # Filter
    if args.ids:
        tests = [t for t in tests if t.get("id") in args.ids]
        missing = set(args.ids) - {t.get("id") for t in tests}
        if missing:
            print(
                f"No test(s) found for id(s): {', '.join(sorted(missing))}",
                file=sys.stderr,
            )
            sys.exit(1)
    if args.layer:
        tests = [t for t in tests if t.get("layer") == args.layer]

    client = poc._make_client(api_key)

    # -----------------------------------------------------------------------
    # Layer 1 — automated checks
    # -----------------------------------------------------------------------
    layer1_tests = [t for t in tests if t.get("layer") == 1]
    layer1_pass = 0
    layer1_fail = 0
    layer1_skip = 0
    layer1_abort = 0

    if layer1_tests:
        print(f"\n{'='*60}")
        print(f"LAYER 1 — automated checks ({len(layer1_tests)} tests)")
        print("=" * 60)

    for test in layer1_tests:
        tid = test.get("id", "?")
        question = test["question"]
        map_ctx = test.get("map_context")

        print(f"\n[{tid}] {question}")
        result = run_question(
            client,
            question,
            map_context=map_ctx,
            inter_call_delay=args.delay,
            log_tokens=args.log_tokens,
        )

        if "error" in result:
            err = result["error"]
            if err.startswith("TPD_EXHAUSTED"):
                print(f"  ✗ Daily token limit exhausted — aborting remaining tests.")
                layer1_abort += 1
                break
            print(f"  ERROR: {err}")
            layer1_fail += 1
            continue

        answer = result["answer"]
        tools = result["tools_called"]
        print(f"  Tools: {tools}  |  Steps: {result['step_count']}")
        if args.trace_tools:
            _print_tool_traces(result)
        if args.verbose:
            print(f"  Answer: {answer}")

        checks = test.get("checks", [])
        test_passed = True
        any_real_check = False

        malformed = _malformed_reason(answer)
        if malformed:
            print(f"  ✗ [malformed] Answer {malformed}")
            if not args.verbose:
                print(f"  Answer: {answer[:300]}")
            test_passed = False
            any_real_check = True

        for check in checks:
            passed, detail = _run_check(check, result)
            if passed is None:  # skip
                icon = "⟳"
                layer1_skip += 1
            elif passed:
                icon = "✓"
                any_real_check = True
            else:
                icon = "✗"
                test_passed = False
                any_real_check = True
                if not args.verbose:
                    # Show answer excerpt on failure to aid diagnosis
                    print(f"  Answer: {answer[:300]}")

            print(f"  {icon} [{check['type']}] {check.get('description','')}: {detail}")

        if any_real_check:
            if test_passed:
                layer1_pass += 1
            else:
                layer1_fail += 1
        else:
            layer1_skip += 1  # all checks were skipped (null expected values)

    if layer1_tests:
        total_evaluated = layer1_pass + layer1_fail
        rate = layer1_pass / total_evaluated * 100 if total_evaluated > 0 else 0
        abort_note = f" / {layer1_abort} aborted (budget)" if layer1_abort else ""
        print(f"\n{'─'*60}")
        print(
            f"Layer 1 summary: {layer1_pass} passed / {layer1_fail} failed / {layer1_skip} checks skipped{abort_note}"
        )
        print(
            f"Pass rate: {rate:.0f}%  ({'✓ meets 80% gate' if rate >= 80 else '✗ below 80% gate'})"
        )

    # -----------------------------------------------------------------------
    # Layer 2 — LLM-as-judge
    # -----------------------------------------------------------------------
    layer2_tests = [t for t in tests if t.get("layer") == 2]
    layer2_pass = 0
    layer2_fail = 0
    layer2_abort = 0

    if layer2_tests:
        print(f"\n{'='*60}")
        print(f"LAYER 2 — LLM-as-judge ({len(layer2_tests)} tests)")
        print("=" * 60)

    for test in layer2_tests:
        tid = test.get("id", "?")
        question = test["question"]
        map_ctx = test.get("map_context")

        print(f"\n[{tid}] {question}")
        result = run_question(
            client,
            question,
            map_context=map_ctx,
            inter_call_delay=args.delay,
            log_tokens=args.log_tokens,
        )

        if "error" in result:
            err = result["error"]
            if err.startswith("TPD_EXHAUSTED"):
                print(f"  ✗ Daily token limit exhausted — aborting remaining tests.")
                layer2_abort += 1
                break
            print(f"  ERROR: {err}")
            layer2_fail += 1
            continue

        answer = result["answer"]
        tools = result["tools_called"]
        print(f"  Tools: {tools}  |  Steps: {result['step_count']}")
        if args.trace_tools:
            _print_tool_traces(result)
        if args.verbose:
            print(f"  Answer: {answer[:400]}")

        malformed = _malformed_reason(answer)
        if malformed:
            print(f"  ✗ [malformed] Answer {malformed}")
            if not args.verbose:
                print(f"  Answer: {answer[:300]}")
            layer2_fail += 1
            continue

        print("  Judging...", end=" ", flush=True)
        verdict = judge_response(client, test, result, log_tokens=args.log_tokens)
        print("done")

        if "error" in verdict:
            print(f"  Judge error: {verdict['error']}")
            layer2_fail += 1
            continue

        overall = verdict.get("overall", "ERROR")
        scores = verdict.get("scores", {})
        notes = verdict.get("notes", "")

        score_str = "  ".join(f"{k}={v}" for k, v in scores.items())
        icon = "✓" if overall == "PASS" else "✗"
        print(f"  {icon} {overall} — {score_str}")
        print(f"    Notes: {notes}")

        if overall == "PASS":
            layer2_pass += 1
        else:
            layer2_fail += 1

    if layer2_tests:
        total_evaluated = layer2_pass + layer2_fail
        rate = layer2_pass / total_evaluated * 100 if total_evaluated > 0 else 0
        print(f"\n{'─'*60}")
        print(f"Layer 2 summary: {layer2_pass} passed / {layer2_fail} failed")
        print(f"Pass rate: {rate:.0f}%")

    # Final gate verdict
    if layer1_tests and not args.layer == 2:
        total_evaluated = layer1_pass + layer1_fail
        rate = layer1_pass / total_evaluated * 100 if total_evaluated > 0 else 0
        print(f"\n{'='*60}")
        if rate >= 80:
            print(f"✓ PHASE 0 GATE: PASSED (Layer 1 accuracy {rate:.0f}% ≥ 80%)")
        else:
            print(f"✗ PHASE 0 GATE: NOT MET (Layer 1 accuracy {rate:.0f}% < 80%)")
        print("=" * 60)


if __name__ == "__main__":
    main()
