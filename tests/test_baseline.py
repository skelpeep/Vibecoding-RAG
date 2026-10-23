"""Focused safety/transport regressions; these are not model integration tests."""
from pathlib import Path
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from atguigu.config.config import RuntimeConfig, MinIoConfig
from atguigu.tool import task_utils
from atguigu.web.api import import_service, query_service
from atguigu.business.security import legacy_data_closed


@pytest.fixture(autouse=True)
def isolated_legacy_transport():
    # Exercise the old wire behavior in isolation only. Stage 2 tests assert the
    # real routes are closed; this override is never installed in a running app.
    for app in (import_service.app, query_service.app):
        app.dependency_overrides[legacy_data_closed] = lambda: None
    yield
    for app in (import_service.app, query_service.app):
        app.dependency_overrides.pop(legacy_data_closed, None)


@pytest.fixture
def uploads(tmp_path, monkeypatch):
    monkeypatch.setattr(RuntimeConfig, "data_dir", tmp_path)
    monkeypatch.setattr(MinIoConfig, "minio_access_key", "")
    monkeypatch.setattr(MinIoConfig, "minio_secret_key", "")
    return TestClient(import_service.app), tmp_path


@pytest.mark.parametrize("filename", ["../escape.md", "..\\escape.md", "C:escape.md"])
def test_rejects_unsafe_filename(uploads, filename):
    client, root = uploads
    assert client.post("/upload", files={"file": (filename, b"text")}).status_code == 400
    assert not list(root.iterdir())


def test_rejects_unsupported_and_empty_files(uploads):
    client, root = uploads
    assert client.post("/upload", files={"file": ("a.docx", b"text")}).status_code == 415
    assert client.post("/upload", files={"file": ("a.md", b"")}).status_code == 400
    assert not list(root.rglob("*.md"))


def test_size_limit_removes_partial_file(uploads, monkeypatch):
    client, root = uploads
    monkeypatch.setattr(RuntimeConfig, "upload_max_bytes", 3)
    assert client.post("/upload", files={"file": ("a.md", b"1234")}).status_code == 413
    assert not list(root.rglob("*.md"))


def test_same_filename_isolated_and_missing_storage_records_failure(uploads):
    client, root = uploads
    ids = []
    for body in [b"first", b"second"]:
        response = client.post("/upload", files={"file": ("same.md", body)})
        assert response.status_code == 200
        task_id = response.json()["task_id"]
        ids.append(task_id)
        status = client.get("/status/" + task_id).json()
        assert status["status"] == "failed"
        assert status["error"]
    assert ids[0] != ids[1]
    assert sorted(p.read_bytes() for p in root.rglob("same.md")) == [b"first", b"second"]


def test_unknown_tasks_are_404():
    assert TestClient(import_service.app).get("/status/missing").status_code == 404
    assert TestClient(query_service.app).get("/stream/missing").status_code == 404


@pytest.mark.parametrize("terminal", ["done", "error"])
def test_sse_terminates_and_cleans_queue(terminal):
    # Only wire transport is synthesized; no answer/model is claimed here.
    task_id = "transport-" + terminal
    task_utils.create_queue(task_id)
    task_utils.put_data(task_id, "progress", {"status": "processing"})
    task_utils.put_data(task_id, terminal, {"status": terminal})
    response = TestClient(query_service.app).get("/stream/" + task_id)
    assert response.status_code == 200
    assert f"event: {terminal}\n" in response.text
    assert task_id not in task_utils.queue_dict
    task_utils.put_data(task_id, "delta", {})  # Must return without hanging after disconnect.


def test_existing_vector_document_is_never_deleted():
    from atguigu.import_process.nodes.node_import_milvus import NodeImportMilvus
    client = Mock()
    client.query.return_value = [{"id": 7}]
    with pytest.raises(ValueError, match="同名"):
        NodeImportMilvus().insert_data([], "test", "existing", client)
    client.delete.assert_not_called()
    client.insert.assert_not_called()


def test_graphs_compile_without_models():
    from atguigu.import_process.main_graph import MainGraphRunner as ImportGraph
    from atguigu.query_process.main_graph import MainGraphRunner as QueryGraph
    assert ImportGraph().builder.compile()
    assert QueryGraph().builder.compile()
