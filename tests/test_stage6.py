"""Deterministic security/statistics checks; fake Redis/embedding are explicit here."""
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest
import redis
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from test_stage5_chat import ctx, chat, source, make_completed
from atguigu.business import models as m, faq_cache as cache, settlement_service as service
from atguigu.business.dashboard_api import aggregate
from atguigu.business.security import load_principal
from atguigu.config.config import SettlementConfig


class FakeRedis:
    def __init__(self):
        self.values = {}
    def setex(self, key, ttl, value): self.values[key] = value
    def get(self, key): return self.values.get(key)
    def delete(self, key): self.values.pop(key, None)


@pytest.fixture
def redis_store(monkeypatch):
    store = FakeRedis()
    monkeypatch.setattr(cache, "client", lambda: store)
    return store


def log(ctx, question="归档怎么做？", deps=None, status="completed", user="kb", when=None, tokens=10, usage="complete"):
    session = m.ChatSession(owner_id=ctx.users[user].id)
    ctx.db.add(session)
    ctx.db.flush()
    row = m.QAAccessLog(session_id=session.id, user_id=ctx.users[user].id, question=question,
        answer="归档完成后登记编号。" if status == "completed" else None, status=status,
        cited_sources_json=deps or [], total_tokens=tokens, response_time_ms=1000,
        details_json={"authorization_dependencies": deps or [], "history_persisted": True, "usage_completeness": usage},
        created_at=when or m.utcnow())
    ctx.db.add(row)
    ctx.db.commit()
    return row


def faq(ctx, deps, status="published"):
    row = m.FAQ(question="归档怎么做？", answer="归档完成后登记编号。", status=status,
                provenance_json={"sources": deps})
    ctx.db.add(row)
    ctx.db.flush()
    ctx.db.add_all(m.FAQSource(faq_id=row.id,unit_id=uid,version_id=vid)
                  for uid,vid in service.source_key(deps))
    ctx.db.commit()
    return row


def factory(ctx): return lambda: Session(ctx.engine, expire_on_commit=False)


def test_cache_normalization_preserves_semantic_operators():
    assert service.normalize_question("温度 -18.5 度？") != service.normalize_question("温度 18.5 度？")
    assert service.normalize_question("温度 18.5 度？") != service.normalize_question("温度 185 度？")
    assert service.normalize_question("Ａ 如何 归档？") == service.normalize_question("a如何归档?")


def test_dashboard_timezone_reconciles_failures_unknown_and_week(ctx):
    deps = [source(ctx, ctx.unit([("global", "*")]))]
    log(ctx,deps=deps,when=datetime(2026,10,21,15,59,59))
    log(ctx,deps=deps,when=datetime(2026,10,21,16),tokens=11)
    log(ctx,status="error",when=datetime(2026,10,22,15,59,59),tokens=None,usage="unknown")
    log(ctx,status="cancelled",when=datetime(2026,10,22,16),tokens=3)
    principal=load_principal(ctx.db,ctx.users["admin"])
    data=aggregate(ctx.db,principal,datetime(2026,10,22).date(),datetime(2026,10,22).date())
    assert data["metrics"]["visits"]==2 and data["metrics"]["total_tokens"]==11
    assert data["metrics"]["unknown_usage"]==1 and data["metrics"]["failed"]==1
    assert sum(p["visits"] for p in data["trends"])==2
    assert sum(b["count"] for b in data["latency"])==2
    assert data["questions"][0]["count"]==1
    week=aggregate(ctx.db,principal,datetime(2026,10,21).date(),datetime(2026,10,22).date(),bucket="week")
    assert len(week["trends"])==1 and week["trends"][0]["visits"]==3


def test_dashboard_rbac_private_rankings_and_bad_dates(ctx):
    deps=[source(ctx,ctx.unit([("user",ctx.users["kb"].id)]))]
    log(ctx,question="敏感问题",deps=deps)
    assert ctx.call("GET","/api/dashboard/overview").status_code==403
    data=ctx.call("GET","/api/dashboard/overview","admin").json()
    assert data["metrics"]["visits"]==1 and data["questions"]==[] and data["units"]==[]
    for query in ("timezone=Bad/Zone","start=2026-10-23&end=2026-10-22","start=2020-01-01&end=2026-01-01"):
        assert ctx.call("GET","/api/dashboard/overview?"+query,"admin").status_code==422


