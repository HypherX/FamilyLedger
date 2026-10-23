"""按模型标好的收支类型加总。不在这里重新解释账单。"""
from .textutil import yuan


def compute_totals(items) -> dict:
    expense = refund = income = transfer = 0
    included = excluded = 0
    for item in items:
        cents = int(item["amount_cents"])
        if not item.get("included", True) or item.get("direction") == "ignore":
            excluded += 1
            continue
        included += 1
        direction = item["direction"]
        if direction == "expense":
            expense += cents
        elif direction == "refund":
            refund += cents
        elif direction == "income":
            income += cents
        elif direction == "transfer":
            transfer += cents
    net = expense - refund
    return {
        "expense_cents": expense,
        "refund_cents": refund,
        "net_expense_cents": net,
        "income_cents": income,
        "transfer_cents": transfer,
        "balance_cents": income - net,
        "included_count": included,
        "excluded_count": excluded,
    }


def explain(totals: dict) -> str:
    text = (
        f"按模型标好的类型加总：支出 {yuan(totals['expense_cents'])}，"
        f"退款 {yuan(totals['refund_cents'])}，净支出 {yuan(totals['net_expense_cents'])}，"
        f"收入 {yuan(totals['income_cents'])}。"
    )
    if totals["transfer_cents"]:
        text += f"划转 {yuan(totals['transfer_cents'])} 没有算进净支出。"
    if totals["excluded_count"]:
        text += f"另有 {totals['excluded_count']} 笔模型标成不入账。"
    return text
