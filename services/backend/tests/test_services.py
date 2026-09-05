"""Service layer tests."""

from __future__ import annotations

import pytest

from aura_backend.domain import GenerationJobState, SessionState, VideoCodec
from aura_backend.errors import JobAlreadyTerminalError, NotFoundError, ValidationFailed
from aura_backend.services import ExperienceService, GenerationJobService, SessionService


def _drive_session_to_uploaded(svc: SessionService, sid: str) -> None:
    """Walk a fresh session through the FSM to UPLOADED."""
    svc.select_language(sid, "en")
    svc.select_theme(sid, "aurora")
    svc.start_countdown(sid)
    svc.start_capture(sid)
    svc.mark_uploaded(sid, "captures/x.jpg")


def test_session_service_create_default(db_session):
    svc = SessionService(db_session)
    s = svc.create()
    assert s.state == SessionState.IDLE
    assert s.language is None


def test_session_service_lifecycle(db_session):
    svc = SessionService(db_session)
    s = svc.create()
    s2 = svc.select_language(s.id, "en")
    assert s2.state == SessionState.LANGUAGE_SELECTED
    s3 = svc.select_theme(s2.id, "aurora")
    assert s3.state == SessionState.THEME_SELECTED
    assert s3.theme_id == "aurora"
    s4 = svc.start_countdown(s3.id)
    assert s4.state == SessionState.COUNTDOWN
    s5 = svc.start_capture(s4.id)
    assert s5.state == SessionState.CAPTURING
    s6 = svc.mark_uploaded(s5.id, "captures/x.jpg")
    assert s6.state == SessionState.UPLOADED
    s7 = svc.mark_generating(s6.id)
    assert s7.state == SessionState.GENERATING
    s8 = svc.mark_completed(s7.id)
    assert s8.state == SessionState.COMPLETED


def test_session_service_get_not_found(db_session):
    svc = SessionService(db_session)
    with pytest.raises(NotFoundError):
        svc.get("does-not-exist")


def test_session_service_create_with_language(db_session):
    svc = SessionService(db_session)
    s = svc.create(language="ar")
    assert s.state == SessionState.LANGUAGE_SELECTED
    assert s.language == "ar"


def test_session_service_reset(db_session):
    svc = SessionService(db_session)
    s = svc.create()
    _drive_session_to_uploaded(svc, s.id)
    svc.mark_generating(s.id)
    svc.mark_completed(s.id)
    reset = svc.reset(s.id)
    assert reset.state == SessionState.IDLE


def test_session_service_mark_uploaded_requires_capturing_state(db_session):
    # Demo FSM is permissive: LANGUAGE_SELECTED -> UPLOADED is now allowed (direct upload path)
    svc = SessionService(db_session)
    s = svc.create()
    svc.select_language(s.id, "en")
    # Direct upload should now succeed (permissive demo FSM)
    s2 = svc.mark_uploaded(s.id, "c.jpg")
    assert s2.state == SessionState.UPLOADED
    assert s2.capture_ref == "c.jpg"


def test_experience_service_list_falls_back_to_seed(db_session):
    svc = ExperienceService(db_session)
    items = svc.list(enabled_only=True)
    assert {e.id for e in items} == {"aurora", "mirage", "pulse"}


def test_experience_service_list_includes_disabled_when_requested(db_session):
    svc = ExperienceService(db_session)
    items = svc.list(enabled_only=False)
    ids = {e.id for e in items}
    assert "aurora" in ids and "driftwood" in ids


def test_experience_service_get_known(db_session):
    svc = ExperienceService(db_session)
    exp = svc.get("aurora")
    assert exp.display_name == "Aurora"


def test_experience_service_get_unknown_raises(db_session):
    svc = ExperienceService(db_session)
    with pytest.raises(NotFoundError):
        svc.get("nope")


def test_generation_job_service_create_requires_capture(db_session):
    sessions = SessionService(db_session)
    jobs = GenerationJobService(db_session)
    s = sessions.create()
    sessions.select_language(s.id, "en")
    sessions.select_theme(s.id, "aurora")
    # No capture uploaded yet
    with pytest.raises(ValidationFailed):
        jobs.create(session_id=s.id, experience_id="aurora")


