"""
schema_pruning.py — [Step 1] 관련 테이블 DDL만 선택.

- 6개 테이블 Full DDL이 context window의 37~88% 차지
  - 질문 키워드 분석 → 관련 테이블만 추출
  - Full DDL ~1,529 토큰 → Pruned DDL ~368 토큰
  - Pruned DDL의 진짜 가치는 "짧은 컨텍스트"로 모델이 (RAG) 예제에 집중하게 하는 것

기본은 키워드 매칭 방식.
임베딩 기반 고도화 — 동일 임베딩 모델(paraphrase-multilingual-MiniLM)
로 질문과 테이블 설명을 비교해 "등록비가 얼마야?" → sc_conf_fee를 올바로 선택하는
모드(embedding/hybrid)도 제공한다.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

import config
from src import schema_utils

# 테이블별 트리거 키워드 (질문에 등장하면 해당 테이블을 후보로 선택)
TABLE_KEYWORDS: dict[str, set[str]] = {
    "sc_users": {
        "회원", "정회원", "준회원", "종신회원", "사용자", "유저", "멤버",
        "승인", "회비", "만료", "유효", "마일리지", "가입", "활성", "등급",
    },
    "sc_class": {"등급", "정회원", "준회원", "종신회원", "등급명", "분류", "유형"},
    "sc_user_orders": {"결제", "주문", "환불", "금액", "구매", "이력", "확인"},
    "sc_conf_conference": {
        "학술대회", "학술행사", "행사", "대회", "컨퍼런스",
        "춘계", "추계", "하계", "동계", "봄", "여름", "가을", "겨울",
        "초록", "논문", "사전등록", "개최", "장소", "계절", "시즌",
        "기간", "일정", "연도", "개최연도",
    },
    "sc_conf_fee": {"등록비", "연회비", "논문등록비", "참가비", "금액", "코드",
                    "선택", "필수", "뱅큇"},
    "sc_conf_registrant": {"등록자", "등록한", "참가자", "소속", "기관", "제출",
                           "결제자", "무통장", "결제방식", "결제수단"},
}

# 등급명(한글)이 등장하면 sc_users ↔ sc_class JOIN이 필요
CLASS_JOIN_HINTS = {"정회원", "준회원", "종신회원", "명예회원", "학생회원", "등급명"}

# 행사 필터(계절/연도)가 있을 때만 conference JOIN이 필요. 단순 "학술대회 등록자 중
# OO 소속" 같은 질문은 등록자(sc_conf_registrant) 단독으로 충분(소속=r.institution).
SEASON_HINTS = {"춘계", "추계", "하계", "동계", "봄", "여름", "가을", "겨울"}
_YEAR_RE = re.compile(r"\d{2,4}\s*년")


def _has_conf_filter(q: str) -> bool:
    return any(h in q for h in SEASON_HINTS) or bool(_YEAR_RE.search(q))


@dataclass
class PruneResult:
    tables: list[str]
    ddl: str
    reason: str


class SchemaPruner:
    def __init__(
        self,
        with_comment: bool = False,
        schema_path: str | None = None,
        mode: str = "keyword", # keyword | embedding | hybrid
        embed_threshold: float | None = None,
        embed_top_k: int | None = None,
    ):
        self.with_comment = with_comment
        self.schema_path = schema_path
        self.table_keywords = TABLE_KEYWORDS
        self.all_tables = schema_utils.all_table_names(schema_path)
        self.mode = mode
        pcfg = config.PipelineConfig
        self.embed_threshold = embed_threshold if embed_threshold is not None else pcfg.pruning_embed_threshold
        self.embed_top_k = embed_top_k if embed_top_k is not None else pcfg.pruning_embed_top_k
        self._embedder = None
        self._table_matrix = None # (T, 384) 테이블 설명 임베딩

    # ------------------------------------------------------------------
    def prune(self, question: str) -> PruneResult:
        if self.mode == "embedding":
            selected, reason = self._select_by_embedding(question)
        elif self.mode == "hybrid":
            kw, _ = self._select_by_keyword(question)
            emb, _ = self._select_by_embedding(question)
            selected = [t for t in self.all_tables if t in set(kw) | set(emb)]
            reason = f"hybrid: 키워드 {len(kw)} ∪ 임베딩 {len(emb)} → {len(selected)}개"
        else:
            selected, reason = self._select_by_keyword(question)

        selected = [t for t in self.all_tables if t in selected] # 정의 순서
        ddl = schema_utils.render_ddl(
            selected, with_comment=self.with_comment, path=self.schema_path
        )
        return PruneResult(tables=selected, ddl=ddl, reason=reason)

    # ------------------------------------------------------------------
    def _select_by_keyword(self, question: str) -> tuple[list[str], str]:
        q = question
        selected: list[str] = []
        for table in self.all_tables:
            kws = self.table_keywords.get(table, set())
            if any(kw in q for kw in kws):
                selected.append(table)

        # 등급 한글명 조회는 sc_class JOIN 필요 — sc_users도 함께 포함
        if any(h in q for h in CLASS_JOIN_HINTS):
            for t in ("sc_users", "sc_class"):
                if t not in selected:
                    selected.append(t)

        # 행사 필터(계절/연도)가 있으면 conference JOIN, 없으면 registrant 단독으로 충분.
        # "학술대회 중 OO 소속인 사람"처럼 행사 필터 없는 질문에서 conference를 빼
        # 모델이 r.institution 대신 c.hostingInstitution을 쓰는 오류를 방지한다.
        if "sc_conf_registrant" in selected:
            if _has_conf_filter(q):
                if "sc_conf_conference" not in selected:
                    selected.append("sc_conf_conference")
            elif "sc_conf_conference" in selected:
                selected.remove("sc_conf_conference")

        if not selected:
            return ["sc_users"], "키워드 미매칭 → 기본 테이블(sc_users)"
        return selected, f"키워드 매칭 테이블 {len(selected)}개"

    # ------------------------------------------------------------------
    def _select_by_embedding(self, question: str) -> tuple[list[str], str]:
        import numpy as np

        self._ensure_embed_index()
        qvec = self._embedder.encode(question, normalize_embeddings=True)
        sims = self._table_matrix @ qvec # 코사인 유사도
        order = np.argsort(-sims)

        selected = [self.all_tables[i] for i in order if sims[i] >= self.embed_threshold]
        if not selected: # 임계값 미달이면 top-k 보장
            selected = [self.all_tables[i] for i in order[: self.embed_top_k]]
        top = float(sims[order[0]])
        return selected, f"임베딩 매칭 {len(selected)}개 (top sim={top:.2f})"

    def _ensure_embed_index(self) -> None:
        if self._table_matrix is not None:
            return
        from sentence_transformers import SentenceTransformer

        schema = schema_utils.load_schema(self.schema_path)
        descriptions = []
        for name in self.all_tables:
            tbl = schema[name]
            cols = " ".join(f"{c.name} {c.comment}" for c in tbl.columns)
            descriptions.append(f"{name} {tbl.comment} {cols}")
        self._embedder = SentenceTransformer(config.EMBED_MODEL)
        self._table_matrix = self._embedder.encode(
            descriptions, normalize_embeddings=True, convert_to_numpy=True
        )
