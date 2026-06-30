"""
build.py — train/blind/coverage/targeted 데이터셋 + seed_data.sql 조립.

핵심 보장(사용자 요구사항):
  · 학습/평가 데이터 간 질문 중복 금지 — 모든 split이 하나의 `seen` 집합을 공유해
    정규화된 질문이 한 번만 등장하도록 한다(평가셋을 먼저 채우고 train에서 제외).
  · TYPE_A/TYPE_C 구분용 seed_data.sql 동시 생성.

생성 순서: blind → targeted → coverage → train (이미 쓰인 질문은 전부 제외).
"""
from __future__ import annotations

import argparse
import json
import random
import re
from pathlib import Path

import config
from data_gen import coverage as cov_mod
from data_gen import seed as seed_mod
from data_gen.templates import GENERAL_TEMPLATES
from data_gen.targeted import PATTERNS
from src import schema_utils

ROOT = Path(__file__).resolve().parent.parent


def norm_q(q: str) -> str:
    # 띄어쓰기/문장부호 무시 — '결제수단별'='결제 수단별' 같은 변형도 중복으로 처리.
    return re.sub(r"[\s\W_]+", "", q.lower())


def collect_unique(rng, sampler, n, seen, *, max_factor=400, quiet=False):
    """sampler(rng)를 반복 호출해 질문 기준 중복 없는 레코드 n개 수집."""
    out, attempts, cap = [], 0, n * max_factor
    while len(out) < n and attempts < cap:
        attempts += 1
        r = sampler(rng)
        key = norm_q(r["question"])
        if key in seen:
            continue
        seen.add(key)
        out.append(r)
    if len(out) < n and not quiet:
        print(f" ! 경고: 목표 {n}개 중 {len(out)}개만 생성(고유 공간 부족). max_factor를 늘리세요.")
    return out


