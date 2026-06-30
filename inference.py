"""
inference.py — NL2SQL 추론 파이프라인 엔드투엔드.

자연어 질문 → [0]Intent → [1]Pruning → [2]RAG → [3]Prompt
            → [4]모델추론 → [5]postprocess → [6]Validator → 최종 SQL

사용:
  python inference.py "2026년 춘계 학술대회에 등록한 정회원 수는?"
  python inference.py --base "..." # 순수 base 모델 설정(RAG ON)
  python inference.py --no-model "..." # 모델 없이 파이프라인 흐름만 점검(드라이런)
"""
from __future__ import annotations

import argparse
import sys
from dataclasses import asdict, dataclass, field

import config
from src.conversation import ConversationSession, Turn, build_context_block, is_followup
from src.intent_classifier import IntentClassifier
from src.postprocess import postprocess_sql
from src.prompt_builder import PromptBuilder
from src.schema_pruning import SchemaPruner
from src.validator import SQLValidator


@dataclass
class PipelineResult:
    question: str
    sql: str | None
    rejected: bool = False
    reject_reason: str = ""
    steps: dict = field(default_factory=dict)


class NL2SQLPipeline:
    def __init__(self, pcfg: config.PipelineConfig | None = None, load_model: bool = True):
        self.cfg = pcfg or config.PipelineConfig.for_finetuned()
        self.intent = IntentClassifier()
        self.pruner = SchemaPruner(
            with_comment=self.cfg.use_ddl_comment,
            mode=self.cfg.schema_pruning_mode, # ⑥ keyword|embedding|hybrid
        )
        self.prompter = PromptBuilder()
        self.validator = SQLValidator(default_limit=self.cfg.default_limit)

        # RAG / 모델 / 실행검증기 / 피드백은 무거우므로 지연 로딩
        self._rag = None
        self._model = None
        self._exec_checker = None
        self._feedback = None
        self._load_model = load_model

    # ------------------------------------------------------------------
    def run(
        self,
        question: str,
        session: ConversationSession() | None = None,
        record_to_session: bool = True,
    ) -> PipelineResult:
        steps: dict = {}
        # ⑦ 후속 질문 판별 (직전 SQL 참조가 필요한 refinement 질문인지)
        followup = self.cfg.multi_turn and is_followup(question, session)

        # [Step 0] Intent
        if self.cfg.use_intent_filter:
            intent = self.intent.classify(question)
            steps["intent"] = asdict(intent)
            # 후속 질문은 도메인 명사가 적어 Intent가 거부할 수 있으므로 예외 통과
            if not intent.is_db_related and not followup:
                return self._finalize(PipelineResult(
                    question=question, sql=None, rejected=True,
                    reject_reason=intent.reason, steps=steps,
                ), session, record_to_session)

        import src.schema_utils as su

        # [Step 1] Schema Pruning (테이블 선택)
        if self.cfg.use_schema_pruning:
            pruned = self.pruner.prune(question)
            tables = pruned.tables
            steps["pruning"] = {"tables": tables, "reason": pruned.reason}
        else:
            tables = su.all_table_names()
            steps["pruning"] = {"tables": tables, "reason": "pruning OFF (full DDL)"}

        # [Step 2] RAG (선택적) + ⑦ 피드백 플라이휠 예제
        examples = []
        if self.cfg.use_rag:
            examples = self._get_rag().retrieve(question, set(tables), self.cfg.rag_top_k)
            steps["rag"] = [
                {"question": ex.question, "similarity": round(sim, 3)}
                for ex, sim in examples
            ]
        if self.cfg.use_feedback:
            fb = self._get_feedback().relevant_examples(question, self.cfg.feedback_top_k)
            if fb:
                examples = fb + examples # 교정 예제를 우선 배치
                steps["feedback"] = [
                    {"question": ex.question, "similarity": round(sim, 3)} for ex, sim in fb
                ]

        # [⑤ Adaptive COMMENT] 검색된 예제 유사도가 낮으면 COMMENT로 도메인 힌트 보완
        use_comment = self.cfg.use_ddl_comment
        if self.cfg.adaptive_comment:
            top_sim = max((sim for _ex, sim in examples), default=0.0)
            use_comment = top_sim < self.cfg.adaptive_comment_threshold
            steps["adaptive_comment"] = {
                "top_similarity": round(top_sim, 3),
                "threshold": self.cfg.adaptive_comment_threshold,
                "use_comment": use_comment,
            }

        # DDL은 COMMENT 결정 이후 최종 렌더링
        ddl = su.render_ddl(tables, with_comment=use_comment)

        # [⑦ 멀티턴] 후속 질문이면 직전 SQL을 컨텍스트로 주입
        context_block = ""
        if followup and session is not None:
            context_block = build_context_block(session, self.cfg.context_max_turns)
            steps["multi_turn"] = {"followup": True, "context_turns": self.cfg.context_max_turns}

        # [Step 3] Prompt
        built = self.prompter.build(question, ddl, examples, context_block=context_block)
        steps["prompt"] = {"used_examples": built.used_examples, "chars": len(built.text)}

        # [Step 4] 모델 추론
        if not self._load_model:
            steps["model"] = "SKIPPED (dry-run)"
            return self._finalize(
                PipelineResult(question=question, sql=None, steps=steps),
                session, record_to_session,
            )
        gen = self._get_model().generate(built.text)
        raw_sql = gen.raw
        steps["model"] = {"prompt_tokens": gen.prompt_tokens, "new_tokens": gen.new_tokens}

        # [Step 5] postprocess
        sql = postprocess_sql(raw_sql) if self.cfg.use_postprocess else raw_sql
        steps["postprocess"] = sql

        # [Step 6] Validator
        if self.cfg.use_validator:
            vr = self.validator.validate(sql)
            steps["validator"] = {
                "blocked": vr.blocked, "removed_columns": vr.removed_columns,
                "added_limit": vr.added_limit, "reason": vr.block_reason,
            }
            if vr.blocked:
                return self._finalize(PipelineResult(
                    question=question, sql=None, rejected=True,
                    reject_reason=f"Validator 차단: {vr.block_reason}", steps=steps,
                ), session, record_to_session)
            sql = vr.sql

        # [⑧ 실행 결과 기반 자동 검증] 경고만 — SQL은 그대로 반환
        if self.cfg.exec_check and sql:
            checker = self._get_exec_checker()
            if checker is not None:
                result = checker.check(sql)
                steps["exec_check"] = {
                    "ran": result.ran, "row_count": result.row_count,
                    "warnings": result.warnings, "error": result.error,
                }

        return self._finalize(
            PipelineResult(question=question, sql=sql, steps=steps),
            session, record_to_session,
        )

    # ------------------------------------------------------------------
    def _finalize(
        self,
        result: PipelineResult,
        session: ConversationSession() | None,
        record: bool,
    ) -> PipelineResult:
        """⑦ 결과를 세션 히스토리에 기록(멀티턴 컨텍스트 누적)."""
        if session is not None and record:
            session.add_turn(Turn(
                question=result.question, sql=result.sql,
                rejected=result.rejected, reason=result.reject_reason,
            ))
        return result

    def record_feedback(
        self, question: str, predicted_sql: str, corrected_sql: str, note: str = ""
    ) -> None:
        """⑦ 사용자가 교정한 SQL을 피드백 스토어에 누적 → 다음 쿼리 예제로 활용."""
        self._get_feedback().add(question, predicted_sql, corrected_sql, "edited", note)

    def _get_feedback(self):
        if self._feedback is None:
            from src.feedback import FeedbackStore
            self._feedback = FeedbackStore()
        return self._feedback

    def _get_rag(self):
        if self._rag is None:
            from src.rag import RagRetriever
            self._rag = RagRetriever()
        return self._rag

    def _get_model(self):
        if self._model is None:
            from src.model import SqlCoderModel
            self._model = SqlCoderModel().load()
        return self._model

    def _get_exec_checker(self):
        if self._exec_checker is None:
            from src.exec_check import ExecutionChecker
            try:
                self._exec_checker = ExecutionChecker(
                    warn_max_rows=self.cfg.exec_warn_max_rows
                ).connect()
            except Exception as e: # noqa: BLE001
                print(f"[exec_check] DB 연결 실패 → 실행 검증 생략: {e}")
                self._exec_checker = False # 재시도 방지 sentinel
        return self._exec_checker or None


