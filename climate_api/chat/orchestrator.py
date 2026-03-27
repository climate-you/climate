"""
Chat orchestrator: runs the agentic loop across a prioritised list of provider tiers
and yields SSE event dicts.

Event types yielded by ChatOrchestrator.run():
  {"type": "tool_call",  "step": N, "name": "...", "args": {...}}
  {"type": "notice",     "text": "..."}            # degraded-model disclaimer, if applicable
  {"type": "answer",     "text": "..."}
  {"type": "done",       "session_id": "...", "step_count": N, "tools_called": [...], "tier": "...",
                         "total_ms": N, "steps_timing": [{"step": N, "model_ms": N, "tools_ms": N}, ...]}
  {"type": "error",      "message": "..."}

Provider tiers are tried in order. If a tier's API call returns a daily-token-quota error
on its *first* call (before any events have been yielded for this question), the orchestrator
silently falls through to the next tier. Any other error is surfaced as an "error" event.
"""
from __future__ import annotations

import datetime
import json
import re
import time as _time
import uuid
from dataclasses import dataclass, field
from typing import Any, Iterator

from climate_api.store.location_index import LocationIndex
from climate_api.store.tile_data_store import TileDataStore
from climate_api.chat import tools as _tools


# ---------------------------------------------------------------------------
# Provider tier
# ---------------------------------------------------------------------------

@dataclass
class ProviderTier:
    """One entry in the fallback chain."""
    name: str           # e.g. "groq_70b_free", "groq_8b", "local"
    client: Any         # groq.Groq or openai.OpenAI instance
    model: str
    is_degraded: bool = False   # True → emit disclaimer notice before answer
    degraded_notice: str = field(default="")

    def __post_init__(self):
        if self.is_degraded and not self.degraded_notice:
            self.degraded_notice = _DEGRADED_MODEL_NOTICE


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_DEGRADED_MODEL_NOTICE = (
    "Note: The primary AI model's daily allowance has been exceeded. "
    "A smaller backup model is being used — answers may be less accurate."
)

_BUDGET_EXHAUSTED_MSG = (
    "The AI assistant's daily budget is exhausted. This project is provided for "
    "free and is self-funded. If you find it useful, please consider supporting "
    "it at ko-fi.com/climatearchive."
)


# ---------------------------------------------------------------------------
# Quota detection
# ---------------------------------------------------------------------------

class _QuotaExhaustedError(Exception):
    """Raised when a tier's first API call hits a daily-token-quota limit."""


def _is_quota_exhausted(exc: Exception) -> bool:
    """Return True if the exception signals a daily token quota exhaustion."""
    # Groq SDK raises RateLimitError for 429; check that first.
    try:
        from groq import RateLimitError
        if isinstance(exc, RateLimitError):
            # Distinguish TPD (daily) from TPM (per-minute).
            # TPM errors should be retried with a delay, not trigger tier fallback.
            msg = str(exc).lower()
            if "tokens per day" in msg or " tpd" in msg:
                return True
            # A generic 429 with no TPM marker is also treated as quota.
            if "tokens per minute" not in msg and "tpm" not in msg:
                return True
    except ImportError:
        pass
    # Fallback: check status code + error body
    if getattr(exc, "status_code", None) == 429:
        body = getattr(exc, "body", {}) or {}
        error_info = (body.get("error") or {})
        msg = error_info.get("message", "").lower()
        if "tokens per day" in msg or " tpd" in msg:
            return True
    return False


def _is_tpm_error(exc: Exception) -> bool:
    """Return True if the exception is a per-minute rate limit (retryable)."""
    msg = str(exc).lower()
    return "tokens per minute" in msg or " tpm" in msg


def _parse_retry_after_s(exc: Exception) -> float:
    m = re.search(r"try again in\s+(?:(\d+)m)?(?:\s*(\d+(?:\.\d+)?)s)?", str(exc), re.I)
    if m:
        return float(m.group(1) or 0) * 60 + float(m.group(2) or 0)
    return 5.0


# ---------------------------------------------------------------------------
# Tool schemas
# ---------------------------------------------------------------------------

TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "find_extreme_location",
            "description": (
                "Find the location(s) with the highest or lowest value of a climate metric. "
                "Use for questions like 'which city is the hottest?', 'top 10 warmest large cities', "
                "'hottest capital', 'warmest city in France'. "
                "Returns a single result when limit=1, or a ranked list when limit>1. "
                "Use min_population to restrict to large cities (e.g. 1000000 for megacities). "
                "Use capital_only=true to restrict to national capital cities. "
                "Use country to restrict to a specific country (full English name, e.g. 'France')."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "metric_id": {"type": "string", "description": "Metric ID from the catalogue"},
                    "aggregation": {
                        "type": "string",
                        "enum": ["mean", "max", "min", "trend_slope"],
                        "description": (
                            "How to aggregate the time series per location: "
                            "mean (average over the period), max, min, or trend_slope (°C/decade)."
                        ),
                    },
                    "extremum": {
                        "type": "string",
                        "enum": ["max", "min"],
                        "description": "Whether to find the location with the highest (max) or lowest (min) value.",
                    },
                    "start_year": {"type": "integer", "description": "First year to include (inclusive)."},
                    "end_year":   {"type": "integer", "description": "Last year to include (inclusive)."},
                    "month_filter": {
                        "type": "array",
                        "items": {"type": "integer"},
                        "description": "Months to include, e.g. [12, 1, 2] for winter. Only for monthly metrics.",
                    },
                    "country": {
                        "type": "string",
                        "description": "Restrict to cities in this country (full English name, e.g. 'France').",
                    },
                    "capital_only": {"type": "boolean", "description": "If true, only consider national capital cities."},
                    "min_population": {
                        "type": "integer",
                        "description": "Only consider cities with at least this population. Use 1000000 for 'large cities'.",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Number of results to return (default 1). Use >1 for ranking questions.",
                    },
                },
                "required": ["metric_id", "aggregation", "extremum"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "find_similar_locations",
            "description": (
                "Find cities whose long-term mean for a metric is closest to a reference city. "
                "Use for questions like 'which cities have a similar climate to London?' or "
                "'cities with similar temperatures to Tokyo'. Scans cities with population >= 100k."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "reference_name": {
                        "type": "string",
                        "description": "Name of the reference city. Use the city name only, e.g. 'London' or 'Tokyo' — do not append country codes.",
                    },
                    "metric_id": {
                        "type": "string",
                        "description": "Metric ID to use for comparison (e.g. t2m_yearly_mean_c).",
                    },
                    "limit": {"type": "integer", "description": "Number of similar cities to return (default 5)."},
                },
                "required": ["reference_name", "metric_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_metric_series",
            "description": (
                "Return a time-series of a climate metric for a named location. "
                "Filter by year range and/or specific months (1=Jan ... 12=Dec). "
                "The returned data array can be used to compute means, trends, extremes, etc."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "location": {
                        "type": "string",
                        "description": (
                            "City or place name, e.g. 'Tokyo' or 'Paris, France'. "
                            "When the user asks about 'here' or 'this location', use the label "
                            "from the map context exactly as provided."
                        ),
                    },
                    "metric_id": {"type": "string", "description": "Metric ID from the catalogue"},
                    "start_year": {"type": "integer", "description": "First year to include (inclusive)"},
                    "end_year":   {"type": "integer", "description": "Last year to include (inclusive)"},
                    "month_filter": {
                        "type": "array",
                        "items": {"type": "integer"},
                        "description": "Months to include, e.g. [12, 1, 2] for winter. Only valid for monthly metrics.",
                    },
                },
                "required": ["location", "metric_id"],
            },
        },
    },
]


# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT_TEMPLATE = """\
You are a climate data assistant. You answer questions about historical climate data \
using the tools available to you.

