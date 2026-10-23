"""Browser acceptance against Stage 2's real API/MySQL. Only this run's QA records are removed."""
import json
import secrets
import sys
from pathlib import Path
from uuid import uuid4

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
BASE = "http://127.0.0.1:5186"
OUT = ROOT / "docs/evidence/stage7/org-ui"


def main():
    credentials = json.loads((ROOT / "var/setup/stage2-accounts.json").read_text(encoding="utf-8"))
    prefix = "stage3_qa_" + uuid4().hex[:8]
    password = secrets.token_urlsafe(24)
    reset_password = secrets.token_urlsafe(24)
    final_password = secrets.token_urlsafe(24)
    report = {"checks": [], "page_errors": [], "cleanup": False, "data": "real Stage 2 API/MySQL; isolated temporary QA records"}
    created = {"user": None, "departments": [], "role": None}
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "interactions").mkdir(exist_ok=True)

    def passed(name):
        report["checks"].append(name)
        print("PASS " + name, flush=True)

    def goto(page, path):
        page.goto(BASE + path, wait_until="networkidle")
        expect(page.locator("h1")).to_be_visible()

    def login(page, username, secret, status=200):
        goto(page, "/login")
        page.get_by_label("用户名", exact=True).fill(username)
        page.get_by_label("密码", exact=True).fill(secret)
        with page.expect_response("**/api/auth/login") as result:
            page.get_by_role("button", name="登录", exact=True).click()
        assert result.value.status == status, f"login status {result.value.status}"
        if status == 200:
            page.wait_for_url(lambda url: "/login" not in url)
            page.wait_for_load_state("networkidle")
        else:
            expect(page.locator(".form-error")).to_be_visible()

    def save_dialog(page, endpoint, method="POST", status=200):
        with page.expect_response(lambda r: r.url.endswith("/api" + endpoint) and r.request.method == method) as result:
            page.get_by_role("dialog").get_by_role("button", name="保存", exact=True).click()
        assert result.value.status == status, f"{endpoint}: {result.value.status}"
        if status < 300:
            expect(page.get_by_role("dialog")).not_to_be_visible()
        else:
            expect(page.get_by_role("dialog").get_by_role("alert")).to_be_visible()
        return result.value.json()

    def more(page, action):
        page.get_by_role("button", name="更多操作 " + prefix, exact=True).click()
        page.get_by_role("button", name=action, exact=True).click()

    def choose_role(page):
        page.locator(".object-row").filter(has_text=prefix).click()

    def permissions_save(page):
        page.get_by_role("button", name="保存权限", exact=True).click()
        with page.expect_response("**/permissions") as response:
            page.get_by_role("button", name="确认保存", exact=True).click()
        assert response.value.status == 200
        expect(page.get_by_role("button", name="保存权限", exact=True)).to_be_disabled()

    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=True)
        admin = browser.new_page(viewport={"width": 1440, "height": 900})
        member = browser.new_page(viewport={"width": 1440, "height": 900})
        for page in (admin, member):
            page.on("pageerror", lambda error: report["page_errors"].append(str(error)))
        try:
            goto(admin, "/org/users")
            assert "/login?redirect=" in admin.url
            passed("anonymous protected route redirects to login")
            login(admin, "admin", credentials["admin"])
            passed("real administrator form login and dynamic navigation")

            goto(admin, "/org/departments")
            admin.get_by_role("button", name="新增部门", exact=True).click()
            admin.get_by_label("部门名称", exact=False).fill("阶段三验收部门")
            admin.get_by_label("部门编码", exact=False).fill(prefix)
            department = save_dialog(admin, "/org/departments", status=201)
            created["departments"].append(department["id"])
            admin.get_by_role("button", name="编辑部门", exact=True).click()
            admin.get_by_label("部门名称", exact=False).fill("阶段三验收部门（已编辑）")
            save_dialog(admin, f"/org/departments/{department['id']}", "PUT")
            passed("department create and edit persist to API")
            admin.get_by_role("button", name="新增部门", exact=True).click()
            admin.get_by_label("部门名称", exact=False).fill("重复编码验收")
            admin.get_by_label("部门编码", exact=False).fill(prefix)
            save_dialog(admin, "/org/departments", status=409)
            admin.get_by_role("dialog").get_by_role("button", name="取消", exact=True).click()
            passed("duplicate department code returns visible conflict")

            goto(admin, "/org/roles")
            admin.get_by_role("button", name="新增角色", exact=True).click()
            admin.get_by_label("角色名称", exact=False).fill("阶段三验收角色")
            admin.get_by_label("角色编码", exact=False).fill(prefix)
            role = save_dialog(admin, "/org/roles", status=201)
            created["role"] = role["id"]
            admin.get_by_role("button", name="编辑角色", exact=True).click()
            admin.get_by_label("角色说明", exact=True).fill("浏览器真实联调临时角色，结束后清理")
            save_dialog(admin, f"/org/roles/{role['id']}", "PUT")
            admin.get_by_label("显示组织管理菜单", exact=True).check()
            admin.get_by_label("查看用户", exact=True).check()
            permissions_save(admin)
            passed("role create/edit and independent menu/operation permission save")
            admin.get_by_label("新增用户", exact=True).check()
            admin.get_by_role("link", name="用户管理", exact=True).click()
            expect(admin.get_by_role("dialog")).to_contain_text("尚未保存")
            admin.get_by_role("button", name="继续编辑", exact=True).click()
            assert admin.url.endswith("/org/roles")
            admin.get_by_label("新增用户", exact=True).uncheck()
            passed("unsaved role changes are protected when leaving route")

            goto(admin, "/org/users")
            admin.get_by_role("button", name="新增用户", exact=True).click()
            admin.get_by_label("用户名", exact=False).fill(prefix)
            admin.get_by_label("显示名称", exact=False).fill("阶段三验收成员")
            admin.get_by_label("所属部门", exact=True).select_option(department["id"])
            admin.get_by_label("初始密码", exact=False).fill(password)
            admin.get_by_role("checkbox", name="阶段三验收角色").check()
            user = save_dialog(admin, "/org/users", status=201)
            created["user"] = user["id"]
            admin.get_by_label("搜索用户", exact=True).fill(prefix)
            expect(admin.locator("tbody tr")).to_have_count(1)
            admin.get_by_role("button", name="编辑 " + prefix, exact=True).click()
            admin.get_by_label("显示名称", exact=False).fill("阶段三验收成员（已编辑）")
            admin.get_by_label("邮箱", exact=True).fill(prefix + "@example.invalid")
            save_dialog(admin, f"/org/users/{user['id']}", "PUT")
            expect(admin.locator("tbody")).to_contain_text("阶段三验收成员（已编辑）")
            passed("user create/edit, department/role assignment and live search")

            login(member, prefix, password)
            expect(member.get_by_role("button", name="新增用户", exact=True)).to_have_count(0)
            expect(member.locator(".row-actions").first).to_contain_text("只读")
            goto(member, "/org/roles")
            assert member.url.endswith("/forbidden")
            passed("read-only role hides mutation actions and rejects direct role route")
            goto(admin, "/org/roles")
            choose_role(admin)
            admin.get_by_label("新增用户", exact=True).check()
            permissions_save(admin)
            goto(member, "/org/users")
            expect(member.get_by_role("button", name="新增用户", exact=True)).to_be_visible()
            passed("saved role permissions change member navigation/actions immediately")

            goto(admin, "/org/departments")
            admin.locator(".department-row").filter(has_text="阶段三验收部门").click()
            admin.get_by_role("button", name="编辑部门", exact=True).click()
            admin.get_by_label("负责人", exact=True).select_option(user["id"])
            expect(admin.get_by_label("上级部门", exact=True).locator(f'option[value="{department["id"]}"]')).to_have_count(0)
            save_dialog(admin, f"/org/departments/{department['id']}", "PUT")
            admin.get_by_role("button", name="新增部门", exact=True).click()
            admin.get_by_label("部门名称", exact=False).fill("阶段三验收子部门")
            admin.get_by_label("部门编码", exact=False).fill(prefix + "_child")
            admin.get_by_label("上级部门", exact=True).select_option(department["id"])
            child = save_dialog(admin, "/org/departments", status=201)
            created["departments"].append(child["id"])
            admin.get_by_role("button", name="添加成员", exact=True).click()
            admin.get_by_label("选择成员", exact=False).select_option(user["id"])
            save_dialog(admin, f"/org/users/{user['id']}", "PUT")
            expect(admin.locator(".member-list")).to_contain_text(prefix)
            admin.locator(".department-row").filter(has_text="阶段三验收部门（已编辑）").click()
            admin.get_by_role("button", name="编辑部门", exact=True).click()
            expect(admin.get_by_label("上级部门", exact=True).locator(f'option[value="{child["id"]}"]')).to_have_count(0)
            admin.get_by_label("负责人", exact=True).select_option("")
            save_dialog(admin, f"/org/departments/{department['id']}", "PUT")
            passed("department leader, child hierarchy, move member, and cycle-safe parent options")

            goto(admin, "/org/users")
            admin.get_by_label("搜索用户", exact=True).fill(prefix)
            expect(admin.locator("tbody tr")).to_have_count(1)
            more(admin, "停用账号")
            with admin.expect_response(f"**/users/{user['id']}/status") as result:
                admin.get_by_role("button", name="确认停用", exact=True).click()
            assert result.value.status == 200
            expect(admin.locator("tbody .status")).to_have_text("停用")
            goto(member, "/profile")
            assert "/login" in member.url
            login(member, prefix, password, 401)
            more(admin, "启用账号")
            with admin.expect_response(f"**/users/{user['id']}/status") as result:
                admin.get_by_role("button", name="确认启用", exact=True).click()
            assert result.value.status == 200
            expect(admin.locator("tbody .status")).to_have_text("启用")
            passed("disable revokes existing session and blocks login; re-enable works")
            more(admin, "重置密码")
            admin.get_by_label("新密码", exact=False).fill(reset_password)
            save_dialog(admin, f"/org/users/{user['id']}/reset-password")
            login(member, prefix, reset_password)
            passed("administrator password reset allows new real login")

            goto(member, "/profile")
            member.get_by_label("显示名称", exact=False).fill("阶段三验收本人")
            with member.expect_response("**/auth/profile") as result:
                member.get_by_role("button", name="保存资料", exact=True).click()
            assert result.value.status == 200
            expect(member.locator(".identity-strip")).to_contain_text("阶段三验收本人")
            member.get_by_label("当前密码", exact=False).fill(reset_password)
            member.locator("input[autocomplete=new-password]").nth(0).fill(final_password)
            member.locator("input[autocomplete=new-password]").nth(1).fill(reset_password)
            member.get_by_role("button", name="更新密码", exact=True).click()
            expect(member.locator(".form-error")).to_contain_text("不一致")
            member.locator("input[autocomplete=new-password]").nth(1).fill(final_password)
            with member.expect_response("**/auth/password") as result:
                member.get_by_role("button", name="更新密码", exact=True).click()
            assert result.value.status == 200
            member.wait_for_url("**/login?expired=1")
            login(member, prefix, reset_password, 401)
            login(member, prefix, final_password)
            passed("self profile save, password mismatch, password change and old-secret rejection")

            # Restore/remove the UI-created objects through their supported UI actions.
            more(admin, "分配角色")
            admin.get_by_role("checkbox", name="阶段三验收角色").uncheck()
            save_dialog(admin, f"/org/users/{user['id']}/roles")
            admin.get_by_role("button", name="编辑 " + prefix, exact=True).click()
            admin.get_by_label("所属部门", exact=True).select_option("")
            save_dialog(admin, f"/org/users/{user['id']}", "PUT")
            goto(member, "/org/users")
            assert member.url.endswith("/forbidden")
            passed("role removal immediately revokes protected routes")
            goto(admin, "/org/roles")
            choose_role(admin)
            admin.get_by_role("button", name="删除角色", exact=True).click()
            with admin.expect_response(lambda r: r.url.endswith("/roles/" + role["id"]) and r.request.method == "DELETE") as result:
                admin.get_by_role("button", name="确认删除", exact=True).click()
            assert result.value.status == 200
            for dep_id, name in ((child["id"], "阶段三验收子部门"), (department["id"], "阶段三验收部门（已编辑）")):
                goto(admin, "/org/departments")
                admin.locator(".department-row").filter(has_text=name).click()
                admin.get_by_role("button", name="删除部门", exact=True).click()
                with admin.expect_response(lambda r: r.url.endswith("/departments/" + dep_id) and r.request.method == "DELETE") as result:
                    admin.get_by_role("button", name="确认删除", exact=True).click()
                assert result.value.status == 200
            passed("unassign roles, remove department membership, delete role and empty departments")

            goto(admin, "/org/users")
            admin.get_by_label("搜索用户", exact=True).fill("no_such_stage3_member")
            expect(admin.locator(".empty-state")).to_contain_text("没有找到")
            admin.screenshot(path=str(OUT / "interactions/empty-search.png"), full_page=True)
            admin.get_by_role("button", name="清除筛选", exact=True).click()
            expect(admin.locator("tbody tr").first).to_be_visible()
            admin.route("**/api/org/users?*", lambda route: route.abort())
            admin.get_by_role("button", name="刷新用户", exact=True).click()
            expect(admin.locator(".error-state")).to_be_visible()
            admin.screenshot(path=str(OUT / "interactions/network-error.png"), full_page=True)
            admin.unroute("**/api/org/users?*")
            admin.locator(".error-state").get_by_role("button").click()
            expect(admin.locator("tbody tr").first).to_be_visible()
            passed("real empty search and reset; simulated network failure and successful retry")
            admin.route("**/api/org/roles", lambda route: route.abort())
            goto(admin, "/org/users")
            expect(admin.get_by_role("alert")).to_contain_text("选项加载失败")
            admin.get_by_role("button", name="更多操作 admin", exact=True).click()
            expect(admin.get_by_role("button", name="分配角色", exact=True)).to_be_disabled()
            admin.get_by_role("button", name="关闭菜单", exact=True).click()
            admin.unroute("**/api/org/roles")
            admin.get_by_role("button", name="重试选项", exact=True).click()
            expect(admin.get_by_role("alert")).to_have_count(0)
            passed("lookup failure cannot clear assignments and can be retried")

            admin.set_viewport_size({"width": 390, "height": 900})
            admin.get_by_role("button", name="展开导航", exact=True).click()
            expect(admin.get_by_role("dialog", name="工作区导航")).to_be_visible()
            assert admin.evaluate("document.body.style.overflow") == "hidden"
            admin.keyboard.press("Shift+Tab")
            assert admin.locator(".sidebar").evaluate("el=>el.contains(document.activeElement)")
            admin.screenshot(path=str(OUT / "interactions/mobile-navigation.png"), full_page=False)
            admin.keyboard.press("Escape")
            expect(admin.get_by_role("button", name="展开导航", exact=True)).to_be_focused()
            admin.get_by_role("button", name="新增用户", exact=True).click()
            expect(admin.get_by_role("dialog")).to_be_visible()
            admin.wait_for_function("!document.querySelector('[class*=dialog-fade-enter]')")
            admin.screenshot(path=str(OUT / "interactions/mobile-user-form.png"), full_page=False)
            admin.keyboard.press("Escape")
            expect(admin.get_by_role("dialog")).not_to_be_visible()
            for route, selector, name in (("/org/roles", ".object-row", "role"), ("/org/departments", ".department-row", "department")):
                goto(admin, route)
                admin.locator(selector).first.click()
                expect(admin.locator(".detail-pane")).to_be_visible()
                expect(admin.locator(".skeleton-list")).to_have_count(0)
                assert not admin.evaluate("document.documentElement.scrollWidth>innerWidth")
                admin.screenshot(path=str(OUT / f"interactions/mobile-{name}-detail.png"), full_page=True)
                admin.locator(".mobile-back").click()
                expect(admin.locator(".master-pane")).to_be_visible()
            passed("mobile navigation focus trap/Escape, form dialog, role/department detail and back")
            for username in ("alice", "no_op_demo"):
                login(member, username, credentials[username])
                expect(member.get_by_role("link", name="用户管理", exact=True)).to_have_count(0)
                goto(member, "/org/users")
                assert member.url.endswith("/forbidden")
            login(member, "disabled_demo", credentials["disabled_demo"], 401)
            passed("ordinary/no-operation demo boundaries and disabled demo login")
            assert not report["page_errors"], report["page_errors"]
        except Exception:
            admin.screenshot(path=str(OUT / "interactions/failure.png"), full_page=True)
            raise
        finally:
            browser.close()
            # No user-delete API exists. Scope SQL cleanup to exact IDs returned by this run;
            # the randomized username is checked before any deletion, with FK enforcement on.
            from sqlalchemy import delete, or_, select, update
            from sqlalchemy.orm import Session
            from atguigu.business.database import get_engine
            from atguigu.business.models import AuditEvent, Department, OutboxEvent, Role, User

            ids = [x for x in [created["user"], created["role"], *created["departments"]] if x]
            with Session(get_engine()) as db:
                if created["user"]:
                    actual = db.get(User, created["user"])
                    assert actual is None or actual.username == prefix
                    db.execute(update(Department).where(Department.id.in_(created["departments"])).values(leader_id=None))
                    db.execute(delete(AuditEvent).where(or_(AuditEvent.actor_id == created["user"], AuditEvent.resource_id.in_(ids))))
                    db.execute(delete(User).where(User.id == created["user"], User.username == prefix))
                else:
                    db.execute(delete(AuditEvent).where(AuditEvent.resource_id.in_(ids)))
                db.execute(delete(OutboxEvent).where(OutboxEvent.aggregate_id.in_(ids)))
                if created["role"]:
                    db.execute(delete(Role).where(Role.id == created["role"], Role.role_code == prefix))
                for dep_id in reversed(created["departments"]):
                    db.execute(delete(Department).where(Department.id == dep_id, Department.code.in_([prefix, prefix + "_child"])))
                db.commit()
                report["cleanup"] = (db.scalar(select(User.id).where(User.username == prefix)) is None and db.scalar(select(Role.id).where(Role.role_code == prefix)) is None and db.scalar(select(Department.id).where(Department.code.in_([prefix,prefix + "_child"]))) is None)
            (OUT / "interactions.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"passed": len(report["checks"]), "page_errors": report["page_errors"], "cleanup": report["cleanup"]}))


if __name__ == "__main__":
    main()
