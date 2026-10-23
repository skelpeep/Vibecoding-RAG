"""Review and gap management; operation grants never bypass source authorization."""
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from atguigu.business import faq_cache, models as m, settlement_service as service
from atguigu.business.api import audit
from atguigu.business.chat_service import valid_sources
from atguigu.business.knowledge_schemas import UnitInput
from atguigu.business.security import Current, Db, Principal, require

router = APIRouter(prefix="/api/settlement", tags=["知识沉淀"])
Read = Annotated[Principal, Depends(require("settlement:faq:read"))]
Review = Annotated[Principal, Depends(require("settlement:faq:review"))]
Publish = Annotated[Principal, Depends(require("settlement:faq:publish"))]
Gaps = Annotated[Principal, Depends(require("settlement:gap:manage"))]


class ReviewBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal["approve", "reject"]
    edited_answer: str | None = Field(None, min_length=1, max_length=50000)
    revision: int = Field(ge=1)


class RevisionBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revision: int = Field(ge=1)


class EditBody(RevisionBody):
    answer: str = Field(min_length=1, max_length=50000)


class GapState(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["unresolved", "ignored", "resolved"]
    request_id: str | None = None


def faq_record(db, principal, faq_id, revision=None):
    row = db.scalar(select(m.FAQ).where(m.FAQ.id == faq_id).with_for_update())
    if not row or not faq_cache.sources(db, row, principal):
        raise HTTPException(404, "FAQ 不存在或其来源当前不可访问")
    if revision is not None and row.revision != revision:
        raise HTTPException(409, "FAQ 已被更新，请刷新后重试")
    return row


def faq_view(db, row, principal):
    sources = faq_cache.sources(db, row, principal)
    return {"id": row.id, "question": row.question, "answer": row.answer if sources else None,
        "status": row.status, "revision": row.revision, "frequency": row.frequency, "hit_count": row.hit_count,
        "category": row.category, "source_type": row.source_type, "sources": sources,
        "source_valid": bool(sources), "updated_at": row.updated_at.isoformat()+"Z",
        "reviewed_at": row.reviewed_at.isoformat()+"Z" if row.reviewed_at else None,
        "cache_state": "eligible" if sources and row.status == "published" else "inactive",
        "mining_mode": row.provenance_json.get("mining_mode")}


def change(db, principal, row, action):
    row.revision += 1
    row.updated_at = m.utcnow()
    db.add(m.OutboxEvent(event_type="faq."+action, aggregate_id=row.id, payload_json={"revision": row.revision}))
    audit(db, principal, "settlement:faq:"+action, row.id, revision=row.revision)
    db.commit()
    faq_cache.invalidate(row.id)


@router.post("/mine")
def mine(db: Db, principal: Review):
    # Separate permission for gap data as this operation processes both queues.
    if "settlement:gap:manage" not in principal.permissions:
        raise HTTPException(403, "缺少知识缺口管理权限")
    result = service.mine(db, principal)
    audit(db, principal, "settlement:mine", principal.user.id, **result)
    return result


@router.get("/faqs/recommendations")
def recommendations(db: Db, principal: Read, response: Response, page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100)):
    return list_faqs(db, principal, response, "pending_review", page, page_size)


@router.get("/faqs")
def list_faqs(db: Db, principal: Read, response: Response,
              status: Literal["pending_review", "published", "rejected", "withdrawn"] = "published",
              page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100)):
    response.headers["Cache-Control"] = "no-store"
    rows = db.scalars(select(m.FAQ).where(m.FAQ.status == status).order_by(m.FAQ.frequency.desc(), m.FAQ.id)).all()
    # Stale entries remain manageable by their reviewer, with answer and question redacted.
    visible = [r for r in rows if faq_cache.sources(db, r, principal) or r.reviewer_id == principal.user.id]
    items = []
    for row in visible[(page-1)*page_size:page*page_size]:
        value = faq_view(db, row, principal)
        if not value["source_valid"]:
            value["question"] = "来源已变化，需重新审核"
        items.append(value)
    return {"items": items, "total": len(visible), "page": page, "page_size": page_size}


@router.post("/faqs/{faq_id}/review")
def review(faq_id: str, body: ReviewBody, db: Db, principal: Review):
    row = faq_record(db, principal, faq_id, body.revision)
    if row.status != "pending_review":
        raise HTTPException(409, "只有待审核 FAQ 可以审核")
    if body.action == "approve" and "settlement:faq:publish" not in principal.permissions:
        raise HTTPException(403, "缺少 FAQ 发布权限")
    if body.edited_answer is not None:
        if not body.edited_answer.strip():
            raise HTTPException(422, "答案不能为空")
        row.answer = body.edited_answer.strip()
    row.status = "published" if body.action == "approve" else "rejected"
    row.reviewer_id, row.reviewed_at = principal.user.id, m.utcnow()
    change(db, principal, row, body.action)
    warmed = faq_cache.publish_cache(db, row) if row.status == "published" else False
    return {**faq_view(db, row, principal), "cache_warmed": warmed}


