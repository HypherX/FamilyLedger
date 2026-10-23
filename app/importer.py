"""保存上传的文件，请模型阅读，再把结果写入账本。"""
import hashlib
import logging
import threading
from pathlib import Path

from . import paths
from .analyze import analyze_text
from .database import open_session
from .ingest import UserError, file_to_text, safe_filename
from .models import ImportBatch, Member, Report, Transaction
from .settings_store import llm_settings
from .textutil import public_error
from .totals import compute_totals, explain

logger = logging.getLogger("familyledger")
_LOCK = threading.Lock()


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _store_upload(batch_id: int, filename: str, raw: bytes) -> str:
    folder = paths.data_dir() / "imports"
    folder.mkdir(parents=True, exist_ok=True)
    stored = f"{batch_id}-{safe_filename(filename)}"
    (folder / stored).write_bytes(raw)
    return stored


def _progress(batch_id: int, value: int, message: str) -> None:
    with open_session() as db:
        batch = db.get(ImportBatch, batch_id)
        if batch is None or batch.status != "running":
            return
        batch.progress = value
        batch.message = message
        db.commit()


def _members(db) -> tuple[list[str], dict[str, int]]:
    rows = db.query(Member).order_by(Member.id).all()
    return [row.name for row in rows], {row.name: row.id for row in rows}


def _ensure_member(db, names: dict[str, int], name: str, note: str = "") -> int | None:
    name = (name or "").strip()
    if not name:
        return None
    if name in names:
        return names[name]
    row = Member(name=name, note=note)
    db.add(row)
    db.flush()
    names[name] = row.id
    return row.id


def _save_result(batch_id: int, result: dict) -> None:
    with open_session() as db:
        batch = db.get(ImportBatch, batch_id)
        if batch is None:
            return
        _, names = _members(db)
        owner = result.get("account_name") or ""
        owner_id = _ensure_member(db, names, owner, "账单户主")
        existing = set()
        fingerprints = [item["fingerprint"] for item in result["transactions"]]
        for start in range(0, len(fingerprints), 400):
            chunk = fingerprints[start:start + 400]
            if not chunk:
                continue
            existing.update(
                value for (value,) in db.query(Transaction.fingerprint).filter(Transaction.fingerprint.in_(chunk))
            )
        added = duplicate = 0
        saved = []
        for item in result["transactions"]:
            if item["fingerprint"] in existing:
                duplicate += 1
                continue
            existing.add(item["fingerprint"])
            member_name = item.get("member_name") or ""
            member_id = names.get(member_name, owner_id)
            row = Transaction(
                batch_id=batch.id,
                fingerprint=item["fingerprint"],
                occurred_at=item["occurred_at"],
                direction=item["direction"],
                amount_cents=item["amount_cents"],
                category=item["category"],
                title=item["title"],
                counterparty=item["counterparty"],
                description=item["description"],
                pay_method=item["pay_method"],
                member_id=member_id,
                note=item["note"],
                included=item["included"],
            )
            db.add(row)
            saved.append(item)
            added += 1
        totals = compute_totals(result["transactions"])
        batch.account_name = result.get("account_name") or ""
        batch.period_start = result.get("period_start") or ""
        batch.period_end = result.get("period_end") or ""
        batch.summary = result.get("summary") or ""
        batch.added = added
        batch.skipped = int(result.get("skipped") or 0)
        batch.duplicate = duplicate
        batch.progress = 100
        batch.status = "done"
        batch.message = f"记入 {added} 笔。" + explain(totals)
        if result.get("note"):
            batch.message = result["note"] + "。" + batch.message
        if batch.summary:
            db.add(Report(
                start_on=batch.period_start,
                end_on=batch.period_end,
                content=batch.summary,
            ))
        db.commit()


def run_import(batch_id: int) -> None:
    with _LOCK:
        try:
            with open_session() as db:
                batch = db.get(ImportBatch, batch_id)
                if batch is None:
                    return
                path = paths.data_dir() / "imports" / batch.stored_name
                filename = batch.filename
                member_names, _ = _members(db)
                settings = llm_settings(db)
            raw = path.read_bytes()
            _progress(batch_id, 4, "正在读取文件")
            _kind, text = file_to_text(raw, filename)
            logger.info("交给模型阅读：%s，%s 字", filename, len(text))
            result = analyze_text(filename, text, settings, member_names, lambda pct, message: _progress(batch_id, pct, message))
            _save_result(batch_id, result)
        except UserError as exc:
            _fail(batch_id, str(exc))
        except Exception as exc:
            logger.exception("导入失败")
            _fail(batch_id, "导入失败：" + public_error(exc))


def _fail(batch_id: int, message: str) -> None:
    with open_session() as db:
        batch = db.get(ImportBatch, batch_id)
        if batch is None:
            return
        batch.status = "error"
        batch.progress = 100
        batch.error = message
        batch.message = "没有记入"
        db.commit()


def start_import(filename: str, raw: bytes) -> dict:
    digest = _sha256(raw)
    with open_session() as db:
        existing = (
            db.query(ImportBatch)
            .filter(ImportBatch.sha256 == digest, ImportBatch.status == "done")
            .order_by(ImportBatch.id.desc())
            .first()
        )
        if existing is not None:
            return {"id": existing.id, "status": existing.status, "duplicate_file": True}
        batch = ImportBatch(filename=safe_filename(filename), sha256=digest, status="running", message="排队中")
        db.add(batch)
        db.commit()
        db.refresh(batch)
        batch.stored_name = _store_upload(batch.id, filename, raw)
        batch.source = filename.lower().rsplit(".", 1)[-1][:16]
        db.commit()
        batch_id = batch.id
    threading.Thread(target=run_import, args=(batch_id,), daemon=True).start()
    return {"id": batch_id, "status": "running", "duplicate_file": False}


def reanalyze(batch_id: int) -> dict:
    with open_session() as db:
        batch = db.get(ImportBatch, batch_id)
        if batch is None:
            raise UserError("找不到这次导入")
        if batch.status == "running":
            raise UserError("这份账单还在读")
        path = paths.data_dir() / "imports" / batch.stored_name
        if not path.is_file():
            raise UserError("原文件不在了，请重新选择文件")
        db.query(Transaction).filter(Transaction.batch_id == batch.id).delete()
        batch.status = "running"
        batch.progress = 0
        batch.error = ""
        batch.summary = ""
        batch.message = "准备让模型重读"
        db.commit()
    threading.Thread(target=run_import, args=(batch_id,), daemon=True).start()
    return {"id": batch_id, "status": "running"}