Rules:
- Always call the tools to retrieve data before answering — never guess numerical values.
- Use the metric catalogue below to choose the correct metric_id directly.
- Pass a place name directly to get_metric_series — it resolves the location internally. \
Never guess or supply your own coordinates.
- Multiple independent tool calls can be made in a single step. When comparing multiple \
locations, call get_metric_series for all of them in one parallel step.
- When the question asks for a specific year or time range, always pass start_year and \
end_year to get_metric_series so the result is focused. For example, to get the 2020 \
value, pass start_year=2020, end_year=2020. Only omit year bounds when you need the full \
historical series (e.g. to find the hottest year across all years).
- Before calling any tool that takes a year, check whether the requested year is in the \
future (beyond today's date). If it is a future year, do not retry — instead explain that \
our dataset only covers historical data up to the date shown in the metric catalogue above.
- Finding the hottest or coldest year at a specific location: use get_metric_series (not \
find_extreme_location) to retrieve the full series for that location, then identify the \
extremum year from the returned data. find_extreme_location is for finding which city or \
region has the most extreme value across many locations — not for finding the extreme year \
at a known location.
- Never mention tool names, function names, or raw JSON in your final response. \
Present findings as natural language only.

Spatial precision: climate data is at 0.25 degree resolution (roughly 28 km per cell). \
A data point covers a geographic area, not a precise city. Prefer phrasing like "in the \
Tokyo area" rather than "in Tokyo specifically".

Two-tier answers: for questions about why something is happening, you may draw on \
general climate science knowledge — but clearly label it: "Beyond what our dataset shows, \
climate science suggests..." and hedge appropriately. Never state general knowledge with \
the same certainty as a tool result.

Data availability: if the tool returns an error saying the requested time period is not \
available, retry with the most recent available period.

Reporting time periods: always state the explicit year or date from the data you retrieved \
— never echo the user's relative phrasing like "last year" or "last month". Say "in 2024" \
not "last year". If the year or month you fetched is the last one listed in the metric \
catalogue, add "(most recent available in our dataset)" after the year.

Respond in English only. Be concise and always include specific numbers from the data.

Today's date: {current_date}. Use this to interpret relative time expressions like \
"last year" or "this decade".
{map_context_block}
Available metrics:
{metric_catalogue}
"""


def _format_metric_catalogue(metrics: list[dict]) -> str:
    lines = []
    for m in metrics:
        line = f"- {m['metric_id']}: {m['description']} ({m['unit']}), available {m['available_range']}, source: {m['source']}"
        if m.get("note"):
            line += f" -- {m['note']}"
        lines.append(line)
    return "\n".join(lines)


def _build_system_prompt(
    tile_store: TileDataStore,
    map_context: dict[str, Any] | None,
) -> str:
    metrics_result = _tools.list_available_metrics(tile_store)
    catalogue = _format_metric_catalogue(metrics_result.get("metrics", []))
    current_date = datetime.date.today().strftime("%Y-%m-%d")

    if map_context:
        label = map_context.get("label") or f"{map_context.get('lat', 0)}, {map_context.get('lon', 0)}"
        map_context_block = (
            f"\nMap context: the user is currently viewing [{label}]. "
            "For questions about 'here', 'this location', or 'this place', "
            f"pass \"{label}\" as the location parameter — do not use raw coordinates.\n"
        )
    else:
        map_context_block = "\n"

    return _SYSTEM_PROMPT_TEMPLATE.format(
        current_date=current_date,
        map_context_block=map_context_block,
        metric_catalogue=catalogue,
    )


# ---------------------------------------------------------------------------
# XML text tool call fallback parser
# ---------------------------------------------------------------------------

def _parse_text_tool_calls(text: str) -> list[dict]:
    """
    Llama models sometimes emit tool calls as XML-ish text instead of structured
    tool_calls. This extracts them as a fallback.
    """
    matches = re.findall(r'<function[^>]*>(.*?)</function>', text, re.DOTALL)
    calls = []
    for raw in matches:
        raw = raw.strip().rstrip(')')
        brace = raw.find('{')
        if brace == -1:
            continue
        name = raw[:brace].lstrip('=(\"').rstrip('=(\"" ')
        try:
            arguments = json.loads(raw[brace:])
        except json.JSONDecodeError:
            continue
        calls.append({"id": f"parsed_{name}_{len(calls)}", "name": name, "arguments": arguments})
    return calls


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

class ChatOrchestrator:
    def __init__(
        self,
        tiers: list[ProviderTier],
        tile_store: TileDataStore,
        location_index: LocationIndex,
        country_names: dict[str, str] | None = None,
        max_steps: int = 5,
    ) -> None:
        self.tiers = tiers
        self.tile_store = tile_store
        self.location_index = location_index
        self.country_name_to_code: dict[str, str] = {}
        if country_names:
            self.country_name_to_code = {v.casefold(): k for k, v in country_names.items()}
        self.max_steps = max_steps

    def _dispatch(self, name: str, args: dict) -> str:
        if name == "get_metric_series":
            result = _tools.get_metric_series(
                location=str(args["location"]),
                metric_id=str(args["metric_id"]),
                tile_store=self.tile_store,
                location_index=self.location_index,
                start_year=args.get("start_year"),
                end_year=args.get("end_year"),
                month_filter=args.get("month_filter"),
            )
        elif name == "find_extreme_location":
            result = _tools.find_extreme_location(
                metric_id=str(args["metric_id"]),
                aggregation=str(args["aggregation"]),
                extremum=str(args["extremum"]),
                tile_store=self.tile_store,
                location_index=self.location_index,
                country_name_to_code=self.country_name_to_code,
                start_year=args.get("start_year"),
                end_year=args.get("end_year"),
                month_filter=args.get("month_filter"),
                country=args.get("country"),
                capital_only=bool(args.get("capital_only", False)),
                min_population=int(args.get("min_population", 0)),
                limit=int(args.get("limit", 1)),
            )
        elif name == "find_similar_locations":
            result = _tools.find_similar_locations(
                reference_name=str(args["reference_name"]),
                metric_id=str(args["metric_id"]),
                tile_store=self.tile_store,
                location_index=self.location_index,
                limit=int(args.get("limit", 5)),
            )
        else:
            result = {"error": f"Unknown tool: '{name}'"}
        return json.dumps(result)

    def _run_tier(
        self,
        tier: ProviderTier,
        question: str,
        map_context: dict[str, Any] | None,
        session_id: str,
    ) -> Iterator[dict]:
        """
        Run the agentic loop for one tier. Yields SSE event dicts.

        Raises _QuotaExhaustedError if the very first API call hits a daily token
        quota limit (before any events have been yielded for this question).
        Any other error is yielded as an "error" event and the generator returns.
        """
        system_prompt = _build_system_prompt(self.tile_store, map_context)
        messages: list[dict] = [
            {"role": "system", "content": system_prompt},
            {"role": "user",   "content": question},
        ]

        tools_called: list[str] = []
        retried = False
        tpm_retries = 0
        events_yielded = False  # True once we've emitted at least one tool_call event

        t_start = _time.monotonic()
        steps_timing: list[dict] = []
        step_model_ms = 0     # accumulated model latency for current step (across retries)
        last_unique_step = 0  # last step that was newly entered (not a retry)

        step = 0
        while step < self.max_steps:
            step += 1
            if step > last_unique_step:
                last_unique_step = step
                step_model_ms = 0  # new step — reset accumulator
            try:
                model_t0 = _time.monotonic()
                response = tier.client.chat.completions.create(
                    model=tier.model,
                    messages=messages,
                    tools=TOOL_SCHEMAS,
                    tool_choice="auto",
                    parallel_tool_calls=True,
                    temperature=0,
                )
                step_model_ms += int((_time.monotonic() - model_t0) * 1000)
            except Exception as exc:
                # Quota exhaustion on the very first call (no events sent yet) →
                # raise so the caller can fall through to the next tier silently.
                if not events_yielded and _is_quota_exhausted(exc):
                    raise _QuotaExhaustedError() from exc

                error_body = getattr(exc, "body", {}) or {}
                error_info = (error_body.get("error") or {})
                error_code = error_info.get("code", "")
                error_msg = error_info.get("message", str(exc))

                if error_code == "tool_use_failed" and not retried:
                    retried = True
                    messages.append({
                        "role": "user",
                        "content": "Your previous tool call was malformed. Please call the tool again using the correct JSON format.",
                    })
                    step -= 1
                    continue

                # Per-minute rate limit — sleep briefly and retry (up to 3 times)
                if _is_tpm_error(exc) and tpm_retries < 3:
                    import time
                    wait = min(_parse_retry_after_s(exc) + 2.0, 30.0)
                    time.sleep(wait)
                    tpm_retries += 1
                    step -= 1
                    continue

                total_ms = int((_time.monotonic() - t_start) * 1000)
                yield {"type": "error", "message": f"API error: {error_msg}"}
                yield {"type": "done", "session_id": session_id, "step_count": step, "tools_called": tools_called, "tier": tier.name, "total_ms": total_ms, "steps_timing": steps_timing}
                return

            message = response.choices[0].message

            # Normalise tool calls: structured first, XML text fallback
            tool_calls = []
            if message.tool_calls:
                tool_calls = [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                    }
                    for tc in message.tool_calls
                ]
            elif message.content and "<function" in message.content:
                parsed = _parse_text_tool_calls(message.content)
                if parsed:
                    tool_calls = [
                        {
                            "id": tc["id"],
                            "type": "function",
                            "function": {"name": tc["name"], "arguments": json.dumps(tc["arguments"])},
                        }
                        for tc in parsed
                    ]

            if tool_calls:
                messages.append({"role": "assistant", "tool_calls": tool_calls})
                tools_t0 = _time.monotonic()
                for tc in tool_calls:
                    args = json.loads(tc["function"]["arguments"])
                    name = tc["function"]["name"]
                    yield {"type": "tool_call", "step": step, "name": name, "args": args}
                    events_yielded = True
                    tools_called.append(name)
                    result = self._dispatch(name, args)
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc["id"],
                        "content": result,
                    })
                tools_ms = int((_time.monotonic() - tools_t0) * 1000)
                steps_timing.append({"step": step, "model_ms": step_model_ms, "tools_ms": tools_ms})
            else:
                # Final text response
                steps_timing.append({"step": step, "model_ms": step_model_ms})
                total_ms = int((_time.monotonic() - t_start) * 1000)
                answer = message.content or ""
                if tier.is_degraded:
                    yield {"type": "notice", "text": tier.degraded_notice}
                yield {"type": "answer", "text": answer}
                yield {"type": "done", "session_id": session_id, "step_count": step, "tools_called": tools_called, "tier": tier.name, "total_ms": total_ms, "steps_timing": steps_timing}
                return

        total_ms = int((_time.monotonic() - t_start) * 1000)
        yield {"type": "error", "message": "Reached maximum steps without a final answer."}
        yield {"type": "done", "session_id": session_id, "step_count": self.max_steps, "tools_called": tools_called, "tier": tier.name, "total_ms": total_ms, "steps_timing": steps_timing}

    def run(
        self,
        question: str,
        map_context: dict[str, Any] | None = None,
        session_id: str | None = None,
        model_override: str | None = None,
    ) -> Iterator[dict]:
        """
        Run the agentic loop, trying each tier in order on quota exhaustion.

        model_override: tier name to start from (e.g. "local" to skip to Ollama).
        If the named tier is not in the list, yields an error event immediately.
        """
        if session_id is None:
            session_id = str(uuid.uuid4())

        tiers = self.tiers

        if model_override:
            idx = next((i for i, t in enumerate(tiers) if t.name == model_override), None)
            if idx is None:
                yield {"type": "error", "message": f"Requested model '{model_override}' is not available on this server."}
                yield {"type": "done", "session_id": session_id, "step_count": 0, "tools_called": [], "tier": None}
                return
            tiers = tiers[idx:]

        for tier in tiers:
            try:
                yield from self._run_tier(tier, question, map_context, session_id)
                return
            except _QuotaExhaustedError:
                continue

        # All tiers quota-exhausted
        yield {"type": "answer", "text": _BUDGET_EXHAUSTED_MSG}
        yield {"type": "done", "session_id": session_id, "step_count": 0, "tools_called": [], "tier": None}
