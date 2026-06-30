"""
intent_classifier.py — [Step 0] 비관련 질문 차단.

목적: "맛집 추천" 같은 DB 무관 질문을 LLM 추론 비용 없이 즉시 거부.
DB 관련 질문만 파이프라인 다음 단계로 통과시킨다.

규칙 기반(키워드/도메인 어휘) 1차 필터 + 선택적 임베딩 유사도 2차 판정.
임베딩 모델은 무거우므로 기본은 규칙 기반만 사용한다.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

# 학회 DB 도메인 어휘 — 이 중 하나라도 등장하면 DB 관련으로 간주
DOMAIN_KEYWORDS = {
    # 회원
    "회원", "정회원", "준회원", "종신회원", "등급", "가입", "승인", "회비", "만료",
    "마일리지", "사용자", "유저", "멤버",
    # 결제/주문
    "결제", "주문", "환불", "금액", "가격", "구매", "이력",
    # 학술대회
    "학술대회", "대회", "춘계", "추계", "학회", "초록", "논문", "사전등록", "등록자",
    "등록비", "연회비", "개최", "장소", "계절", "시즌",
    # 조회/집계 동사
    "몇", "수는", "개수", "총", "합계", "평균", "최대", "최소", "목록", "리스트",
    "조회", "알려", "보여", "찾아", "검색", "얼마", "누구", "언제", "어디",
}

# 명백히 DB와 무관한 잡담/외부 도메인 신호
OFF_TOPIC_HINTS = {
    "맛집", "날씨", "주식", "코인", "여행", "노래", "영화", "게임", "레시피",
    "운세", "번역해", "농담", "시 써", "코드 짜",
}


@dataclass
class IntentResult:
    is_db_related: bool
    reason: str
    score: float = 0.0


class IntentClassifier():
    def __init__(
        self,
        domain_keywords: set[str] | None = None,
        off_topic_hints: set[str] | None = None,
        use_embedding: bool = False,
        embed_threshold: float = 0.35,
    ):
        self.domain_keywords = domain_keywords or DOMAIN_KEYWORDS
        self.off_topic_hints = off_topic_hints or OFF_TOPIC_HINTS
        self.use_embedding = use_embedding
        self.embed_threshold = embed_threshold
        self._embedder = None
        self._domain_centroid = None

    # ------------------------------------------------------------------
    def classify(self, question: str) -> IntentResult:
        q = question.strip()
        if not q:
            return IntentResult(False, "빈 질문")

        # 1) 명시적 off-topic 신호 → 즉시 거부
        for hint in self.off_topic_hints:
            if hint in q:
                return IntentResult(False, f"비관련 신호 감지: '{hint}'")

        # 2) 도메인 키워드 매칭 (규칙 기반 1차 필터)
        hits = [kw for kw in self.domain_keywords if kw in q]
        if hits:
            return IntentResult(True, f"도메인 키워드 {len(hits)}개 매칭", score=min(1.0, len(hits) / 3))

        # 3) 선택적 임베딩 2차 판정 (키워드로 못 거를 때만)
        if self.use_embedding:
            sim = self._embedding_similarity(q)
            if sim >= self.embed_threshold:
                return IntentResult(True, f"임베딩 유사도 {sim:.2f} ≥ {self.embed_threshold}", score=sim)
            return IntentResult(False, f"임베딩 유사도 {sim:.2f} 미달", score=sim)

        # 4) 키워드 0개 + 임베딩 미사용 → 보수적으로 거부
        return IntentResult(False, "도메인 키워드 미검출")

    # ------------------------------------------------------------------
    def _embedding_similarity(self, question: str) -> float:
        import numpy as np

        if self._embedder is None:
            from sentence_transformers import SentenceTransformer
            import config

            self._embedder = SentenceTransformer(config.EMBED_MODEL)
            anchors = self._embedder.encode(
                list(self.domain_keywords), normalize_embeddings=True
            )
            self._domain_centroid = anchors.mean(axis=0)
            self._domain_centroid /= np.linalg.norm(self._domain_centroid) + 1e-9

        vec = self._embedder.encode(question, normalize_embeddings=True)
        return float(np.dot(vec, self._domain_centroid))
