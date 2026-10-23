"""把 CSV、Excel、PDF 转成模型能读的文字。不判断哪一笔是支出或收入。"""
import html
import io
from datetime import datetime
from pathlib import Path

from .textutil import redact


class UserError(Exception):
    pass


def decode_bytes(raw: bytes) -> str:
    if raw.startswith(b"\xef\xbb\xbf"):
        return raw.decode("utf-8-sig")
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("gb18030", errors="replace")


def sniff(raw: bytes, filename: str) -> str:
    name = filename.lower()
    if raw.startswith(b"%PDF") or name.endswith(".pdf"):
        return "pdf"
    if raw.startswith(b"PK") or name.endswith(".xlsx"):
        return "xlsx"
    if raw.startswith(b"\xd0\xcf\x11\xe0") or name.endswith(".xls"):
        return "xls"
    return "csv"


def _cell(value) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M:%S")
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def _table_text(rows: list[list[str]]) -> str:
    return "\n".join("\t".join(cell for cell in row) for row in rows if any(cell.strip() for cell in row))


def _pdf_text(raw: bytes) -> str:
    try:
        import pymupdf
    except ImportError as exc:
        raise UserError("还不能读 PDF。请先在项目里执行 pip install pymupdf") from exc
    try:
        document = pymupdf.open(stream=raw, filetype="pdf")
    except Exception as exc:
        raise UserError("这个 PDF 打不开") from exc
    if document.needs_pass:
        document.close()
        raise UserError("PDF 有打开密码，请先取消密码，或改用 CSV、Excel")
    if document.page_count > 40:
        document.close()
        raise UserError("PDF 超过 40 页，请拆开后再交给模型")
    parts = []
    try:
        for page in document:
            parts.append(page.get_text("text") or "")
    finally:
        document.close()
    return "\n\n".join(part.strip() for part in parts if part.strip())


def _xlsx_text(raw: bytes) -> str:
    import openpyxl
    try:
        workbook = openpyxl.load_workbook(io.BytesIO(raw), read_only=True, data_only=True)
    except Exception as exc:
        raise UserError("这个 Excel 打不开，请另存为 CSV 后再试") from exc
    blocks = []
    try:
        for sheet in workbook.worksheets:
            rows = [[_cell(cell) for cell in row] for row in sheet.iter_rows(values_only=True)]
            text = _table_text(rows)
            if text.strip():
                blocks.append(f"# {sheet.title}\n{text}")
    finally:
        workbook.close()
    return "\n\n".join(blocks)


def _xls_text(raw: bytes) -> str:
    import xlrd
    try:
        book = xlrd.open_workbook(file_contents=raw)
    except Exception as exc:
        raise UserError("这个旧版 Excel 打不开，请另存为 CSV 后再试") from exc
    blocks = []
    for sheet in book.sheets():
        rows = []
        for index in range(sheet.nrows):
            values = []
            for cell in sheet.row(index):
                if cell.ctype == xlrd.XL_CELL_DATE:
                    try:
                        values.append(xlrd.xldate_as_datetime(cell.value, book.datemode).strftime("%Y-%m-%d %H:%M:%S"))
                    except Exception:
                        values.append(_cell(cell.value))
                else:
                    values.append(_cell(cell.value))
            rows.append(values)
        text = _table_text(rows)
        if text.strip():
            blocks.append(f"# {sheet.name}\n{text}")
    return "\n\n".join(blocks)


def file_to_text(raw: bytes, filename: str) -> tuple[str, str]:
    if not raw:
        raise UserError("文件是空的")
    if len(raw) > 20 * 1024 * 1024:
        raise UserError("文件超过 20MB")
    kind = sniff(raw, filename)
    if kind == "pdf":
        text = _pdf_text(raw)
    elif kind == "xlsx":
        text = _xlsx_text(raw)
    elif kind == "xls":
        text = _xls_text(raw)
    else:
        text = decode_bytes(raw)
    text = html.unescape(text.replace("\r\n", "\n").replace("\r", "\n")).strip()
    if len(re_compact(text)) < 8:
        raise UserError("文件里没有能阅读的文字。扫描版 PDF 请先换成 CSV 或 Excel。")
    return kind, text


def re_compact(text: str) -> str:
    return "".join(text.split())


def safe_filename(name: str) -> str:
    base = Path(name or "bill").name
    cleaned = []
    for char in base:
        if char.isalnum() or char in "._- ()（）" or "\u4e00" <= char <= "\u9fff":
            cleaned.append(char)
        else:
            cleaned.append("_")
    return "".join(cleaned)[:80] or "bill"


def mask_for_log(text: str) -> str:
    return redact(text)[:120]
