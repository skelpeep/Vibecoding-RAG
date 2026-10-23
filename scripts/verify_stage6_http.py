"""Real MySQL/Redis/Mongo/Milvus/models acceptance. Retains labelled demo records."""
import json
import os
from pathlib import Path
import sys
import time
from datetime import datetime, timezone
from uuid import uuid4

import httpx
from sqlalchemy import select, func
from sqlalchemy.orm import Session

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from atguigu.business import models as m
from atguigu.business.database import get_engine
from atguigu.business.faq_cache import client as redis_client, key, consume_outbox
from atguigu.business.seed import seed_id
from scripts.verify_stage5_http import parse_sse

OUT = ROOT / "docs/evidence/stage6"
BASE = os.getenv("STAGE6_API", "http://127.0.0.1:8105")


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    run = uuid4().hex[:8]
    report = {"run": run, "captured_at_utc": datetime.now(timezone.utc).isoformat(), "passed": False,
        "services": "real MySQL Redis MongoDB MinIO Milvus embedding rerank chat", "checks": [],
        "units": [], "sessions": [], "requests": [], "faq_ids": [], "gap_ids": []}
    def save(): (OUT / "http.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    def check(name, **extra):
        report["checks"].append({"name": name, **extra}); save(); print("PASS " + name, flush=True)
    credentials = json.loads((ROOT / "var/setup/stage2-accounts.json").read_text(encoding="utf-8"))
    headers = {}
    c = httpx.Client(base_url=BASE, timeout=300, trust_env=False)
    def req(method, path, who="kb_admin", expected=200, **kwargs):
        r = c.request(method, path, headers=headers[who], **kwargs)
        assert r.status_code == expected, (method, path, r.status_code, r.text[:250])
        return r.json() if r.content else None
    def grants(names): return [{"target_type":"user","target_id":seed_id("user/"+n)} for n in names]
    def ready(unit):
        deadline=time.monotonic()+300
        while time.monotonic()<deadline:
            detail=req("GET","/api/knowledge/units/"+unit["id"])
            version=detail["latest_version"]
            if version["status"]=="ready":
                req("POST",f"/api/knowledge/units/{unit['id']}/versions/{version['id']}/activate")
                req("POST",f"/api/knowledge/units/{unit['id']}/status",json={"status":"published"})
                return version["id"]
            assert version["status"]!="failed",detail
            time.sleep(2)
        raise TimeoutError("Real indexing did not complete")
    def ask(question, who="alice"):
        events=[]
        with c.stream("POST","/api/ai/chat/stream",headers=headers[who],json={"question":question}) as r:
            assert r.status_code==200
            events=list(parse_sse(r.iter_lines()))
        assert events[-1]["event"]=="end",events
        end=events[-1]["data"]
        answer="".join(e["data"].get("text","") for e in events if e["event"]=="delta")
        ss=[e["data"]["sources"] for e in events if e["event"]=="sources"]
        row={"who":who,"question":question,"request_id":end["request_id"],"session_id":end["session_id"],
             "status":end["status"],"cache_status":end["cache_status"],"answer":answer,"sources":ss[-1] if ss else [],"end":end}
        report["requests"].append(row);report["sessions"].append({"id":end["session_id"],"who":who});save()
        return row
    def mine():
        result=req("POST","/api/settlement/mine")
        assert result["mode"]=="semantic",result
        return result
    try:
        assert c.get("/ready").json()["database_revision"]=="0005"
        assert redis_client().ping()
        for name in ("kb_admin","admin","alice","bob","carol"):
            r=c.post("/api/auth/login",json={"username":name,"password":credentials[name]});r.raise_for_status()
            headers[name]={"Authorization":"Bearer "+r.json()["access_token"]}
        check("0005 ready, existing accounts and real Redis")
        project="青梧"+run+"交接"
        question=f"{project}需要提前几天申请、由谁复核，专用确认码是什么？"
        marker="QW-"+run
        report.update(question=question,marker=marker)
        files=[("申请流程.md",f"# {project}申请流程（交付演示）\n\n{project}需要提前四个工作日申请，由青梧资料组复核。申请人提交清单和归档链接，青梧资料组检查齐全后批准。专用确认码仅在独立的确认规范中提供。\n"),
               ("确认规范.txt",f"{project}确认规范（交付演示）\n{project}的专用确认码为 {marker}。需要青梧复核组核对确认码后再完成交接。确认码不能由申请流程推断。")]
        batch=req("POST","/api/knowledge/import",expected=202,
            files=[("files",(name,content.encode(),"text/plain")) for name,content in files],data={"idempotency_key":"stage6-"+run})
        report["batch"]=batch;save()
        tasks=batch.get("tasks") or batch.get("items")
        if not tasks:
            detail=req("GET","/api/knowledge/batches/"+batch["id"])
            tasks=detail["tasks"]
        tasks = sorted(tasks, key=lambda task: task.get("file_name", ""))
        ordered_units = {}
        for task in tasks:
            uid=task["unit_id"]
            report["units"].append(uid);save()
            info=req("GET","/api/knowledge/units/"+uid)
            is_public="申请" in info["title"]
            ordered_units["public" if is_public else "private"]=uid
            req("POST",f"/api/knowledge/units/{uid}/permissions",json={"grants":grants(["kb_admin","alice","bob"] if is_public else ["kb_admin","alice"])})
            ready({"id":uid})
        assert len(report["units"])==2
        report["units"]=[ordered_units["public"],ordered_units["private"]];save()
        check("batch Markdown/TXT import, independent private objects, real indexing and publish")
        for _ in range(3):
            result=ask(question)
            assert result["status"]=="completed" and marker in result["answer"],result
            assert {s["unit_id"] for s in result["sources"]}==set(report["units"])
        check("three real model answers with both source documents")
        mining=mine()
        candidates=req("GET","/api/settlement/faqs/recommendations?page_size=100")["items"]
        candidate=next(f for f in candidates if f["question"]==question)
        report["faq_ids"].append(candidate["id"]);save()
        assert candidate["frequency"]==3
        assert mine()["created_faqs"]==0
        published=req("POST",f"/api/settlement/faqs/{candidate['id']}/review",json={"action":"approve","revision":candidate["revision"]})
        assert published["cache_warmed"] and redis_client().get(key(candidate["id"]))
        check("real semantic mining, idempotent frequency, review and Redis publication",mining=mining)
        hit=ask(question);assert hit["status"]=="completed" and hit["cache_status"]=="hit" and marker in hit["answer"]
        with Session(get_engine()) as db:
            log=db.get(m.QAAccessLog,hit["request_id"])
            assert log.total_tokens==0 and log.cache_status=="hit" and db.get(m.FAQ,candidate["id"]).hit_count==1
        partial=ask(question,"bob");assert partial["cache_status"]!="hit" and marker not in partial["answer"]
        check("authorized Redis hit has zero model tokens; partial-source user never gets cached secret")
        req("POST",f"/api/knowledge/units/{report['units'][1]}/permissions",json={"grants":grants(["kb_admin"])})
        denied=ask(question);assert denied["cache_status"]!="hit" and marker not in denied["answer"]
        history=req("GET",f"/api/ai/chat/sessions/{hit['session_id']}/messages","alice")
        assert history["items"][0]["assistant"]["redacted"]
        with Session(get_engine()) as db:count=consume_outbox(db,1000)
        assert redis_client().get(key(candidate["id"])) is None
        req("POST",f"/api/knowledge/units/{report['units'][1]}/permissions",json={"grants":grants(["kb_admin","alice"])})
        check("permission revocation blocks cached answer and history; durable outbox deletes Redis key",processed_events=count)
        assert ask(question)["cache_status"]=="hit"
        req("POST",f"/api/settlement/faqs/{candidate['id']}/withdraw",json={"revision":published["revision"]})
        withdrawn=ask(question);assert withdrawn["cache_status"]!="hit"
        check("FAQ withdrawal bypasses cache on next real question")
        # Re-review edited standard answer, then change the underlying active version.
        latest=req("GET","/api/settlement/faqs?status=withdrawn&page_size=100")["items"]
        row=next(f for f in latest if f["id"]==candidate["id"])
        edited=req("PUT",f"/api/settlement/faqs/{row['id']}",json={"revision":row["revision"],"answer":published["answer"]})
        req("POST",f"/api/settlement/faqs/{row['id']}/review",json={"revision":edited["revision"],"action":"approve"})
        uid=report["units"][1]
        detail=req("GET","/api/knowledge/units/"+uid)
        updated=req("PUT","/api/knowledge/units/"+uid,json={"title":detail["title"],"content":detail["content"]+"\n版本更新：复核后记录操作日期。"})
        ready(updated)
        changed=ask(question);assert changed["cache_status"]!="hit" and changed["status"]=="completed"
        check("active source version change prevents old FAQ cache use")
        # Truly absent domain, followed by real knowledge completion and the original question.
        gap_question=f"银桦{run}月面标本的冷链封签温度是多少？"
        absent=ask(gap_question,"kb_admin");assert absent["status"] in {"no_match","low_confidence"},absent
        mine()
        gap=next(g for g in req("GET","/api/settlement/knowledge-gaps?page_size=100")["items"] if g["question_pattern"]==gap_question)
        report["gap_ids"].append(gap["id"]);save()
        req("POST",f"/api/settlement/knowledge-gaps/{gap['id']}/status",expected=422,json={"status":"resolved"})
        draft=req("POST",f"/api/settlement/knowledge-gaps/{gap['id']}/draft",expected=201,json={
            "title":f"银桦{run}月面标本封签规范（交付演示）",
            "content":f"# 银桦{run}月面标本封签规范\n\n银桦{run}月面标本的冷链封签温度必须保持在零下十八摄氏度，也就是 -18°C。封签前检查冷柜记录，由样品管理员登记并签名。这是演示用虚构操作规范。",
            "grants":grants(["kb_admin","alice"])})
        report["units"].append(draft["unit"]["id"]);save();ready(draft["unit"])
        verified=ask(gap_question,"kb_admin");assert verified["status"]=="completed" and draft["unit"]["id"] in {s["unit_id"] for s in verified["sources"]}
        resolved=req("POST",f"/api/settlement/knowledge-gaps/{gap['id']}/status",json={"status":"resolved","request_id":verified["request_id"]})
        assert resolved["status"]=="resolved"
        check("real no-match mining, linked draft, real index/publication, original-question answer and verified resolution")
        overview=req("GET","/api/dashboard/overview","admin")
        lower=datetime.fromisoformat(overview["range"]["utc_start"].replace("Z","+00:00")).replace(tzinfo=None)
        upper=datetime.fromisoformat(overview["range"]["utc_end_exclusive"].replace("Z","+00:00")).replace(tzinfo=None)
        with Session(get_engine()) as db:
            logs=db.scalars(select(m.QAAccessLog).where(m.QAAccessLog.created_at>=lower,m.QAAccessLog.created_at<upper)).all()
            assert overview["metrics"]["visits"]==len(logs)
            assert overview["metrics"]["unique_users"]==len({l.user_id for l in logs})
            assert overview["metrics"]["total_tokens"]==sum(l.total_tokens or 0 for l in logs if l.status!="processing")
            assert sum(p["visits"] for p in overview["trends"])==len(logs)
        assert c.get("/api/dashboard/overview").status_code==401
        req("GET","/api/dashboard/overview","alice",expected=403)
        check("dashboard recomputed from real logs, timezone range, counts/tokens/UV reconcile and RBAC")
        # Leave a useful, current published FAQ for the delivered demo.
        for _ in range(2):assert ask(question)["status"]=="completed"
        mine()
        current=next(f for f in req("GET","/api/settlement/faqs/recommendations?page_size=100")["items"] if f["question"]==question)
        report["faq_ids"].append(current["id"])
        req("POST",f"/api/settlement/faqs/{current['id']}/review",json={"action":"approve","revision":current["revision"]})
        assert ask(question)["cache_status"]=="hit"
        report["current_faq_id"]=current["id"]
        report["passed"]=True
        check("retained labelled demo has current published FAQ and verified resolved gap")
    finally:
        save();c.close()
    print(json.dumps({"passed":report["passed"],"checks":len(report["checks"]),"run":run},ensure_ascii=False))


if __name__=="__main__":main()