@router.post("/faqs/{faq_id}/withdraw")
def withdraw(faq_id: str, body: RevisionBody, db: Db, principal: Publish):
    row = db.scalar(select(m.FAQ).where(m.FAQ.id == faq_id).with_for_update())
    if not row or (row.reviewer_id != principal.user.id and not faq_cache.sources(db, row, principal)):
        raise HTTPException(404, "FAQ 不存在或不可访问")
    if row.revision != body.revision or row.status != "published":
        raise HTTPException(409, "FAQ 状态已变化，请刷新")
    row.status = "withdrawn"
    change(db, principal, row, "withdraw")
    return {"id": row.id, "status": row.status, "revision": row.revision}


@router.put("/faqs/{faq_id}")
def edit(faq_id: str, body: EditBody, db: Db, principal: Review):
    row = faq_record(db, principal, faq_id, body.revision)
    if row.status == "published" and "settlement:faq:publish" not in principal.permissions:
        raise HTTPException(403, "缺少修改已发布 FAQ 的权限")
    if not body.answer.strip():
        raise HTTPException(422, "答案不能为空")
    row.answer, row.status = body.answer.strip(), "pending_review"
    change(db, principal, row, "edit")
    return faq_view(db, row, principal)


def gap_record(db, gap_id):
    row = db.scalar(select(m.KnowledgeGap).where(m.KnowledgeGap.id == gap_id).with_for_update())
    if not row:
        raise HTTPException(404, "知识缺口不存在")
    return row


def gap_view(row):
    return {"id": row.id, "question_pattern": row.question_pattern, "sample_questions": row.sample_questions_json,
        "ask_count": row.ask_count, "status": row.status, "resolved_unit_id": row.resolved_unit_id,
        "last_asked_at": row.last_asked_at.isoformat()+"Z" if row.last_asked_at else None,
        "resolution_request_id": row.resolution_json.get("request_id")}


@router.get("/knowledge-gaps")
def gaps(db: Db, principal: Gaps, response: Response, status: Literal["unresolved", "resolved", "ignored"] = "unresolved",
         page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100)):
    response.headers["Cache-Control"] = "no-store"
    rows = db.scalars(select(m.KnowledgeGap).where(m.KnowledgeGap.status == status)
                      .order_by(m.KnowledgeGap.ask_count.desc(), m.KnowledgeGap.id)).all()
    return {"items": [gap_view(r) for r in rows[(page-1)*page_size:page*page_size]], "total": len(rows), "page": page, "page_size": page_size}


@router.post("/knowledge-gaps/{gap_id}/draft", status_code=201)
def create_draft(gap_id: str, body: UnitInput, db: Db, principal: Gaps):
    if "knowledge:create" not in principal.permissions:
        raise HTTPException(403, "缺少新建知识权限")
    row = gap_record(db, gap_id)
    if row.resolved_unit_id:
        raise HTTPException(409, "该缺口已有补全知识，请继续编辑现有草稿")
    from atguigu.business.knowledge_api import create_unit
    unit = create_unit(body, db, principal)
    row.resolved_unit_id = unit["id"]
    row.status = "unresolved"
    row.resolution_json = {**row.resolution_json, "draft_created_at": m.utcnow().isoformat()+"Z"}
    audit(db, principal, "settlement:gap:draft", row.id, unit_id=unit["id"])
    return {"gap": gap_view(row), "unit": unit}


@router.post("/knowledge-gaps/{gap_id}/status")
def gap_status(gap_id: str, body: GapState, db: Db, principal: Gaps):
    row = gap_record(db, gap_id)
    if body.status == "resolved":
        log = db.get(m.QAAccessLog, body.request_id) if body.request_id else None
        unit = db.get(m.KnowledgeUnit, row.resolved_unit_id) if row.resolved_unit_id else None
        if not log or log.user_id != principal.user.id or log.status != "completed" or not log.details_json.get("history_persisted"):
            raise HTTPException(422, "请先用当前账号验证原问题，并提供成功问答的请求编号")
        if not unit or unit.status != "published" or log.created_at < unit.updated_at:
            raise HTTPException(422, "请发布补全知识后重新验证原问题")
        questions = {service.normalize_question(q) for q in [row.question_pattern, *row.sample_questions_json]}
        if service.normalize_question(log.question) not in questions or not valid_sources(db, principal, service.dependencies(log)):
            raise HTTPException(422, "验证必须回答原缺口问题，且所有来源当前可访问")
        if not any(s.get("unit_id") == unit.id and s.get("version_id") == unit.active_version_id for s in log.cited_sources_json):
            raise HTTPException(422, "验证回答未引用当前补全知识")
        row.resolution_json = {**row.resolution_json, "request_id": log.id, "verified_at": m.utcnow().isoformat()+"Z"}
    row.status = body.status
    audit(db, principal, "settlement:gap:"+body.status, row.id, request_id=body.request_id)
    return gap_view(row)