def test_semantic_mining_idempotent_source_boundaries_and_gaps(ctx,monkeypatch):
    monkeypatch.setattr(SettlementConfig,"min_frequency",3)
    deps=[source(ctx,ctx.unit([("global","*")]))]
    for q in ("如何归档资料？","资料怎样归档？","资料归档的步骤是什么？"):
        log(ctx,question=q,deps=deps)
    log(ctx,question="找不到月球发票",status="no_match")
    denied=log(ctx,question="秘密",status="low_confidence")
    denied.unauthorized_unit_ids_json=[deps[0]["unit_id"]];ctx.db.commit()
    principal=load_principal(ctx.db,ctx.users["kb"])
    embed=lambda texts:[[1,0] if "归档" in t else [0,1] for t in texts]
    result=service.mine(ctx.db,principal,embed)
    ctx.db.commit()
    assert result["created_faqs"]==1 and result["created_gaps"]==1 and result["mode"]=="semantic"
    result=service.mine(ctx.db,principal,embed);ctx.db.commit()
    assert result["created_faqs"]==result["created_gaps"]==0
    row=ctx.db.scalar(select(m.FAQ));assert row.frequency==3 and row.status=="pending_review"
    assert len(row.provenance_json["sample_questions"])==3
    # Another provenance set cannot count towards this candidate.
    other=[source(ctx,ctx.unit([("global","*")]))]
    log(ctx,question="资料归档的步骤是什么？",deps=other)
    service.mine(ctx.db,principal,embed);ctx.db.commit();ctx.db.refresh(row)
    assert row.frequency==3


def test_mining_never_embeds_unauthorized_or_external_answers(ctx):
    private=[source(ctx,ctx.unit())]
    log(ctx,question="private question",deps=private)
    def fail_if_called(texts): raise AssertionError("Unauthorized text reached model")
    result=service.mine(ctx.db,load_principal(ctx.db,ctx.users["kb"]),fail_if_called)
    assert result["eligible_logs"]==0


def test_mining_explicit_exact_fallback(ctx):
    for _ in range(3):log(ctx,question="无依据问题",status="no_match")
    def unavailable(texts):raise RuntimeError("provider unavailable")
    result=service.mine(ctx.db,load_principal(ctx.db,ctx.users["kb"]),unavailable)
    assert result["mode"]=="exact_fallback" and result["created_gaps"]==1


def test_multisource_cache_permissions_version_withdraw_and_corruption(ctx,redis_store):
    public=ctx.unit([("global","*")]);private=ctx.unit([("user",ctx.users["alice"].id)])
    row=faq(ctx,[source(ctx,public),source(ctx,private)])
    f=factory(ctx)
    def lookup(name):return cache.lookup(f,ctx.users[name].id,ctx.users[name].token_version,row.question)
    value,state=lookup("alice");assert state=="hit" and value["answer"]==row.answer
    assert lookup("bob")== (None,"miss")
    for corrupted in ('{"answer":"injected","signature":"bad"}', '[1]', 'true', '42', '"invalid"'):
        redis_store.values[cache.key(row.id)] = corrupted
        assert lookup("alice")[0]["answer"] == row.answer
    ctx.db.execute(delete(m.UnitPermission).where(m.UnitPermission.unit_id==private.id));ctx.db.commit()
    assert lookup("alice")== (None,"miss")
    ctx.db.add(m.UnitPermission(unit_id=private.id,target_type="global",target_id="*"));ctx.db.commit()
    assert lookup("bob")[1]=="hit"
    row.status="withdrawn";ctx.db.commit();assert lookup("bob")== (None,"miss")
    row.status="published";private.status="disabled";ctx.db.commit();assert lookup("alice")== (None,"miss")


def test_cache_redis_outage_falls_back_and_outbox_retries(ctx,redis_store,monkeypatch):
    row=faq(ctx,[source(ctx,ctx.unit([("global","*")]))])
    class Offline:
        def get(self,*a):raise redis.ConnectionError("secret must not escape")
        def delete(self,*a):raise redis.ConnectionError("offline")
    monkeypatch.setattr(cache,"client",lambda:Offline())
    assert cache.lookup(factory(ctx),ctx.users["alice"].id,1,row.question)==(None,"unavailable")
    ev=m.OutboxEvent(event_type="faq.edit",aggregate_id=row.id);ctx.db.add(ev);ctx.db.commit()
    assert cache.consume_outbox(ctx.db)==0;ctx.db.refresh(ev);assert ev.processed_at is None
    monkeypatch.setattr(cache,"client",lambda:redis_store)
    assert cache.consume_outbox(ctx.db)==1;ctx.db.refresh(ev);assert ev.processed_at


