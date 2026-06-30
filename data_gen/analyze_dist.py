"""
analyze_dist.py — 학습 데이터의 패턴 다양성/균형 분석.

train_pairs.json의 SQL을 특징별로 집계해, 특정 패턴에 치우치지 않고
다양한 패턴을 고루 학습하도록 설계됐는지 수치로 확인한다.

사용: python -m data_gen.analyze_dist
"""
from __future__ import annotations

import json
import re
import sys
from collections import Counter
from pathlib import Path

import config
from src import schema_utils

TABLES = ["sc_users", "sc_class", "sc_user_orders",
          "sc_conf_conference", "sc_conf_fee", "sc_conf_registrant"]
MEMBER = {"sc_users", "sc_class", "sc_user_orders"}
CONF = {"sc_conf_conference", "sc_conf_fee", "sc_conf_registrant"}


def feature_set(sql: str) -> set[str]:
    s = sql.lower()
    f = set()
    if "count(" in s: f.add("COUNT")
    if "sum(" in s: f.add("SUM")
    if "avg(" in s: f.add("AVG")
    if "max(" in s: f.add("MAX")
    if "min(" in s: f.add("MIN")
    if " join " in s: f.add("JOIN")
    if "(select" in s: f.add("서브쿼리")
    if "is null" in s: f.add("IS NULL")
    if "is not null" in s: f.add("IS NOT NULL")
    if "group by" in s: f.add("GROUP BY")
    if "order by" in s: f.add("ORDER BY")
    if "between" in s: f.add("BETWEEN")
    if " like " in s: f.add("LIKE")
    if "curdate" in s: f.add("CURDATE()")
    if "interval" in s: f.add("INTERVAL")
    if "distinct" in s: f.add("DISTINCT")
    if "year(" in s: f.add("YEAR")
    if not (f & {"COUNT", "SUM", "AVG", "MAX", "MIN"}):
        f.add("단순 SELECT")
    return f


def tables_in(sql: str) -> set[str]:
    s = sql.lower()
    return {t for t in TABLES if t in s}


def bar(n, total, width=30):
    fill = int(width * n / total) if total else 0
    return "█" * fill + "░" * (width - fill)


def main() -> int:
    path = sys.argv[1] if len(sys.argv) > 1 else str(config.DATA_DIR / "train_pairs.json")
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    n = len(data)
    print(f"### 파일: {Path(path).name}")

    feat = Counter()
    tbl = Counter()
    ntables = Counter()
    domain = Counter()

    for r in data:
        sql = r["sql"]
        for f in feature_set(sql):
            feat[f] += 1
        ts = tables_in(sql)
        for t in ts:
            tbl[t] += 1
        ntables[len(ts)] += 1
        m, c = bool(ts & MEMBER), bool(ts & CONF)
        domain["크로스(회원+학술)" if (m and c) else ("회원" if m else "학술")] += 1

    print(f"학습 데이터 {n}개 분석\n" + "=" * 58)

    print("[SQL 연산/패턴 분포] (한 쿼리가 여러 특징 보유 가능)")
    for k, v in feat.most_common:
        print(f" {k:10} {v:5d} ({100*v/n:5.1f}%) {bar(v, n)}")

    print("\n[테이블 등장 빈도]")
    for t in TABLES:
        v = tbl[t]
        print(f" {t:22} {v:5d} ({100*v/n:5.1f}%) {bar(v, n)}")

    print("\n[쿼리당 테이블 수 (단일 vs 다중 JOIN)]")
    for k in sorted(ntables):
        v = ntables[k]
        print(f" {k}개 테이블 {v:5d} ({100*v/n:5.1f}%) {bar(v, n)}")

    print("\n[도메인 분포]")
    for k, v in domain.most_common:
        print(f" {k:14} {v:5d} ({100*v/n:5.1f}%) {bar(v, n)}")

    # 균형 지표: 가장 흔한 테이블 / 가장 드문 테이블 비율
    mx, mn = max(tbl.values()), min(tbl[t] for t in TABLES)
    print("\n" + "=" * 58)
    print(f"테이블 최대/최소 등장비: {mx}/{mn} = {mx/mn:.1f}x "
          f"({'균형적' if mx/mn < 4 else '다소 편중'})")

    # targeted: 패턴별 균형
    if any("pattern" in r for r in data):
        pat = Counter((r.get("pattern"), r.get("pattern_name", "")) for r in data)
        print("\n[Targeted 패턴별 문항 수]")
        for (pid, pname), v in sorted(pat.items()):
            print(f" 패턴{pid:>2} {pname:24} {v:3d}개")
        vals = list(pat.values())
        print(f" → 패턴 {len(pat)}개, 각 {min(vals)}~{max(vals)}개 "
              f"({'완전 균형' if min(vals) == max(vals) else '약간 불균형'})")

    # coverage: 컬럼 커버리지
    if any("column" in r for r in data):
        schema = schema_utils.load_schema()
        all_cols = {(t, c) for t, tbl_ in schema.items() for c in tbl_.column_names}
        covered = {(r["table"], r["column"]) for r in data if r.get("column")}
        print(f"\n[Coverage 컬럼 커버리지] {len(covered)}/{len(all_cols)} 컬럼 "
              f"({100*len(covered)/len(all_cols):.0f}%)")
        per_tbl = Counter(t for (t, _c) in covered)
        for t in TABLES:
            tot = len(schema[t].columns)
            print(f" {t:22} {per_tbl[t]:2d}/{tot} 컬럼")
        missing = all_cols - covered
        if missing:
            print(f" 미커버 {len(missing)}개: " + ", ".join(f"{t}.{c}" for t, c in list(missing)[:8]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
