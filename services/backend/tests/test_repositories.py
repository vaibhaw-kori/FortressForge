"""Repository tests (round-trip domain <-> ORM)."""

from __future__ import annotations

from aura_backend.db.models import GenerationJobRow, SessionStateDB
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
from aura_backend.repositories import (
    ExperienceRepository,
    GenerationJobRepository,
    ReelItemRepository,
    SessionRepository,
    VideoAssetRepository,
)


def test_session_repository_round_trip(db_session):
    s = Session()
    s.select_language("en")
    s.select_theme("aurora")
    repo = SessionRepository(db_session)
    added = repo.add(s)
    db_session.commit()
    fetched = repo.get(added.id)
    assert fetched is not None
    assert fetched.language == "en"
    assert fetched.theme_id == "aurora"
    assert fetched.state == SessionState.THEME_SELECTED


def test_session_repository_update(db_session):
    s = Session()
    s.select_language("en")
    repo = SessionRepository(db_session)
    added = repo.add(s)
    db_session.commit()
    added.select_theme("aurora")
    repo.update(added)
    db_session.commit()
    fetched = repo.get(added.id)
    assert fetched.theme_id == "aurora"
    assert fetched.state == SessionState.THEME_SELECTED


def test_session_repository_remove(db_session):
    s = Session()
    repo = SessionRepository(db_session)
    added = repo.add(s)
    db_session.commit()
    repo.remove(added.id)
    db_session.commit()
    assert repo.get(added.id) is None


def test_experience_repository_round_trip(db_session):
    repo = ExperienceRepository(db_session)
    exp = Experience(
        id="aurora",
        display_name="Aurora",
        description="d",
        prompt="a portrait",
        theme=ExperienceTheme(palette={"primary": "#fff"}, background_music="x.mp3"),
        metadata={"cat": "abstract"},
    )
    repo.add(exp)
    db_session.commit()
    fetched = repo.get("aurora")
    assert fetched is not None
    assert fetched.display_name == "Aurora"
    assert fetched.theme.palette == {"primary": "#fff"}
    assert fetched.theme.background_music == "x.mp3"
    assert fetched.motion.strength == 0.7
    assert fetched.metadata == {"cat": "abstract"}


def test_experience_repository_list_enabled_filter(db_session):
    repo = ExperienceRepository(db_session)
    repo.add(
        Experience(id="on", display_name="ON", description="d", prompt="p", enabled=True)
    )
    repo.add(
        Experience(id="off", display_name="OFF", description="d", prompt="p", enabled=False)
    )
    db_session.commit()
    enabled = repo.list(enabled_only=True)
    assert {e.id for e in enabled} == {"on"}
    all_items = repo.list(enabled_only=False)
    assert {e.id for e in all_items} == {"on", "off"}


def test_experience_repository_orders_by_display_order(db_session):
    repo = ExperienceRepository(db_session)
    repo.add(
        Experience(
            id="c",
            display_name="C",
            description="d",
            prompt="p",
            display_order=30,
        )
    )
    repo.add(
        Experience(
            id="a",
            display_name="A",
            description="d",
            prompt="p",
            display_order=10,
        )
    )
    repo.add(
        Experience(
            id="b",
            display_name="B",
            description="d",
            prompt="p",
            display_order=20,
        )
    )
    db_session.commit()
    items = repo.list(enabled_only=False)
    assert [e.id for e in items] == ["a", "b", "c"]


def test_experience_repository_upsert_replaces_all_fields(db_session):
    repo = ExperienceRepository(db_session)
    original = Experience(
        id="x",
        display_name="Original",
        description="d",
        prompt="original prompt",
        supported_languages=("en",),
        default_language="en",
    )
    repo.upsert(original)
    db_session.commit()

    updated = Experience(
        id="x",
        display_name="Updated",
        description="d2",
        prompt="new prompt",
        supported_languages=("en", "ar"),
        default_language="en",
        rtl_text=True,
    )
    repo.upsert(updated)
    db_session.commit()

    fetched = repo.get("x")
    assert fetched is not None
    assert fetched.display_name == "Updated"
    assert fetched.prompt == "new prompt"
    assert fetched.rtl_text is True
    assert "ar" in fetched.supported_languages


