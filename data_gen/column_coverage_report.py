"""
column_coverage_report.py — coverage+targeted(+blind)가 스키마 컬럼을 얼마나
참조하는지 분석. 미참조 컬럼을 테이블별로, COMMENT와 함께 보고한다.

사용: python -m data_gen.column_coverage_report
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import config
from src import schema_utils


def cols_in_sql(sql: str, all_names: list[str]) -> set[str]:
    """SQL 텍스트에서 참조된 스키마 컬럼명(대소문자 구분 단어경계) 추출."""
    found = set()
    for name in all_names:
        if re.search(rf"\b{re.escape(name)}\b", sql): # 대소문자 구분
            found.add(name)
    return found


def main() -> int:
    schema = schema_utils.load_schema()
    all_names = sorted({c for t in schema.values() for c in t.column_names}, key=len, reverse=True)

    files = {
        "coverage": config.COVERAGE_TEST_PATH,
        "targeted": config.TARGETED_TEST_PATH,
        "blind": config.BLIND_TEST_PATH,
    }
    covered = {k: set() for k in files}
    for k, f in files.items():
        for r in json.loads(Path(f).read_text(encoding="utf-8")):
            covered[k] |= cols_in_sql(r["sql"], all_names)

    cov_tgt = covered["coverage"] | covered["targeted"]
    cov_tgt_blind = cov_tgt | covered["blind"]

    total = sum(len(t.columns) for t in schema.values())
    print(f"스키마 전체 컬럼: {total}개\n" + "=" * 60)
    print(f"coverage 참조 : {len(covered['coverage'])}개 컬럼명")
    print(f"targeted 참조 : {len(covered['targeted'])}개 컬럼명")
    print(f"coverage+targeted : {len(cov_tgt)}개 컬럼명")
    print(f"coverage+targeted+blind : {len(cov_tgt_blind)}개 컬럼명")

    print("\n[테이블별 미참조 컬럼 (coverage+targeted 기준)]")
    miss_total = 0
    for tname, tbl in schema.items():
        miss = [c for c in tbl.columns if c.name not in cov_tgt]
        if miss:
            print(f"\n {tname} — 미참조 {len(miss)}/{len(tbl.columns)}:")
            for c in miss:
                print(f" · {c.name:24} ({c.comment[:30]})")
            miss_total += len(miss)
    print(f"\n 미참조 합계: {miss_total}개 / 참조 {total - miss_total}개")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
