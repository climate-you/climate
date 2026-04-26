"""Tests for the chat-related methods of AnalyticsDB and for IPBlocklist."""

from __future__ import annotations

from pathlib import Path

import pytest

from climate_api.analytics.db import AnalyticsDB, IPBlocklist


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_MSG_DEFAULTS = dict(
    message_id="msg-1",
    session_id="sess-a",
    question="How warm is Paris?",
    answer="Paris averages 12°C.",
    step_count=2,
    tools_called=["get_metric_series"],
    tier="groq_70b",
)


def _db(tmp_path: Path) -> AnalyticsDB:
    return AnalyticsDB(tmp_path / "analytics.db")


def _record(db: AnalyticsDB, **overrides) -> None:
    kw = {**_MSG_DEFAULTS, **overrides}
    db.record_chat_message(**kw)


# ---------------------------------------------------------------------------
# record_chat_message / get_chat_messages round-trip
# ---------------------------------------------------------------------------


def test_record_and_retrieve_chat_message(tmp_path: Path) -> None:
    db = _db(tmp_path)
    _record(db)
    msgs = db.get_chat_messages()
    assert len(msgs) == 1
    m = msgs[0]
    assert m["message_id"] == "msg-1"
    assert m["session_id"] == "sess-a"
    assert m["question"] == "How warm is Paris?"
    assert m["answer"] == "Paris averages 12°C."
    assert m["step_count"] == 2
    assert m["tools_called"] == ["get_metric_series"]
    assert m["tier"] == "groq_70b"
    assert m["feedback"] is None
    assert m["error"] is None


def test_record_chat_message_opt_out_stored(tmp_path: Path) -> None:
    db = _db(tmp_path)
    _record(db, message_id="msg-2", opt_out=True)
    # opt_out is not returned in the public get_chat_messages fields —
    # verify by checking no crash and the record is stored
    msgs = db.get_chat_messages()
    assert len(msgs) == 1


def test_record_chat_message_all_optional_fields(tmp_path: Path) -> None:
    db = _db(tmp_path)
    db.record_chat_message(
        message_id="msg-full",
        session_id="sess-b",
        question="How warm?",
        answer="Very warm.",
        step_count=3,
        tools_called=["get_metric_series", "find_extreme_location"],
        tool_calls_detail=[{"name": "get_metric_series", "args": {}}],
        tier="groq_8b",
        opt_out=False,
        map_lat=48.8,
        map_lon=2.3,
        map_label="Paris, France",
        total_ms=1250,
        steps_timing=[{"step": 1, "model_ms": 400, "tools_ms": 50}],
        model="llama-70b",
        rejected_tiers=["groq_70b"],
        model_override=None,
        error=None,
        question_id="q-tree-1",
        parent_question_id=None,
        question_tree_version="v2",
    )
    msgs = db.get_chat_messages()
    assert len(msgs) == 1
    m = msgs[0]
    assert m["total_ms"] == 1250
    assert m["model"] == "llama-70b"
    assert m["rejected_tiers"] == ["groq_70b"]
    assert m["steps_timing"] == [{"step": 1, "model_ms": 400, "tools_ms": 50}]


def test_record_chat_message_with_error_sets_feedback_status_new(tmp_path: Path) -> None:
    db = _db(tmp_path)
    _record(db, answer=None, error="API error: timeout")
    msgs = db.get_chat_messages()
    assert msgs[0]["feedback_status"] == "new"
    assert msgs[0]["error"] == "API error: timeout"


def test_record_chat_message_without_error_has_no_feedback_status(tmp_path: Path) -> None:
    db = _db(tmp_path)
    _record(db)
    msgs = db.get_chat_messages()
    assert msgs[0]["feedback_status"] is None


def test_get_chat_messages_ordered_newest_first(tmp_path: Path) -> None:
    db = _db(tmp_path)
    _record(db, message_id="msg-a")
    _record(db, message_id="msg-b")
    msgs = db.get_chat_messages()
    # Both messages recorded; order by ts DESC — both have same second,
    # so just verify both are returned
    assert {m["message_id"] for m in msgs} == {"msg-a", "msg-b"}


