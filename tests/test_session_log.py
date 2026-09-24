"""Tests for the plain-text session export."""

from __future__ import annotations

from climate_api.analytics.session_log import format_session_log, session_log_filename


def _msg(**overrides) -> dict:
    base = dict(
        message_id="msg-1",
        session_id="7c8ce746-1111-2222-3333",
        ts=1756288931,
        question="Which city warmed the most?",
        answer="Paris warmed the most.",
        step_count=2,
        tools_called=["find_extreme_location"],
        tool_calls_detail=[
            {
                "name": "find_extreme_location",
                "args": {"metric_id": "t2m_yearly_mean_c", "limit": 10},
                "step": 1,
            }
        ],
        tier="groq_primary_free",
        model="openai/gpt-oss-120b",
        rejected_tiers=[],
        model_override=None,
        feedback=None,
        feedback_status=None,
        total_ms=93000,
        steps_timing=[
            {
                "step": 1,
                "model_ms": 42000,
                "tools_ms": 50000,
                "prompt_tokens": 6573,
                "completion_tokens": 217,
            },
            {"step": 2, "model_ms": 94, "error": True},
        ],
        error=None,
        question_id=None,
        parent_question_id=None,
        question_tree_version=None,
        opt_out=False,
    )
    base.update(overrides)
    return base


class TestHeader:
    def test_reports_session_and_count(self):
        out = format_session_log([_msg(), _msg(message_id="msg-2")])
        assert "7c8ce746-1111-2222-3333" in out
        assert "Messages: 2" in out

    def test_message_timestamp_rendered_as_utc(self):
        """Fixed to the message's own ts — never to whatever today happens to be."""
        out = format_session_log([_msg(ts=1756288931)])
        assert "2025-08-27 10:02:11 UTC" in out

    def test_empty_session_says_so(self):
        out = format_session_log([], session_id="nope")
        assert "No messages found" in out and "nope" in out

    def test_flags_a_prefix_that_hit_several_sessions(self):
        out = format_session_log([_msg(session_id="a-1"), _msg(session_id="a-2")])
        assert "matched 2 sessions" in out


class TestMessageBlock:
    def test_question_and_answer_present(self):
        out = format_session_log([_msg()])
        assert "Which city warmed the most?" in out
        assert "Paris warmed the most." in out

    def test_tool_calls_include_arguments(self):
        """The args are the point — a bad limit or metric_id is the usual cause."""
        out = format_session_log([_msg()])
        assert "find_extreme_location" in out
        assert '"limit": 10' in out
        assert '"metric_id": "t2m_yearly_mean_c"' in out

    def test_token_counts_are_shown_per_step(self):
        out = format_session_log([_msg()])
        assert "6573p + 217c tokens" in out

    def test_failed_step_is_marked(self):
        out = format_session_log([_msg()])
        assert "ERROR" in out

    def test_error_text_is_included(self):
        out = format_session_log([_msg(error="Request too large for model")])
        assert "Request too large for model" in out

    def test_rejected_tiers_listed(self):
        out = format_session_log([_msg(rejected_tiers=["groq_primary_free"])])
        assert "rejected=groq_primary_free" in out

    def test_opt_out_flagged(self):
        assert "opt_out=true" in format_session_log([_msg(opt_out=True)])
        assert "opt_out=true" not in format_session_log([_msg(opt_out=False)])

    def test_multi_line_answer_is_indented(self):
        out = format_session_log([_msg(answer="line one\nline two")])
        assert "    line one" in out and "    line two" in out

    def test_empty_answer_is_explicit(self):
        assert "(empty)" in format_session_log([_msg(answer="")])

    def test_messages_are_numbered(self):
        out = format_session_log([_msg(), _msg(message_id="m2"), _msg(message_id="m3")])
        assert "[1/3]" in out and "[2/3]" in out and "[3/3]" in out

    def test_falls_back_to_tool_names_when_no_detail_stored(self):
        """Older rows recorded names only."""
        out = format_session_log([_msg(tool_calls_detail=[])])
        assert "Tools called: find_extreme_location" in out

    def test_missing_optional_fields_do_not_crash(self):
        out = format_session_log([{"question": "hi", "session_id": "s"}])
        assert "hi" in out and "unknown" in out


class TestFilename:
    def test_uses_first_eight_characters(self):
        assert session_log_filename("7c8ce746-1111-2222") == "session_7c8ce746.log"

    def test_strips_path_characters(self):
        assert "/" not in session_log_filename("../../etc/passwd")
        assert session_log_filename("a/b").startswith("session_ab")

    def test_empty_id_still_names_a_file(self):
        assert session_log_filename("") == "session_unknown.log"
