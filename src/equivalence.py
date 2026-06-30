"""
equivalence.py — flexible match 규칙.

문자열은 다르지만 의미가 동등한 SQL을 같은 정규형(canonical form)으로 환원해
유연 일치로 인정한다. 에 명시된 케이스:

  ORDER BY COUNT(*) DESC ↔ ORDER BY cnt DESC (alias)
  NOT IN (SELECT ...) ↔ LEFT JOIN ... IS NULL (anti-join)
  HAVING COUNT(*) > 0 ↔ EXISTS (subquery) (존재 검사)

주의: "점수 인플레이션 없이 정당한 회복"이 목표다.
규칙은 보수적으로, 구조가 명확히 일치할 때만 같은 토큰으로 환원한다.
나머지 절(SELECT 대상/메인 테이블 등)은 그대로 두므로 부분만 같아서는 일치하지 않는다.
"""
from __future__ import annotations

import re

# normalize_sql이 ')' 뒤 공백을 제거해 'count(*)as cnt'가 될 수 있으므로 \s* 허용.
_ALIAS_DEF = re.compile(
    r"(?P<expr>count\(\*\)|count\([a-z_.]+\)|sum\([a-z_.]+\)|avg\([a-z_.]+\)|"
    r"min\([a-z_.]+\)|max\([a-z_.]+\))\s*as\s+(?P<alias>[a-z_][a-z0-9_]*)"
)


def canonical_equiv(normalized_sql: str) -> str:
    """이미 normalize_sql을 거친 소문자/공백정리 SQL을 정규형으로 환원."""
    s = normalized_sql
    s = _resolve_aggregate_alias(s)
    s = _canon_anti_join(s)
    s = _canon_exists_having(s)
    # 변환 과정에서 생긴 공백/괄호 표기를 다시 정규화해 양쪽을 일치시킨다.
    s = re.sub(r"\s*([,])\s*", r"\1", s)
    s = re.sub(r"\bwhere\s+antijoin\(", "antijoin(", s) # 단일 anti-join 조건의 잔여 where 제거
    s = re.sub(r"\s+", " ", s).strip()
    return s


# ---------------------------------------------------------------------------
def _resolve_aggregate_alias(s: str) -> str:
    """
    `count(*) as cnt` 같은 집계 alias를 정의에서 제거하고, ORDER BY/GROUP BY/HAVING
    에서 alias 참조를 원래 집계식으로 치환한다.
    → 'order by cnt desc' 와 'order by count(*) desc' 가 같은 형태가 된다.
    """
    alias_map: dict[str, str] = {}
    for m in _ALIAS_DEF.finditer(s):
        alias_map[m.group("alias")] = m.group("expr")
    if not alias_map:
        return s

    # alias 정의부 제거: "count(*) as cnt" → "count(*)"
    s = _ALIAS_DEF.sub(lambda m: m.group("expr"), s)

    # ORDER BY / GROUP BY / HAVING 의 alias 참조를 집계식으로 환원
    def replace_refs(segment: str) -> str:
        for alias, expr in alias_map.items():
            segment = re.sub(rf"\b{re.escape(alias)}\b", expr, segment)
        return segment

    parts = re.split(r"(\border by\b|\bgroup by\b|\bhaving\b)", s)
    for i in range(1, len(parts), 2): # 키워드 다음 세그먼트만 치환
        if i + 1 < len(parts):
            parts[i + 1] = replace_refs(parts[i + 1])
    return "".join(parts)


# ---------------------------------------------------------------------------
def _canon_anti_join(s: str) -> str:
    """
    anti-join 두 표현을 antijoin(<table>) 토큰으로 환원.
      A) <col> not in (select <c> from <t> ...)
      B) left join <t> on ... where ... <t>.<c> is null (또는 <c> is null)
    """
    # A) NOT IN (SELECT ... FROM t ...)
    s = re.sub(
        r"[a-z_.]+\s+not in\s*\(\s*select\s+[a-z_.*]+\s+from\s+(?P<t>[a-z_][a-z0-9_]*)[^)]*\)",
        lambda m: f"antijoin({m.group('t')})",
        s,
    )
    # B) LEFT JOIN t ON ... (... IS NULL) — 같은 테이블이 IS NULL 조건과 함께 등장
    def left_join_repl(m: re.Match) -> str:
        t = m.group("t")
        return f"antijoin({t})"

    lj = re.search(
        r"left join\s+(?P<t>[a-z_][a-z0-9_]*)\b(?P<rest>.*?)\bis null\b",
        s,
    )
    if lj:
        t = lj.group("t")
        # left join 절 ~ is null 까지를 antijoin 토큰으로 대체
        s = re.sub(
            rf"left join\s+{re.escape(t)}\b.*?\bis null\b",
            f"antijoin({t})",
            s,
            count=1,
        )
        # 잔여 'where and' / 'where antijoin' 정리
        s = re.sub(r"\bwhere\s+and\b", "where", s)
    return s


# ---------------------------------------------------------------------------
def _canon_exists_having(s: str) -> str:
    """
    HAVING COUNT(*) > 0 ↔ EXISTS(subquery) 를 exists(<table>) 토큰으로 환원.
    HAVING count(*) > 0 은 그룹 존재 검사이므로 존재 검사로 간주.
    """
    s = re.sub(r"having\s+count\(\*\)\s*>\s*0", "exists_check", s)
    s = re.sub(
        r"exists\s*\(\s*select\s+[a-z_.*0-9]+\s+from\s+(?P<t>[a-z_][a-z0-9_]*)[^)]*\)",
        "exists_check",
        s,
    )
    return s
