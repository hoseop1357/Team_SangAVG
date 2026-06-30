"""
validator.py — [Step 6] SQLValidator: 안전 검사 + 환각 제거.

- DML 차단 (INSERT/UPDATE/DELETE/DROP 등) → SELECT-only
  - 환각 컬럼 자동 제거 (스키마에 없는 WHERE 조건 삭제)
  - LIMIT 100 자동 추가

base 모델은 SELECT-only를 생성해 차단 0건이지만,
안전성/안정성 목적상 운영 단계에서 항상 켜둔다.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from src import schema_utils

DML_KEYWORDS = (
    "INSERT", "UPDATE", "DELETE", "DROP", "ALTER", "CREATE",
    "TRUNCATE", "REPLACE", "GRANT", "REVOKE", "MERGE", "CALL",
)


@dataclass
class ValidationResult:
    sql: str
    blocked: bool = False
    block_reason: str = ""
    removed_columns: list[str] = field(default_factory=list)
    added_limit: bool = False


class SQLValidator:
    def __init__(self, default_limit: int = 100, schema_path: str | None = None):
        self.default_limit = default_limit
        self.schema_columns = schema_utils.all_columns(schema_path)
        # 전 테이블 컬럼 합집합 (alias 미해석 시 보수적 판단용)
        self._known = {c.lower() for cols in self.schema_columns.values() for c in cols}

    # ------------------------------------------------------------------
    def validate(self, sql: str) -> ValidationResult:
        s = (sql or "").strip()
        if not s:
            return ValidationResult(sql=s, blocked=True, block_reason="빈 SQL")

        # 1) DML / 다중 구문 차단
        blocked, reason = self._check_dml(s)
        if blocked:
            return ValidationResult(sql=s, blocked=True, block_reason=reason)

        # 2) 환각 컬럼 제거 (WHERE 단순 조건)
        s, removed = self._remove_hallucinated_conditions(s)

        # 3) LIMIT 자동 추가
        s, added = self._ensure_limit(s)

        return ValidationResult(
            sql=s, blocked=False, removed_columns=removed, added_limit=added
        )

    # ------------------------------------------------------------------
    def _check_dml(self, s: str) -> tuple[bool, str]:
        body = re.sub(r"--.*?$", "", s, flags=re.MULTILINE)
        # 세미콜론으로 끝나는 단일 구문만 허용 (구문 주입 방지)
        statements = [st for st in body.split(";") if st.strip()]
        if len(statements) > 1:
            return True, "다중 구문 금지 (단일 SELECT만 허용)"
        first = statements[0].strip().upper() if statements else ""
        if not first.startswith(("SELECT", "WITH")):
            return True, "SELECT/WITH로 시작하지 않음"
        for kw in DML_KEYWORDS:
            if re.search(rf"\b{kw}\b", first):
                return True, f"DML/DDL 키워드 차단: {kw}"
        return False, ""

    # ------------------------------------------------------------------
    def _remove_hallucinated_conditions(self, s: str) -> tuple[str, list[str]]:
        """
        WHERE/AND 절의 단순 비교 조건 중, 스키마에 존재하지 않는 컬럼을 참조하는
        조건을 제거한다. (alias.col 형태는 컬럼명만 떼어 검사)
        보수적으로 `col <op> value` 형태의 단순 조건만 대상으로 한다.
        """
        removed: list[str] = []

        cond_re = re.compile(
            r"(?P<conn>\bWHERE\b|\bAND\b|\bOR\b)\s+"
            r"(?P<expr>(?:[\w`]+\.)?(?P<col>[\w`]+)\s*"
            r"(?:=|!=|<>|>=|<=|>|<|\bLIKE\b|\bIN\b|\bIS\b)\s*[^()]+?)"
            r"(?=\s+(?:AND|OR|GROUP|ORDER|LIMIT|HAVING)\b|\s*;|\s*\)|$)",
            re.IGNORECASE,
        )

        def keep(m: re.Match) -> bool:
            col = m.group("col").strip("`").lower()
            # 함수/리터럴/예약 토큰은 컬럼 아님 → 유지
            if col in {"and", "or", "select", "count", "sum", "avg", "true", "false"}:
                return True
            return col in self._known

        out_parts = []
        last = 0
        matches = list(cond_re.finditer(s))
        for m in matches:
            if keep(m):
                continue
            removed.append(m.group("col").strip("`"))
            # 해당 조건 구간을 삭제 표시 (뒤에서 일괄 제거)
            out_parts.append((m.start(), m.end(), m.group("conn").upper()))

        if not removed:
            return s, removed

        # 뒤에서부터 제거하여 인덱스 안정성 유지
        for start, end, conn in sorted(out_parts, key=lambda x: -x[0]):
            s = s[:start] + s[end:]
        # 정리: WHERE AND → WHERE, 연속 AND/OR, 떠도는 WHERE 제거
        s = re.sub(r"\bWHERE\s+(AND|OR)\b", "WHERE", s, flags=re.IGNORECASE)
        s = re.sub(r"\b(AND|OR)\s+(AND|OR)\b", r"\1", s, flags=re.IGNORECASE)
        s = re.sub(r"\bWHERE\s+(GROUP|ORDER|LIMIT|HAVING|;|$)", r"\1", s, flags=re.IGNORECASE)
        s = re.sub(r"\s+(AND|OR)\s*(;|$)", r"\2", s, flags=re.IGNORECASE)
        s = re.sub(r"[ \t]{2,}", " ", s).strip()
        return s, removed

    # ------------------------------------------------------------------
    def _ensure_limit(self, s: str) -> tuple[str, bool]:
        body = s.rstrip().rstrip(";")
        if re.search(r"\bLIMIT\b", body, flags=re.IGNORECASE):
            return s, False
        # COUNT/SUM/AVG 단일 집계(GROUP BY 없음)는 한 행이라 LIMIT 불필요하지만,
        # 명세상 일괄 추가한다.
        return f"{body} LIMIT {self.default_limit};", True
