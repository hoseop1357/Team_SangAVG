"""
prompt_builder.py — [Step 3] 프롬프트 구성.

질문 + Pruned DDL (+ DDL COMMENT) + RAG 예제
  총 입력 토큰 ~368 (pruned, RAG 있을 때)

sqlcoder-7b-2 계열 프롬프트 포맷을 따른다. 생성은 [SQL] 직후부터 시작하고
[/SQL]에서 중단한다.
훈련(finetune.py)과 추론(inference)이 동일 템플릿을 써야 분포가 일치한다.
"""
from __future__ import annotations

from dataclasses import dataclass

from src.rag import Example

# 학습/추론 공통 템플릿. {examples}는 RAG OFF일 때 빈 문자열.
PROMPT_TEMPLATE = """### Task
다음 질문에 답하는 단일 MySQL SELECT 쿼리를 생성하라.
[QUESTION]{question}[/QUESTION]

### Database Schema
쿼리는 아래 스키마의 DB에서 실행된다:
{schema}
{examples}{context}
### Answer
주어진 스키마에 근거하여, 위 질문에 답하는 SQL 쿼리는 다음과 같다:
[SQL]"""

EXAMPLE_BLOCK = """
### Examples
유사한 질문-SQL 예시:
{examples}
"""


@dataclass
class BuiltPrompt:
    text: str
    used_examples: int


class PromptBuilder():
    def __init__(self, template: str = PROMPT_TEMPLATE):
        self.template = template

    def build(
        self,
        question: str,
        schema_ddl: str,
        examples: list[tuple[Example, float]] | None = None,
        context_block: str = "",
    ) -> BuiltPrompt:
        examples = examples or []
        if examples:
            rendered = "\n".join(
                f"-- Q: {ex.question}\n{ex.sql.strip().rstrip(';')};"
                for ex, _sim in examples
            )
            example_text = EXAMPLE_BLOCK.format(examples=rendered)
        else:
            example_text = ""

        text = self.template.format(
            question=question.strip(),
            schema=schema_ddl.strip(),
            examples=example_text,
            context=context_block, # ⑦ 멀티턴 대화 컨텍스트 (기본 "")
        )
        return BuiltPrompt(text=text, used_examples=len(examples))

    @staticmethod
    def format_training_example(prompt_text: str, target_sql: str) -> str:
        """finetune.py용: 프롬프트 + 정답 SQL + [/SQL] (라벨 포함 전체 시퀀스)."""
        sql = target_sql.strip().rstrip(";")
        return f"{prompt_text}\n{sql};\n[/SQL]"
