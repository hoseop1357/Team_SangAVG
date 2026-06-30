"""
verify_dedup.py — 학습/평가 데이터 중복 검증.

정책: 중복의 기준은 '질문 문자열'이다.
  · train과 test에 동일한 질문이 있으면 중복(누수) → 0이어야 함.
  · 같은 SQL이라도 질문 표현이 다르면 중복이 아님(패러프레이즈, 의도된 설계).
    → NL2SQL의 paraphrase 일반화 검증에 해당.

사용: python -m data_gen.verify_dedup
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import config


def norm_q(q: str) -> str:
    return re.sub(r"\s+", " ", q.strip()).lower()


def strict_q(q: str) -> str:
    # 공백·문장부호 모두 제거 (사소한 표기차만 다른 '사실상 동일' 질문 탐지)
    return re.sub(r"[\s\W_]+", "", q.lower())


def norm_sql(s: str) -> str:
    return re.sub(r"\s+", " ", s.lower()).strip().rstrip(";")


def load(p):
    return json.loads(Path(p).read_text(encoding="utf-8"))


def main() -> int:
    train = load(config.DATA_DIR / "train_pairs.json")
    tests = {
        "blind": load(config.BLIND_TEST_PATH),
        "coverage": load(config.COVERAGE_TEST_PATH),
        "targeted": load(config.TARGETED_TEST_PATH),
    }
    all_test = [r for d in tests.values() for r in d]

    train_q = [norm_q(r["question"]) for r in train]
    train_qset = set(train_q)
    train_strict = {strict_q(r["question"]) for r in train}
    train_sql = {norm_sql(r["sql"]) for r in train}

    test_q = [norm_q(r["question"]) for r in all_test]
    test_strict = {strict_q(r["question"]) for r in all_test}

    print(f"train {len(train)} / test {len(all_test)} (blind {len(tests['blind'])}, "
          f"coverage {len(tests['coverage'])}, targeted {len(tests['targeted'])})")
    print("=" * 64)

    # 1) 정확 질문 중복 (핵심 기준)
    exact_overlap = train_qset & set(test_q)
    print(f"[1] train∩test 정확 질문 중복 : {len(exact_overlap)}건 (0이어야 정상)")

    # 2) 사소한 표기차만 다른 '사실상 동일' 질문
    strict_overlap = train_strict & test_strict
    print(f"[2] 공백·기호 제거 후 동일 질문 : {len(strict_overlap)}건 (0이어야 정상)")
    for s in list(strict_overlap)[:5]:
        print(f" ⚠ {s}")

    # 3) split 내부 중복
    print(f"[3] train 내부 질문 중복 : {len(train_q) - len(train_qset)}건")
    for name, d in tests.items():
        qs = [norm_q(r["question"]) for r in d]
        print(f" {name:9} 내부 질문 중복 : {len(qs) - len(set(qs))}건")

    # 4) SQL 공유 (허용 — 중복 아님)
    shared_sql = train_sql & {norm_sql(r["sql"]) for r in all_test}
    test_items_shared = sum(1 for r in all_test if norm_sql(r["sql"]) in train_sql)
    print("=" * 64)
    print(f"[참고/정상] train·test 공유 SQL : {len(shared_sql)}종")
    print(f" test {len(all_test)}개 중 {test_items_shared}개({100*test_items_shared/len(all_test):.0f}%)가 "
          f"train에 있는 SQL과 같음 — 단, 질문 표현은 다름(= 패러프레이즈, 중복 아님)")

    # 5) 예시: 같은 SQL을 다르게 물은 train/test 쌍
    train_by_sql = {}
    for r in train:
        train_by_sql.setdefault(norm_sql(r["sql"]), r["question"])
    print("\n [예시] 동일 SQL · 다른 질문 (train vs test):")
    shown = 0
    for r in all_test:
        k = norm_sql(r["sql"])
        if k in train_by_sql and norm_q(r["question"]) != norm_q(train_by_sql[k]):
            print(f" · train: {train_by_sql[k]}")
            print(f" test : {r['question']}")
            shown += 1
            if shown >= 3:
                break

    print("=" * 64)
    ok = (len(exact_overlap) == 0 and len(strict_overlap) == 0
          and len(train_q) == len(train_qset))
    print("결론:", "✓ 질문 중복 없음 (누수 없음). SQL 공유는 의도된 패러프레이즈."
          if ok else "✗ 질문 중복 발견 — 확인 필요")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
