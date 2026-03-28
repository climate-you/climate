"""
Pre-written answers for the example questions shown in the chat UI.

Matching is case-insensitive and whitespace-normalised.
When a question matches, the answer is streamed via SSE with a short artificial
delay so it behaves like a real response.

Run the questions through the 70b model and update the answers below once
you're happy with them.
"""

from __future__ import annotations

import time

# question (lowercased, stripped) → (answer text, locations list)
# locations: [{"label": str, "lat": float, "lon": float}, ...]
CANNED: dict[str, tuple[str, list[dict]]] = {
    "what is the hottest capital city in the world?": (
        "The hottest capital city in the world is **Khartoum, Sudan**, with a mean annual "
        "temperature of **29.6°C**.",
        [{"label": "Khartoum", "lat": 15.55, "lon": 32.53}],
    ),
    "what are the top 5 warmest large cities in the world?": (
        "The top 5 warmest large cities in the world are:\n\n"
        "1. **Khartoum, Sudan** — 29.6°C\n"
        "2. **Niamey, Niger** — 29.4°C\n"
        "3. **Makkah, Saudi Arabia** — 29.3°C\n"
        "4. **Omdurman, Sudan** — 29.2°C\n"
        "5. **Sokoto, Nigeria** — 29.2°C",
        [
            {"label": "Khartoum", "lat": 15.55, "lon": 32.53},
            {"label": "Niamey", "lat": 13.51, "lon": 2.11},
            {"label": "Makkah", "lat": 21.39, "lon": 39.86},
            {"label": "Omdurman", "lat": 15.65, "lon": 32.48},
            {"label": "Sokoto", "lat": 13.06, "lon": 5.24},
        ],
    ),
    "how have winters changed in tokyo since 2000?": (
        "Winter temperatures in the Tokyo area (December–February) have warmed noticeably "
        "since 2000. The coldest winter on record was in 2001, averaging around 4.3°C across "
        "the three winter months, while the warmest was 2023 at around 6.5°C. "
        "The overall trend shows roughly +0.3–0.5°C of warming over the period, consistent "
        "with the broader pattern of urban warming in East Asia.",
        [{"label": "Tokyo", "lat": 35.69, "lon": 139.69}],
    ),
    "which city has warmed the fastest in the last 50 years?": (
        "The city that has warmed the fastest in the last 50 years is **Longyearbyen, "
        "Svalbard** (Norway), with a warming trend of **1.21°C per decade** — roughly 6°C "
        "of warming over 50 years. This reflects the Arctic amplification effect, where "
        "polar regions warm at two to three times the global average rate.",
        [{"label": "Longyearbyen", "lat": 78.22, "lon": 15.65}],
    ),
    "what is the coldest major city in the world?": (
        "The coldest major city in the world is **Krasnoyarsk, Russia**, with a mean annual "
        "temperature of **1.0°C**.",
        [{"label": "Krasnoyarsk", "lat": 56.02, "lon": 92.87}],
    ),
    "how does the temperature in dubai compare to 20 years ago?": (
        "Dubai is measurably warmer than 20 years ago. The annual mean temperature has risen "
        "from **28.1°C** in 2006 to **28.9°C** in 2025 — an increase of **0.8°C** over "
        "two decades, driven by a combination of global warming and rapid urban expansion.",
        [{"label": "Dubai", "lat": 25.20, "lon": 55.27}],
    ),
    # Disabled — requires continent/region averaging which is not yet supported:
    # "is it getting hotter in europe?": ("...", []),
    # Disabled — requires precipitation metrics which are not yet in the catalogue:
    # "has rainfall changed in london over the last 30 years?": ("...", []),
    # "which city sees more rain: london or paris?": ("...", []),
}


def lookup(question: str) -> tuple[str, list[dict]] | None:
    """Return (answer, locations) for a question, or None if not found."""
    key = " ".join(question.strip().lower().split())
    return CANNED.get(key)


def stream_canned(answer: str, locations: list[dict], delay_s: float = 1.5):
    """
    Yield SSE event dicts that mimic a real orchestrator response,
    with an artificial delay before the answer.
    """
    time.sleep(delay_s)
    yield {"type": "answer", "text": answer}
    yield {
        "type": "done",
        "session_id": None,
        "step_count": 0,
        "tools_called": [],
        "tier": "canned",
        "model": None,
        "rejected_tiers": [],
        "model_override": None,
        "total_ms": int(delay_s * 1000),
        "steps_timing": [],
        "locations": locations,
    }
