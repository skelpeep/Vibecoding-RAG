"""Real storage smoke checks using unique project-owned records; no model substitute."""
import io
import json
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import unquote, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from atguigu.config.config import BusinessConfig, MilvusConfig, MinIoConfig, MongoConfig


def main():
    run_id = uuid.uuid4().hex
    result = {"captured_at_utc": datetime.now(timezone.utc).isoformat(), "run_id": run_id,
              "model_inference": "not_tested", "services": {}}

    def check(name, operation):
        try:
            result["services"][name] = {"passed": True, **operation()}
        except Exception as exc:
            # Never persist exception text containing credential-bearing URLs.
            result["services"][name] = {"passed": False, "error_type": type(exc).__name__}

    def milvus():
        from pymilvus import MilvusClient
        client = MilvusClient(uri=MilvusConfig.milvus_url, token=MilvusConfig.milvus_token, timeout=10)
        try:
            # No synthetic embeddings or writes: verify the real server/protocol here.
            version = client.get_server_version()
            names = client.list_collections()
            return {"version": version, "collection_count": len(names), "vector_search": "not_tested_without_model"}
        finally:
            client.close()

    def minio():
        from atguigu.tool.minio_client_tool import get_minio_client
        client = get_minio_client()
        data = ("storage-probe:" + run_id).encode()
        name = "verification/" + run_id + ".txt"
        client.put_object(MinIoConfig.minio_bucket_name, name, io.BytesIO(data), len(data), content_type="text/plain")
        response = client.get_object(MinIoConfig.minio_bucket_name, name)
        try:
            assert response.read() == data
        finally:
            response.close()
            response.release_conn()
        return {"bucket": MinIoConfig.minio_bucket_name, "object": name, "write_read_equal": True}

    def mongo():
        from pymongo import MongoClient
        from atguigu.tool.mongo_client_tool import add_or_update_history, get_recent_history_list
        client = MongoClient(MongoConfig.mongo_url, serverSelectionTimeoutMS=5000)
        try:
            assert client.admin.command("ping")["ok"] == 1
            session = "storage-probe-" + run_id
            add_or_update_history(session, "user", "存储验证问题（非模型问答）")
            add_or_update_history(session, "assistant", "存储验证记录（非模型生成）")
            items = get_recent_history_list(session)
            assert len(items) == 2
            return {"database": MongoConfig.mongo_db_name, "session_id": session, "history_records": len(items)}
        finally:
            client.close()

    def mysql():
        import pymysql
        url = urlsplit(BusinessConfig.mysql_url)
        connection = pymysql.connect(host=url.hostname, port=url.port or 3306,
                                     user=unquote(url.username or ""), password=unquote(url.password or ""),
                                     database=url.path.lstrip("/"), connect_timeout=5, charset="utf8mb4")
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT DATABASE(), VERSION()")
                database, version = cursor.fetchone()
                # A connection-local temporary table leaves no business schema behind.
                cursor.execute("CREATE TEMPORARY TABLE kb_storage_probe (value VARCHAR(64))")
                cursor.execute("INSERT INTO kb_storage_probe VALUES (%s)", (run_id,))
                cursor.execute("SELECT value FROM kb_storage_probe")
                assert cursor.fetchone()[0] == run_id
                cursor.execute("SELECT @@global.time_zone, @@session.time_zone")
                global_tz, session_tz = cursor.fetchone()
            return {"database": database, "version": version, "temporary_table_write_read": True,
                    "global_time_zone": global_tz, "session_time_zone": session_tz}
        finally:
            connection.close()

    def redis():
        from redis import Redis
        client = Redis.from_url(BusinessConfig.redis_url, socket_connect_timeout=5, socket_timeout=5)
        try:
            assert client.ping()
            key = "kb:storage-probe:" + run_id
            assert client.set(key, run_id, ex=60, nx=True)
            assert client.get(key).decode() == run_id
            return {"ping": True, "write_read_equal": True, "probe_ttl_seconds": 60}
        finally:
            client.close()

    for name, operation in [("milvus", milvus), ("minio", minio), ("mongodb", mongo), ("mysql", mysql), ("redis", redis)]:
        check(name, operation)
    result["all_passed"] = all(service["passed"] for service in result["services"].values())
    target = Path("docs/evidence/stage1/vm-storage.json")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["all_passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