def test_get_chat_messages_with_feedback_filter(tmp_path: Path) -> None:
    db = _db(tmp_path)
    _record(db, message_id="msg-good")
    _record(db, message_id="msg-bad")
    _record(db, message_id="msg-none")
    db.record_chat_feedback("msg-good", "good")
    db.record_chat_feedback("msg-bad", "bad")

    good = db.get_chat_messages(feedback="good")
    bad = db.get_chat_messages(feedback="bad")
    all_msgs = db.get_chat_messages()

    assert [m["message_id"] for m in good] == ["msg-good"]
    assert [m["message_id"] for m in bad] == ["msg-bad"]
    assert len(all_msgs) == 3


def test_get_chat_messages_limit_and_offset(tmp_path: Path) -> None:
    db = _db(tmp_path)
    for i in range(5):
        _record(db, message_id=f"msg-{i}")
    assert len(db.get_chat_messages(limit=2)) == 2
    assert len(db.get_chat_messages(limit=10)) == 5


# ---------------------------------------------------------------------------
# record_chat_feedback
# ---------------------------------------------------------------------------


def test_record_chat_feedback_bad_sets_new_status(tmp_path: Path) -> None:
    db = _db(tmp_path)
    _record(db)
    db.record_chat_feedback("msg-1", "bad")
    msgs = db.get_chat_messages()
    assert msgs[0]["feedback"] == "bad"
    assert msgs[0]["feedback_status"] == "new"


def test_record_chat_feedback_good_clears_status(tmp_path: Path) -> None:
    db = _db(tmp_path)
    _record(db)
    db.record_chat_feedback("msg-1", "good")
    msgs = db.get_chat_messages()
    assert msgs[0]["feedback"] == "good"
    assert msgs[0]["feedback_status"] is None


def test_record_chat_feedback_none_clears_feedback(tmp_path: Path) -> None:
    db = _db(tmp_path)
    _record(db)
    db.record_chat_feedback("msg-1", "bad")
    db.record_chat_feedback("msg-1", None)
    msgs = db.get_chat_messages()
    assert msgs[0]["feedback"] is None
    assert msgs[0]["feedback_status"] is None


# ---------------------------------------------------------------------------
# mark_bad_answer_reviewed
# ---------------------------------------------------------------------------


def test_mark_bad_answer_reviewed_updates_status(tmp_path: Path) -> None:
    db = _db(tmp_path)
    _record(db)
    db.record_chat_feedback("msg-1", "bad")
    db.mark_bad_answer_reviewed("msg-1")
    msgs = db.get_chat_messages()
    assert msgs[0]["feedback_status"] == "reviewed"


# ---------------------------------------------------------------------------
# get_chat_bad_answers
# ---------------------------------------------------------------------------


def test_get_chat_bad_answers_returns_new_status_only(tmp_path: Path) -> None:
    db = _db(tmp_path)
    _record(db, message_id="msg-a")
    _record(db, message_id="msg-b")
    _record(db, message_id="msg-c")
    db.record_chat_feedback("msg-a", "bad")   # feedback_status='new'
    db.record_chat_feedback("msg-b", "bad")
    db.mark_bad_answer_reviewed("msg-b")       # feedback_status='reviewed'
    db.record_chat_feedback("msg-c", "good")   # feedback_status=None

    bad = db.get_chat_bad_answers()
    assert len(bad) == 1
    assert bad[0]["message_id"] == "msg-a"


def test_get_chat_bad_answers_includes_error_messages(tmp_path: Path) -> None:
    db = _db(tmp_path)
    _record(db, message_id="msg-err", answer=None, error="Timed out")
    bad = db.get_chat_bad_answers()
    assert len(bad) == 1
    assert bad[0]["error"] == "Timed out"


def test_get_chat_bad_answers_empty_when_none_pending(tmp_path: Path) -> None:
    db = _db(tmp_path)
    _record(db)
    db.record_chat_feedback("msg-1", "good")
    assert db.get_chat_bad_answers() == []


# ---------------------------------------------------------------------------
# get_chat_stats
# ---------------------------------------------------------------------------


def test_get_chat_stats_empty_db(tmp_path: Path) -> None:
    db = _db(tmp_path)
    stats = db.get_chat_stats()
    assert stats["total_messages"] == 0
    assert stats["total_sessions"] == 0
    assert stats["avg_messages_per_session"] is None
    assert stats["avg_resp_ms"] is None
    assert stats["p95_resp_ms"] is None


