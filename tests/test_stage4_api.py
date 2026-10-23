"""Real HTTP authorization/transaction tests; object storage and indexing are fakes here.

The separate stage-four integration suite exercises real MinIO/Milvus. These tests
intentionally cover denied paths before any storage call, immutable reader views,
and atomic transitions rather than mirroring implementation helpers.
"""
from hashlib import sha256
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from atguigu.business import knowledge_api as api, models as m
from test_stage2 import ctx, engine  # Shared isolated SQLite/MySQL transactional fixture.


class MemoryStorage:
    bucket = "stage4-test"

    def __init__(self):
        self.objects = {}
        self.reads = 0

    def put_bytes(self, key, data, content_type="application/octet-stream", bucket=None):
        self.objects[key] = data

    def get_bytes(self, key, bucket=None):
        self.reads += 1
        return self.objects[key]


@pytest.fixture
def store(monkeypatch):
    storage = MemoryStorage()
    monkeypatch.setattr(api, "storage", lambda: storage)

    def fake_enqueue(db, principal, unit, version):
        source = m.StoredFile(owner_id=principal.user.id, unit_id=unit.id, version_id=version.id,
                              file_name=unit.title + ".md", object_key=uuid4().hex, bucket=storage.bucket)
        batch = m.ImportBatch(owner_id=principal.user.id, idempotency_key=uuid4().hex, file_count=1)
        db.add_all([source, batch]); db.flush()
        task = m.ImportTask(owner_id=principal.user.id, batch_id=batch.id, file_id=source.id,
                            unit_id=unit.id, version_id=version.id, idempotency_key=uuid4().hex)
        db.add(task); db.flush()
        storage.put_bytes(source.object_key, version.content.encode())
        return task

    monkeypatch.setattr(api, "enqueue", fake_enqueue)
    return storage


def create(ctx, **values):
    body = {"title": "工程知识", "content": "版本一正文", "category": "工程", "tags": ["运维", "运维"], **values}
    response = ctx.call("POST", "/api/knowledge/units", "kb", json=body)
    assert response.status_code == 201, response.text
    return response.json()


def make_ready(ctx, version_id):
    version = ctx.db.get(m.KnowledgeVersion, version_id)
    version.status = "ready"
    ctx.db.commit()


def activate_publish(ctx, record):
    uid, vid = record["id"], record["latest_version"]["id"]
    make_ready(ctx, vid)
    assert ctx.call("POST", f"/api/knowledge/units/{uid}/versions/{vid}/activate", "kb").status_code == 200
    assert ctx.call("POST", f"/api/knowledge/units/{uid}/status", "kb", json={"status": "published"}).status_code == 200


def test_draft_creator_maintenance_does_not_open_reader_or_admin_access(ctx, store):
    record = create(ctx)
    uid, vid = record["id"], record["latest_version"]["id"]
    assert record["status"] == "draft" and record["tags"] == ["运维"]
    assert record["can_edit"] is True and record["content"] == "版本一正文"
    assert record["task_id"] and record["batch_id"]
    for actor in ("alice", "admin"):
        assert ctx.call("GET", f"/api/knowledge/units/{uid}", actor).status_code == 404
        listing = ctx.call("GET", "/api/knowledge/units?search=工程知识", actor).json()
        assert listing["total"] == 0 and listing["items"] == []
        assert "工程" not in str(ctx.call("GET", "/api/knowledge/categories", actor).json())
    assert ctx.call("GET", f"/api/knowledge/units/{uid}", "kb").status_code == 200
    assert ctx.call("POST", "/api/knowledge/check-permissions", "kb", json={"unit_ids": [uid]}).json()["authorized_unit_ids"] == []
    assert ctx.call("POST", f"/api/knowledge/units/{uid}/versions/{vid}/activate", "kb").status_code == 409
    assert ctx.call("POST", f"/api/knowledge/units/{uid}/status", "kb", json={"status": "published"}).status_code == 409


