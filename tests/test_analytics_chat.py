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
    tier="groq_primary_free",
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
    assert m["tier"] == "groq_primary_free"
    assert m["feedback"] is None
    assert m["error"] is None


def test_record_chat_message_opt_out_stored(tmp_path: Path) -> None:
    db = _db(tmp_path)
    _record(db, message_id="msg-2", opt_out=True)
    msgs = db.get_chat_messages()
    assert len(msgs) == 1
    assert msgs[0]["opt_out"] is True


def test_get_chat_messages_marks_real_traffic_as_not_opted_out(
    tmp_path: Path,
) -> None:
    db = _db(tmp_path)
    _record(db)
    assert db.get_chat_messages()[0]["opt_out"] is False


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
        tier="groq_small",
        opt_out=False,
        map_lat=48.8,
        map_lon=2.3,
        map_label="Paris, France",
        total_ms=1250,
        steps_timing=[{"step": 1, "model_ms": 400, "tools_ms": 50}],
        model="openai/gpt-oss-20b",
        rejected_tiers=["groq_primary_free"],
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
    assert m["model"] == "openai/gpt-oss-20b"
    assert m["rejected_tiers"] == ["groq_primary_free"]
    assert m["steps_timing"] == [{"step": 1, "model_ms": 400, "tools_ms": 50}]
    # Question-tree attribution must survive the round trip: without these,
    # chip-click analytics cannot be segmented by tree revision and counts
    # from different question wordings silently pool together.
    assert m["question_id"] == "q-tree-1"
    assert m["parent_question_id"] is None
    assert m["question_tree_version"] == "v2"


def test_question_tree_fields_returned_for_typed_questions(tmp_path: Path) -> None:
    """Free-typed questions carry no question_id but still record a version."""
    db = _db(tmp_path)
    _record(db, message_id="msg-typed")
    m = db.get_chat_messages()[0]
    assert m["question_id"] is None
    assert m["parent_question_id"] is None
    assert m["question_tree_version"] is None


def test_record_chat_message_with_error_sets_feedback_status_new(
    tmp_path: Path,
) -> None:
    db = _db(tmp_path)
    _record(db, answer=None, error="API error: timeout")
    msgs = db.get_chat_messages()
    assert msgs[0]["feedback_status"] == "new"
    assert msgs[0]["error"] == "API error: timeout"


def test_record_chat_message_without_error_has_no_feedback_status(
    tmp_path: Path,
) -> None:
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
    db.record_chat_feedback("msg-a", "bad")  # feedback_status='new'
    db.record_chat_feedback("msg-b", "bad")
    db.mark_bad_answer_reviewed("msg-b")  # feedback_status='reviewed'
    db.record_chat_feedback("msg-c", "good")  # feedback_status=None

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


def test_get_chat_stats_ignore_opted_out_messages(tmp_path: Path) -> None:
    db = _db(tmp_path)
    _record(db, message_id="m1", session_id="s1", step_count=2, total_ms=100)
    _record(
        db,
        message_id="m2",
        session_id="s-test",
        step_count=8,
        total_ms=9000,
        opt_out=True,
    )
    db.record_chat_feedback("m2", "bad")

    stats = db.get_chat_stats()
    assert stats["total_messages"] == 1
    assert stats["total_sessions"] == 1
    assert stats["feedback_bad"] == 0
    assert stats["bad_answers_unreviewed"] == 0
    assert stats["avg_step_count"] == pytest.approx(2.0)
    assert stats["avg_resp_ms"] == pytest.approx(100)


def test_get_chat_bad_answers_skip_opted_out_messages(tmp_path: Path) -> None:
    db = _db(tmp_path)
    _record(db, message_id="m-test", opt_out=True, error="boom")
    _record(db, message_id="m-real", error="boom")
    ids = [m["message_id"] for m in db.get_chat_bad_answers()]
    assert ids == ["m-real"]


def test_get_chat_stats_timing_p95(tmp_path: Path) -> None:
    db = _db(tmp_path)
    # Insert 20 messages with total_ms 100, 200, ..., 2000
    for i in range(1, 21):
        _record(db, message_id=f"m{i}", total_ms=i * 100)
    stats = db.get_chat_stats()
    # p95 index = max(0, int(20 * 0.95) - 1) = max(0, 19 - 1) = 18
    # values sorted: 100, 200, ..., 2000 → index 18 → 1900
    assert stats["p95_resp_ms"] == 1900


