"""Capture the original UI, including real missing-dependency feedback."""
import json
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from atguigu.config.config import PROJECT_ROOT, RuntimeConfig


def main():
    out = PROJECT_ROOT / "docs/evidence/stage1"
    out.mkdir(parents=True, exist_ok=True)
    report = {"viewport": {"width": 1440, "height": 1000}, "pages": []}
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=True)
        report["browser"] = browser.version
        page = browser.new_page(viewport=report["viewport"])
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        for name, port in [("import", RuntimeConfig.import_port), ("chat", RuntimeConfig.query_port)]:
            page.goto(f"http://127.0.0.1:{port}/", wait_until="networkidle")
            page.screenshot(path=str(out / f"{name}-initial.png"), full_page=True)
            if name == "import":
                page.locator('input[type="file"]').set_input_files(str(PROJECT_ROOT / "examples/KB-DEMO-180.md"))
                page.wait_for_function("document.body.innerText.includes('失败')", timeout=30000)
            else:
                page.locator("#input").fill("KB-DEMO-180 演示设备应如何停机？")
                page.locator("#send").click()
                page.wait_for_function("document.body.innerText.includes('查询失败')", timeout=30000)
            page.screenshot(path=str(out / f"{name}-dependency-failure.png"), full_page=True)
            report["pages"].append({"name": name, "title": page.title(), "page_errors": list(errors),
                                    "body_text": page.locator("body").inner_text()})
            errors.clear()
        browser.close()
    (out / "browser.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