def test_edit_metadata_and_body_remain_private_until_ready_activation(ctx, store):
    record = create(ctx, grants=[{"target_type": "global", "target_id": "*"}])
    activate_publish(ctx, record)
    uid, old_id = record["id"], record["latest_version"]["id"]
    updated = ctx.call("PUT", f"/api/knowledge/units/{uid}", "kb", json={
        "title": "未发布机密标题", "content": "未发布机密正文", "summary": "机密摘要", "category": "机密分类", "tags": ["机密标签"]})
    assert updated.status_code == 200, updated.text
    draft = updated.json()
    assert draft["title"] == "未发布机密标题" and draft["latest_version"]["status"] == "pending"
    public = ctx.call("GET", f"/api/knowledge/units/{uid}").json()
    assert public["title"] == "工程知识" and public["content"] == "版本一正文"
    assert public["latest_version"]["id"] == old_id and "机密" not in str(public)
    assert ctx.call("GET", "/api/knowledge/units?search=机密").json()["total"] == 0
    assert ctx.call("GET", "/api/knowledge/categories").json()["items"] == ["工程"]
    new_id = draft["latest_version"]["id"]
    failed = ctx.db.get(m.KnowledgeVersion, new_id); failed.status = "failed"; ctx.db.commit()
    assert ctx.call("POST", f"/api/knowledge/units/{uid}/versions/{new_id}/activate", "kb").status_code == 409
    assert ctx.call("GET", f"/api/knowledge/units/{uid}").json()["active_version_id"] == old_id
    make_ready(ctx, new_id)
    assert ctx.call("POST", f"/api/knowledge/units/{uid}/versions/{new_id}/activate", "kb").status_code == 200
    public = ctx.call("GET", f"/api/knowledge/units/{uid}").json()
    assert public["title"] == "未发布机密标题" and public["content"] == "未发布机密正文"
    assert public["active_version_id"] == new_id
    # The author can roll back to a still-ready old version; its metadata follows it.
    assert ctx.call("POST", f"/api/knowledge/units/{uid}/versions/{old_id}/activate", "kb").status_code == 200
    assert ctx.call("GET", f"/api/knowledge/units/{uid}").json()["title"] == "工程知识"


def test_versions_traceability_rebuild_and_cross_unit_denial(ctx, store):
    record = create(ctx, grants=[{"target_type": "global", "target_id": "*"}])
    activate_publish(ctx, record)
    uid, vid = record["id"], record["latest_version"]["id"]
    ctx.db.add(m.KnowledgeChunk(unit_id=uid, version_id=vid, chunk_index=0,
                                content="切片正文", position_json={"page": 2, "start": 10, "end": 20}))
    ctx.db.commit()
    detail = ctx.call("GET", f"/api/knowledge/units/{uid}/versions/{vid}", "kb").json()
    assert detail["chunks"][0]["unit_id"] == uid and detail["chunks"][0]["version_id"] == vid
    assert detail["chunks"][0]["position"]["page"] == 2
    for actor in ("alice", "admin"):
        assert ctx.call("GET", f"/api/knowledge/units/{uid}/versions", actor).status_code == 404
        assert ctx.call("GET", f"/api/knowledge/units/{uid}/versions/{vid}", actor).status_code == 404
    rebuilt = ctx.call("POST", f"/api/knowledge/units/{uid}/versions/{vid}/rebuild", "kb")
    assert rebuilt.status_code == 202, rebuilt.text
    assert rebuilt.json()["latest_version"]["id"] != vid
    assert rebuilt.json()["latest_version"]["version_number"] == 2
    assert ctx.call("GET", f"/api/knowledge/units/{uid}").json()["active_version_id"] == vid
    other = create(ctx)
    assert ctx.call("POST", f"/api/knowledge/units/{uid}/versions/{other['latest_version']['id']}/activate", "kb").status_code == 404


@pytest.mark.parametrize("transition", ["revoke", "draft", "disabled", "deleted"])
def test_download_image_and_titles_revoke_immediately_before_storage(ctx, store, transition):
    record = create(ctx, grants=[{"target_type": "global", "target_id": "*"}])
    uid = record["id"]
    image = b"\x89PNG\r\n\x1a\n" + b"image-test-payload"
    upload = ctx.call("POST", f"/api/knowledge/units/{uid}/attachments", "kb",
                      files={"file": ("../private.png", image, "image/png")})
    assert upload.status_code == 201, upload.text
    fid = upload.json()["id"]
    assert upload.json()["file_name"] == "private.png"
    activate_publish(ctx, record)
    for suffix in ("", "/download", "/image"):
        response = ctx.call("GET", f"/api/knowledge/files/{fid}{suffix}")
        assert response.status_code == 200, response.text
        if suffix:
            assert response.content == image and "no-store" in response.headers["cache-control"]
    if transition == "revoke":
        assert ctx.call("POST", f"/api/knowledge/units/{uid}/permissions", "kb", json={"grants": []}).status_code == 200
    elif transition == "deleted":
        assert ctx.call("DELETE", "/api/knowledge/units", "kb", json={"unit_ids": [uid]}).status_code == 200
    else:
        assert ctx.call("POST", f"/api/knowledge/units/{uid}/status", "kb", json={"status": transition}).status_code == 200
    old_reads = store.reads
    for actor in ("alice", "admin"):
        for suffix in ("", "/download", "/image"):
            assert ctx.call("GET", f"/api/knowledge/files/{fid}{suffix}", actor).status_code == 404
        assert ctx.call("GET", f"/api/knowledge/units/{uid}", actor).status_code == 404
        assert ctx.call("GET", "/api/knowledge/units", actor).json()["total"] == 0
    assert store.reads == old_reads
    assert ctx.call("POST", "/api/knowledge/check-permissions", json={"unit_ids": [uid]}).json()["authorized_unit_ids"] == []


