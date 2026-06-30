"""
rag.py — [Step 2] 유사 질문-SQL 예제 검색 (선택적).

- 4,412개 훈련 페어에서 코사인 유사도 top-3 검색
  - 같은 도메인 그룹 내에서만 검색 (회원/학술대회/등록비 등)
  - RAG 기여(+22.4%p)의 90%가 few-shot 예제에서 옴
  - 단, 파인튜닝(v46) 모델에서는 RAG가 오히려 -3.8%p → 기본 OFF

임베딩: sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2 (384차원).
도메인 그룹은 정답 SQL이 참조하는 테이블 집합으로 자동 추정한다.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import config

# 도메인 그룹 정의 — 같은 그룹 내에서만 예제 검색
DOMAIN_GROUPS = {
    "member": {"sc_users", "sc_class", "sc_user_orders"},
    "conference": {"sc_conf_conference", "sc_conf_fee", "sc_conf_registrant"},
}


def infer_domain(tables: set[str]) -> str:
    """선택된 테이블 집합으로 도메인 그룹 추정 (겹침 최대 그룹)."""
    best, best_overlap = "member", -1
    for name, group in DOMAIN_GROUPS.items():
        overlap = len(tables & group)
        if overlap > best_overlap:
            best, best_overlap = name, overlap
    # 두 그룹에 모두 걸치는 크로스 도메인 질문
    if tables & DOMAIN_GROUPS["member"] and tables & DOMAIN_GROUPS["conference"]:
        return "cross"
    return best


@dataclass
class Example:
    question: str
    sql: str
    tables: set[str]
    domain: str


class RagRetriever:
    """훈련 페어를 임베딩 인덱싱하고 코사인 유사도 top-k 예제를 검색한다."""

    def __init__(self, pairs_path: str | None = None, embed_model: str | None = None):
        self.pairs_path = Path(pairs_path) if pairs_path else config.TRAIN_PAIRS_PATH
        self.embed_model = embed_model or config.EMBED_MODEL
        self._embedder = None
        self._examples: list[Example] = []
        self._matrix = None # (N, 384) 정규화 임베딩

    # ------------------------------------------------------------------
    def _ensure_index(self) -> None:
        if self._matrix is not None:
            return
        import numpy as np
        from sentence_transformers import SentenceTransformer

        raw = json.loads(Path(self.pairs_path).read_text(encoding="utf-8"))
        for item in raw:
            sql = item["sql"]
            tables = _tables_in_sql(sql)
            self._examples.append(
                Example(
                    question=item["question"],
                    sql=sql,
                    tables=tables,
                    domain=infer_domain(tables),
                )
            )
        self._embedder = SentenceTransformer(self.embed_model)
        if self._examples:
            self._matrix = self._embedder.encode(
                [e.question for e in self._examples],
                normalize_embeddings=True,
                convert_to_numpy=True,
            )
        else:
            self._matrix = np.zeros((0, 384), dtype="float32")

    # ------------------------------------------------------------------
    def retrieve(
        self, question: str, tables: set[str], top_k: int | None = None
    ) -> list[tuple[Example, float]]:
        import numpy as np

        self._ensure_index()
        if not self._examples:
            return []
        top_k = top_k or config.PipelineConfig.rag_top_k

        q_domain = infer_domain(tables)
        # 같은 도메인 그룹 내에서만 검색 (cross는 전체 허용)
        idx = [
            i for i, e in enumerate(self._examples)
            if q_domain == "cross" or e.domain == q_domain or e.domain == "cross"
        ]
        if not idx:
            idx = list(range(len(self._examples)))

        qvec = self._embedder.encode(question, normalize_embeddings=True)
        sims = self._matrix[idx] @ qvec # 정규화 → 내적 = 코사인 유사도
        order = np.argsort(-sims)[:top_k]
        return [(self._examples[idx[j]], float(sims[j])) for j in order]


def _tables_in_sql(sql: str) -> set[str]:
    """SQL 문자열에서 참조 테이블 추출 (도메인 그룹 추정용, 가벼운 매칭)."""
    found = set()
    low = sql.lower()
    for t in (
        "sc_users", "sc_class", "sc_user_orders",
        "sc_conf_conference", "sc_conf_fee", "sc_conf_registrant",
    ):
        if t in low:
            found.add(t)
    return found
