"""
evaluate.py — 3-layer 평가 + MySQL 실행 기반 TYPE_A 보정.

평가 레이어:
  Blind blind_test_all6_tables.json 214문항 전체 도메인 일반화
  Coverage column_coverage_test_v2.json 680문항 컬럼별 커버리지
  Targeted targeted_test_v2.json 300문항 10개 패턴 집중

채점:
  - exact : 정규화 문자열 완전 일치
  - flexible: 핵심 구성요소(SELECT 항목/테이블/조건) 집합 일치
  - raw 점수 = exact + flexible

TYPE_A 보정: MySQL에서 Gold/Pred를 실제 실행해 결과를 비교.
  TYPE_A 결과 완전 일치 → 정답으로 보정
  TYPE_C 결과 불일치 → 진짜 오류
  EXEC_ERR Pred 실행 오류 → 잘못된 SQL
  보정 점수 = 문자열 점수 + TYPE_A 건수

사용:
  python evaluate.py --layer blind
  python evaluate.py --layer all --exec # MySQL 실행 보정 포함
  python evaluate.py --layer targeted --no-model --gold-as-pred # 채점 로직 점검
"""
from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

import config
from src.equivalence import canonical_equiv
from src.postprocess import postprocess_sql

LAYERS = {
    "blind": config.BLIND_TEST_PATH,
    "coverage": config.COVERAGE_TEST_PATH,
    "targeted": config.TARGETED_TEST_PATH,
}


# ---------------------------------------------------------------------------
# 문자열 채점
# ---------------------------------------------------------------------------
def normalize_sql(sql: str) -> str:
    """대소문자/공백/별칭 백틱/세미콜론 정규화 후 비교용 문자열 생성."""
    s = postprocess_sql(sql or "")
    s = s.lower().replace("`", "")
    s = re.sub(r"\s+", " ", s)
    s = re.sub(r"\s*([,])\s*", r"\1", s)
    s = s.rstrip("; ").strip()
    return s


def exact_match(gold: str, pred: str) -> bool:
    return normalize_sql(gold) == normalize_sql(pred)


_SELECT_RE = re.compile(r"select\s+(.*?)\s+from\s+(.+)", re.IGNORECASE | re.DOTALL)


def _components(sql: str) -> set[str]:
    """SELECT 항목 + FROM/JOIN 테이블 + WHERE 토큰의 집합(유연 일치용)."""
    s = normalize_sql(sql)
    toks = set(re.findall(r"[a-z_][a-z0-9_]*", s))
    # 의미 없는 SQL 키워드 제거
    stop = {"select", "from", "where", "and", "or", "as", "on", "join", "inner",
            "left", "right", "group", "by", "order", "limit", "asc", "desc", "in"}
    return toks - stop


def flexible_match(gold: str, pred: str, threshold: float = 0.9) -> bool:
    """
    유연 일치 판정. 두 경로 중 하나라도 통과하면 인정:
      (1) ③ 의미 동등 규칙: 정규형(canonical_equiv)이 완전 일치
      (2) 구성요소 집합 Jaccard ≥ threshold
    """
    # (1) flexible match 규칙 — alias / anti-join / exists 동등성
    if canonical_equiv(normalize_sql(gold)) == canonical_equiv(normalize_sql(pred)):
        return True

    # (2) 구성요소 유사도
    g, p = _components(gold), _components(pred)
    if not g:
        return False
    jaccard = len(g & p) / len(g | p) if (g | p) else 0.0
    return jaccard >= threshold


# ---------------------------------------------------------------------------
# MySQL 실행 기반 TYPE 분류
# ---------------------------------------------------------------------------
@dataclass
class ExecVerdict:
    type: str # MATCH(=TYPE_A) / TYPE_C / EXEC_ERR / BOTH_EMPTY / SKIPPED
    detail: str = ""


class MySQLExecutor:
    def __init__(self, mysql_cfg: config.MySQLConfig | None = None):
        self.cfg = mysql_cfg or config.MYSQL
        self._conn = None

    def connect(self):
        import mysql.connector
        self._conn = mysql.connector.connect(
            host=self.cfg.host, port=self.cfg.port, user=self.cfg.user,
            password=self.cfg.password, database=self.cfg.database,
        )
        return self

    def _run(self, sql: str):
        cur = self._conn.cursor()
        cur.execute(sql)
        rows = cur.fetchall()
        cur.close()
        return rows

    def compare(self, gold: str, pred: str) -> ExecVerdict:
        if self._conn is None:
            return ExecVerdict("SKIPPED", "DB 미연결")
        try:
            gold_rows = self._run(gold.rstrip("; ") )
        except Exception as e: # gold가 깨졌으면 평가 불가
            return ExecVerdict("SKIPPED", f"gold 실행 오류: {e}")
        try:
            pred_rows = self._run(pred.rstrip("; "))
        except Exception as e:
            return ExecVerdict("EXEC_ERR", str(e))

        # 순서 무관 비교 (멀티셋)
        def canon(rows):
            return sorted(tuple(str(c) for c in r) for r in rows)

        g, p = canon(gold_rows), canon(pred_rows)
        if not g and not p:
            return ExecVerdict("BOTH_EMPTY", "양쪽 결과 0건")
        if g == p:
            return ExecVerdict("MATCH") # TYPE_A
        return ExecVerdict("TYPE_C", f"gold {len(g)}행 vs pred {len(p)}행")


