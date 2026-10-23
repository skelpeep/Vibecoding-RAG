"""Real HTTP/node evidence. A failing dependency is never substituted with a model stub."""
import argparse
import json
import shutil
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from atguigu.config.config import PROJECT_ROOT, RuntimeConfig
from atguigu.import_process.nodes.node_entry import NodeEntry
from atguigu.import_process.nodes.node_md_img import NodeMDImg
from atguigu.import_process.nodes.node_document_split import NodeDocumentSplit


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--import-url", default=f"http://127.0.0.1:{RuntimeConfig.import_port}")
    parser.add_argument("--query-url", default=f"http://127.0.0.1:{RuntimeConfig.query_port}")
    parser.add_argument("--output", default="docs/evidence/stage1/verification.json")
    parser.add_argument("--timeout", type=int, default=120)
    args = parser.parse_args()
    run_id = uuid.uuid4().hex
    work = RuntimeConfig.data_dir / "verification" / run_id
    work.mkdir(parents=True)
    sample = work / f"KB-DEMO-180-{run_id}.md"
    shutil.copyfile(PROJECT_ROOT / "examples/KB-DEMO-180.md", sample)
    state = {"task_id": run_id, "local_file_path": str(sample), "local_dir": str(work)}
    for node in [NodeEntry(), NodeMDImg(), NodeDocumentSplit()]:
        state.update(node(state))
    assert state["chunks"] and all(chunk["content"].strip() for chunk in state["chunks"])
    report = {"captured_at_utc": datetime.now(timezone.utc).isoformat(), "run_id": run_id,
              "sample": str(sample.relative_to(PROJECT_ROOT)), "models_mocked": False,
              "markdown_parse": {"passed": True, "chunks": len(state["chunks"])}}
    with httpx.Client(timeout=20, trust_env=False) as client:
        for service, url in [("import", args.import_url), ("query", args.query_url)]:
            health = client.get(url + "/health")
            health.raise_for_status()
            assert health.json().get("service") == service, "端口上运行的不是本项目服务"
            report[f"{service}_health"] = health.json()
            report[f"{service}_page_status"] = client.get(url + "/").status_code
        with sample.open("rb") as stream:
            response = client.post(args.import_url + "/upload", files={"file": (sample.name, stream, "text/markdown")})
        report["upload"] = {"http_status": response.status_code, "body": response.json()}
        if response.is_success:
            deadline = time.monotonic() + args.timeout
            while time.monotonic() < deadline:
                status = client.get(args.import_url + "/status/" + response.json()["task_id"]).json()
                report["import_result"] = status
                if status.get("status") in {"failed", "completed"}:
                    break
                time.sleep(0.5)
        session_id = "baseline-" + run_id
        response = client.get(args.query_url + "/history/" + session_id)
        report["history_before"] = {"http_status": response.status_code, "body": response.json()}
        response = client.post(args.query_url + "/query", json={"query": "KB-DEMO-180 演示设备应如何停机？", "session_id": session_id})
        report["query"] = {"http_status": response.status_code, "body": response.json()}
        if response.is_success:
            with client.stream("GET", args.query_url + "/stream/" + response.json()["task_id"], timeout=args.timeout) as stream:
                report["sse_http_status"] = stream.status_code
                # Store real wire events, including terminal failures.
                report["sse_lines"] = list(stream.iter_lines())
        response = client.get(args.query_url + "/history/" + session_id)
        report["history_after"] = {"http_status": response.status_code, "body": response.json()}
    events = report.get("sse_lines", [])
    report["full_chain_verified"] = (
        report.get("import_result", {}).get("status") == "completed"
        and any(line == "event: delta" for line in events)
        and any(line == "event: done" for line in events)
        and report["history_after"]["http_status"] == 200
        and len(report["history_after"]["body"].get("items", [])) >= 2
    )
    target = Path(args.output)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["full_chain_verified"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
