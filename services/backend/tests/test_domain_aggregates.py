"""Domain aggregate tests: Session, Experience, GenerationJob, VideoAsset, ReelItem."""

from __future__ import annotations

import pytest

from aura_backend.domain import (
    Experience,
    ExperienceTheme,
    GenerationJob,
    GenerationJobState,
    ReelItem,
    ReelItemKind,
    Session,
    SessionState,
    VideoAsset,
    VideoCodec,
)


class TestSession:
    def test_create_defaults(self):
        s = Session()
        assert s.id and len(s.id) == 32
        assert s.state == SessionState.IDLE
        assert s.language is None
        assert s.theme_id is None

    def test_select_language_requires_non_empty(self):
        s = Session()
        with pytest.raises(ValueError):
            s.select_language("")
        with pytest.raises(ValueError):
            s.select_language("a" * 9)

    def test_select_language_idle_only(self):
        s = Session()
        s.select_language("en")
        assert s.state == SessionState.LANGUAGE_SELECTED
        with pytest.raises(Exception):
            s.select_language("ar")

    def test_full_happy_path(self):
        s = Session()
        s.select_language("en")
        s.select_theme("aurora")
        s.start_countdown()
        s.start_capture()
        s.mark_uploaded("captures/x.jpg")
        s.mark_generating()
        s.mark_completed()
        assert s.state == SessionState.COMPLETED
        assert s.capture_ref == "captures/x.jpg"
        assert s.language == "en"
        assert s.theme_id == "aurora"

    def test_reset_from_terminal(self):
        s = Session()
        s.select_language("en")
        s.select_theme("aurora")
        s.start_countdown()
        s.start_capture()
        s.mark_uploaded("c.jpg")
        s.mark_generating()
        s.mark_completed()
        s.reset()
        assert s.state == SessionState.IDLE

    def test_error_path(self):
        s = Session()
        s.select_language("en")
        s.select_theme("aurora")
        s.start_countdown()
        s.start_capture()
        s.mark_uploaded("c.jpg")
        s.mark_generating()
        s.mark_error()
        assert s.state == SessionState.ERROR


class TestExperience:
    def _valid(self, **kw):
        defaults = dict(
            id="aurora",
            display_name="Aurora",
            description="desc",
            prompt="a portrait, cinematic",
        )
        defaults.update(kw)
        return Experience(**defaults)

    def test_minimal_valid(self):
        e = self._valid()
        assert e.id == "aurora"
        assert e.duration_sec == 4.0
        assert e.fps == 12
        assert e.aspect_ratio == "9:16"

    def test_id_required(self):
        with pytest.raises(ValueError):
            self._valid(id="")

    def test_display_name_required(self):
        with pytest.raises(ValueError):
            self._valid(display_name="")

    def test_description_required(self):
        with pytest.raises(ValueError):
            self._valid(description="")

    def test_prompt_required(self):
        with pytest.raises(ValueError):
            self._valid(prompt="")
        with pytest.raises(ValueError):
            self._valid(prompt="   ")

    def test_prompt_length_bound(self):
        with pytest.raises(ValueError):
            self._valid(prompt="x" * 4001)

    def test_negative_prompt_length_bound(self):
        with pytest.raises(ValueError):
            self._valid(prompt="ok", negative_prompt="x" * 4001)

    def test_duration_bounds(self):
        with pytest.raises(ValueError):
            self._valid(duration_sec=0)
        with pytest.raises(ValueError):
            self._valid(duration_sec=31)

    def test_fps_bounds(self):
        with pytest.raises(ValueError):
            self._valid(fps=0)
        with pytest.raises(ValueError):
            self._valid(fps=61)

    def test_resolution_validation(self):
        with pytest.raises(ValueError):
            self._valid(resolution="not-a-res")
        with pytest.raises(ValueError):
            self._valid(resolution="10x10")

    def test_aspect_ratio_validation(self):
        with pytest.raises(ValueError):
            self._valid(aspect_ratio="bad")
        with pytest.raises(ValueError):
            self._valid(aspect_ratio="100:100")

    def test_default_language_must_be_in_supported(self):
        with pytest.raises(ValueError):
            self._valid(supported_languages=("en",), default_language="ar")

    def test_supported_languages_required(self):
        with pytest.raises(ValueError):
            self._valid(supported_languages=())

    def test_theme_and_metadata_round_trip(self):
        theme = ExperienceTheme(palette={"primary": "#fff"}, background_music="song.mp3")
        e = self._valid(theme=theme, metadata={"k": "v"})
        assert e.theme.palette == {"primary": "#fff"}
        assert e.theme.background_music == "song.mp3"
        assert e.metadata == {"k": "v"}
        # motion lives on the MotionConfig object now
        assert e.motion.strength == 0.7