# ---------------------------------------------------------------------------
# 평가 루프
# ---------------------------------------------------------------------------
@dataclass
class LayerReport:
    layer: str
    total: int = 0
    exact: int = 0
    flexible: int = 0
    type_a: int = 0
    type_c: int = 0
    exec_err: int = 0
    both_empty: int = 0
    details: list[dict] = field(default_factory=list)

    @property
    def raw(self) -> int:
        return self.exact + self.flexible

    def summary(self) -> str:
        n = self.total or 1
        raw_pct = 100 * self.raw / n
        corrected_pct = 100 * (self.raw + self.type_a) / n
        lines = [
            f"[{self.layer}] N={self.total}",
            f" exact : {self.exact:4d} ({100*self.exact/n:5.1f}%)",
            f" flexible : {self.flexible:4d} ({100*self.flexible/n:5.1f}%)",
            f" raw 점수 : {self.raw:4d} ({raw_pct:5.1f}%)",
        ]
        if self.type_a or self.type_c or self.exec_err:
            lines += [
                f" TYPE_A : {self.type_a:4d} (실행 결과 일치 → 정답 보정)",
                f" TYPE_C : {self.type_c:4d} (진짜 오류)",
                f" EXEC_ERR : {self.exec_err:4d} (SQL 실행 오류)",
                f" 보정 점수: {self.raw + self.type_a:4d} ({corrected_pct:5.1f}%)",
            ]
        return "\n".join(lines)


def evaluate_layer(
    layer: str, path: Path, pipeline, executor: MySQLExecutor | None, gold_as_pred: bool,
    limit: int = 0,
) -> LayerReport:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if limit and limit > 0:
        data = data[:limit]
    rep = LayerReport(layer=layer, total=len(data))

    for item in data:
        q, gold = item["question"], item["sql"]

        if gold_as_pred:
            pred = gold # 채점 로직 자체 점검용
        elif pipeline is not None:
            result = pipeline.run(q)
            pred = result.sql or ""
        else:
            pred = ""

        is_exact = exact_match(gold, pred)
        is_flex = (not is_exact) and flexible_match(gold, pred)
        if is_exact:
            rep.exact += 1
        elif is_flex:
            rep.flexible += 1

        verdict = ExecVerdict("SKIPPED")
        # 문자열 불일치 건만 실행 보정 대상
        if executor is not None and not (is_exact or is_flex) and pred.strip():
            verdict = executor.compare(gold, pred)
            if verdict.type == "MATCH":
                rep.type_a += 1
            elif verdict.type == "TYPE_C":
                rep.type_c += 1
            elif verdict.type == "EXEC_ERR":
                rep.exec_err += 1
            elif verdict.type == "BOTH_EMPTY":
                rep.both_empty += 1

        rep.details.append({
            "question": q, "gold": gold, "pred": pred,
            "match": "exact" if is_exact else ("flexible" if is_flex else "miss"),
            "exec": verdict.type,
        })
    return rep


# ---------------------------------------------------------------------------
def main() -> int:
    ap = argparse.ArgumentParser(description="3-layer 평가 + TYPE_A 보정")
    ap.add_argument("--layer", choices=[*LAYERS, "all"], default="blind")
    ap.add_argument("--exec", action="store_true", help="MySQL 실행 기반 TYPE_A 보정")
    ap.add_argument("--no-model", action="store_true", help="모델 로드 없이(드라이런)")
    ap.add_argument("--gold-as-pred", action="store_true", help="gold를 pred로 사용(채점 점검)")
    ap.add_argument("--base", action="store_true", help="순수 base 모델 설정")
    ap.add_argument("--out", default="", help="상세 결과 JSON 저장 경로")
    ap.add_argument("--limit", type=int, default=0, help="레이어당 평가 문항 수 제한(스모크)")
    args = ap.parse_args()

    pipeline = None
    if not args.gold_as_pred:
        from inference import NL2SQLPipeline
        cfg = config.PipelineConfig.for_base_model() if args.base else config.PipelineConfig.for_finetuned()
        pipeline = NL2SQLPipeline(cfg, load_model=not args.no_model)

    executor = None
    if args.exec:
        try:
            executor = MySQLExecutor().connect()
            print(f"[eval] MySQL 연결: {config.MYSQL.database}")
        except Exception as e:
            print(f"[eval] MySQL 연결 실패 → 실행 보정 생략: {e}")

    targets = list(LAYERS) if args.layer == "all" else [args.layer]
    all_details = {}
    for layer in targets:
        path = LAYERS[layer]
        if not Path(path).exists():
            print(f"[eval] 건너뜀(파일 없음): {path}")
            continue
        rep = evaluate_layer(layer, path, pipeline, executor, args.gold_as_pred, limit=args.limit)
        print("=" * 60)
        print(rep.summary())
        all_details[layer] = rep.details

    if args.out and all_details:
        Path(args.out).write_text(
            json.dumps(all_details, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"\n[eval] 상세 결과 저장 → {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
