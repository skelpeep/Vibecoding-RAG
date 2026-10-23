"""Redis acceleration with current MySQL provenance as the security authority."""
import asyncio
from hashlib import sha256
import json

import redis
from sqlalchemy import select, update

from atguigu.business import models as m
from atguigu.business.authorization import authorized_units
from atguigu.config.config import BusinessConfig, SettlementConfig


def client():
    return redis.Redis.from_url(BusinessConfig.redis_url, socket_connect_timeout=1, socket_timeout=1,
                                decode_responses=True)


def key(faq_id):
    return SettlementConfig.cache_prefix + faq_id


def sources(db, faq, principal):
    """Every answer dependency must still be published, current, and authorized."""
    from atguigu.business.chat_service import valid_sources
    values = faq.provenance_json.get("sources", [])
    links = set(db.execute(select(m.FAQSource.unit_id, m.FAQSource.version_id).where(m.FAQSource.faq_id == faq.id)).all())
    if not values or links != {(s.get("unit_id"), s.get("version_id")) for s in values}:
        return []
    return values if valid_sources(db, principal, values) else []


def valid_faq(db, principal, faq_id, revision):
    faq = db.get(m.FAQ, faq_id, populate_existing=True)
    return bool(faq and faq.status == "published" and faq.revision == revision and sources(db, faq, principal))


def signature(db, faq):
    values = []
    for source in faq.provenance_json.get("sources", []):
        unit = db.get(m.KnowledgeUnit, source["unit_id"], populate_existing=True)
        grants = sorted(db.execute(select(m.UnitPermission.target_type, m.UnitPermission.target_id)
                                   .where(m.UnitPermission.unit_id == source["unit_id"])).all())
        values.append([source, unit.status if unit else None, unit.active_version_id if unit else None,
                       str(unit.updated_at) if unit else None, unit.permission_revision if unit else None, [list(g) for g in grants]])
    return sha256(json.dumps([faq.revision, faq.status, faq.answer, values], sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def publish_cache(db, faq):
    payload = {"signature": signature(db, faq), "answer": faq.answer, "revision": faq.revision}
    try:
        client().setex(key(faq.id), SettlementConfig.cache_ttl, json.dumps(payload, ensure_ascii=False))
        return True
    except (redis.RedisError, ValueError):
        return False


def invalidate(faq_id):
    try:
        client().delete(key(faq_id))
        return True
    except redis.RedisError:
        return False


def lookup(factory, user_id, token_version, question):
    from atguigu.business.chat_service import fresh_principal
    from atguigu.business.settlement_service import normalize_question
    normalized = normalize_question(question)
    with factory() as db:
        principal = fresh_principal(db, user_id, token_version)
        # Only exact normalized questions are eligible for direct cache answers.
        # Semantic clustering creates review candidates, never unreviewed paraphrase answers.
        faqs = db.scalars(select(m.FAQ).where(m.FAQ.status == "published").order_by(m.FAQ.id)).all()
        for faq in faqs:
            if normalized != normalize_question(faq.question):
                continue
            dependencies = sources(db, faq, principal)
            if not dependencies:
                continue
            try:
                raw = client().get(key(faq.id))
                payload = json.loads(raw) if raw else None
                if not isinstance(payload, dict):
                    payload = None
                if not payload or payload.get("signature") != signature(db, faq) or payload.get("answer") != faq.answer:
                    publish_cache(db, faq)
                    raw = client().get(key(faq.id))
                    payload = json.loads(raw) if raw else None
                    if not isinstance(payload, dict):
                        payload = None
                if not payload or payload.get("signature") != signature(db, faq) or payload.get("answer") != faq.answer:
                    return None, "unavailable"
            except (redis.RedisError, ValueError, TypeError):
                return None, "unavailable"
            return {"faq_id": faq.id, "revision": faq.revision, "answer": payload["answer"],
                    "sources": dependencies}, "hit"
    return None, "miss"


def consume_outbox(db, limit=200):
    processed = 0
    rows = db.scalars(select(m.OutboxEvent).where(m.OutboxEvent.processed_at.is_(None))
        .order_by(m.OutboxEvent.created_at, m.OutboxEvent.id).limit(limit).with_for_update(skip_locked=True)).all()
    for row in rows:
        ids = [row.aggregate_id] if row.event_type.startswith("faq.") else list(db.scalars(
            select(m.FAQSource.faq_id).where(m.FAQSource.unit_id == row.aggregate_id)))
        if not all(invalidate(faq_id) for faq_id in set(ids)):
            break
        row.processed_at = m.utcnow()
        processed += 1
    db.commit()
    return processed


class CachedPipeline:
    def __init__(self, factory, fallback):
        self.factory, self.fallback = factory, fallback
        self.result = None
        self.cache_status = "miss"

    def snapshot(self):
        if self.result:
            return {"metrics": self.result.metrics, "usage": self.result.usage}
        data = self.fallback.snapshot()
        return {**data, "metrics": {**data.get("metrics", {}), "cache_status": self.cache_status}}

    async def run(self, **kwargs):
        from atguigu.business.rag import RagResult
        # Contextual follow-up questions must retain normal multi-turn retrieval.
        history = await kwargs["history_loader"]()
        cached = None
        if not history:
            cached, self.cache_status = await asyncio.to_thread(lookup, self.factory,
                kwargs["user_id"], kwargs["token_version"], kwargs["question"])
        if not cached:
            self.result = await self.fallback.run(**kwargs)
            self.result.metrics["cache_status"] = self.cache_status
            self.result.metrics["degradations"] = self.result.degradations
            return self.result
        deps = cached["sources"]
        ids = sorted({s["unit_id"] for s in deps})
        self.result = RagResult(answer=cached["answer"], status="completed", sources=deps,
            metrics={"cache_status": "hit", "faq_id": cached["faq_id"], "faq_revision": cached["revision"],
                     "authorization_dependencies": deps, "recalled_unit_ids": ids, "authorized_unit_ids": ids},
            usage={"cache": {"known": True, "prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}})
        def check():
            from atguigu.business.chat_service import fresh_principal
            from fastapi import HTTPException
            with self.factory() as db:
                principal = fresh_principal(db, kwargs["user_id"], kwargs["token_version"])
                if not valid_faq(db, principal, cached["faq_id"], cached["revision"]):
                    raise HTTPException(403, "FAQ 或知识授权已变化")
        await asyncio.to_thread(check)
        await kwargs["on_progress"]({"stage": "cache", "status": "hit", "message": "已命中审核发布的 FAQ"})
        await kwargs["on_sources"](deps)
        for offset in range(0, len(cached["answer"]), 80):
            await asyncio.to_thread(check)
            await kwargs["on_delta"](cached["answer"][offset:offset+80])
        return self.result
