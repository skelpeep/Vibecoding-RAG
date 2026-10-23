"""Real authorized screenshots; no test fixtures are presented as business data."""
import json
import sys
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs/evidence/stage3/screens"


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    credentials = json.loads((ROOT / "var/setup/stage2-accounts.json").read_text(encoding="utf-8"))
    report = {"screens": [], "page_errors": [], "fonts": []}
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=True)
        page = browser.new_page()
        page.on("pageerror", lambda error: report["page_errors"].append(str(error)))
        page.goto("http://127.0.0.1:5183/login", wait_until="networkidle")
        for width in (1440, 768, 390):
            page.set_viewport_size({"width": width, "height": 900})
            page.screenshot(path=str(OUT / f"login-{width}.png"), full_page=True)
            report["screens"].append({"name":"login", "width":width,"overflow":page.evaluate("document.documentElement.scrollWidth > innerWidth")})
        page.get_by_label("用户名", exact=True).fill("admin")
        page.get_by_label("密码", exact=True).fill(credentials["admin"])
        with page.expect_response("**/api/auth/login") as response:
            page.get_by_role("button", name="登录", exact=True).click()
        assert response.value.status == 200
        page.wait_for_url("**/org/users")
        for route, name in [("/org/users", "users"), ("/org/roles", "roles"), ("/org/departments", "departments"), ("/profile", "profile"), ("/dashboard", "module")]:
            page.goto("http://127.0.0.1:5183" + route, wait_until="networkidle")
            for width in (1440, 768, 390):
                page.set_viewport_size({"width": width, "height": 900})
                page.evaluate("document.fonts.ready")
                page.screenshot(path=str(OUT / f"{name}-{width}.png"), full_page=True)
                report["screens"].append({"name": name, "width": width, "url": page.url,
                    "overflow": page.evaluate("document.documentElement.scrollWidth > innerWidth"),
                    "font": page.locator("h1").evaluate("el => getComputedStyle(el).fontFamily")})
            if name == "users":
                cdp = page.context.new_cdp_session(page)
                cdp.send("DOM.enable")
                cdp.send("CSS.enable")
                root_id = cdp.send("DOM.getDocument")["root"]["nodeId"]
                for selector in ("h1", ".date-cell", ".person small"):
                    node_id = cdp.send("DOM.querySelector", {"nodeId":root_id,"selector":selector})["nodeId"]
                    report["fonts"].append({"selector":selector, **cdp.send("CSS.getPlatformFontsForNode", {"nodeId":node_id})})
                cdp.detach()
        browser.close()
    (OUT.parent / "screens.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"screens": len(report["screens"]), "errors": report["page_errors"],
                      "overflow": [s for s in report["screens"] if s["overflow"]]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
