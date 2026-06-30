"""
conversation.py — 멀티턴 대화 지원.

단발성(질문 1 → SQL 1) 구조를 세션 기반 멀티턴으로 확장한다.
후속 질문("이 중에서 정회원만")이 들어오면 직전 턴의 SQL을 컨텍스트로 제공해
모델이 조건을 더하거나 수정하도록 한다.

  턴1: "2026년 학술대회 등록자 수" → SELECT COUNT(*) ...
  턴2: "이 중에서 정회원만" → (턴1 SQL 참조) WHERE 조건 추가

후속 질문 판별은 조응 표현(anaphora) 기반 휴리스틱이다.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime

# 후속(refinement) 질문 신호 — 직전 결과를 가리키는 조응 표현/수정 의도
FOLLOWUP_CUES = (
    "이 중", "이중", "그 중", "그중", "여기서", "거기서", "위 결과", "방금",
    "앞서", "이전", "그 결과", "그것", "이것들", "그들", "이들",
    "추가로", "거기에", "더해서", "빼고", "제외하고", "필터", "다시",
    "정렬해", "정렬", "상위", "하위", "그럼", "그러면", "그리고",
)
# 후속 신호가 cue 없이도 성립하는 짧은 수정 명령 패턴
_SHORT_REFINE = re.compile(r"^(정회원|준회원|승인|환불|취소|최근|오래된)?\s*(만|들만|중)?\s*$")


@dataclass
class Turn:
    question: str
    sql: str | None
    rejected: bool = False
    reason: str = ""
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))


@dataclass
class ConversationSession():
    turns: list[Turn] = field(default_factory=list)

    def add_turn(self, turn: Turn) -> None:
        self.turns.append(turn)

    @property
    def last_sql(self) -> str | None:
        for t in reversed(self.turns):
            if t.sql:
                return t.sql
        return None

    @property
    def last_question(self) -> str | None:
        return self.turns[-1].question if self.turns else None

    def recent(self, n: int = 1) -> list[Turn]:
        """SQL이 생성된 최근 n개 턴(오래된→최신 순)."""
        answered = [t for t in self.turns if t.sql]
        return answered[-n:]

    def reset(self) -> None:
        self.turns.clear


def is_followup(question: str, session: ConversationSession() | None) -> bool:
    """직전 SQL을 참조해야 하는 후속 질문인지 판별."""
    if not session or session.last_sql is None:
        return False
    q = question.strip()
    if any(cue in q for cue in FOLLOWUP_CUES):
        return True
    # 테이블/도메인 명사가 거의 없는 아주 짧은 수정 명령 (예: "정회원만")
    if len(q) <= 8 and _SHORT_REFINE.match(q):
        return True
    return False


def build_context_block(session: ConversationSession(), max_turns: int = 1) -> str:
    """프롬프트에 삽입할 이전 대화 컨텍스트 블록."""
    recent = session.recent(max_turns)
    if not recent:
        return ""
    lines = ["", "### 이전 대화 (후속 질문은 아래 SQL을 기반으로 조건을 더하거나 수정하라)"]
    for t in recent:
        lines.append(f"-- 이전 질문: {t.question}")
        lines.append(f"{t.sql.strip().rstrip(';')};")
    return "\n".join(lines)