def test_generation_job_service_create_success(db_session):
    sessions = SessionService(db_session)
    jobs = GenerationJobService(db_session)
    s = sessions.create()
    _drive_session_to_uploaded(sessions, s.id)
    job = jobs.create(session_id=s.id, experience_id="aurora")
    assert job.state == GenerationJobState.QUEUED
    assert job.session_id == s.id
    assert job.experience_id == "aurora"
    assert job.provider_id


def test_generation_job_service_create_session_missing(db_session):
    jobs = GenerationJobService(db_session)
    with pytest.raises(NotFoundError):
        jobs.create(session_id="missing", experience_id="aurora")


def test_generation_job_service_full_pipeline(db_session):
    sessions = SessionService(db_session)
    jobs = GenerationJobService(db_session)
    s = sessions.create()
    _drive_session_to_uploaded(sessions, s.id)
    job = jobs.create(session_id=s.id, experience_id="aurora")
    assert job.state == GenerationJobState.QUEUED
    job = jobs.begin_processing(job.id)
    assert job.state == GenerationJobState.PROCESSING
    job = jobs.begin_generating(job.id)
    assert job.state == GenerationJobState.GENERATING
    job = jobs.begin_post_processing(job.id)
    assert job.state == GenerationJobState.POST_PROCESSING
    job = jobs.begin_encoding(job.id)
    assert job.state == GenerationJobState.ENCODING
    job = jobs.complete(
        job.id,
        output_key="generated/x.mp4",
        output_url="https://cdn/x.mp4",
        duration_sec=4.0,
        codec=VideoCodec.H264,
        size_bytes=1024,
    )
    assert job.state == GenerationJobState.COMPLETED
    assert job.output is not None
    assert job.output.key == "generated/x.mp4"
    assert job.output.codec == VideoCodec.H264


def test_generation_job_service_cancel(db_session):
    sessions = SessionService(db_session)
    jobs = GenerationJobService(db_session)
    s = sessions.create()
    _drive_session_to_uploaded(sessions, s.id)
    job = jobs.create(session_id=s.id, experience_id="aurora")
    cancelled = jobs.cancel(job.id)
    assert cancelled.state == GenerationJobState.CANCELLED


def test_generation_job_service_cannot_cancel_completed(db_session):
    sessions = SessionService(db_session)
    jobs = GenerationJobService(db_session)
    s = sessions.create()
    _drive_session_to_uploaded(sessions, s.id)
    job = jobs.create(session_id=s.id, experience_id="aurora")
    jobs.begin_processing(job.id)
    jobs.begin_generating(job.id)
    jobs.begin_post_processing(job.id)
    jobs.begin_encoding(job.id)
    jobs.complete(
        job.id, output_key="k", output_url="u", duration_sec=4.0
    )
    with pytest.raises(JobAlreadyTerminalError):
        jobs.cancel(job.id)


def test_generation_job_service_fail(db_session):
    sessions = SessionService(db_session)
    jobs = GenerationJobService(db_session)
    s = sessions.create()
    _drive_session_to_uploaded(sessions, s.id)
    job = jobs.create(session_id=s.id, experience_id="aurora")
    failed = jobs.fail(job.id, "submit_failed", "no creds")
    assert failed.state == GenerationJobState.FAILED
    assert failed.error_code == "submit_failed"


def test_generation_job_service_timeout(db_session):
    sessions = SessionService(db_session)
    jobs = GenerationJobService(db_session)
    s = sessions.create()
    _drive_session_to_uploaded(sessions, s.id)
    job = jobs.create(session_id=s.id, experience_id="aurora")
    jobs.begin_processing(job.id)
    timed_out = jobs.timeout(job.id)
    assert timed_out.state == GenerationJobState.TIMEOUT
    assert timed_out.error_code == "timeout"


def test_generation_job_service_update_progress(db_session):
    sessions = SessionService(db_session)
    jobs = GenerationJobService(db_session)
    s = sessions.create()
    _drive_session_to_uploaded(sessions, s.id)
    job = jobs.create(session_id=s.id, experience_id="aurora")
    jobs.begin_processing(job.id)
    updated = jobs.update_progress(job.id, 0.5)
    assert updated.progress == 0.5


def test_generation_job_service_get(db_session):
    sessions = SessionService(db_session)
    jobs = GenerationJobService(db_session)
    s = sessions.create()
    _drive_session_to_uploaded(sessions, s.id)
    job = jobs.create(session_id=s.id, experience_id="aurora")
    fetched = jobs.get(job.id)
    assert fetched.id == job.id