def test_old_version_files_and_active_html_cannot_be_served_inline(ctx, store):
    record = create(ctx, grants=[{"target_type": "global", "target_id": "*"}])
    uid = record["id"]
    attachment = ctx.call("POST", f"/api/knowledge/units/{uid}/attachments", "kb",
                          files={"file": ("fake.png", b"<script>alert(1)</script>", "image/png")}).json()
    activate_publish(ctx, record)
    fid = attachment["id"]
    assert ctx.call("GET", f"/api/knowledge/files/{fid}/image").status_code == 415
    download = ctx.call("GET", f"/api/knowledge/files/{fid}/download")
    assert download.status_code == 200 and download.headers["content-type"] == "application/octet-stream"
    assert download.headers["content-disposition"].startswith("attachment")
    updated = ctx.call("PUT", f"/api/knowledge/units/{uid}", "kb", json={"title": "new", "content": "next"}).json()
    inherited = [f for f in updated["attachments"] if f["purpose"] == "attachment"]
    assert len(inherited) == 1 and inherited[0]["id"] != fid
    assert inherited[0]["version_id"] == updated["latest_version"]["id"]
    make_ready(ctx, updated["latest_version"]["id"])
    ctx.call("POST", f"/api/knowledge/units/{uid}/versions/{updated['latest_version']['id']}/activate", "kb")
    assert ctx.call("GET", f"/api/knowledge/files/{fid}/download").status_code == 404
    assert ctx.call("GET", f"/api/knowledge/files/{inherited[0]['id']}/download").status_code == 200
    assert ctx.call("GET", f"/api/knowledge/files/{fid}/download", "kb").status_code == 200
    assert ctx.call("DELETE", f"/api/knowledge/units/{uid}/attachments/{fid}", "kb").status_code == 200
    assert ctx.call("GET", f"/api/knowledge/files/{fid}/download", "kb").status_code == 404


def test_batch_delete_is_atomic_and_operation_permission_never_grants_others_body(ctx, store):
    own = create(ctx)
    other = ctx.unit()
    other.creator_id = ctx.users["bob"].id; ctx.db.commit()
    response = ctx.call("DELETE", "/api/knowledge/units", "kb", json={"unit_ids": [own["id"], other.id]})
    assert response.status_code == 404
    assert ctx.call("GET", f"/api/knowledge/units/{own['id']}", "kb").status_code == 200
    assert ctx.call("GET", f"/api/knowledge/units/{other.id}", "kb").status_code == 404
    assert ctx.call("PUT", f"/api/knowledge/units/{other.id}", "kb", json={"title": "x", "content": "x"}).status_code == 404
    assert ctx.call("POST", "/api/knowledge/units", json={"title": "x", "content": "x"}).status_code == 403
    assert ctx.call("POST", "/api/knowledge/units", "kb", json={"title": "x", "content": "x", "creator_id": ctx.users["bob"].id}).status_code == 422