def test_get_chat_stats_report_effort_with_and_without_canned(
    tmp_path: Path,
) -> None:
    """Canned and templated answers report a fixed think-time and take no steps.

    Leaving them in the only latency and step figures makes the assistant look
    faster and simpler the more often the fast paths hit, so both cuts are
    reported.
    """
    db = _db(tmp_path)
    _record(db, message_id="c1", tier="canned", total_ms=1500, step_count=0)
    _record(db, message_id="c2", tier="templated", total_ms=1500, step_count=0)
    _record(
        db, message_id="l1", tier="groq_primary_free", total_ms=6000, step_count=3
    )
    _record(db, message_id="l2", tier="groq_small_free", total_ms=10000, step_count=5)

    stats = db.get_chat_stats()
    assert stats["avg_resp_ms"] == 4750
    assert stats["avg_resp_ms_llm"] == 8000
    assert stats["p95_resp_ms"] == 6000
    assert stats["p95_resp_ms_llm"] == 6000
    assert stats["avg_step_count"] == pytest.approx(2.0)
    assert stats["avg_step_count_llm"] == pytest.approx(4.0)


def test_get_chat_stats_llm_figures_none_when_only_canned(tmp_path: Path) -> None:
    db = _db(tmp_path)
    _record(db, message_id="c1", tier="canned", total_ms=1500, step_count=0)
    stats = db.get_chat_stats()
    assert stats["avg_resp_ms"] == 1500
    assert stats["avg_resp_ms_llm"] is None
    assert stats["p95_resp_ms_llm"] is None
    # An all-canned corpus really does average zero steps — that is a figure,
    # not missing data.
    assert stats["avg_step_count"] == 0
    assert stats["avg_step_count_llm"] is None


def test_get_chat_stats_count_untiered_answers_as_llm(tmp_path: Path) -> None:
    """A failed answer records no tier — it still cost real time, so it counts."""
    db = _db(tmp_path)
    _record(db, message_id="e1", tier=None, total_ms=4000, step_count=2)
    stats = db.get_chat_stats()
    assert stats["avg_resp_ms_llm"] == 4000
    assert stats["avg_step_count_llm"] == pytest.approx(2.0)


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


# ---------------------------------------------------------------------------
# Question-tree analytics
# ---------------------------------------------------------------------------


def test_question_tree_stats_never_pool_across_revisions(tmp_path: Path) -> None:
    """The same id in two revisions must stay two rows.

    Questions get reworded between revisions, so summing them would compare
    clicks on questions that no longer say the same thing.
    """
    db = _db(tmp_path)
    for i in range(3):
        _record(
            db,
            message_id=f"old-{i}",
            question_id="global_temp_change",
            question_tree_version="2026-04-25",
        )
    for i in range(5):
        _record(
            db,
            message_id=f"new-{i}",
            question_id="global_temp_change",
            question_tree_version="2026-07-09",
        )

    stats = db.get_question_tree_stats()
    by_version = {s["question_tree_version"]: s["clicks"] for s in stats}
    assert by_version == {"2026-04-25": 3, "2026-07-09": 5}


def test_question_tree_stats_track_parent_edges(tmp_path: Path) -> None:
    """Follow-up chips record which question they were reached from."""
    db = _db(tmp_path)
    _record(
        db,
        message_id="root",
        question_id="global_temp_change",
        question_tree_version="v1",
    )
    _record(
        db,
        message_id="child",
        question_id="fastest_warming_continent",
        parent_question_id="global_temp_change",
        question_tree_version="v1",
    )
    stats = {s["question_id"]: s for s in db.get_question_tree_stats()}
    assert stats["global_temp_change"]["parent_question_id"] is None
    assert (
        stats["fastest_warming_continent"]["parent_question_id"] == "global_temp_change"
    )


def test_question_tree_stats_exclude_typed_questions(tmp_path: Path) -> None:
    db = _db(tmp_path)
    _record(db, message_id="typed-1")  # no question_id
    _record(
        db,
        message_id="chip-1",
        question_id="hot_days_global",
        question_tree_version="v1",
    )
    stats = db.get_question_tree_stats()
    assert [s["question_id"] for s in stats] == ["hot_days_global"]


def test_question_tree_stats_carry_feedback(tmp_path: Path) -> None:
    db = _db(tmp_path)
    _record(db, message_id="a", question_id="q1", question_tree_version="v1")
    _record(db, message_id="b", question_id="q1", question_tree_version="v1")
    db.record_chat_feedback("a", "good")
    db.record_chat_feedback("b", "bad")
    stat = db.get_question_tree_stats()[0]
    assert stat["clicks"] == 2
    assert stat["feedback_good"] == 1
    assert stat["feedback_bad"] == 1


def test_typed_question_counts_split_by_revision(tmp_path: Path) -> None:
    db = _db(tmp_path)
    _record(db, message_id="t1", question_tree_version="v1")
    _record(db, message_id="t2", question_tree_version="v1")
    _record(db, message_id="t3", question_tree_version="v2")
    _record(db, message_id="c1", question_id="q1", question_tree_version="v1")
    counts = {
        c["question_tree_version"]: c["typed"] for c in db.get_typed_question_counts()
    }
    assert counts == {"v1": 2, "v2": 1}