def test_review_edit_reapprove_reject_withdraw_and_revision(ctx,redis_store):
    row=faq(ctx,[source(ctx,ctx.unit([("global","*")]))],"pending_review")
    path=f"/api/settlement/faqs/{row.id}"
    assert ctx.call("POST",path+"/review",json={"action":"approve","revision":1}).status_code==403
    response=ctx.call("POST",path+"/review","kb",json={"action":"approve","revision":1,"edited_answer":"审核后的答案"})
    assert response.status_code==200 and response.json()["cache_warmed"]
    assert ctx.call("PUT",path,"kb",json={"revision":1,"answer":"outdated"}).status_code==409
    response=ctx.call("PUT",path,"kb",json={"revision":2,"answer":"新答案"})
    assert response.json()["status"]=="pending_review"
    response=ctx.call("POST",path+"/review","kb",json={"action":"reject","revision":3})
    assert response.json()["status"]=="rejected"
    assert ctx.call("PUT",path,"kb",json={"revision":4,"answer":"再次修订"}).status_code==200
    assert ctx.call("POST",path+"/review","kb",json={"action":"approve","revision":5}).status_code==200
    assert ctx.call("POST",path+"/withdraw","kb",json={"revision":6}).status_code==200
    assert cache.key(row.id) not in redis_store.values


def test_stale_faq_redacted_and_reviewer_can_withdraw(ctx,redis_store):
    unit=ctx.unit([("global","*")]);row=faq(ctx,[source(ctx,unit)],"pending_review")
    assert ctx.call("POST",f"/api/settlement/faqs/{row.id}/review","kb",json={"action":"approve","revision":1}).status_code==200
    unit.status="disabled";ctx.db.commit()
    data=ctx.call("GET","/api/settlement/faqs","kb").json()["items"][0]
    assert data["answer"] is None and data["sources"]==[] and data["question"]!=row.question
    assert ctx.call("POST",f"/api/settlement/faqs/{row.id}/withdraw","kb",json={"revision":2}).status_code==200


def test_gap_requires_own_current_published_original_answer(ctx):
    unit=ctx.unit([("global","*")]);deps=[source(ctx,unit)]
    gap=m.KnowledgeGap(question_pattern="归档怎么做？",resolved_unit_id=unit.id)
    ctx.db.add(gap);ctx.db.commit()
    path=f"/api/settlement/knowledge-gaps/{gap.id}/status"
    assert ctx.call("POST",path,"kb",json={"status":"resolved"}).status_code==422
    wrong=log(ctx,question="别的问题",deps=deps)
    assert ctx.call("POST",path,"kb",json={"status":"resolved","request_id":wrong.id}).status_code==422
    other=log(ctx,deps=deps,user="alice")
    assert ctx.call("POST",path,"kb",json={"status":"resolved","request_id":other.id}).status_code==422
    good=log(ctx,deps=deps)
    assert ctx.call("POST",path,"kb",json={"status":"resolved","request_id":good.id}).status_code==200
    assert ctx.call("POST",path,"kb",json={"status":"unresolved"}).status_code==200
    unit.status="disabled";ctx.db.commit()
    assert ctx.call("POST",path,"kb",json={"status":"resolved","request_id":good.id}).status_code==422


def test_real_sse_transport_with_fake_redis_cached_answer_no_model(ctx,chat,redis_store,monkeypatch):
    from atguigu.business import chat_api
    row=faq(ctx,[source(ctx,ctx.unit([("global","*")]))])
    class NoModel:
        def snapshot(self):return {}
        async def run(self,**kwargs):raise AssertionError("Cache hit must not call RAG")
    monkeypatch.setattr(chat_api,"get_pipeline",lambda f:cache.CachedPipeline(f,NoModel()))
    response=ctx.call("POST","/api/ai/chat/stream",json={"question":row.question})
    assert response.status_code==200 and '"cache_status": "hit"' in response.text and row.answer in response.text
    ctx.db.expire_all();record=ctx.db.scalar(select(m.QAAccessLog))
    assert record.status=="completed" and record.total_tokens==0 and record.cache_status=="hit"
    ctx.db.refresh(row);assert row.hit_count==1
    row.status="withdrawn";ctx.db.commit()
    history=ctx.call("GET",f"/api/ai/chat/sessions/{record.session_id}/messages").json()
    assert history["items"][0]["assistant"]["redacted"] and not history["items"][0]["assistant"]["content"]
    assert ctx.call("GET",f"/api/ai/chat/requests/{record.id}/citations/{record.cited_sources_json[0]['chunk_id']}").status_code==404
