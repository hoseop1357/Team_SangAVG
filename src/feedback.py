"""
feedback.py — 피드백 플라이휠.

사용자가 수정한 SQL을 feedback_store.json에 누적하고, 이후 쿼리에서 유사한
질문의 "교정된 정답 SQL"을 few-shot 예제로 즉시 활용한다.
멀티턴 대화 + 피드백을 결합하면 사용자가 고친 SQL이 바로 다음 쿼리에 반영된다.

저장 형식(기존 data/feedback_store.json과 동일):
  { "version": 1, "entries": [
      {timestamp, question, predicted_sql, corrected_sql, user_action, note}, ... ] }

기본 검색은 토큰 Jaccard 유사도(의존성 없음). RAG와 동일하게 Example로 변환해
PromptBuilder에 주입한다.
"""
from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path

import config
from src.rag import Example, _tables_in_sql, infer_domain

_TOKEN = re.compile(r"[0-9A-Za-z가-힣]+")


def _char_ngrams(text: str, n: int = 2) -> set[str]:
    """
    문자 n-gram 집합. 한국어 조사(정회원/정회원이/정회원만)로 어절이 달라져도
    형태소 분석기 없이 강건하게 유사도를 측정하기 위함.
    """
    s = "".join(_TOKEN.findall(text or "")) # 공백/기호 제거, 문자만
    if len(s) < n:
        return {s} if s else set()
    return {s[i:i + n] for i in range(len(s) - n + 1)}


def _similarity(a: str, b: str) -> float:
    ga, gb = _char_ngrams(a), _char_ngrams(b)
    if not ga or not gb:
        return 0.0
    union = ga | gb
    return len(ga & gb) / len(union) if union else 0.0


class FeedbackStore:
    def __init__(self, path: str | None = None):
        self.path = Path(path) if path else config.FEEDBACK_STORE_PATH
        self._data = self._load()

    # ------------------------------------------------------------------
    def _load(self) -> dict:
        if Path(self.path).exists():
            try:
                return json.loads(Path(self.path).read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                pass
        return {"version": 1, "entries": []}

    def _save(self) -> None:
        Path(self.path).write_text(
            json.dumps(self._data, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    @property
    def entries(self) -> list[dict]:
        return [e for e in self._data.get("entries", []) if isinstance(e, dict) and "question" in e]

    # ------------------------------------------------------------------
    def add(
        self,
        question: str,
        predicted_sql: str,
        corrected_sql: str,
        user_action: str = "edited",
        note: str = "",
    ) -> None:
        """사용자 피드백 1건 추가 후 저장."""
        self._data.setdefault("entries", []).append({
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "question": question,
            "predicted_sql": predicted_sql,
            "corrected_sql": corrected_sql,
            "user_action": user_action,
            "note": note,
        })
        self._save()

    # ------------------------------------------------------------------
    def relevant_examples(
        self, question: str, top_k: int = 2, min_overlap: float = 0.1
    ) -> list[tuple[Example, float]]:
        """질문과 문자 n-gram 유사도가 높은 교정 예제를 Example로 반환."""
        if not question.strip():
            return []
        scored: list[tuple[Example, float]] = []
        for e in self.entries:
            corrected = e.get("corrected_sql")
            if not corrected:
                continue
            sim = _similarity(question, e["question"])
            if sim < min_overlap:
                continue
            tables = _tables_in_sql(corrected)
            ex = Example(
                question=e["question"], sql=corrected,
                tables=tables, domain=infer_domain(tables),
            )
            scored.append((ex, sim))
        scored.sort(key=lambda x: -x[1])
        return scored[:top_k]
