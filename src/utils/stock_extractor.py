"""从自然语言查询中提取股票代码与公司名称。"""
from __future__ import annotations

import re


def extract_stock_info(query: str) -> tuple[str | None, str | None]:
    """精确提取股票代码和公司名称。"""
    stock_code = None
    company_name = None

    pattern1 = r"请帮我分析一下\s*([^（(]+?)\s*[（(](\d{5,6})[)）]"
    if match := re.search(pattern1, query):
        return match.group(1).strip(), match.group(2)

    pattern2 = r"分析一下\s*([^（(]+?)\s*[（(](\d{5,6})[)）]"
    if match := re.search(pattern2, query):
        return match.group(1).strip(), match.group(2)

    pattern3 = r"分析\s*([^（(]+?)\s*[（(](\d{5,6})[)）]"
    if match := re.search(pattern3, query):
        return match.group(1).strip(), match.group(2)

    pattern4 = r"分析\s*[（(](\d{5,6})[)）]\s*([^）)]+)"
    if match := re.search(pattern4, query):
        return match.group(2).strip(), match.group(1)

    pattern5 = r"帮我看看\s*[（(](\d{5,6})[)）]\s*([^）)]+?)(?:\s*这只|\s*这个)?\s*股票"
    if match := re.search(pattern5, query):
        return match.group(2).strip(), match.group(1)

    pattern6 = r"我想了解一下\s*([^（(]+?)\s*[（(](\d{5,6})[)）]"
    if match := re.search(pattern6, query):
        return match.group(1).strip(), match.group(2)

    pattern7 = r"帮我看看\s*([^（(]+?)\s*[（(](\d{5,6})[)）]"
    if match := re.search(pattern7, query):
        return match.group(1).strip(), match.group(2)

    pattern8 = r"^([^（(]+?)\s*[（(](\d{5,6})[)）]"
    if match := re.search(pattern8, query):
        return match.group(1).strip(), match.group(2)

    for pattern in (
        r"分析一下\s*([^0-9（）()\s]+?)(?:\s*的|\s|$)",
        r"分析\s*([^0-9（）()\s]+)",
        r"([^0-9（）()\s]+)\s*(?:这只|这个|的)?\s*股票",
        r"了解一下\s*([^0-9（）()\s]+?)(?:\s*的|\s|$)",
        r"给我分析一下\s*([^0-9（）()\s]+?)(?:\s*的|\s|$)",
        r"([^0-9（）()\s]+?)\s*的\s*(?:财务表现|盈利能力|现金流状况|资产负债情况|技术面|股价走势|技术指标|技术面表现|估值水平|市盈率|市净率|估值|投资风险|风险因素|风险评估|投资价值|股票|基本面情况|基本面|财务状况)",
        r"([^0-9（）()\s]+?)\s*在\s*[^0-9（）()\s]*\s*中",
        r"([^0-9（）()\s]+?)\s*在\s*[^0-9（）()\s]*\s*中\s*的",
        r"([^0-9（）()\s]+?)\s*面临",
    ):
        if match := re.search(pattern, query):
            if not company_name:
                company_name = match.group(1).strip()

    if match := re.search(r"\b(\d{5,6})\b", query):
        stock_code = match.group(1)

    for pattern in (
        r"(\d{5,6})\s*(?:这个|这只)?\s*股票\s*值得买",
        r"(\d{5,6})\s*这个\s*股票\s*最近表现",
    ):
        if match := re.search(pattern, query):
            if not stock_code:
                stock_code = match.group(1)

    if company_name:
        stop_words = [
            "的", "这个", "这只", "一下", "看看", "了解", "分析", "帮我",
            "我想", "给我", "财务状况", "投资价值", "基本面情况", "这只股票", "这个股票",
        ]
        for word in stop_words:
            company_name = company_name.replace(word, "").strip()
        if len(company_name) < 2:
            company_name = None

    return company_name, stock_code


def normalize_stock_code(code: str | None) -> str | None:
    if not code:
        return None
    digits = re.sub(r"\D", "", code)
    if not digits:
        return code
    if digits.startswith("6"):
        return f"sh.{digits}"
    if digits.startswith(("0", "3")):
        return f"sz.{digits}"
    return digits
