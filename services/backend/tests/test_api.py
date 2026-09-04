"""API v1 endpoint validation tests."""

from __future__ import annotations


# ---- health ----


def test_health_endpoint(client):
    r = client.get("/api/v1/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["service"] == "aura-backend"


def test_ready_endpoint(client):
    r = client.get("/api/v1/ready")
    assert r.status_code == 200
    body = r.json()
    assert body["db"]["ok"] is True


# ---- experiences ----


def test_list_experiences_enabled_only(client):
    r = client.get("/api/v1/experiences")
    assert r.status_code == 200
    body = r.json()
    ids = {e["id"] for e in body["items"]}
    assert {"aurora", "mirage", "pulse"}.issubset(ids)
    assert "driftwood" not in ids


def test_list_experiences_include_disabled(client):
    r = client.get("/api/v1/experiences?enabled_only=false")
    assert r.status_code == 200
    ids = {e["id"] for e in r.json()["items"]}
    assert "driftwood" in ids


def test_get_experience_known(client):
    r = client.get("/api/v1/experiences/aurora")
    assert r.status_code == 200
    body = r.json()
    assert body["id"] == "aurora"
    assert body["display_name"] == "Aurora"
    assert body["duration_sec"] == 4.0
    assert body["fps"] == 12
    assert body["aspect_ratio"] == "9:16"
    assert body["display_order"] >= 0
    assert "theme" in body
    assert body["theme"]["palette"]["primary"]
    # Trusted AI config exposed for provider layer:
    assert body["prompt"]
    assert body["model_params"]["num_inference_steps"] >= 1
    assert body["visual_style"]["aesthetic"]
    assert body["motion"]["strength"] >= 0


def test_get_experience_404(client):
    r = client.get("/api/v1/experiences/missing")
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "not_found"


def test_get_experience_localized_arabic(client):
    r = client.get("/api/v1/experiences/aurora?language=ar")
    assert r.status_code == 200
    body = r.json()
    assert body["display_name"] == "الشفق القطبي"
    assert "أشرطة" in body["description"] or "نيون" in body["description"]
    assert body["rtl_text"] is True
    assert body["localized_names"] is not None
    assert body["localized_names"]["value"] == "الشفق القطبي"
    assert body["localized_names"]["language"] == "ar"
    assert body["localized_names"]["rtl"] is True


def test_get_experience_falls_back_to_default_language(client):
    # French is not supported, so we fall back to default (English).
    r = client.get("/api/v1/experiences/aurora?language=fr")
    assert r.status_code == 200
    body = r.json()
    assert body["display_name"] == "Aurora"


def test_list_experiences_default_orders_by_display_order(client):
    r = client.get("/api/v1/experiences")
    body = r.json()
    orders = [item["display_order"] for item in body["items"]]
    assert orders == sorted(orders)


def test_list_experiences_exposes_prompt_and_model_params(client):
    r = client.get("/api/v1/experiences")
    body = r.json()
    aurora = next(e for e in body["items"] if e["id"] == "aurora")
    assert aurora["prompt"]
    assert aurora["model_params"]["num_inference_steps"] >= 1
    assert aurora["supported_languages"] == ["en", "ar"]


# ---- sessions ----


def test_create_session(client):
    r = client.post("/api/v1/sessions", json={})
    assert r.status_code == 201
    body = r.json()
    assert body["state"] == "IDLE"
    assert body["language"] is None


def test_create_session_with_language(client):
    r = client.post("/api/v1/sessions", json={"language": "ar"})
    assert r.status_code == 201
    assert r.json()["language"] == "ar"
    assert r.json()["state"] == "LANGUAGE_SELECTED"


def test_create_session_language_too_long(client):
    r = client.post("/api/v1/sessions", json={"language": "abcdefghi"})
    assert r.status_code == 422


def test_get_session(client):
    sid = client.post("/api/v1/sessions", json={"language": "en"}).json()["id"]
    r = client.get(f"/api/v1/sessions/{sid}")
    assert r.status_code == 200
    assert r.json()["id"] == sid


def test_get_session_404(client):
    r = client.get("/api/v1/sessions/missing")
    assert r.status_code == 404


def test_session_transition_happy_path(client):
    sid = client.post("/api/v1/sessions", json={}).json()["id"]
    r = client.post(
        f"/api/v1/sessions/{sid}/transition",
        json={"to": "LANGUAGE_SELECTED", "language": "en"},
    )
    assert r.status_code == 200 and r.json()["state"] == "LANGUAGE_SELECTED"
    r = client.post(
        f"/api/v1/sessions/{sid}/transition",
        json={"to": "THEME_SELECTED", "theme_id": "aurora"},
    )
    assert r.status_code == 200 and r.json()["state"] == "THEME_SELECTED"
    r = client.post(f"/api/v1/sessions/{sid}/transition", json={"to": "COUNTDOWN"})
    assert r.status_code == 200 and r.json()["state"] == "COUNTDOWN"
    r = client.post(f"/api/v1/sessions/{sid}/transition", json={"to": "CAPTURING"})
    assert r.status_code == 200 and r.json()["state"] == "CAPTURING"


def test_session_illegal_transition_returns_409(client):
    sid = client.post("/api/v1/sessions", json={}).json()["id"]
    r = client.post(
        f"/api/v1/sessions/{sid}/transition", json={"to": "GENERATING"}
    )
    assert r.status_code == 409
    body = r.json()
    assert body["error"]["code"] == "illegal_transition"
    assert body["error"]["details"]["scope"] == "session"


def test_session_transition_requires_language_for_language_selected(client):
    sid = client.post("/api/v1/sessions", json={}).json()["id"]
    r = client.post(
        f"/api/v1/sessions/{sid}/transition", json={"to": "LANGUAGE_SELECTED"}
    )
    assert r.status_code == 422


def test_session_transition_requires_theme_id_for_theme_selected(client):
    sid = client.post("/api/v1/sessions", json={}).json()["id"]
    client.post(
        f"/api/v1/sessions/{sid}/transition",
        json={"to": "LANGUAGE_SELECTED", "language": "en"},
    )
    r = client.post(
        f"/api/v1/sessions/{sid}/transition", json={"to": "THEME_SELECTED"}
    )
    assert r.status_code == 422


def test_session_transition_404(client):
    r = client.post(
        "/api/v1/sessions/missing/transition",
        json={"to": "LANGUAGE_SELECTED", "language": "en"},
    )
    assert r.status_code == 404


# ---- generation jobs ----


def test_create_generation_job_requires_capture(client, db_session):
    from aura_backend.services import SessionService

    svc = SessionService(db_session)
    s = svc.create(language="en")
    svc.select_theme(s.id, "aurora")
    db_session.commit()

    r = client.post(
        "/api/v1/generation/jobs",
        json={"session_id": s.id, "experience_id": "aurora"},
    )
    # Session not yet captured -> 422 validation_failed
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "validation_failed"


def test_create_generation_job_success(client, db_session):
    from aura_backend.services import SessionService

    svc = SessionService(db_session)
    s = svc.create(language="en")
    svc.select_theme(s.id, "aurora")
    svc.start_countdown(s.id)
    svc.start_capture(s.id)
    svc.mark_uploaded(s.id, "captures/x.jpg")
    db_session.commit()

    r = client.post(
        "/api/v1/generation/jobs",
        json={"session_id": s.id, "experience_id": "aurora"},
    )
    assert r.status_code == 201
    body = r.json()
    assert body["state"] == "QUEUED"
    assert body["session_id"] == s.id
    assert body["experience_id"] == "aurora"


def test_create_generation_job_unknown_session(client):
    r = client.post(
        "/api/v1/generation/jobs",
        json={"session_id": "missing", "experience_id": "aurora"},
    )
    assert r.status_code == 404


def test_create_generation_job_validation_missing_fields(client):
    r = client.post(
        "/api/v1/generation/jobs", json={"session_id": "x", "experience_id": ""}
    )
    assert r.status_code == 422


def test_get_generation_job(client, db_session):
    from aura_backend.services import SessionService

    svc = SessionService(db_session)
    s = svc.create(language="en")
    svc.select_theme(s.id, "aurora")
    svc.start_countdown(s.id)
    svc.start_capture(s.id)
    svc.mark_uploaded(s.id, "captures/x.jpg")
    db_session.commit()

    created = client.post(
        "/api/v1/generation/jobs",
        json={"session_id": s.id, "experience_id": "aurora"},
    ).json()

    r = client.get(f"/api/v1/generation/jobs/{created['id']}")
    assert r.status_code == 200
    assert r.json()["id"] == created["id"]


def test_get_generation_job_404(client):
    r = client.get("/api/v1/generation/jobs/missing")
    assert r.status_code == 404


def test_list_generation_jobs_empty(client):
    r = client.get("/api/v1/generation/jobs")
    assert r.status_code == 200
    assert r.json() == []


def test_list_generation_jobs_filter_by_session(client, db_session):
    from aura_backend.services import SessionService

    svc = SessionService(db_session)
    s = svc.create(language="en")
    svc.select_theme(s.id, "aurora")
    svc.start_countdown(s.id)
    svc.start_capture(s.id)
    svc.mark_uploaded(s.id, "captures/x.jpg")
    db_session.commit()

    client.post(
        "/api/v1/generation/jobs",
        json={"session_id": s.id, "experience_id": "aurora"},
    )

    r = client.get(f"/api/v1/generation/jobs?session_id={s.id}")
    assert r.status_code == 200
    body = r.json()
    assert len(body) == 1
    assert body[0]["session_id"] == s.id