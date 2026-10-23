"""Generate local secrets, upgrade MySQL, then add demo identities without overwriting."""
import json
import os
import secrets
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    # Persist locally before DB writes; passwords are never printed or committed.
    env_path = ROOT / ".env"
    from dotenv import dotenv_values
    values = dotenv_values(env_path)
    if not (os.getenv("JWT_SECRET") or values.get("JWT_SECRET")):
        with env_path.open("a", encoding="utf-8") as stream:
            stream.write("\nJWT_SECRET=" + secrets.token_urlsafe(48) + "\n")
    elif len((os.getenv("JWT_SECRET") or values["JWT_SECRET"]).encode()) < 32:
        raise ValueError("现有 JWT_SECRET 太短；未覆盖，请设置至少 32 字节随机密钥")

    from alembic import command
    from alembic.config import Config
    from sqlalchemy.orm import Session
    from sqlalchemy import text
    from atguigu.business.database import get_engine
    from atguigu.business.seed import USERS, seed_demo

    command.upgrade(Config(str(ROOT / "alembic.ini")), "head")
    credential_path = ROOT / "var/setup/stage2-accounts.json"
    credential_path.parent.mkdir(parents=True, exist_ok=True)
    credentials = json.loads(credential_path.read_text(encoding="utf-8")) if credential_path.exists() else {}
    for username, *_ in USERS:
        credentials.setdefault(username, secrets.token_urlsafe(18))
    credential_path.write_text(json.dumps(credentials, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    with Session(get_engine()) as db, db.begin():
        created = seed_demo(db, credentials)
        revision = db.scalar(text("SELECT version_num FROM alembic_version"))
    print(json.dumps({"migration": revision, "created_accounts": created,
                      "credentials_file": "var/setup/stage2-accounts.json", "existing_records": "preserved"}, ensure_ascii=False))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"初始化失败：{type(exc).__name__}；未输出含凭据的异常详情", file=sys.stderr)
        raise SystemExit(1)
