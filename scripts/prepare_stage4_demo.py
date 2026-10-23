"""Prepare a labelled image draft and an isolated transient-failure UI fixture."""
import base64
import io
import json
import sys
from pathlib import Path
from uuid import uuid4

import httpx
from PIL import Image, ImageDraw
from sqlalchemy import event
from sqlalchemy.orm import Session, with_loader_criteria

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from atguigu.business import import_worker as worker
from atguigu.business.import_errors import ImportFailure
from atguigu.business.models import ImportTask
from atguigu.config.config import ImportConfig


def main():
    credentials = json.loads((ROOT / "var/setup/stage2-accounts.json").read_text(encoding="utf-8"))
    with httpx.Client(base_url="http://127.0.0.1:8103", timeout=60, trust_env=False) as client:
        token = client.post("/api/auth/login", json={"username": "kb_admin", "password": credentials["kb_admin"]}).json()["access_token"]
        client.headers["Authorization"] = "Bearer " + token
        diagram = Image.new("RGB", (700, 170), "white"); draw = ImageDraw.Draw(diagram)
        for x, label in ((20, "Draft"), (255, "Ready"), (490, "Published")):
            draw.rounded_rectangle((x, 35, x + 190, 125), radius=6, outline="#1b6c80", width=3)
            draw.text((x + 60, 75), label, fill="#111111")
        for x in (210, 445):
            draw.line((x + 2, 80, x + 37, 80), fill="#111111", width=2)
            draw.polygon(((x + 42, 80), (x + 33, 75), (x + 33, 85)), fill="#111111")
        buffer = io.BytesIO(); diagram.save(buffer, format="PNG")
        content = "# 知识发布流程（阶段四示例）\n\n此文档用于演示，非正式制度。\n\n1. 保存草稿并等待构建完成。\n2. 配置访问范围并激活版本。\n3. 发布后，读者按授权访问。\n\n![发布流程](data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode() + ")"
        response = client.post("/api/knowledge/import", data={"idempotency_key": "stage4-demo-" + uuid4().hex,
                               "category": "阶段四示例"}, files={"files": ("知识发布流程（示例）.md", content.encode(), "text/markdown")})
        response.raise_for_status(); image_task = response.json()["tasks"][0]
        response = client.post("/api/knowledge/units", json={"title": "重试流程（阶段四验收）", "content": "这是故障恢复验收草稿。一次临时依赖故障后，可对同一任务重试。", "category": "阶段四验收"})
        response.raise_for_status(); retry_unit = response.json()
    # Queue filtering is local to this validation process, never a product bypass.
    target_id = image_task["id"]
    @event.listens_for(Session, "do_orm_execute")
    def isolate(execution):
        if execution.is_select:
            execution.statement = execution.statement.options(with_loader_criteria(ImportTask, ImportTask.id == target_id))
    claimed = worker.claim_next()
    assert claimed and claimed[0] == target_id
    assert worker.process_task(*claimed)
    target_id = retry_unit["task_id"]
    claimed = worker.claim_next()
    assert claimed and claimed[0] == target_id
    # Persist the real failure transition, with a deliberately injected timeout.
    original = ImportConfig.retry_base_seconds
    ImportConfig.retry_base_seconds = 300
    worker.finish_failure(*claimed, ImportFailure("QA_TRANSIENT_TIMEOUT", "验收注入的临时超时，可重试同一任务", True), "embedding")
    ImportConfig.retry_base_seconds = original
    report = {"image_unit_id": image_task["unit_id"], "image_task_id": image_task["id"],
              "retry_unit_id": retry_unit["id"], "retry_task_id": retry_unit["task_id"],
              "retry_batch_id": retry_unit["batch_id"],
              "transient_failure": "Injected timeout via real worker failure transition; queued retry, no fake successful vectors"}
    (ROOT / "docs/evidence/stage4/demo.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
