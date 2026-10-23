"""Read-only environment probes. Never prints secrets or changes stored data."""
import argparse
import importlib.metadata
import json
import platform
import socket
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from atguigu.config.config import (
    BusinessConfig, EmbeddingConfig, LLMConfig, McpConfig, MilvusConfig,
    MinIoConfig, MineruConfig, MongoConfig, RerankConfig,
)


def command(args):
    try:
        result = subprocess.run(args, capture_output=True, text=True, timeout=15, errors="replace")
        return {"ok": result.returncode == 0, "exit_code": result.returncode,
                "output": (result.stdout.strip() or result.stderr.strip())[:600]}
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"ok": False, "error_type": type(exc).__name__}


def tcp_probe(entry):
    name, url, default_port = entry
    parsed = urlsplit(url if "://" in url else "tcp://" + url)
    host, port = parsed.hostname, parsed.port or default_port
    try:
        with socket.create_connection((host, port), timeout=2):
            return name, {"tcp_reachable": True, "protocol_authenticated": "not_checked", "host": host, "port": port}
    except OSError as exc:
        return name, {"tcp_reachable": False, "protocol_authenticated": "not_checked", "host": host, "port": port, "error_type": type(exc).__name__}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="docs/evidence/stage1/environment.json")
    args = parser.parse_args()
    services = [
        ("milvus", MilvusConfig.milvus_url, 19530),
        ("minio", MinIoConfig.minio_endpoint, 9000),
        ("mongodb", MongoConfig.mongo_url, 27017),
        ("mysql", BusinessConfig.mysql_url, 3306),
        ("redis", BusinessConfig.redis_url, 6379),
    ]
    with ThreadPoolExecutor(max_workers=5) as executor:
        probes = dict(executor.map(tcp_probe, services))
    packages = {}
    for name in ["fastapi", "uvicorn", "langgraph", "langchain", "pymilvus", "pymongo", "minio", "torch", "FlagEmbedding", "playwright"]:
        try:
            packages[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            packages[name] = None
    report = {
        "captured_at_utc": datetime.now(timezone.utc).isoformat(), "report_timezone": "Asia/Shanghai",
        "python": sys.version, "platform": platform.platform(), "packages": packages,
        "node": command(["node", "--version"]), "uv": command(["uv", "--version"]),
        "docker": command(["docker", "info", "--format", "{{.ServerVersion}}"]),
        "gpu": command(["nvidia-smi", "--query-gpu=name,memory.total,driver_version", "--format=csv,noheader"]),
        "services": probes,
        "models": {
            "chat_configured": bool(LLMConfig.openai_api_base and LLMConfig.openai_api_key and LLMConfig.item_model),
            "vision_configured": bool(LLMConfig.vl_base_url and LLMConfig.vl_model and LLMConfig.vl_api_key),
            "rerank_configured": bool(RerankConfig.rerank_base_url and RerankConfig.model and RerankConfig.rerank_api_key),
            "pdf_configured": bool(MineruConfig.mineru_token),
            "embedding_configured": bool(EmbeddingConfig.embedding_base_url and EmbeddingConfig.embedding_api_key and EmbeddingConfig.model),
            "embedding_provider": "remote_api",
            "embedding_model": EmbeddingConfig.model,
            "embedding_dimensions": EmbeddingConfig.dimensions,
            "web_search_enabled": McpConfig.enabled,
            "model_inference": "not_verified",
        },
        "credentials": {"minio_configured": bool(MinIoConfig.minio_access_key and MinIoConfig.minio_secret_key)},
    }
    target = Path(args.output)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
