"""家庭账本的接口。账单内容只在导入时发给已配置的模型。"""
import csv
import io
from datetime import datetime

from fastapi import APIRouter, Body, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import Response
from sqlalchemy.orm import Session

from . import ledger
from .analyze import DIRECTIONS, summarize_ledger
from .database import get_db
from .importer import reanalyze, start_import
from .ingest import UserError
from .models import ImportBatch, Member, Report, Transaction
from .settings_store import llm_settings, public_settings, update_settings
from .textutil import public_error, yuan
from .version import VERSION

router = APIRouter()


def _batch(row: ImportBatch) -> dict:
    return {
        "id": row.id,
        "filename": row.filename,
        "source": row.source,
        "status": row.status,
        "progress": row.progress,
        "message": row.message,
        "error": row.error,
        "summary": row.summary,
        "added": row.added,
        "skipped": row.skipped,
        "duplicate": row.duplicate,
        "account_name": row.account_name,
        "period_start": row.period_start,
        "period_end": row.period_end,
        "created_at": row.created_at.isoformat(timespec="minutes"),
    }


def _member(row: Member) -> dict:
    return {"id": row.id, "name": row.name, "note": row.note}


@router.get("/api/meta")
def meta(db: Session = Depends(get_db)):
    moments = [row[0] for row in db.query(Transaction.occurred_at).all()]
    months = sorted({item.strftime("%Y-%m") for item in moments})
    span = None
    if moments:
        days = [item.date() for item in moments]
        span = {"start": min(days).isoformat(), "end": max(days).isoformat()}
    latest = (
        db.query(ImportBatch).filter(ImportBatch.status == "done").order_by(ImportBatch.id.desc()).first()
    )
    categories = sorted({row[0] for row in db.query(Transaction.category).distinct() if row[0]})
    settings = public_settings(db)
    return {
        "version": VERSION,
        "household_name": settings["household_name"],
        "months": months,
        "span": span,
        "categories": categories,
        "directions": ["expense", "income", "refund", "transfer", "ignore"],
        "latest_batch": None if latest is None else _batch(latest),
    }


@router.get("/api/settings")
def read_settings(db: Session = Depends(get_db)):
    return public_settings(db)


@router.put("/api/settings")
def write_settings(body: dict = Body(...), db: Session = Depends(get_db)):
    update_settings(db, body if isinstance(body, dict) else {})
    return public_settings(db)


@router.post("/api/settings/test")
def test_settings(body: dict | None = Body(default=None), db: Session = Depends(get_db)):
    from .llm import LLMSettings, complete
    current = llm_settings(db)
    patch = body or {}
    settings = LLMSettings(
        base_url=str(patch.get("base_url") or current.base_url),
        api_key=str(patch.get("api_key") or current.api_key),
        model=str(patch.get("model") or current.model),
    )
    if not settings.ready():
        raise HTTPException(400, "请把接口地址、密钥和模型名填完整")
    try:
        reply = complete(settings, [{"role": "user", "content": "只回复两个字：已连通"}], timeout=45)
    except Exception as exc:
        raise HTTPException(502, "没有连上模型：" + public_error(exc)) from exc
    return {"ok": True, "reply": (reply or "").strip()[:80]}


@router.get("/api/members")
def list_members(db: Session = Depends(get_db)):
    return [_member(row) for row in db.query(Member).order_by(Member.id).all()]


@router.post("/api/members")
def create_member(body: dict = Body(...), db: Session = Depends(get_db)):
    name = str(body.get("name") or "").strip()
    if not name or len(name) > 32:
        raise HTTPException(400, "请填写家人的名字")
    if db.query(Member).filter(Member.name == name).first():
        raise HTTPException(400, "已经有这个名字了")
    row = Member(name=name, note=str(body.get("note") or "").strip()[:80])
    db.add(row)
    db.commit()
    db.refresh(row)
    return _member(row)


@router.patch("/api/members/{member_id}")
def patch_member(member_id: int, body: dict = Body(...), db: Session = Depends(get_db)):
    row = db.get(Member, member_id)
    if row is None:
        raise HTTPException(404, "找不到这个家人")
    if "name" in body:
        name = str(body.get("name") or "").strip()
        if not name:
            raise HTTPException(400, "名字不能为空")
        row.name = name[:32]
    if "note" in body:
        row.note = str(body.get("note") or "").strip()[:80]
    db.commit()
    return _member(row)


@router.delete("/api/members/{member_id}")
def delete_member(member_id: int, db: Session = Depends(get_db)):
    row = db.get(Member, member_id)
    if row is None:
        raise HTTPException(404, "找不到这个家人")
    db.delete(row)
    db.commit()
    return {"ok": True}


@router.post("/api/imports")
async def upload_bill(file: UploadFile = File(...)):
    raw = await file.read()
    if not raw:
        raise HTTPException(400, "文件是空的")
    if len(raw) > 20 * 1024 * 1024:
        raise HTTPException(400, "文件超过 20MB")
    return start_import(file.filename or "bill", raw)


@router.get("/api/imports")
def list_imports(db: Session = Depends(get_db)):
    rows = db.query(ImportBatch).order_by(ImportBatch.id.desc()).limit(30).all()
    return [_batch(row) for row in rows]