def collect_quota(rng, templates, n, seen):
    """
    패턴 균형: 먼저 각 템플릿에 동일 할당량(per)을 배정해 고르게 채우고,
    부족분만 전체 템플릿에서 추가로 채운다. → 고용량 템플릿의 독점 방지.
    """
    per = max(1, n // len(templates))
    out = []
    for t in templates:
        out += collect_unique(rng, t, per, seen, max_factor=60, quiet=True)
    if len(out) < n:
        out += collect_unique(rng, lambda r: r.choice(templates)(r), n - len(out), seen)
    return out[:n]


def build_coverage(rng, n, seen):
    """실무 probe 라운드로빈으로 업무 컬럼을 covering하며 n개 수집."""
    probes = cov_mod.COVERAGE_PROBES
    out, attempts, cap = [], 0, n * 400
    while len(out) < n and attempts < cap:
        progressed = False
        for (_table, _col, fn) in probes:
            if len(out) >= n:
                break
            r = fn(rng)
            key = norm_q(r["question"])
            if key not in seen:
                seen.add(key)
                out.append(r)
                progressed = True
        attempts += 1
        if not progressed:
            print(f" ! coverage 실무 질문 공간 소진 — {len(out)}/{n}")
            break
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="학습/평가 데이터 + seed 생성")
    ap.add_argument("--train", type=int, default=4412)
    ap.add_argument("--blind", type=int, default=214)
    ap.add_argument("--coverage", type=int, default=680)
    ap.add_argument("--targeted", type=int, default=300) # 30 × 10 패턴
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--no-seed-sql", action="store_true", help="seed_data.sql 생성 생략")
    ap.add_argument("--coverage-only", action="store_true",
                    help="coverage만 재생성(기존 train/blind/targeted 질문 제외 → 누수 방지)")
    ap.add_argument("--targeted-only", action="store_true",
                    help="targeted만 재생성(기존 train/blind/coverage 질문 제외)")
    ap.add_argument("--test-only", action="store_true",
                    help="blind/coverage/targeted 전체 재생성(기존 train 제외, 띄어쓰기 변형까지)")
    args = ap.parse_args()

    rng = random.Random(args.seed)
    seen: set[str] = set()

    # ---- test 3종 전체 재생성 (train 고정, 띄어쓰기 무시 누수 차단) ----
    if args.test_only:
        train = json.loads(Path(config.DATA_DIR / "train_pairs.json").read_text(encoding="utf-8"))
        for r in train:
            seen.add(norm_q(r["question"]))
        print(f"기존 train {len(train)}개 제외(띄어쓰기 무시)")

        blind = collect_quota(rng, GENERAL_TEMPLATES, args.blind, seen)
        for i, rec in enumerate(blind, 1):
            rec_id(rec, f"blind_{i:04d}")

        per = args.targeted // len(PATTERNS)
        targeted = []
        for pid, pname, fn in PATTERNS:
            chunk = collect_unique(rng, fn, per, seen)
            for rec in chunk:
                rec["pattern"] = pid
                rec["pattern_name"] = pname
            targeted.extend(chunk)
        for i, rec in enumerate(targeted, 1):
            rec_id(rec, f"tgt_{i:04d}")

        coverage = build_coverage(rng, args.coverage, seen)
        for i, rec in enumerate(coverage, 1):
            rec_id(rec, f"cov_{i:04d}")

        # 검증: train과, test 내부 모두 (띄어쓰기 무시) 중복 0
        tq = {norm_q(r["question"]) for r in train}
        allt = [norm_q(r["question"]) for r in blind + coverage + targeted]
        assert not (set(allt) & tq), "train 누수!"
        assert len(allt) == len(set(allt)), "test 내부 중복!"
        write_json(config.BLIND_TEST_PATH,
                   [slim(r, ["id", "question", "sql", "tables"]) for r in blind])
        write_json(config.TARGETED_TEST_PATH,
                   [slim(r, ["id", "pattern", "pattern_name", "question", "sql", "tables"]) for r in targeted])
        write_json(config.COVERAGE_TEST_PATH,
                   [slim(r, ["id", "question", "sql", "table", "column", "tables"]) for r in coverage])
        print(f" ✓ test 재생성 (blind {len(blind)}, targeted {len(targeted)}, coverage {len(coverage)}) "
              f"— train 누수 0, 띄어쓰기 변형까지 제거")
        return 0

    # ---- targeted만 재생성 ----
    if args.targeted_only:
        others = [config.DATA_DIR / "train_pairs.json", config.BLIND_TEST_PATH,
                  config.COVERAGE_TEST_PATH]
        for f in others:
            for r in json.loads(Path(f).read_text(encoding="utf-8")):
                seen.add(norm_q(r["question"]))
        print(f"기존 train/blind/coverage 질문 {len(seen)}개 제외")
        per = args.targeted // len(PATTERNS)
        targeted = []
        for pid, pname, fn in PATTERNS:
            chunk = collect_unique(rng, fn, per, seen)
            for rec in chunk:
                rec["pattern"] = pid
                rec["pattern_name"] = pname
            targeted.extend(chunk)
        for i, rec in enumerate(targeted, 1):
            rec_id(rec, f"tgt_{i:04d}")
        existing = set()
        for f in others:
            existing |= {norm_q(r["question"]) for r in json.loads(Path(f).read_text(encoding="utf-8"))}
        tq = [norm_q(r["question"]) for r in targeted]
        assert not (set(tq) & existing) and len(tq) == len(set(tq)), "targeted 중복!"
        write_json(config.TARGETED_TEST_PATH,
                   [slim(r, ["id", "pattern", "pattern_name", "question", "sql", "tables"]) for r in targeted])
        print(f" ✓ targeted {len(targeted)}개 재생성 (기존 셋과 중복 0)")
        return 0

    # ---- coverage만 재생성 (이미 학습된 모델의 train과 누수 방지) ----
    if args.coverage_only:
        for f in (config.DATA_DIR / "train_pairs.json", config.BLIND_TEST_PATH,
                  config.TARGETED_TEST_PATH):
            for r in json.loads(Path(f).read_text(encoding="utf-8")):
                seen.add(norm_q(r["question"]))
        print(f"기존 train/blind/targeted 질문 {len(seen)}개를 제외 집합에 로드")
        coverage = build_coverage(rng, args.coverage, seen)
        for i, rec in enumerate(coverage, 1):
            rec_id(rec, f"cov_{i:04d}")
        # 검증: 기존 셋과 중복 없음
        existing = set()
        for f in (config.DATA_DIR / "train_pairs.json", config.BLIND_TEST_PATH,
                  config.TARGETED_TEST_PATH):
            existing |= {norm_q(r["question"]) for r in json.loads(Path(f).read_text(encoding="utf-8"))}
        cov_q = [norm_q(r["question"]) for r in coverage]
        assert not (set(cov_q) & existing), "coverage가 기존 셋과 중복!"
        assert len(cov_q) == len(set(cov_q)), "coverage 내부 중복!"
        write_json(config.COVERAGE_TEST_PATH,
                   [slim(r, ["id", "question", "sql", "table", "column", "tables"]) for r in coverage])
        print(f" ✓ coverage {len(coverage)}개 재생성 (기존 셋과 중복 0)")
        return 0

    # ---- 평가셋 먼저 (질문 선점) ----
    print("[1/4] blind 생성 (패턴 균형 quota)...")
    blind = collect_quota(rng, GENERAL_TEMPLATES, args.blind, seen)
    for i, rec in enumerate(blind, 1):
        rec_id(rec, f"blind_{i:04d}")

    print("[2/4] targeted 생성 (10패턴)...")
    per = args.targeted // len(PATTERNS)
    targeted = []
    for pid, pname, fn in PATTERNS:
        chunk = collect_unique(rng, fn, per, seen)
        for rec in chunk:
            rec["pattern"] = pid
            rec["pattern_name"] = pname
        targeted.extend(chunk)
    for i, rec in enumerate(targeted, 1):
        rec_id(rec, f"tgt_{i:04d}", front=True)

    print("[3/4] coverage 생성 (컬럼 라운드로빈)...")
    coverage = build_coverage(rng, args.coverage, seen)
    for i, rec in enumerate(coverage, 1):
        rec_id(rec, f"cov_{i:04d}", front=True)

    # ---- 학습셋 (평가 질문 전부 제외) ----
    print("[4/4] train 생성 (패턴 균형 quota, 평가셋 질문 제외)...")
    train = collect_quota(rng, GENERAL_TEMPLATES, args.train, seen)
    for rec in train:
        rec.pop("pattern", None)

    # ---- 검증: 중복 없음 ----
    verify_no_overlap(train, blind, coverage, targeted)

    # ---- 저장 ----
    write_json(config.DATA_DIR / "train_pairs.json",
               [slim(r, ["question", "sql", "tables"]) for r in train])
    write_json(config.BLIND_TEST_PATH,
               [slim(r, ["id", "question", "sql", "tables"]) for r in blind])
    write_json(config.COVERAGE_TEST_PATH,
               [slim(r, ["id", "question", "sql", "table", "column", "tables"]) for r in coverage])
    write_json(config.TARGETED_TEST_PATH,
               [slim(r, ["id", "pattern", "pattern_name", "question", "sql", "tables"]) for r in targeted])

    if not args.no_seed_sql:
        seed_sql = seed_mod.generate_seed(random.Random(args.seed))
        (ROOT / "seed_data.sql").write_text(seed_sql, encoding="utf-8")
        print(f" seed_data.sql 저장 ({len(seed_sql.splitlines())} 줄)")

    print("\n=== 생성 완료 ===")
    print(f" train : {len(train)}")
    print(f" blind : {len(blind)}")
    print(f" coverage : {len(coverage)}")
    print(f" targeted : {len(targeted)}")
    return 0


def rec_id(rec: dict, value: str, front: bool = False) -> None:
    rec["id"] = value


def slim(rec: dict, keys: list[str]) -> dict:
    return {k: rec[k] for k in keys if k in rec}


def write_json(path, data) -> None:
    Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f" 저장: {Path(path).name} ({len(data)})")


def verify_no_overlap(train, blind, coverage, targeted) -> None:
    tq = {norm_q(r["question"]) for r in train}
    for name, ds in (("blind", blind), ("coverage", coverage), ("targeted", targeted)):
        overlap = tq & {norm_q(r["question"]) for r in ds}
        assert not overlap, f"train ∩ {name} 질문 중복 {len(overlap)}건: {list(overlap)[:3]}"
    # 평가셋 내부 중복도 확인
    all_test = [norm_q(r["question"]) for r in blind + coverage + targeted]
    assert len(all_test) == len(set(all_test)), "평가셋 내부 질문 중복 발견"
    # train 내부 중복
    train_q = [norm_q(r["question"]) for r in train]
    assert len(train_q) == len(set(train_q)), "train 내부 질문 중복 발견"
    print(" ✓ 중복 검증 통과 (train ∩ test = ∅, 각 split 내부 고유)")


if __name__ == "__main__":
    raise SystemExit(main())