# ---------------------------------------------------------------------------
def main() -> int:
    ap = argparse.ArgumentParser(description="NL2SQL 추론")
    ap.add_argument("question", nargs="*", help="자연어 질문")
    ap.add_argument("--base", action="store_true", help="순수 base 모델 설정 (RAG ON)")
    ap.add_argument("--no-model", action="store_true", help="모델 없이 드라이런")
    ap.add_argument("--rag", action="store_true", help="RAG 강제 ON")
    ap.add_argument("--pruning-mode", choices=["keyword", "embedding", "hybrid"],
                    default=None, help="⑥ Schema Pruning 방식")
    ap.add_argument("--adaptive-comment", action="store_true",
                    help="⑤ 유사도 기반 DDL COMMENT 동적 전환")
    ap.add_argument("--exec-check", action="store_true",
                    help="⑧ 실행 결과 기반 자동 검증(경고)")
    ap.add_argument("--chat", action="store_true",
                    help="⑦ 멀티턴 대화 모드(REPL). 후속 질문이 직전 SQL을 참조")
    ap.add_argument("--feedback", action="store_true",
                    help="⑦ 피드백 플라이휠: 교정 SQL을 예제로 주입")
    args = ap.parse_args()

    cfg = config.PipelineConfig.for_base_model() if args.base else config.PipelineConfig.for_finetuned()
    if args.rag:
        cfg.use_rag = True
    if args.pruning_mode:
        cfg.schema_pruning_mode = args.pruning_mode
    if args.adaptive_comment:
        cfg.adaptive_comment = True
    if args.exec_check:
        cfg.exec_check = True
    if args.feedback:
        cfg.use_feedback = True
    if args.chat:
        cfg.multi_turn = True

    pipe = NL2SQLPipeline(cfg, load_model=not args.no_model)

    if args.chat:
        return chat_loop(pipe)

    question = " ".join(args.question).strip()
    if not question:
        print("질문을 입력하세요. 예) python inference.py \"2026년 등록자 수는?\"")
        return 1
    print_result(pipe.run(question))
    return 0


