"""
Tests for the SSE keepalive around the chat stream.

A chat turn can spend a minute inside one provider call without emitting an
event. Proxies treat that silence as a dead connection and close it, which the
browser sees as a stream that simply ends with no answer in it — the failure
looks like a network fault rather than a timeout.
"""

from __future__ import annotations

import itertools
import threading
import time

import pytest

from climate_api.main import _SSE_HEARTBEAT, _with_heartbeat


def _is_ping(chunk: str) -> bool:
    return chunk.startswith(":")


def test_heartbeat_fills_a_silent_gap():
    def stalling():
        yield "data: first\n\n"
        time.sleep(0.5)
        yield "data: second\n\n"

    out = list(_with_heartbeat(stalling(), interval_s=0.1))

    assert any(_is_ping(c) for c in out), "a stall must produce keepalives"
    # Payload order is preserved and nothing is dropped.
    assert [c for c in out if not _is_ping(c)] == [
        "data: first\n\n",
        "data: second\n\n",
    ]


def test_no_heartbeat_when_the_producer_keeps_up():
    """Canned answers finish in well under the interval and must stay clean."""
    out = list(_with_heartbeat(iter(["data: a\n\n", "data: b\n\n"]), interval_s=30))
    assert out == ["data: a\n\n", "data: b\n\n"]


def test_heartbeat_is_an_sse_comment():
    """The client skips every line that is not `data: `, so a comment is inert."""
    assert _SSE_HEARTBEAT.startswith(":")
    assert _SSE_HEARTBEAT.endswith("\n\n")
    assert not _SSE_HEARTBEAT.startswith("data:")


def test_producer_exception_reaches_the_caller():
    """A provider failure must not be swallowed by the worker thread."""

    def boom():
        yield "data: a\n\n"
        raise RuntimeError("provider exploded")

    gen = _with_heartbeat(boom(), interval_s=0.05)
    assert next(gen) == "data: a\n\n"
    with pytest.raises(RuntimeError, match="provider exploded"):
        list(gen)


def test_empty_stream_terminates():
    assert list(_with_heartbeat(iter([]), interval_s=0.05)) == []


def test_disconnect_stops_the_producer():
    """Closing the stream must stop the turn.

    Without this the worker would run the model to completion for a request
    nobody is reading, burning provider quota on abandoned questions.
    """
    produced: list[int] = []
    ticked = threading.Event()

    def counting():
        for i in itertools.count():
            produced.append(i)
            ticked.set()
            yield f"data: {i}\n\n"
            time.sleep(0.02)

    gen = _with_heartbeat(counting(), interval_s=5)
    next(gen)
    next(gen)
    at_close = len(produced)
    gen.close()

    time.sleep(0.4)  # long enough for many more items had it kept going
    # The producer only notices between yields, so allow it to finish the one
    # already in flight — but it must not still be running.
    assert len(produced) - at_close <= 2