def test_options_preview_and_outbox_state_changes(ctx, store):
    record = create(ctx, grants=[{"target_type": "user", "target_id": ctx.users["alice"].id}])
    uid = record["id"]
    assert ctx.call("GET", "/api/knowledge/permission-options").status_code == 403
    options = ctx.call("GET", "/api/knowledge/permission-options", "kb").json()
    assert any(u["id"] == ctx.users["alice"].id for u in options["users"])
    assert "password" not in str(options)
    body = {"user_id": ctx.users["alice"].id, "unit_ids": [uid]}
    assert ctx.call("POST", "/api/knowledge/preview-permissions", "kb", json=body).json()["authorized_unit_ids"] == []
    activate_publish(ctx, record)
    assert ctx.call("POST", "/api/knowledge/preview-permissions", "kb", json=body).json()["authorized_unit_ids"] == [uid]
    assert ctx.call("DELETE", "/api/knowledge/units", "kb", json={"unit_ids": [uid]}).status_code == 200
    event_types = set(ctx.db.scalars(select(m.OutboxEvent.event_type).where(m.OutboxEvent.aggregate_id == uid)))
    assert {"unit.created", "unit.permissions.changed", "unit.version.activated", "unit.status.changed", "unit.deleted"} <= event_types


def test_paginated_mixed_grants_filter_before_count_and_search(ctx, store):
    grants = [{"target_type": "department", "target_id": ctx.departments["sales"].id},
              {"target_type": "role", "target_id": ctx.roles["engineer"].id}]
    records = [create(ctx, title=f"可见知识{i}", category="可见类别", grants=grants) for i in range(3)]
    for record in records:
        activate_publish(ctx, record)
    private = create(ctx, title="隐私唯一标题", category="隐私类别")
    activate_publish(ctx, private)
    for actor in ("alice", "bob"):
        first = ctx.call("GET", "/api/knowledge/units?page_size=2&category=可见类别&status=published", actor).json()
        second = ctx.call("GET", "/api/knowledge/units?page_size=2&page=2&category=可见类别", actor).json()
        assert first["total"] == second["total"] == 3
        assert len(first["items"]) == 2 and len(second["items"]) == 1
        assert len({u["id"] for u in first["items"] + second["items"]}) == 3
        assert ctx.call("GET", "/api/knowledge/units?search=隐私", actor).json()["total"] == 0
    assert ctx.call("GET", "/api/knowledge/units", "carol").json()["total"] == 0
    assert ctx.call("GET", "/api/knowledge/units", "admin").json()["total"] == 0


def test_author_maintenance_is_lost_when_operations_are_revoked(ctx, store):
    record = create(ctx)
    uid = record["id"]
    attachment = ctx.call("POST", f"/api/knowledge/units/{uid}/attachments", "kb",
                          files={"file": ("private.txt", b"private-content", "text/plain")}).json()
    role = ctx.roles["kb"]
    remaining = ["knowledge:read", "knowledge:file:read", "knowledge:check", "knowledge:permissions"]
    response = ctx.call("POST", f"/api/org/roles/{role.id}/permissions", "admin", json={"permission_codes": remaining})
    assert response.status_code == 200
    assert ctx.call("GET", f"/api/knowledge/units/{uid}", "kb").status_code == 404
    assert ctx.call("GET", f"/api/knowledge/files/{attachment['id']}/download", "kb").status_code == 404
    assert ctx.call("GET", "/api/knowledge/units", "kb").json()["total"] == 0
    # Explicit grants metadata administration remains separate from body access.
    assert ctx.call("GET", f"/api/knowledge/units/{uid}/permissions", "kb").status_code == 200


def test_storage_failures_are_sanitized_and_database_creation_rolls_back(ctx, store, monkeypatch):
    def unavailable():
        raise RuntimeError("secret-endpoint-and-credentials")

    record = create(ctx)
    monkeypatch.setattr(api, "storage", unavailable)
    response = ctx.call("POST", f"/api/knowledge/units/{record['id']}/attachments", "kb",
                        files={"file": ("private.txt", b"private", "text/plain")})
    assert response.status_code == 503
    assert "secret" not in response.text
    assert ctx.db.scalar(select(func.count()).select_from(m.StoredFile).where(
        m.StoredFile.purpose == "attachment", m.StoredFile.unit_id == record["id"])) == 0


def test_linked_file_without_a_version_is_not_a_reader_backdoor(ctx, store):
    record = create(ctx, grants=[{"target_type": "global", "target_id": "*"}])
    activate_publish(ctx, record)
    file = m.StoredFile(owner_id=ctx.users["alice"].id, unit_id=record["id"], version_id=None,
                         file_name="unversioned-secret.txt", object_key=uuid4().hex, bucket=store.bucket)
    ctx.db.add(file); ctx.db.commit()
    assert ctx.call("GET", f"/api/knowledge/files/{file.id}").status_code == 404
    assert ctx.call("GET", f"/api/knowledge/files/{file.id}/download").status_code == 404