def print_result(result: PipelineResult) -> None:
    print("=" * 60)
    print(f"Q: {result.question}")
    print("-" * 60)
    if result.rejected:
        print(f"[거부] {result.reject_reason}")
    elif result.sql:
        print(result.sql)
    else:
        print("(SQL 생성 안 됨)")
    print("-" * 60)
    for name, info in result.steps.items():
        print(f" · {name}: {info}")


def chat_loop(pipe: "NL2SQLPipeline") -> int:
    """⑦ 멀티턴 REPL. 명령: /reset 세션 초기화 /fix <SQL> 직전 답을 교정·저장 /quit 종료"""
    session = ConversationSession()
    print("멀티턴 대화 모드. 후속 질문 예) '이 중에서 정회원만'")
    print("명령: /reset(세션 초기화) /fix <교정 SQL>(피드백 저장) /quit(종료)\n")
    while True:
        try:
            q = input("you> ").strip()
        except (EOFError, KeyboardInterrupt):
            print
            return 0
        if not q:
            continue
        if q in ("/quit", "/exit"):
            return 0
        if q == "/reset":
            session.reset()
            print("[세션 초기화됨]\n")
            continue
        if q.startswith("/fix "):
            corrected = q[len("/fix "):].strip()
            last = session.turns[-1] if session.turns else None
            if last is None:
                print("[교정할 직전 답이 없습니다]\n")
                continue
            pipe.record_feedback(last.question, last.sql or "", corrected,
                                 note="대화 중 사용자 교정")
            last.sql = corrected # 세션 컨텍스트도 교정본으로 갱신
            print("[피드백 저장됨 — 다음 쿼리부터 예제로 활용]\n")
            continue

        result = pipe.run(q, session=session)
        if result.rejected:
            sql = f"(거부: {result.reject_reason})"
        else:
            sql = result.sql or "(SQL 없음)"
        tag = " [후속]" if result.steps.get("multi_turn") else ""
        print(f"sql>{tag} {sql}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
