"""
compare_dist.py — train vs 각 test셋의 SQL 패턴 비율을 나란히 비교.

각 패턴(연산/구조/도메인)이 train과 test에서 비슷한 비율로 분포하는지 확인한다.

사용: python -m data_gen.compare_dist
"""
from __future__ import annotations

import json
from pathlib import Path

import config
from data_gen.analyze_dist import feature_set, tables_in, MEMBER, CONF, TABLES

FILES = {
    "train": config.DATA_DIR / "train_pairs.json",
    "blind": config.BLIND_TEST_PATH,
    "coverage": config.COVERAGE_TEST_PATH,
    "targeted": config.TARGETED_TEST_PATH,
}

# 비교할 패턴 라벨(순서 고정)
PATTERNS = ["COUNT", "단순 SELECT", "JOIN", "서브쿼리", "GROUP BY", "ORDER BY",
            "BETWEEN", "IS NULL", "IS NOT NULL", "AVG", "SUM", "MAX", "MIN",
            "DISTINCT", "CURDATE()", "YEAR"]


def profile(records):
    n = len(records)
    feat = {p: 0 for p in PATTERNS}
    multi = 0
    dom = {"회원": 0, "학술": 0, "크로스": 0}
    for r in records:
        fs = feature_set(r["sql"])
        for p in PATTERNS:
            if p in fs:
                feat[p] += 1
        ts = tables_in(r["sql"])
        if len(ts) >= 2:
            multi += 1
        m, c = bool(ts & MEMBER), bool(ts & CONF)
        dom["크로스" if (m and c) else ("회원" if m else "학술")] += 1
    return n, feat, multi, dom


def main() -> int:
    data = {k: profile(json.loads(Path(f).read_text(encoding="utf-8"))) for k, f in FILES.items()}

    cols = list(FILES)
    print(f"{'패턴':14}" + "".join(f"{c:>11}" for c in cols))
    print(f"{'(N)':14}" + "".join(f"{data[c][0]:>11}" for c in cols))
    print("-" * 60)
    for p in PATTERNS:
        row = f"{p:14}"
        for c in cols:
            n, feat, _m, _d = data[c]
            row += f"{100*feat[p]/n:>10.1f}%"
        print(row)
    print("-" * 60)
    row = f"{'다중테이블(JOIN)':14}"
    for c in cols:
        n, _f, multi, _d = data[c]
        row += f"{100*multi/n:>10.1f}%"
    print(row)
    print("\n[도메인 비율]")
    for dm in ("회원", "학술", "크로스"):
        row = f"{dm:14}"
        for c in cols:
            n, _f, _m, dom = data[c]
            row += f"{100*dom[dm]/n:>10.1f}%"
        print(row)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
