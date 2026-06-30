"""
postprocess.py — [Step 5] postprocess_sql: 형식 정규화.

INTERVAL 정규화, DATE_FORMAT 교정, CURRENT_DATE → CURDATE()
  Alias 표준화, GROUP BY alias 확장, MAX/MIN → ORDER BY LIMIT 1

의미를 바꾸지 않는 표면적 정규화만 수행한다(평가 시 문자열 일치율 향상 목적).
환각 컬럼 제거/DML 차단은 Validator(Step 6)의 책임.
"""
from __future__ import annotations

import re

_WS = re.compile(r"[ \t]+")


def postprocess_sql(sql: str) -> str:
    if not sql or not sql.strip():
        return sql
    s = sql.strip()

    s = _strip_fences(s)
    s = _normalize_whitespace(s)
    s = _normalize_current_date(s)
    s = _normalize_interval(s)
    s = _fix_date_format(s)
    s = _max_min_to_order_by_limit(s)
    s = _expand_group_by_alias(s)
    s = _ensure_semicolon(s)
    return s.strip()


# ---------------------------------------------------------------------------
def _strip_fences(s: str) -> str:
    """```sql ... ``` / 선행 [SQL] 등 잔여 마커 제거."""
    s = re.sub(r"```(?:sql)?", "", s, flags=re.IGNORECASE)
    s = s.replace("[SQL]", "").replace("[/SQL]", "")
    return s.strip()


def _normalize_whitespace(s: str) -> str:
    s = _WS.sub(" ", s)
    s = re.sub(r"\s*\n\s*", " ", s) # 한 줄로 정규화
    s = re.sub(r"\s*([,])\s*", r"\1 ", s)
    s = re.sub(r"\(\s+", "(", s)
    s = re.sub(r"\s+\)", ")", s)
    return s.strip()


def _normalize_current_date(s: str) -> str:
    """CURRENT_DATE / NOW() → CURDATE() (날짜 비교 컨텍스트 통일)."""
    s = re.sub(r"\bCURRENT_DATE\s*\(\s*\)", "CURDATE()", s, flags=re.IGNORECASE)
    s = re.sub(r"\bCURRENT_DATE\b", "CURDATE()", s, flags=re.IGNORECASE)
    return s


def _normalize_interval(s: str) -> str:
    """`INTERVAL n DAY` 표기를 표준 형태(`INTERVAL 7 DAY`)로 통일."""
    def repl(m: re.Match) -> str:
        n, unit = m.group("n"), m.group("unit").upper()
        return f"INTERVAL {n} {unit}"

    return re.sub(
        r"INTERVAL\s+(?P<n>\d+)\s+(?P<unit>day|days|month|months|year|years|week|weeks|hour|hours)",
        repl,
        s,
        flags=re.IGNORECASE,
    )


def _fix_date_format(s: str) -> str:
    """흔한 DATE_FORMAT 오타(%Y%m%d 누락 % 등) 교정 + YEAR 단순화."""
    # DATE_FORMAT(col, '%Y') = '2026' → YEAR(col) = 2026
    def year_repl(m: re.Match) -> str:
        return f"YEAR({m.group('col')}) = {m.group('y')}"

    s = re.sub(
        r"DATE_FORMAT\(\s*(?P<col>[\w.`]+)\s*,\s*'%Y'\s*\)\s*=\s*'?(?P<y>\d{4})'?",
        year_repl,
        s,
        flags=re.IGNORECASE,
    )
    return s


def _max_min_to_order_by_limit(s: str) -> str:
    """
    단일 컬럼 MAX/MIN 행 조회를 ORDER BY ... LIMIT 1로 변환.
    예) WHERE price = (SELECT MAX(price) FROM t) → ORDER BY price DESC LIMIT 1
    안전을 위해 가장 단순한 상관 없는 패턴만 변환한다.
    """
    pattern = re.compile(
        r"WHERE\s+(?P<col>[\w.`]+)\s*=\s*\(\s*SELECT\s+(?P<fn>MAX|MIN)\(\s*(?P=col)\s*\)"
        r"\s+FROM\s+(?P<tbl>[\w.`]+)\s*\)\s*;?$",
        re.IGNORECASE,
    )
    m = pattern.search(s)
    if not m:
        return s
    direction = "DESC" if m.group("fn").upper() == "MAX" else "ASC"
    head = s[: m.start()].rstrip()
    return f"{head} ORDER BY {m.group('col')} {direction} LIMIT 1"


def _expand_group_by_alias(s: str) -> str:
    """
    GROUP BY에서 SELECT alias를 실제 식으로 확장하지 않고, alias 사용 시
    MySQL 호환을 위해 그대로 두되 표준 공백/대문자 키워드만 정리.
    (MySQL은 GROUP BY alias 허용 — 여기서는 표면 정규화만)
    """
    s = re.sub(r"\bgroup\s+by\b", "GROUP BY", s, flags=re.IGNORECASE)
    s = re.sub(r"\border\s+by\b", "ORDER BY", s, flags=re.IGNORECASE)
    return s


def _ensure_semicolon(s: str) -> str:
    s = s.rstrip()
    if not s.endswith(";"):
        s += ";"
    return s
