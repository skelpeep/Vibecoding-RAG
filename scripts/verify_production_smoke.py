"""Final browser smoke against the built UI and real API; keeps labelled demo history."""
import json
from datetime import datetime, timezone
from pathlib import Path
import sys

from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
WEB = "http://127.0.0.1:8105"
OUT = ROOT / "docs/evidence/stage7"


def main():
    credentials = json.loads((ROOT / "var/setup/stage2-accounts.json").read_text(encoding="utf8"))
    fixture = json.loads((ROOT / "docs/evidence/stage6/http.json").read_text(encoding="utf8"))
    report = {"passed": False, "origin": WEB, "captured_at_utc": datetime.now(timezone.utc).isoformat(),
              "checks": [], "errors": [], "screens": []}
    def save():
        (OUT / "production-smoke.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf8")
    def check(name):
        report["checks"].append(name)
        save()
        print("PASS " + name, flush=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=True)
        def login(user):
            context = browser.new_context(viewport={"width": 1440, "height": 900})
            page = context.new_page()
            page.on("pageerror", lambda error: report["errors"].append(str(error)))
            page.goto(WEB + "/login", wait_until="networkidle")
            page.get_by_label("用户名", exact=True).fill(user)
            page.get_by_label("密码", exact=True).fill(credentials[user])
            page.get_by_role("button", name="登录", exact=True).click()
            page.wait_for_url(lambda url: "/login" not in url)
            return context, page
        def capture(page, name):
            for width in (1440, 768, 390):
                page.set_viewport_size({"width": width, "height": 900})
                page.evaluate("async () => {await document.fonts.ready; await Promise.all(document.getAnimations().map(a=>a.finished.catch(()=>{}))); await new Promise(requestAnimationFrame)}")
                assert not page.evaluate("document.documentElement.scrollWidth > innerWidth"), (name, width)
                page.screenshot(path=str(OUT / f"{name}-{width}.png"), full_page=True)
                report["screens"].append({"name": name, "width": width, "overflow": False})
            page.set_viewport_size({"width": 1440, "height": 900})
        try:
            context, page = login("admin")
            assert context.request.get(WEB + "/ready").json() == {"status": "ready", "database_revision": "0005"}
            assert context.request.get(WEB + "/dashboard").status == 200
            missing = context.request.get(WEB + "/api/not-an-endpoint")
            assert missing.status == 404 and "application/json" in missing.headers["content-type"]
            check("production form login, migration 0005, SPA deep link and unknown API JSON 404")
            page.goto(WEB + "/dashboard", wait_until="networkidle")
            expect(page.locator(".data-chart svg")).to_have_count(3)
            expect(page.locator(".lead-number")).not_to_have_text("0")
            chart = page.locator('.data-chart[aria-label="平均响应时间（毫秒）"]')
            expect(chart.locator("circle[data-isolated-point]")).to_have_count(1)
            point = chart.locator("circle[data-isolated-point]")
            assert float(point.get_attribute("cy")) > 0
            capture(page, "production-dashboard")
            check("three real dashboard charts, isolated duration measurement visible, responsive at three widths")
            page.get_by_label("开始日期").fill("2020-01-01")
            page.get_by_label("结束日期").fill("2020-01-02")
            page.get_by_role("button", name="应用范围", exact=True).click()
            expect(page.locator(".lead-number")).to_have_text("0")
            expect(page.get_by_text("当前范围暂无可用数据。", exact=True)).to_be_visible()
            expect(chart.locator("circle[data-isolated-point]")).to_have_count(0)
            check("zero visits remain zero; absent duration remains a gap with an explicit empty state")
            context.close()

            context, page = login("kb_admin")
            page.goto(WEB + "/knowledge/" + fixture["units"][0], wait_until="networkidle")
            expect(page.locator(".document-title")).to_have_text("申请流程")
            page.reload(wait_until="networkidle")
            expect(page.locator(".document-title")).to_have_text("申请流程")
            page.goto(WEB + "/settlement?tab=published", wait_until="networkidle")
            row = page.locator(".settlement-row").filter(has=page.get_by_role("heading", name=fixture["question"], exact=True))
            expect(row).to_have_count(1)
            row.get_by_role("button", name="编辑并重新审核", exact=True).click()
            expect(page.get_by_label("标准答案")).to_be_visible()
            capture(page, "production-faq-dialog")
            page.get_by_role("button", name="取消", exact=True).click()
            expect(page.locator(".el-dialog")).not_to_be_visible()
            check("production knowledge deep route reload and published FAQ edit dialog, three widths, cancelled without mutation")
            context.close()

            context, page = login("alice")
            page.goto(WEB + "/chat", wait_until="networkidle")
            page.locator("#chat-question").fill(fixture["question"])
            with page.expect_response(lambda r: r.url.endswith("/api/ai/chat/stream") and r.request.method == "POST") as response_info:
                page.get_by_role("button", name="发送问题", exact=True).click()
            response = response_info.value
            expect(page.locator(".chat-turn-status").last).to_have_text("FAQ 缓存回答", timeout=60000)
            expect(page.locator(".chat-answer").last).to_contain_text(fixture["marker"])
            from atguigu.business.chat_service import session_factory
            from atguigu.business.models import QAAccessLog
            request_id = response.headers["x-request-id"]
            with session_factory() as db:
                log = db.get(QAAccessLog, request_id)
                assert log.status == "completed" and log.cache_status == "hit" and log.total_tokens == 0
                assert log.details_json.get("history_persisted")
                report["cache_request"] = {"id": request_id, "session_id": log.session_id,
                    "cache_status": log.cache_status, "total_tokens": log.total_tokens}
            capture(page, "production-faq-hit")
            check("production first-turn Redis answer, persisted real log, all sources authorized, zero model tokens")
            assert not report["errors"], report["errors"]
            context.close()
            report["passed"] = True
            save()
        finally:
            save()
            browser.close()


if __name__ == "__main__":
    main()
