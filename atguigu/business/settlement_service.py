"""Idempotent, source-aware semantic mining and auditable settlement operations."""
from collections import defaultdict
from datetime import timedelta
from hashlib import sha256
import math
import re
import unicodedata

from sqlalchemy import select

from atguigu.business import models as m
from atguigu.business.chat_service import valid_sources
from atguigu.config.config import SettlementConfig


def normalize_question(question):
    # Keep signs, decimal points and operators: “-18” and “18” are not the same fact.
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", question).casefold()).rstrip("?？!！。")


def cosine(a, b):
    if not a or len(a) != len(b):
        return 0.0
    norm = math.sqrt(sum(x*x for x in a) * sum(y*y for y in b))
    return sum(x*y for x, y in zip(a, b)) / norm if norm else 0.0


def dependencies(log):
    return log.details_json.get("authorization_dependencies") or log.cited_sources_json


def source_key(values):
    return tuple(sorted({(s["unit_id"], s["version_id"]) for s in values}))


def mine(db, principal, embed=None):
    """Recompute a bounded rolling window; repeated runs never add frequencies twice.

    Source sets form hard cluster boundaries. External-assisted, cache and incomplete
    answers cannot become FAQ evidence. Only currently authorized text is embedded.
    """
    if embed is None:
        from atguigu.tool.embedding_client_tool import get_embeddings
        embed = lambda texts: get_embeddings(texts)["dense"]
    rows = db.scalars(select(m.QAAccessLog).where(
        m.QAAccessLog.created_at >= m.utcnow() - timedelta(days=SettlementConfig.window_days),
        m.QAAccessLog.status.in_(["completed", "no_match", "low_confidence"]))
        .order_by(m.QAAccessLog.created_at.desc(), m.QAAccessLog.id).limit(SettlementConfig.max_logs + 1)).all()
    truncated = len(rows) > SettlementConfig.max_logs
    rows = list(reversed(rows[:SettlementConfig.max_logs]))
    eligible = []
    for row in rows:
        if row.status in {"no_match", "low_confidence"}:
            if not row.unauthorized_unit_ids_json and not row.details_json.get("metrics", {}).get("degradations"):
                eligible.append(("gap", (), row))
        elif row.answer and row.cache_status != "hit" and row.details_json.get("history_persisted"):
            if not row.details_json.get("metrics", {}).get("external_sources") and valid_sources(db, principal, dependencies(row)):
                eligible.append(("faq", source_key(dependencies(row)), row))
    unique = list(dict.fromkeys(row.question for _, _, row in eligible))
    vectors, mode = {}, "semantic"
    try:
        for offset in range(0, len(unique), 16):
            batch = unique[offset:offset+16]
            result = embed(batch)
            if len(result) != len(batch) or any(not v or not all(math.isfinite(x) for x in v) for v in result):
                raise ValueError("Invalid mining embeddings")
            vectors.update(zip(batch, result))
    except Exception:
        vectors, mode = {}, "exact_fallback"
    from atguigu.business.security import load_principal
    from fastapi import HTTPException
    db.expire_all()
    user = db.get(m.User, principal.user.id, populate_existing=True)
    if not user or user.status != "active":
        raise HTTPException(403, "挖掘期间账号权限已变化")
    principal = load_principal(db, user)
    if not {"settlement:faq:review", "settlement:gap:manage"}.issubset(principal.permissions):
        raise HTTPException(403, "挖掘期间操作权限已变化")
    groups = []
    for kind, provenance, row in eligible:
        normalized = normalize_question(row.question)
        if not normalized:
            continue
        group = next((g for g in groups if g["kind"] == kind and g["provenance"] == provenance
            and (normalized in g["normalized"] or cosine(vectors.get(row.question), vectors.get(g["question"])) >= SettlementConfig.similarity)), None)
        if group is None:
            group = {"kind": kind, "provenance": provenance, "question": row.question, "normalized": set(), "rows": []}
            groups.append(group)
        group["normalized"].add(normalized)
        group["rows"].append(row)
    existing_faqs = db.scalars(select(m.FAQ)).all()
    existing_gaps = db.scalars(select(m.KnowledgeGap)).all()
    created_faqs = created_gaps = 0
    for group in groups:
        logs = group["rows"]
        if group["kind"] == "faq":
            if len(logs) < SettlementConfig.min_frequency:
                continue
            latest = logs[-1]
            # Recheck after the potentially slow model boundary.
            db.flush()
            db.expire_all()
            from atguigu.business.security import load_principal
            user = db.get(m.User, principal.user.id, populate_existing=True)
            if not user or user.status != "active":
                continue
            principal = load_principal(db, user)
            if "settlement:faq:review" not in principal.permissions:
                continue
            if not all(valid_sources(db, principal, dependencies(log)) for log in logs):
                continue
            row = next((f for f in existing_faqs if source_key(f.provenance_json.get("sources", [])) == group["provenance"]
                and (set(f.provenance_json.get("normalized_questions", [])) | {normalize_question(f.question)}) & group["normalized"]), None)
            if row is None:
                fingerprint = sha256(repr((normalize_question(group["question"]), group["provenance"])).encode()).hexdigest()
                row = m.FAQ(question=group["question"], answer=latest.answer, source_type="auto_mined",
                    fingerprint=fingerprint, related_unit_id=group["provenance"][0][0],
                    provenance_json={"sources": dependencies(latest), "request_id": latest.id})
                db.add(row)
                db.flush()
                db.add_all(m.FAQSource(faq_id=row.id, unit_id=uid, version_id=vid) for uid, vid in group["provenance"])
                existing_faqs.append(row)
                created_faqs += 1
            row.frequency = len(logs)
            row.provenance_json = {**row.provenance_json, "normalized_questions": sorted(group["normalized"]),
                "sample_questions": list(dict.fromkeys(log.question for log in logs))[:10],
                "mining_mode": mode, "window_days": SettlementConfig.window_days, "mined_at": m.utcnow().isoformat()+"Z"}
        else:
            row = next((g for g in existing_gaps if normalize_question(g.question_pattern) in group["normalized"]
                or set(g.resolution_json.get("normalized_questions", [])) & group["normalized"]), None)
            if row is None:
                row = m.KnowledgeGap(question_pattern=group["question"],
                    fingerprint=sha256(normalize_question(group["question"]).encode()).hexdigest())
                db.add(row)
                db.flush()
                existing_gaps.append(row)
                created_gaps += 1
            row.ask_count = len(logs)
            row.last_asked_at = max(log.created_at for log in logs)
            row.sample_questions_json = list(dict.fromkeys(log.question for log in logs))[:10]
            row.resolution_json = {**row.resolution_json, "normalized_questions": sorted(group["normalized"]), "mining_mode": mode}
    db.flush()
    return {"created_faqs": created_faqs, "created_gaps": created_gaps, "scanned_logs": len(rows),
            "eligible_logs": len(eligible), "mode": mode, "truncated": truncated,
            "window_days": SettlementConfig.window_days, "min_frequency": SettlementConfig.min_frequency,
            "similarity": SettlementConfig.similarity}
