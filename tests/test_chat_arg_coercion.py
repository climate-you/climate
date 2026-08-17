"""
Tests for tool-call argument coercion in the chat orchestrator.

Models do not reliably honour the JSON schema attached to a tool definition.
qwen3.6-27b, for instance, emits `"true"`/`"false"` as strings for boolean
parameters. Plain `bool("false")` is True, which would silently invert flags
such as `capital_only` — turning "hottest capital city" into "hottest city".
"""

from __future__ import annotations

import pytest

from climate_api.chat.orchestrator import _as_bool


@pytest.mark.parametrize(
    "value",
    [True, "true", "True", "TRUE", " true ", "yes", "1", 1, 2, -1, [0], {"a": 1}],
)
def test_truthy_values(value):
    assert _as_bool(value) is True


@pytest.mark.parametrize(
    "value",
    [
        False,
        "false",
        "False",
        "FALSE",
        " false ",
        "no",
        "0",
        "none",
        "null",
        "",
        "   ",
        0,
        None,
        [],
        {},
    ],
)
def test_falsey_values(value):
    assert _as_bool(value) is False


def test_string_false_is_not_truthy():
    """The specific bug: bool("false") is True, _as_bool("false") is False."""
    assert bool("false") is True
    assert _as_bool("false") is False


def test_returns_real_bools_not_truthy_objects():
    for value in ("true", "false", 1, 0, None, [], "x"):
        assert isinstance(_as_bool(value), bool)
