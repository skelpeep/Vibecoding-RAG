"""Real image import / private storage / version inheritance / revocation check."""
import base64
import io
import json
import os
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

import httpx
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
OUT = ROOT / "docs/evidence/stage4"


def main():
    credentials = json.loads((ROOT / "var/setup/stage2-accounts.json").read_text(encoding="utf-8"))
    report = {"checks": [], "passed": False, "cleanup": False}
    uid = None
    with httpx.Client(base_url=os.getenv("STAGE4_API_BASE", "http://127.0.0.1:8103"), timeout=60, trust_env=False) as client:
        def login(name):
            r = client.post("/api/auth/login", json={"username": name, "password": credentials[name]})
            r.raise_for_status()
            return {"Authorization": "Bearer " + r.json()["access_token"]}
        owner, reader = login("kb_admin"), login("alice")
        def req(method, path, headers=owner, status=200, **kwargs):
            r = client.request(method, "/api/knowledge" + path, headers=headers, **kwargs)
            assert r.status_code == status, (path, r.status_code, r.text[:100])
            return r
        def worker():
            with (OUT / "image-worker.log").open("a", encoding="utf-8") as log:
                r = subprocess.run([sys.executable, "-m", "atguigu.cli", "worker", "--once"], cwd=ROOT,
                                   stdout=log, stderr=log, timeout=180)
            assert r.returncode == 0
        def check(name):
            report["checks"].append(name); print("PASS " + name, flush=True)
        try:
            diagram = Image.new("RGB", (600, 140), "white")
            drawing = ImageDraw.Draw(diagram)
            for x, label in ((15, "Draft"), (215, "Ready"), (415, "Published")):
                drawing.rectangle((x, 30, x + 170, 100), outline="#1b6c80", width=3)
                drawing.text((x + 45, 58), label, fill="#111111")
            drawing.line((186, 65, 211, 65), fill="#111111", width=2)
            drawing.line((386, 65, 411, 65), fill="#111111", width=2)
            buffer = io.BytesIO(); diagram.save(buffer, format="PNG"); blob = buffer.getvalue()
            content = "# 图片导入（示例）\n草稿构建成功后激活，再发布。\n![发布流程](data:image/png;base64," + base64.b64encode(blob).decode() + ")"
            result = req("POST", "/import", status=202, files={"files": ("发布流程含图.md", content.encode(), "text/markdown")},
                         data={"idempotency_key": "stage4-image-" + uuid4().hex}).json()
            task = result["tasks"][0]; uid, vid = task["unit_id"], task["version_id"]
            report["unit_id"] = uid
            worker()
            state = req("GET", "/tasks/" + task["id"]).json()
            assert state["status"] == "completed", state
            detail = req("GET", "/units/" + uid).json()
            image = next(a for a in detail["attachments"] if a["purpose"] == "image")
            assert "data:image" not in detail["content"] and image["id"] in detail["content"]
            assert req("GET", "/files/" + image["id"] + "/image").content == blob
            check("embedded PNG parsed, stored privately and rewritten to authenticated image ID")
            req("POST", f"/units/{uid}/versions/{vid}/activate")
            req("POST", f"/units/{uid}/status", json={"status": "published"})
            req("POST", f"/units/{uid}/permissions", json={"grants": [{"target_type": "global", "target_id": "*"}]})
            assert req("GET", "/files/" + image["id"] + "/image", reader).content == blob
            check("published authorized image response equals original PNG")
            edit = req("PUT", "/units/" + uid, json={"title": detail["title"], "content": detail["content"] + "\n新增修订说明。"}).json()
            worker()
            updated = req("GET", "/units/" + uid).json()
            new_image = next(a for a in updated["attachments"] if a["purpose"] == "image")
            assert new_image["id"] != image["id"] and new_image["id"] in updated["content"]
            assert updated["latest_version"]["status"] == "ready"
            req("POST", f"/units/{uid}/versions/{updated['latest_version']['id']}/activate")
            assert req("GET", "/files/" + new_image["id"] + "/image", reader).content == blob
            req("GET", "/files/" + image["id"] + "/image", reader, status=404)
            check("edited version retains private image with new version ID and rejects previous image")
            # Leave no public image after verification.
            req("POST", f"/units/{uid}/permissions", json={"grants": []})
            req("GET", "/files/" + new_image["id"] + "/image", reader, status=404)
            check("revoked image access immediately returns 404")
            report["passed"] = True
        except Exception as exc:
            report["failure"] = {"type": type(exc).__name__, "detail": str(exc)[:500]}
            print("FAIL " + str(exc)[:300], flush=True)
        finally:
            if uid:
                req("DELETE", "/units", json={"unit_ids": [uid]})
                report["cleanup"] = True
            (OUT / "images.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
