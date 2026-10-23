"""金额、时间和对外发送前的脱敏。"""
import html
import re
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP

_PHONE = re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")


def redact(text: str) -> str:
    text = html.unescape(text or "")
    text = text.replace("\t", " ").replace("\u3000", " ")
    text = re.sub(r"\s+", " ", text).strip()
    return _PHONE.sub(lambda match: match.group(0)[:3] + "****" + match.group(0)[-4:], text)


def mask_account(value: str) -> str:
    digits = re.sub(r"\D", "", value or "")
    if len(digits) >= 7:
        return digits[:3] + "****" + digits[-4:]
    return redact(value)


def parse_cents(value) -> int:
    if isinstance(value, bool):
        raise ValueError("金额不正确")
    if isinstance(value, (int, float)):
        quantized = Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        return int(quantized * 100)
    text = redact(str(value)).replace(",", "").replace("，", "")
    text = text.replace("¥", "").replace("￥", "").replace("元", "").replace(" ", "")
    if text in {"", "-", "/", "--", "—"}:
        return 0
    negative = text.startswith("-")
    text = text.lstrip("+-")
    text = re.sub(r"[^0-9.]", "", text)
    if not text or text.count(".") > 1:
        raise ValueError("金额不正确")
    quantized = Decimal(text).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    cents = int(quantized * 100)
    return -cents if negative else cents


def parse_time(value) -> datetime | None:
    if isinstance(value, datetime):
        return value.replace(tzinfo=None)
    text = redact(str(value)).replace("/", "-").replace(".", "-")
    text = text.replace("年", "-").replace("月", "-").replace("日", " ")
    text = re.sub(r"\s+", " ", text).strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d", "%Y%m%d %H:%M:%S", "%Y%m%d"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    match = re.match(r"(\d{4})-(\d{1,2})-(\d{1,2})(?:\s+(\d{1,2}):(\d{2})(?::(\d{2}))?)?", text)
    if not match:
        return None
    year, month, day, hour, minute, second = match.groups()
    try:
        return datetime(int(year), int(month), int(day), int(hour or 0), int(minute or 0), int(second or 0))
    except ValueError:
        return None


def yuan(cents: int) -> str:
    sign = "-" if cents < 0 else ""
    cents = abs(int(cents))
    return f"{sign}{cents // 100:,}.{cents % 100:02d}"


def public_error(exc: Exception) -> str:
    text = re.sub(r"sk-[A-Za-z0-9]+", "sk-***", str(exc))
    return text.replace("\n", " ")[:300]
