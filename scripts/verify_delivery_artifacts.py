"""Verify final source distribution completeness without disclosing local secrets."""
import json
from pathlib import Path
import tarfile

from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]


def main():
    archive = max((ROOT / "dist").glob("*.tar.gz"), key=lambda p: p.stat().st_mtime)
    required = ["uv.lock", "README.md", ".env.example", "pyproject.toml", "alembic.ini",
                "migrations/versions/0005_settlement_provenance.py", "scripts/start-project.ps1",
                "scripts/stop-project.ps1", "scripts/init_stage2.py", "frontend/package-lock.json",
                "frontend/src/views/DashboardView.vue", "frontend/src/views/SettlementView.vue",
                "frontend/src/vendor/taste-charts.js", "frontend/tsconfig.json", "frontend/vite.config.ts",
                "docs/final-validation.md", "docs/final-delivery.md", ".taste-skill/final-review.md",
                "知识库管理平台.md", "流程记忆.md", "阶段提示词.md"]
    accounts = ROOT / "var/setup/stage2-accounts.json"
    secrets = list(json.loads(accounts.read_text(encoding="utf8")).values()) if accounts.is_file() else []
    for name, value in dotenv_values(ROOT / ".env").items():
        if any(word in name.upper() for word in ("PASSWORD", "SECRET", "API_KEY", "TOKEN")) and value and len(value) >= 12:
            secrets.append(value)
    needles = [s.encode() for s in secrets if isinstance(s, str) and len(s) >= 8]
    with tarfile.open(archive, "r:gz") as package:
        members = [m for m in package.getmembers() if m.isfile()]
        names = [m.name.split("/", 1)[1] for m in members]
        missing = [name for name in required if name not in names]
        forbidden = [name for name in names if any(part in {".env", "var", "node_modules", ".venv", ".git", "__pycache__"} for part in Path(name).parts)]
        leaks = []
        for member, name in zip(members, names):
            if Path(name).suffix.lower() in {".py", ".md", ".json", ".toml", ".yaml", ".yml", ".txt", ".ps1", ".js", ".ts", ".vue", ".log"} or name == ".env.example":
                content = package.extractfile(member).read()
                if any(secret in content for secret in needles):
                    leaks.append(name)
        report = {"archive": str(archive.relative_to(ROOT)), "source_files": len(names), "required_files": required,
                  "missing_entries": missing, "forbidden_entries": forbidden, "secret_value_matches": leaks,
                  "frontend_source": any(name.startswith("frontend/src/") for name in names),
                  "frontend_lockfile": "frontend/package-lock.json" in names, "python_lockfile": "uv.lock" in names,
                  "passed": not (missing or forbidden or leaks)}
        (ROOT / "docs/evidence/stage7/packaging.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf8")
        assert report["passed"], {"missing": missing, "forbidden": forbidden, "sensitive_files": leaks}
        print(json.dumps({"passed": True, "source_files": len(names), "required_files_present": len(required),
                          "forbidden_entries": 0, "secret_value_matches": 0}))


if __name__ == "__main__":
    main()