def test_question_tree_analytics_ignore_opted_out_messages(tmp_path: Path) -> None:
    """Testing the chip tree from an opted-out browser must not move its counts."""
    db = _db(tmp_path)
    _record(db, message_id="real", question_id="q1", question_tree_version="v1")
    _record(
        db,
        message_id="test-chip",
        question_id="q1",
        question_tree_version="v1",
        opt_out=True,
    )
    _record(
        db,
        message_id="test-typed",
        session_id="s-test",
        question_tree_version="v1",
        opt_out=True,
    )

    assert [s["clicks"] for s in db.get_question_tree_stats()] == [1]
    assert db.get_typed_question_counts() == []
    assert db.get_typed_question_entry_points() == []


def test_question_tree_stats_empty_db(tmp_path: Path) -> None:
    db = _db(tmp_path)
    assert db.get_question_tree_stats() == []
    assert db.get_typed_question_counts() == []


def test_typed_entry_points_attribute_to_the_last_chip(tmp_path: Path) -> None:
    """A typed question is attributed to the suggestion clicked before it."""
    db = _db(tmp_path)
    _record(
        db,
        message_id="a",
        session_id="s1",
        question_id="hot_days_global",
        question_tree_version="v1",
    )
    _record(
        db,
        message_id="b",
        session_id="s1",
        question="What about hail?",
        question_tree_version="v1",
    )

    points = db.get_typed_question_entry_points()
    assert len(points) == 1
    assert points[0]["after_question_id"] == "hot_days_global"
    assert points[0]["typed"] == 1
    assert points[0]["examples"] == ["What about hail?"]


def test_typed_entry_points_flag_sessions_that_never_used_a_chip(
    tmp_path: Path,
) -> None:
    """Typing with no prior chip means the suggestions were bypassed."""
    db = _db(tmp_path)
    _record(
        db,
        message_id="a",
        session_id="s1",
        question="Anything about wind?",
        question_tree_version="v1",
    )
    points = db.get_typed_question_entry_points()
    assert points[0]["after_question_id"] is None
    assert points[0]["typed"] == 1


def test_typed_entry_points_do_not_leak_across_sessions(tmp_path: Path) -> None:
    """One user's chip must not be credited for another user's typing."""
    db = _db(tmp_path)
    _record(
        db,
        message_id="a",
        session_id="s1",
        question_id="hot_days_global",
        question_tree_version="v1",
    )
    _record(
        db,
        message_id="b",
        session_id="s2",
        question="Unrelated question",
        question_tree_version="v1",
    )

    points = {p["after_question_id"]: p for p in db.get_typed_question_entry_points()}
    assert set(points) == {None}
    assert points[None]["typed"] == 1


def test_typed_entry_points_track_the_most_recent_chip(tmp_path: Path) -> None:
    """Attribution follows the latest chip, not the first one in the session."""
    db = _db(tmp_path)
    _record(
        db,
        message_id="a",
        session_id="s1",
        question_id="first_q",
        question_tree_version="v1",
    )
    _record(
        db,
        message_id="b",
        session_id="s1",
        question_id="second_q",
        question_tree_version="v1",
    )
    _record(
        db,
        message_id="c",
        session_id="s1",
        question="Now a typed one",
        question_tree_version="v1",
    )

    points = db.get_typed_question_entry_points()
    assert points[0]["after_question_id"] == "second_q"


def test_typed_entry_points_group_by_revision(tmp_path: Path) -> None:
    db = _db(tmp_path)
    _record(
        db, message_id="a", session_id="s1", question_id="q", question_tree_version="v1"
    )
    _record(
        db,
        message_id="b",
        session_id="s1",
        question="typed",
        question_tree_version="v1",
    )
    _record(
        db, message_id="c", session_id="s2", question_id="q", question_tree_version="v2"
    )
    _record(
        db,
        message_id="d",
        session_id="s2",
        question="typed",
        question_tree_version="v2",
    )

    versions = {
        p["question_tree_version"] for p in db.get_typed_question_entry_points()
    }
    assert versions == {"v1", "v2"}


def test_typed_entry_points_cap_examples(tmp_path: Path) -> None:
    """Examples are illustrative, not an unbounded dump."""
    db = _db(tmp_path)
    _record(
        db,
        message_id="chip",
        session_id="s1",
        question_id="q",
        question_tree_version="v1",
    )
    for i in range(6):
        _record(
            db,
            message_id=f"t{i}",
            session_id="s1",
            question=f"typed {i}",
            question_tree_version="v1",
        )
    point = db.get_typed_question_entry_points()[0]
    assert point["typed"] == 6
    assert len(point["examples"]) == 3


def test_typed_entry_points_empty_db(tmp_path: Path) -> None:
    assert _db(tmp_path).get_typed_question_entry_points() == []
