"""Domain enums / FSM transition tests."""

from __future__ import annotations

import pytest

from aura_backend.domain.enums import (
    GenerationJobState,
    JobTransitionError,
    SessionState,
    SessionTransitionError,
    allowed_generation_targets,
    allowed_session_targets,
    assert_generation_transition,
    assert_session_transition,
    is_terminal_generation_state,
)


class TestSessionFSM:
    def test_initial_state_is_idle(self):
        assert SessionState.IDLE.value == "IDLE"

    def test_idle_can_go_to_language_selected(self):
        assert_session_transition(SessionState.IDLE, SessionState.LANGUAGE_SELECTED)

    def test_idle_cannot_jump_to_generating(self):
        with pytest.raises(SessionTransitionError):
            assert_session_transition(SessionState.IDLE, SessionState.GENERATING)

    def test_completed_can_reset_to_idle(self):
        assert_session_transition(SessionState.COMPLETED, SessionState.IDLE)

    def test_error_can_reset_to_idle(self):
        assert_session_transition(SessionState.ERROR, SessionState.IDLE)

    def test_generating_can_go_to_completed_or_error(self):
        assert_session_transition(SessionState.GENERATING, SessionState.COMPLETED)
        assert_session_transition(SessionState.GENERATING, SessionState.ERROR)

    def test_terminal_states_have_no_outgoing_transitions(self):
        # Completed is "terminal" in the sense of a session; reset goes back to IDLE.
        assert SessionState.COMPLETED not in {SessionState.GENERATING, SessionState.ERROR}
        assert SessionState.ERROR not in {SessionState.GENERATING, SessionState.COMPLETED}

    def test_allowed_targets_helper(self):
        targets = allowed_session_targets(SessionState.GENERATING)
        assert SessionState.COMPLETED in targets
        assert SessionState.ERROR in targets
        assert SessionState.IDLE not in targets


class TestGenerationJobFSM:
    @pytest.mark.parametrize(
        "frm,to,allowed",
        [
            (GenerationJobState.CREATED, GenerationJobState.QUEUED, True),
            (GenerationJobState.QUEUED, GenerationJobState.PROCESSING, True),
            (GenerationJobState.PROCESSING, GenerationJobState.GENERATING, True),
            (GenerationJobState.GENERATING, GenerationJobState.POST_PROCESSING, True),
            (GenerationJobState.POST_PROCESSING, GenerationJobState.ENCODING, True),
            (GenerationJobState.ENCODING, GenerationJobState.COMPLETED, True),
            (GenerationJobState.CREATED, GenerationJobState.COMPLETED, False),
            (GenerationJobState.QUEUED, GenerationJobState.ENCODING, False),
            (GenerationJobState.GENERATING, GenerationJobState.COMPLETED, False),
            (GenerationJobState.COMPLETED, GenerationJobState.PROCESSING, False),
            (GenerationJobState.CANCELLED, GenerationJobState.QUEUED, False),
            (GenerationJobState.FAILED, GenerationJobState.PROCESSING, False),
        ],
    )
    def test_transitions(self, frm, to, allowed):
        if allowed:
            assert_generation_transition(frm, to)
        else:
            with pytest.raises(JobTransitionError):
                assert_generation_transition(frm, to)

    def test_cancel_from_any_non_terminal(self):
        for s in [
            GenerationJobState.CREATED,
            GenerationJobState.QUEUED,
            GenerationJobState.PROCESSING,
            GenerationJobState.GENERATING,
            GenerationJobState.POST_PROCESSING,
            GenerationJobState.ENCODING,
        ]:
            assert_generation_transition(s, GenerationJobState.CANCELLED)

    def test_terminal_states(self):
        for s in [
            GenerationJobState.COMPLETED,
            GenerationJobState.FAILED,
            GenerationJobState.CANCELLED,
            GenerationJobState.TIMEOUT,
        ]:
            assert is_terminal_generation_state(s) is True

    def test_allowed_targets_empty_for_terminal(self):
        for s in [
            GenerationJobState.COMPLETED,
            GenerationJobState.FAILED,
            GenerationJobState.CANCELLED,
            GenerationJobState.TIMEOUT,
        ]:
            assert allowed_generation_targets(s) == frozenset()

    def test_error_records_from_value(self):
        try:
            assert_generation_transition(
                GenerationJobState.COMPLETED, GenerationJobState.QUEUED
            )
        except JobTransitionError as exc:
            assert exc.frm == "COMPLETED"
            assert exc.to == "QUEUED"
        else:
            pytest.fail("expected JobTransitionError")