@router.get("/api/imports/{batch_id}")
def read_import(batch_id: int, db: Session = Depends(get_db)):
    row = db.get(ImportBatch, batch_id)
    if row is None:
        raise HTTPException(404, "找不到这次导入")
    return _batch(row)


@router.delete("/api/imports/{batch_id}")
def delete_import(batch_id: int, db: Session = Depends(get_db)):
    row = db.get(ImportBatch, batch_id)
    if row is None:
        raise HTTPException(404, "找不到这次导入")
    if row.status == "running":
        raise HTTPException(400, "模型还在读，稍后再删")
    db.delete(row)
    db.commit()
    return {"ok": True}


@router.post("/api/imports/{batch_id}/reanalyze")
def reanalyze_import(batch_id: int):
    try:
        return reanalyze(batch_id)
    except UserError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.get("/api/overview")
def read_overview(
    start: str = "",
    end: str = "",
    db: Session = Depends(get_db),
):
    return ledger.overview(db, start, end)


@router.get("/api/transactions")
def list_transactions(
    start: str = "",
    end: str = "",
    bucket: str = "booked",
    category: str = "",
    q: str = "",
    limit: int = Query(300, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    base = ledger.transaction_query(db, start, end, bucket, category, q.strip())
    total = base.count()
    rows = ledger.load_transactions(base).limit(limit).offset(offset).all()
    return {"total": total, "items": ledger.public_transactions(rows)}


@router.patch("/api/transactions/{txn_id}")
def patch_transaction(txn_id: int, body: dict = Body(...), db: Session = Depends(get_db)):
    row = db.get(Transaction, txn_id)
    if row is None:
        raise HTTPException(404, "找不到这笔账")
    if "direction" in body:
        direction = DIRECTIONS.get(str(body.get("direction") or "").strip(), "")
        if not direction:
            raise HTTPException(400, "收支类型不正确")
        row.direction = direction
        if direction == "ignore":
            row.included = False
    if "category" in body:
        row.category = str(body.get("category") or "未分类").strip()[:16] or "未分类"
    if "title" in body:
        row.title = str(body.get("title") or "").strip()[:40]
    if "note" in body:
        row.note = str(body.get("note") or "").strip()[:200]
    if "included" in body:
        row.included = bool(body.get("included"))
        if row.included and row.direction == "ignore":
            row.direction = "expense"
    if "member_id" in body:
        member_id = body.get("member_id")
        if member_id in ("", None):
            row.member_id = None
        else:
            member = db.get(Member, int(member_id))
            if member is None:
                raise HTTPException(400, "找不到这个家人")
            row.member_id = member.id
    db.commit()
    db.refresh(row)
    return ledger.public_transactions([row])[0]


@router.delete("/api/transactions/{txn_id}")
def delete_transaction(txn_id: int, db: Session = Depends(get_db)):
    row = db.get(Transaction, txn_id)
    if row is None:
        raise HTTPException(404, "找不到这笔账")
    db.delete(row)
    db.commit()
    return {"ok": True}


@router.post("/api/reports")
def create_report(body: dict = Body(...), db: Session = Depends(get_db)):
    start = str(body.get("start") or "")
    end = str(body.get("end") or "")
    base = ledger.transaction_query(db, start, end, "booked", "", "")
    rows = base.order_by(Transaction.occurred_at).all()
    items = [
        {
            "occurred_at": row.occurred_at,
            "direction": row.direction,
            "amount_cents": row.amount_cents,
            "category": row.category,
            "title": row.title,
            "counterparty": row.counterparty,
            "included": row.included,
        }
        for row in rows
    ]
    try:
        content = summarize_ledger("当前账本", items, llm_settings(db))
    except UserError as exc:
        raise HTTPException(400, str(exc)) from exc
    report = Report(start_on=start, end_on=end, content=content)
    db.add(report)
    db.commit()
    return {"id": report.id, "content": report.content, "created_at": report.created_at.isoformat(timespec="minutes")}


@router.get("/api/export.csv")
def export_csv(start: str = "", end: str = "", db: Session = Depends(get_db)):
    labels = {"expense": "支出", "income": "收入", "refund": "退款", "transfer": "划转", "ignore": "不入账"}
    rows = ledger.load_transactions(ledger.transaction_query(db, start, end, "all", "", "")).all()
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["时间", "类型", "金额", "分类", "名称", "对方", "支付方式", "家人", "备注", "是否入账", "来源文件"])
    for row in rows:
        writer.writerow([
            row.occurred_at.strftime("%Y-%m-%d %H:%M:%S"),
            labels.get(row.direction, row.direction),
            yuan(row.amount_cents),
            row.category,
            row.title,
            row.counterparty,
            row.pay_method,
            row.member.name if row.member else "",
            row.note,
            "是" if row.included else "否",
            row.batch.filename if row.batch else "",
        ])
    content = "\ufeff" + buffer.getvalue()
    stamp = datetime.now().strftime("%Y%m%d")
    return Response(content, media_type="text/csv; charset=utf-8", headers={
        "Content-Disposition": f'attachment; filename="family-ledger-{stamp}.csv"',
    })