def test_experience_repository_localization_round_trip(db_session):
    repo = ExperienceRepository(db_session)
    from aura_backend.domain import LocalizedText

    exp = Experience(
        id="aurora",
        display_name="Aurora",
        description="Flowing neon ribbons.",
        prompt="p",
        localized_names=LocalizedText(
            translations={"en": "Aurora", "ar": "الشفق"}, rtl=True
        ),
        localized_descriptions=LocalizedText(
            translations={"en": "Flowing neon ribbons.", "ar": "أشرطة نيون متدفقة."},
            rtl=True,
        ),
    )
    repo.add(exp)
    db_session.commit()
    fetched = repo.get("aurora")
    assert fetched.localized_names.translations["ar"] == "الشفق"
    assert fetched.localized_descriptions.translations["ar"] == "أشرطة نيون متدفقة."
    assert fetched.localized_names.rtl is True


def test_generation_job_repository_round_trip(db_session):
    repo = GenerationJobRepository(db_session)
    job = GenerationJob(session_id="s1", experience_id="aurora", provider_id="fake")
    job.enqueue()
    job.begin_processing()
    repo.add(job)
    db_session.commit()
    fetched = repo.get(job.id)
    assert fetched is not None
    assert fetched.state == GenerationJobState.PROCESSING
    assert fetched.started_at is not None


def test_generation_job_repository_complete_persists_output(db_session):
    repo = GenerationJobRepository(db_session)
    job = GenerationJob(session_id="s1", experience_id="aurora")
    job.enqueue()
    job.begin_processing()
    job.begin_generating()
    job.begin_post_processing()
    job.begin_encoding()
    asset = VideoAsset(key="k", url="u", duration_sec=4.0, codec=VideoCodec.H264)
    job.complete(asset)
    repo.add(job)
    db_session.commit()
    fetched = repo.get(job.id)
    assert fetched.state == GenerationJobState.COMPLETED
    assert fetched.output is not None
    assert fetched.output.key == "k"
    assert fetched.output.codec == VideoCodec.H264


def test_generation_job_repository_list_by_session(db_session):
    repo = GenerationJobRepository(db_session)
    j1 = GenerationJob(session_id="s1", experience_id="aurora")
    j1.enqueue()
    j2 = GenerationJob(session_id="s1", experience_id="mirage")
    j2.enqueue()
    j3 = GenerationJob(session_id="s2", experience_id="aurora")
    j3.enqueue()
    repo.add(j1)
    repo.add(j2)
    repo.add(j3)
    db_session.commit()
    s1_jobs = repo.list_by_session("s1")
    assert {j.id for j in s1_jobs} == {j1.id, j2.id}


def test_reel_item_repository_round_trip(db_session):
    repo = ReelItemRepository(db_session)
    item = ReelItem(src="/x.mp4", kind=ReelItemKind.GENERATED, duration_sec=3.0)
    added = repo.add(item)
    db_session.commit()
    fetched = repo.get(added.id)
    assert fetched is not None
    assert fetched.kind == ReelItemKind.GENERATED
    assert fetched.src == "/x.mp4"
    assert fetched.duration_sec == 3.0


def test_video_asset_repository_round_trip(db_session):
    repo = VideoAssetRepository(db_session)
    asset = VideoAsset(
        key="captures/x.jpg",
        url="https://x/c.jpg",
        duration_sec=4.0,
        codec=VideoCodec.H264,
        size_bytes=1024,
    )
    repo.add(asset)
    db_session.commit()
    fetched = repo.get_by_key("captures/x.jpg")
    assert fetched is not None
    assert fetched.codec == VideoCodec.H264
    assert fetched.size_bytes == 1024