"""One UTC range and snapshot for every dashboard metric and ranking."""
from collections import Counter, defaultdict
from datetime import date, datetime, time, timedelta, timezone
from typing import Annotated, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import func, select

from atguigu.business import models as m
from atguigu.business.authorization import authorized_units
from atguigu.business.security import Db, Principal, require

router = APIRouter(prefix="/api/dashboard", tags=["数据看板"])
Read = Annotated[Principal, Depends(require("dashboard:read"))]


def date_range(start, end, timezone_name):
    try:
        zone = ZoneInfo(timezone_name)
    except (ZoneInfoNotFoundError, ValueError):
        raise HTTPException(422, "统计时区无效") from None
    end = end or datetime.now(zone).date()
    start = start or end - timedelta(days=6)
    if end < start or (end - start).days > 365:
        raise HTTPException(422, "请选择不超过 366 天的有效日期范围")
    def utc(day):
        return datetime.combine(day, time.min, zone).astimezone(timezone.utc).replace(tzinfo=None)
    return start, end, zone, utc(start), utc(end + timedelta(days=1))


def aggregate(db, principal, start=None, end=None, timezone_name="Asia/Shanghai", bucket="day", limit=5):
    start, end, zone, lower, upper = date_range(start, end, timezone_name)
    rows = db.scalars(select(m.QAAccessLog).where(m.QAAccessLog.created_at >= lower,
        m.QAAccessLog.created_at < upper).order_by(m.QAAccessLog.created_at, m.QAAccessLog.id)).all()
    finished = [r for r in rows if r.status != "processing"]
    counts = Counter(r.status for r in rows)
    known = [r.total_tokens for r in finished if r.total_tokens is not None]
    durations = [r.response_time_ms for r in finished if r.response_time_ms is not None]
    trends = {}
    def key(day):
        return (day - timedelta(days=day.weekday()) if bucket == "week" else day).isoformat()
    for offset in range((end - start).days + 1):
        trends.setdefault(key(start + timedelta(days=offset)), {"visits": 0, "tokens": 0, "unknown_usage": 0, "durations": []})
    questions, units = Counter(), Counter()
    for row in rows:
        point = trends[key(row.created_at.replace(tzinfo=timezone.utc).astimezone(zone).date())]
        point["visits"] += 1
        if row.status != "processing":
            point["tokens"] += row.total_tokens or 0
            point["unknown_usage"] += row.total_tokens is None
            if row.response_time_ms is not None:
                point["durations"].append(row.response_time_ms)
        # Aggregate access does not confer access to question text or source titles.
        if row.status == "completed":
            from atguigu.business.chat_service import valid_sources
            deps = row.details_json.get("authorization_dependencies") or row.cited_sources_json
            if valid_sources(db, principal, deps):
                questions[row.question] += 1
            units.update(set(s.get("unit_id") for s in row.cited_sources_json if s.get("unit_id")))
    allowed = authorized_units(db, principal, set(units))
    unit_ranks = [{"unit_id": uid, "title": db.get(m.KnowledgeUnit, uid).title, "count": n}
                  for uid, n in units.most_common() if uid in allowed][:limit]
    bins = [(0, 1000, "0–1 秒"), (1000, 3000, "1–3 秒"), (3000, 10000, "3–10 秒"),
            (10000, 30000, "10–30 秒"), (30000, None, "30 秒及以上")]
    return {"range": {"start": start.isoformat(), "end": end.isoformat(), "timezone": timezone_name,
            "bucket": bucket, "utc_start": lower.isoformat()+"Z", "utc_end_exclusive": upper.isoformat()+"Z"},
        "metrics": {"visits": len(rows), "unique_users": len({r.user_id for r in rows}),
            "knowledge_units": db.scalar(select(func.count()).select_from(m.KnowledgeUnit).where(m.KnowledgeUnit.status != "deleted")),
            "total_tokens": sum(known) if known else (0 if not finished else None),
            "average_response_ms": round(sum(durations)/len(durations), 1) if durations else None,
            "completed": counts["completed"], "failed": counts["error"], "cancelled": counts["cancelled"],
            "restricted": counts["restricted"], "unanswered": counts["no_match"] + counts["low_confidence"],
            "processing": counts["processing"], "cache_hits": sum(r.cache_status == "hit" for r in finished),
            "unknown_usage": sum(r.total_tokens is None for r in finished),
            "partial_usage": sum(r.details_json.get("usage_completeness") == "partial" for r in finished)},
        "trends": [{"date": day, **{k: v for k, v in p.items() if k != "durations"},
                    "average_response_ms": round(sum(p["durations"])/len(p["durations"]), 1) if p["durations"] else None}
                   for day, p in trends.items()],
        "questions": [{"question": q, "count": n} for q, n in questions.most_common(limit)], "units": unit_ranks,
        "latency": [{"label": label, "min_ms": lo, "max_ms": hi,
                     "count": sum(v >= lo and (hi is None or v < hi) for v in durations)} for lo, hi, label in bins],
        "definitions": {"visits": "已接纳并写入日志的请求，包含失败、受限、取消及处理中请求；登录前拒绝不计入。",
            "tokens": "已知模型用量之和；部分或未知用量单独披露，不等同完整账单。FAQ 命中为 0。",
            "latency": "已结束请求的总响应时间，包含缓存、失败和取消；不包含处理中请求。",
            "rankings": "问题与知识标题仅展示当前拥有全部来源访问权的记录；每轮每篇引用计一次。",
            "knowledge_units": "当前未删除知识总量，包含草稿，不是时间范围内新增量。"}}


@router.get("/overview")
def overview(db: Db, principal: Read, response: Response, start: date | None = None, end: date | None = None,
             timezone: str = "Asia/Shanghai", bucket: Literal["day", "week"] = "day", limit: int = Query(5, ge=1, le=100)):
    response.headers["Cache-Control"] = "no-store"
    return aggregate(db, principal, start, end, timezone, bucket, limit)


@router.get("/metrics")
def metrics(db: Db, principal: Read, start: date | None = None, end: date | None = None, timezone: str = "Asia/Shanghai"):
    result = aggregate(db, principal, start, end, timezone)
    return {**result["metrics"], "range": result["range"], "definitions": result["definitions"]}


@router.get("/rankings/{kind}")
def rankings(kind: Literal["questions", "units"], db: Db, principal: Read, start: date | None = None,
             end: date | None = None, timezone: str = "Asia/Shanghai", limit: int = Query(10, ge=1, le=100)):
    data = aggregate(db, principal, start, end, timezone, limit=limit)
    return {"items": data[kind], "range": data["range"]}


@router.get("/stats/tokens")
def stats(db: Db, principal: Read, start: date | None = None, end: date | None = None,
          timezone: str = "Asia/Shanghai", bucket: Literal["day", "week"] = "day"):
    data = aggregate(db, principal, start, end, timezone, bucket)
    return {"items": data["trends"], "latency": data["latency"], "range": data["range"]}
