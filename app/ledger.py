"""账本查询。数字只加总模型已经标好的交易。"""
from datetime import datetime, timedelta

from sqlalchemy.orm import Session, joinedload

from .models import Report, Transaction
from .totals import compute_totals, explain


def _within(query, start: str, end: str):
    if start:
        query = query.filter(Transaction.occurred_at >= datetime.fromisoformat(start))
    if end:
        query = query.filter(Transaction.occurred_at < datetime.fromisoformat(end) + timedelta(days=1))
    return query


def transaction_query(db: Session, start: str, end: str, bucket: str, category: str, q: str):
    query = _within(db.query(Transaction), start, end)
    if bucket == "expense":
        query = query.filter(Transaction.included.is_(True), Transaction.direction == "expense")
    elif bucket == "income":
        query = query.filter(Transaction.included.is_(True), Transaction.direction == "income")
    elif bucket == "refund":
        query = query.filter(Transaction.included.is_(True), Transaction.direction == "refund")
    elif bucket == "transfer":
        query = query.filter(Transaction.included.is_(True), Transaction.direction == "transfer")
    elif bucket == "excluded":
        query = query.filter(Transaction.included.is_(False))
    elif bucket != "all":
        query = query.filter(Transaction.included.is_(True))
    if category:
        query = query.filter(Transaction.category == category)
    if q:
        like = f"%{q.replace('%', '').replace('_', '')}%"
        query = query.filter(
            Transaction.title.like(like)
            | Transaction.counterparty.like(like)
            | Transaction.category.like(like)
            | Transaction.note.like(like)
            | Transaction.pay_method.like(like)
        )
    return query


def overview(db: Session, start: str, end: str) -> dict:
    rows = _within(db.query(Transaction), start, end).all()
    totals = compute_totals([
        {"included": row.included, "direction": row.direction, "amount_cents": row.amount_cents}
        for row in rows
    ])
    categories: dict[str, dict] = {}
    daily: dict[str, dict] = {}
    top = []
    for row in rows:
        if not row.included or row.direction != "expense":
            continue
        bucket = categories.setdefault(row.category, {"category": row.category, "cents": 0, "count": 0})
        bucket["cents"] += row.amount_cents
        bucket["count"] += 1
        day = row.occurred_at.date().isoformat()
        slot = daily.setdefault(day, {"date": day, "expense_cents": 0, "refund_cents": 0, "income_cents": 0})
        slot["expense_cents"] += row.amount_cents
        top.append(row)
    for row in rows:
        if not row.included or row.direction not in {"refund", "income"}:
            continue
        day = row.occurred_at.date().isoformat()
        slot = daily.setdefault(day, {"date": day, "expense_cents": 0, "refund_cents": 0, "income_cents": 0})
        if row.direction == "refund":
            slot["refund_cents"] += row.amount_cents
        else:
            slot["income_cents"] += row.amount_cents
    top.sort(key=lambda row: row.amount_cents, reverse=True)
    report = (
        db.query(Report)
        .filter(Report.start_on == (start or ""), Report.end_on == (end or ""))
        .order_by(Report.id.desc())
        .first()
    )
    if report is None and not start and not end:
        report = db.query(Report).order_by(Report.id.desc()).first()
    return {
        **totals,
        "start": start,
        "end": end,
        "explain": explain(totals),
        "categories": sorted(categories.values(), key=lambda item: item["cents"], reverse=True),
        "daily": [daily[key] for key in sorted(daily)],
        "top": [_public_txn(row) for row in top[:8]],
        "summary": None if report is None else {
            "id": report.id,
            "content": report.content,
            "created_at": report.created_at.isoformat(timespec="minutes"),
        },
    }


def _public_txn(row: Transaction) -> dict:
    return {
        "id": row.id,
        "occurred_at": row.occurred_at.strftime("%Y-%m-%dT%H:%M:%S"),
        "direction": row.direction,
        "amount_cents": row.amount_cents,
        "category": row.category,
        "title": row.title,
        "counterparty": row.counterparty,
        "description": row.description,
        "pay_method": row.pay_method,
        "member_id": row.member_id,
        "member_name": row.member.name if row.member else "",
        "note": row.note,
        "included": row.included,
        "batch_id": row.batch_id,
        "filename": row.batch.filename if row.batch else "",
    }


def public_transactions(rows: list[Transaction]) -> list[dict]:
    return [_public_txn(row) for row in rows]


def load_transactions(query):
    return query.options(joinedload(Transaction.member), joinedload(Transaction.batch)).order_by(
        Transaction.occurred_at.desc(), Transaction.id.desc())
