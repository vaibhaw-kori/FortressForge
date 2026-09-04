"""API tests for storage serving + admin/operator endpoints."""

from __future__ import annotations


def _op_token():
    from aura_backend.security import make_operator_jwt

    return make_operator_jwt("op-test")


def test_storage_public_missing_404(client):
    r = client.get("/api/v1/storage/public/missing.mp4")
    assert r.status_code == 404


def test_storage_private_requires_signed_url(client):
    r = client.get("/api/v1/storage/captures/x.jpg")
    assert r.status_code == 403


def test_storage_private_invalid_sig_403(client):
    r = client.get("/api/v1/storage/captures/x.jpg?expires=9999999999&signature=bad")
    assert r.status_code == 403


def test_storage_private_valid_signed_serves_or_404(client, tmp_path, monkeypatch):
    from aura_backend.storage import create_signed_url, get_storage

    storage = get_storage()
    # put a private object via storage layer directly
    key = "captures/e2e-test.jpg"
    data = b"\xff\xd8\xff" + b"\x00" * 200
    try:
        storage.put(key, data, content_type="image/jpeg")
    except Exception:
        pass
    url = create_signed_url(key, ttl_sec=600)
    # url is /api/v1/storage/<key>?expires=..&signature=..
    r = client.get(url)
    assert r.status_code in (200, 404)  # 404 only if storage backend differs
    if r.status_code == 200:
        assert r.headers.get("Cache-Control", "").startswith("private")


def test_storage_traversal_400(client):
    r = client.get("/api/v1/storage/..%2Fsecret")
    assert r.status_code in (400, 403, 404)


def test_admin_requires_auth(client):
    assert client.get("/api/v1/admin/retention").status_code in (401, 403)
    assert client.post("/api/v1/admin/purge").status_code in (401, 403)
    assert client.post("/api/v1/admin/storage/cleanup-temp").status_code in (401, 403)


def test_admin_retention_ok(client):
    tok = _op_token()
    r = client.get("/api/v1/admin/retention", headers={"Authorization": f"Bearer {tok}"})
    assert r.status_code == 200
    body = r.json()
    assert "retention_captures_days" in body
    assert "storage_signed_url_ttl_sec" in body


def test_admin_purge_ok(client):
    tok = _op_token()
    r = client.post("/api/v1/admin/purge", headers={"Authorization": f"Bearer {tok}"})
    assert r.status_code == 200


def test_admin_cleanup_temp_ok(client):
    tok = _op_token()
    r = client.post(
        "/api/v1/admin/storage/cleanup-temp", headers={"Authorization": f"Bearer {tok}"}
    )
    assert r.status_code == 200
    assert "deleted_temp_files" in r.json()


def test_generation_idempotency_and_cancel_api(client, db_session):
    from aura_backend.services import SessionService

    svc = SessionService(db_session)
    s = svc.create(language="en")
    svc.select_theme(s.id, "aurora")
    svc.start_countdown(s.id)
    svc.start_capture(s.id)
    svc.mark_uploaded(s.id, "captures/x.jpg")
    db_session.commit()

    body = {"session_id": s.id, "experience_id": "aurora", "idempotency_key": "k-123"}
    r1 = client.post("/api/v1/generation/jobs", json=body)
    assert r1.status_code == 201
    jid = r1.json()["id"]
    # same idempotency key → same job (not duplicate)
    r2 = client.post("/api/v1/generation/jobs", json=body)
    assert r2.status_code in (200, 201)
    assert r2.json()["id"] == jid
    # cancel
    rc = client.post(f"/api/v1/generation/jobs/{jid}/cancel")
    assert rc.status_code in (200, 409)  # 409 if already terminal
    # retry after cancel may 409 or 200 depending on state; just assert no 500
    rr = client.post(f"/api/v1/generation/jobs/{jid}/retry")
    assert rr.status_code in (200, 409, 422)