class TestVideoAsset:
    def test_minimal_valid(self):
        a = VideoAsset(key="k", url="https://x/v.mp4", duration_sec=3.0)
        assert a.codec == VideoCodec.H264
        assert a.duration_sec == 3.0

    def test_key_and_url_required(self):
        with pytest.raises(ValueError):
            VideoAsset(key="", url="u", duration_sec=1.0)
        with pytest.raises(ValueError):
            VideoAsset(key="k", url="", duration_sec=1.0)

    def test_duration_positive(self):
        with pytest.raises(ValueError):
            VideoAsset(key="k", url="u", duration_sec=0)
        with pytest.raises(ValueError):
            VideoAsset(key="k", url="u", duration_sec=-1)


class TestReelItem:
    def test_minimal_valid(self):
        r = ReelItem(src="/x.mp4")
        assert r.kind == ReelItemKind.CURATED
        assert r.duration_sec == 4.0

    def test_src_required(self):
        with pytest.raises(ValueError):
            ReelItem(src="")

    def test_duration_positive(self):
        with pytest.raises(ValueError):
            ReelItem(src="/x.mp4", duration_sec=0)

    def test_kind_string_normalized(self):
        r = ReelItem(src="/x.mp4", kind="generated")  # type: ignore[arg-type]
        assert r.kind == ReelItemKind.GENERATED


class TestGenerationJob:
    def _make(self, **kw) -> GenerationJob:
        base = dict(
            session_id="s1",
            experience_id="aurora",
            provider_id="fake",
            max_attempts=2,
        )
        base.update(kw)
        return GenerationJob(**base)

    def test_construction_validates_session_and_experience(self):
        with pytest.raises(ValueError):
            GenerationJob(session_id="", experience_id="aurora")
        with pytest.raises(ValueError):
            GenerationJob(session_id="s", experience_id="")

    def test_default_state_is_created(self):
        j = self._make()
        assert j.state == GenerationJobState.CREATED
        assert j.attempts == 0
        assert j.progress == 0.0

    def test_enqueue_sets_started_at(self):
        j = self._make()
        assert j.started_at is None
        j.enqueue()
        assert j.state == GenerationJobState.QUEUED
        assert j.started_at is not None

    def test_full_pipeline(self):
        j = self._make()
        j.enqueue()
        j.begin_processing()
        j.begin_generating()
        j.begin_post_processing()
        j.begin_encoding()
        asset = VideoAsset(key="k", url="u", duration_sec=4.0)
        j.complete(asset)
        assert j.state == GenerationJobState.COMPLETED
        assert j.output == asset
        assert j.progress == 1.0
        assert j.finished_at is not None

    def test_cannot_complete_without_going_through_encoding(self):
        j = self._make()
        j.enqueue()
        j.begin_processing()
        with pytest.raises(Exception):
            j.complete(VideoAsset(key="k", url="u", duration_sec=1.0))

    def test_fail_requires_code(self):
        j = self._make()
        j.enqueue()
        j.fail("submit_failed", "boom")
        assert j.state == GenerationJobState.FAILED
        assert j.error_code == "submit_failed"

    def test_fail_empty_code_raises(self):
        j = self._make()
        j.enqueue()
        with pytest.raises(ValueError):
            j.fail("")

    def test_timeout_sets_error_code(self):
        j = self._make()
        j.enqueue()
        j.begin_processing()
        j.timeout()
        assert j.state == GenerationJobState.TIMEOUT
        assert j.error_code == "timeout"

    def test_cancel_from_created(self):
        j = self._make()
        j.cancel()
        assert j.state == GenerationJobState.CANCELLED

    def test_progress_only_updates_in_running_states(self):
        j = self._make()
        # CREATED: progress update must be a no-op (state guard)
        j.update_progress(0.5)
        assert j.progress == 0.0
        j.enqueue()
        j.begin_processing()
        j.update_progress(0.25)
        assert j.progress == 0.25
        # monotonic
        j.update_progress(0.10)
        assert j.progress == 0.25

    def test_progress_out_of_range(self):
        j = self._make()
        with pytest.raises(ValueError):
            j.update_progress(-0.1)
        with pytest.raises(ValueError):
            j.update_progress(1.5)

    def test_can_retry_logic(self):
        j = self._make(max_attempts=2)
        assert j.can_retry() is False  # not in FAILED yet
        j.enqueue()
        j.fail("submit_failed", "x")
        assert j.attempts == 0
        assert j.can_retry() is True  # 0 < 2
        j.increment_attempts()  # attempts = 1
        assert j.can_retry() is True  # 1 < 2
        j.increment_attempts()  # attempts = 2
        assert j.can_retry() is False  # 2 == max_attempts

    def test_increment_attempts_overflow(self):
        j = self._make(max_attempts=1)
        j.increment_attempts()
        with pytest.raises(ValueError):
            j.increment_attempts()