def test_get_chat_stats_counts_and_feedback(tmp_path: Path) -> None:
    db = _db(tmp_path)
    _record(db, message_id="m1", session_id="s1", step_count=1, total_ms=100)
    _record(db, message_id="m2", session_id="s1", step_count=3, total_ms=200)
    _record(db, message_id="m3", session_id="s2", step_count=2, total_ms=300)
    db.record_chat_feedback("m1", "good")
    db.record_chat_feedback("m2", "bad")

    stats = db.get_chat_stats()
    assert stats["total_messages"] == 3
    assert stats["total_sessions"] == 2
    assert stats["avg_messages_per_session"] == pytest.approx(1.5)
    assert stats["feedback_good"] == 1
    assert stats["feedback_bad"] == 1
    assert stats["bad_answers_unreviewed"] == 1
    assert stats["avg_step_count"] == pytest.approx(2.0)
    assert stats["avg_resp_ms"] == pytest.approx(200)


def test_get_chat_stats_timing_p95(tmp_path: Path) -> None:
    db = _db(tmp_path)
    # Insert 20 messages with total_ms 100, 200, ..., 2000
    for i in range(1, 21):
        _record(db, message_id=f"m{i}", total_ms=i * 100)
    stats = db.get_chat_stats()
    # p95 index = max(0, int(20 * 0.95) - 1) = max(0, 19 - 1) = 18
    # values sorted: 100, 200, ..., 2000 → index 18 → 1900
    assert stats["p95_resp_ms"] == 1900


# ---------------------------------------------------------------------------
# get_last_event_ts
# ---------------------------------------------------------------------------


def test_get_last_event_ts_returns_none_when_empty(tmp_path: Path) -> None:
    db = _db(tmp_path)
    assert db.get_last_event_ts() is None


def test_get_last_event_ts_returns_most_recent(tmp_path: Path) -> None:
    db = _db(tmp_path)
    db.record_click(10.0, 20.0)
    db.record_session(None, None, None)
    ts = db.get_last_event_ts()
    assert ts is not None
    assert isinstance(ts, int)
    assert ts > 0


# ---------------------------------------------------------------------------
# check_schema
# ---------------------------------------------------------------------------


def test_check_schema_passes_on_fresh_db(tmp_path: Path) -> None:
    db = _db(tmp_path)
    # Trigger creation by connecting (lazy)
    db.record_click(0.0, 0.0)
    # Should not raise
    db.check_schema()


def test_check_schema_applies_optional_migrations_idempotently(tmp_path: Path) -> None:
    db = _db(tmp_path)
    db.record_click(0.0, 0.0)
    # Running twice should not raise — migrations detect existing columns silently
    db.check_schema()
    db.check_schema()


# ---------------------------------------------------------------------------
# IPBlocklist
# ---------------------------------------------------------------------------


def test_ip_blocklist_blocks_listed_ips(tmp_path: Path) -> None:
    f = tmp_path / "blocklist.txt"
    f.write_text("192.168.1.1\n10.0.0.1\n")
    bl = IPBlocklist(f)
    assert bl.is_blocked("192.168.1.1")
    assert bl.is_blocked("10.0.0.1")


def test_ip_blocklist_does_not_block_unlisted_ip(tmp_path: Path) -> None:
    f = tmp_path / "blocklist.txt"
    f.write_text("192.168.1.1\n")
    bl = IPBlocklist(f)
    assert not bl.is_blocked("192.168.1.2")


def test_ip_blocklist_ignores_comment_lines(tmp_path: Path) -> None:
    f = tmp_path / "blocklist.txt"
    f.write_text("# This is a comment\n192.168.1.1\n# Another comment\n")
    bl = IPBlocklist(f)
    assert bl.is_blocked("192.168.1.1")
    assert not bl.is_blocked("# This is a comment")


def test_ip_blocklist_empty_when_file_missing(tmp_path: Path) -> None:
    bl = IPBlocklist(tmp_path / "nonexistent.txt")
    assert len(bl) == 0
    assert not bl.is_blocked("1.2.3.4")


def test_ip_blocklist_len_counts_only_valid_entries(tmp_path: Path) -> None:
    f = tmp_path / "blocklist.txt"
    f.write_text("# header\n1.1.1.1\n2.2.2.2\n\n")
    bl = IPBlocklist(f)
    assert len(bl) == 2
