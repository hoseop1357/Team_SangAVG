"""
validate_columns.py — 생성된 데이터의 모든 SQL이 schema.sql의 실제 컬럼만
참조하는지 검사한다(generalPrereg 같은 오타/환각 컬럼 조기 발견).

사용: python -m data_gen.validate_columns
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import config
from src import schema_utils

# SQL 키워드/함수/리터럴 — 컬럼이 아님
SQL_KEYWORDS = {
    "select", "from", "where", "and", "or", "not", "in", "is", "null", "as", "on",
    "join", "inner", "left", "right", "outer", "group", "by", "order", "having",
    "limit", "asc", "desc", "distinct", "between", "like", "count", "sum", "avg",
    "min", "max", "year", "month", "day", "curdate", "now", "interval", "case",
    "when", "then", "else", "end", "exists", "union", "all", "date_format", "cast",
    "true", "false", "default",
}
# 시간 단위/기타 토큰
EXTRA_OK = {"month", "day", "year", "week", "hour", "cnt", "total", "val",
            "avg_price", "avg_mileage", "max_price", "max_mileage", "avg_amount"}


def known_identifiers():
    schema = schema_utils.load_schema()
    cols = {c.lower() for t in schema.values() for c in t.column_names}
    tables = {t.lower() for t in schema}
    return cols, tables


def check_sql(sql: str, cols: set, tables: set) -> list[str]:
    # 문자열 리터럴 제거
    s = re.sub(r"'(?:[^']|'')*'", " ", sql)
    bad = []
    for tok in re.findall(r"[A-Za-z_][A-Za-z0-9_]*", s):
        low = tok.lower()
        if low in SQL_KEYWORDS or low in EXTRA_OK:
            continue
        if low in cols or low in tables:
            continue
        if len(tok) <= 2: # u, c, r, o, f, cl 등 별칭 허용
            continue
        bad.append(tok)
    return bad


def main() -> int:
    cols, tables = known_identifiers()
    files = [
        config.DATA_DIR / "train_pairs.json",
        config.BLIND_TEST_PATH, config.COVERAGE_TEST_PATH, config.TARGETED_TEST_PATH,
    ]
    total, problems = 0, []
    for f in files:
        if not Path(f).exists():
            continue
        data = json.loads(Path(f).read_text(encoding="utf-8"))
        for rec in data:
            total += 1
            bad = check_sql(rec["sql"], cols, tables)
            if bad:
                problems.append((Path(f).name, rec.get("id", ""), set(bad), rec["sql"]))

    print(f"검사한 SQL: {total}")
    if not problems:
        print("✓ 모든 SQL이 실제 스키마 컬럼만 참조합니다.")
        return 0
    print(f"✗ 미상 식별자 발견 {len(problems)}건 (상위 15):")
    for fname, rid, bad, sql in problems[:15]:
        print(f" [{fname}:{rid}] {bad} :: {sql[:90]}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
