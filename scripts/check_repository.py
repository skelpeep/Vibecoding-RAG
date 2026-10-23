"""Check Git upload contents and optionally export a checked source snapshot."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path, PurePosixPath
import re
import subprocess
from urllib.parse import unquote, urlsplit
import zipfile

ROOT = Path(__file__).resolve().parents[1]
MAX_FILE_BYTES = 100 * 1024 * 1024
PATTERNS = {
    "private_key": re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "provider_key": re.compile(
        rb"(?<![A-Za-z0-9])(?:sk-[A-Za-z0-9_-]{20,}|gh[pousr]_[A-Za-z0-9]{20,}"
        rb"|github_pat_[A-Za-z0-9_]{30,}|AKIA[A-Z0-9]{16})"
    ),
    "credential_url": re.compile(
        rb"(?:mysql[^:\s]*|mongodb(?:\+srv)?|redis|https?)://[^\s'\"<>/:]+:[^\s'\"<>/@]+@"
    ),
}
LOCAL_PARTS = {".env", ".git", ".idea", ".vscode", ".venv", "venv", "__pycache__",
               ".pytest_cache", "node_modules", "var", "dist", "build"}
REQUIRED = ("README.md", ".env.example", ".gitignore", "pyproject.toml", "uv.lock",
            "frontend/package.json", "frontend/package-lock.json", "frontend/vite.config.ts",
            "migrations/versions/0005_settlement_provenance.py", "scripts/start-project.ps1",
            "scripts/stop-project.ps1", "scripts/init_stage2.py", "docs/setup.md",
            "docs/github-upload.md", "THIRD_PARTY_NOTICES.md", ".github/workflows/ci.yml")


def git(*args):
    return subprocess.check_output(["git", *args], cwd=ROOT)


def local_secrets():
    """Compare exact local credential values without printing their contents."""
    result = set()
    env = ROOT / ".env"
    if env.is_file():
        for line in env.read_text(encoding="utf-8-sig").splitlines():
            match = re.match(r"\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*?)\s*$", line)
            if not match:
                continue
            name, value = match.groups()
            if len(value) > 1 and value[0] == value[-1] and value[0] in "\"'":
                value = value[1:-1]
            if any(word in name.upper() for word in ("PASSWORD", "SECRET", "API_KEY", "TOKEN")):
                result.add(value)
            try:
                if "://" in value:
                    password = urlsplit(value).password
                    if password:
                        result.update((password, unquote(password)))
            except ValueError:
                continue
    accounts = ROOT / "var/setup/stage2-accounts.json"
    if accounts.is_file():
        values = json.loads(accounts.read_text(encoding="utf-8-sig"))
        result.update(v for v in values.values() if isinstance(v, str))
    return [value.encode() for value in result if len(value) >= 8]


def scan(data, path, secrets, historical=False):
    findings = []
    if any(value in data for value in secrets):
        findings.append({"path": path, "rule": "local_secret_value"})
    for rule, pattern in PATTERNS.items():
        for match in pattern.finditer(data):
            start = data.rfind(b"\n", 0, match.start()) + 1
            end = data.find(b"\n", match.end())
            line = data[start:end if end >= 0 else len(data)]
            # Only explicit, synthetic test URLs can opt out of this one rule.
            if rule == "credential_url" and path.startswith("tests/") and b"repository-check: allow-credential-url" in line:
                continue
            findings.append({"path": path, "rule": rule,
                             "line": data[:match.start()].count(b"\n") + 1})
    for finding in findings:
        finding["scope"] = "history" if historical else "worktree"
    return findings


def history(secrets):
    objects = git("rev-list", "--objects", "--all").splitlines()
    findings, checked = [], 0
    process = subprocess.Popen(["git", "cat-file", "--batch"], cwd=ROOT,
                               stdin=subprocess.PIPE, stdout=subprocess.PIPE)
    try:
        for entry in objects:
            parts = entry.split(b" ", 1)
            if len(parts) != 2:
                continue
            oid, name = parts
            process.stdin.write(oid + b"\n")
            process.stdin.flush()
            header = process.stdout.readline().split()
            if len(header) != 3:
                raise RuntimeError("Cannot inspect historical Git object")
            data = process.stdout.read(int(header[2]))
            process.stdout.read(1)
            if header[1] == b"blob":
                checked += 1
                path = name.decode("utf8", errors="replace")
                if len(data) >= MAX_FILE_BYTES:
                    findings.append({"path": path, "rule": "github_file_limit", "scope": "history"})
                if PurePosixPath(path).name == ".env":
                    findings.append({"path": path, "rule": "historical_local_config", "scope": "history"})
                for finding in scan(data, path, secrets, True):
                    findings.append({**finding, "object": oid[:12].decode()})
    finally:
        process.stdin.close()
        process.stdout.close()
        process.wait()
    return checked, findings


def forbidden(name):
    parts = PurePosixPath(name).parts
    leaf = parts[-1]
    return (any(part in LOCAL_PARTS for part in parts)
            or (leaf.startswith(".env.") and leaf != ".env.example")
            or leaf.endswith((".pyc", ".pyo", ".tsbuildinfo", ".pem", ".key", ".p12", ".pfx"))
            or name == "deploy/vm/redis.conf"
            or (name.startswith("docs/evidence/") and name != "docs/evidence/README.md")
            or (name.startswith(".taste-skill/") and not (len(parts) == 2 and
                (leaf.endswith(".md") or leaf == "direction.json"))))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--history", action="store_true", help="also scan all reachable Git history")
    parser.add_argument("--archive", type=Path, help="write checked source ZIP (no Git history)")
    parser.add_argument("--report", type=Path, default=Path("var/reports/github-readiness.json"))
    args = parser.parse_args()
    paths = sorted({p.decode("utf8") for p in git("ls-files", "--cached", "--others", "--exclude-standard", "-z").split(b"\0") if p})
    paths = [name for name in paths if (ROOT / name).is_file()]
    secrets = local_secrets()
    findings, large, manifest = [], [], []
    for name in paths:
        path = ROOT / name
        if path.is_symlink() or not path.resolve().is_relative_to(ROOT):
            findings.append({"path": name, "rule": "symlink_or_outside_workspace"})
            continue
        if forbidden(name):
            findings.append({"path": name, "rule": "local_or_generated_file"})
        size = path.stat().st_size
        manifest.append({"path": name, "bytes": size})
        if size >= MAX_FILE_BYTES:
            findings.append({"path": name, "rule": "github_file_limit"})
        elif size >= 10 * 1024 * 1024:
            large.append({"path": name, "bytes": size})
        data = path.read_bytes()
        if path.suffix == ".ps1" and any(byte > 127 for byte in data) and not data.startswith(b"\xef\xbb\xbf"):
            findings.append({"path": name, "rule": "powershell_utf8_bom_required"})
        findings.extend(scan(data, name, secrets))
    for name in REQUIRED:
        if name not in paths:
            findings.append({"path": name, "rule": "required_file_missing"})
    historical_count = 0
    if args.history:
        historical_count, historical_findings = history(secrets)
        findings.extend(historical_findings)
    report = {"captured_at_utc": datetime.now(timezone.utc).isoformat(), "passed": not findings,
              "files": len(manifest), "source_bytes": sum(row["bytes"] for row in manifest),
              "historical_blobs_checked": historical_count, "findings": findings,
              "large_files": large, "manifest": manifest}
    if args.archive and not findings:
        archive = args.archive if args.archive.is_absolute() else ROOT / args.archive
        # Export only into ignored dist/, so a future git add cannot absorb the ZIP.
        if not archive.resolve().is_relative_to((ROOT / "dist").resolve()) or archive.suffix != ".zip":
            parser.error("--archive must name a .zip inside this project's dist/ directory")
        archive.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as output:
            for row in manifest:
                output.write(ROOT / row["path"], "knowledge-platform/" + row["path"])
        report["archive"] = str(archive.relative_to(ROOT))
        report["archive_bytes"] = archive.stat().st_size
    target = args.report if args.report.is_absolute() else ROOT / args.report
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf8")
    print(json.dumps({key: value for key, value in report.items() if key != "manifest"},
                     ensure_ascii=True, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
