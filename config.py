"""
config.py — 전역 설정

NL2SQL: 학회 관리 DB 대상 한국어 자연어 → MySQL 변환 시스템
베이스 모델: defog/sqlcoder-7b-2 (+ QLoRA 도메인 어댑터)
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

# ---------------------------------------------------------------------------
# 경로
# ---------------------------------------------------------------------------
ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
SCHEMA_PATH = ROOT / "schema.sql"

# 학습 산출물(어댑터) 위치 — finetune.py가 저장, inference/evaluate가 로드
ADAPTER_DIR = os.environ.get("NL2SQL_ADAPTER", str(ROOT / "outputs" / "v46"))

# 데이터 파일
TRAIN_PAIRS_PATH = DATA_DIR / "train_pairs.json" # 4,412 페어 (data_gen으로 생성)
BLIND_TEST_PATH = DATA_DIR / "blind_test_all6_tables.json" # 214문항
COVERAGE_TEST_PATH = DATA_DIR / "column_coverage_test_v2.json" # 680문항
TARGETED_TEST_PATH = DATA_DIR / "targeted_test_v2.json" # 300문항
FEEDBACK_STORE_PATH = DATA_DIR / "feedback_store.json" # 피드백 플라이휠


# ---------------------------------------------------------------------------
# 베이스 모델 / 양자화
# ---------------------------------------------------------------------------
BASE_MODEL = "defog/sqlcoder-7b-2" # LLaMA-2 7B 기반 SQL 특화 사전학습 모델
MAX_LENGTH = 4096 # context window 한계
EMBED_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2" # 384차원, 50개국어


# ---------------------------------------------------------------------------
# QLoRA 하이퍼파라미터
# ---------------------------------------------------------------------------
@dataclass
class LoRAConfig:
    r: int = 16 # 랭크. 표현력 ↔ 메모리 균형
    alpha: int = 32 # 스케일 (α/r = 2)
    dropout: float = 0.05 # 소량 데이터 과적합 방지
    # Attention + FFN 전 레이어
    target_modules: tuple[str, ...] = (
        "q_proj", "k_proj", "v_proj", "o_proj",
        "gate_proj", "up_proj", "down_proj",
    )
    bias: str = "none"
    task_type: str = "CAUSAL_LM"


@dataclass
class TrainConfig:
    learning_rate: float = 2e-4 # 코사인 스케줄러
    lr_scheduler_type: str = "cosine"
    per_device_batch_size: int = 4
    gradient_accumulation_steps: int = 4 # 실효 배치 4×4 = 16
    num_epochs: int = 8 # v46 기준 (early stopping으로 조기 종료 가능)
    warmup_ratio: float = 0.03
    weight_decay: float = 0.0
    early_stopping_patience: int = 3 # val_loss 기준
    eval_steps: int = 50
    save_steps: int = 50
    logging_steps: int = 10
    max_length: int = MAX_LENGTH
    seed: int = 42


# ---------------------------------------------------------------------------
# 추론 생성 파라미터
# ---------------------------------------------------------------------------
@dataclass
class GenConfig:
    max_new_tokens: int = 400
    do_sample: bool = False # Greedy Decoding
    num_beams: int = 1
    stop_token: str = "[/SQL]" # [/SQL] 감지 시 즉시 중단


# ---------------------------------------------------------------------------
# 추론 시점 기술 토글
# - Fine-tuning 완료 후에는 RAG/COMMENT 끄는 것이 최적 (발견 4)
# - base 모델만 있을 때는 RAG ON 권장
# ---------------------------------------------------------------------------
@dataclass
class PipelineConfig:
    use_intent_filter: bool = True # Step 0
    use_schema_pruning: bool = True # Step 1
    use_rag: bool = False # Step 2 — 파인튜닝 모델에서는 기본 OFF (-3.8%p)
    use_ddl_comment: bool = False # 파인튜닝 모델에서는 기본 OFF (RAG와 함께 -4.6%p)
    use_postprocess: bool = True # Step 5
    use_validator: bool = True # Step 6
    rag_top_k: int = 3 # 코사인 유사도 top-3
    rag_similarity_floor: float = 0.0 # Adaptive COMMENT용 임계값 참고(0.75)
    default_limit: int = 100 # LIMIT 자동 추가

    # --- 개선안 ---
    # ⑤ Adaptive COMMENT: RAG 예제 유사도가 낮으면 COMMENT로 도메인 힌트 보완
    adaptive_comment: bool = False
    adaptive_comment_threshold: float = 0.75 # top 유사도 < 0.75 → COMMENT ON
    # ⑥ Schema Pruning 모드: keyword(현행) | embedding | hybrid
    schema_pruning_mode: str = "keyword"
    pruning_embed_threshold: float = 0.30 # 임베딩 유사도 채택 임계값
    pruning_embed_top_k: int = 3 # 최소 보장 테이블 수
    # ⑧ 실행 결과 기반 자동 검증(경고만, SQL은 그대로 반환)
    exec_check: bool = False
    exec_warn_max_rows: int = 10000 # 초과 시 "조건이 너무 넓음" 경고
    # ⑦ 멀티턴 대화 + 피드백 플라이휠
    multi_turn: bool = False # 후속 질문 시 직전 SQL 컨텍스트 참조
    context_max_turns: int = 1 # 컨텍스트로 넣을 직전 턴 수
    use_feedback: bool = False # 교정된 SQL을 few-shot 예제로 주입
    feedback_top_k: int = 2

    @classmethod
    def for_base_model(cls) -> "PipelineConfig":
        """순수 base 모델용 권장 설정 (RAG ON, COMMENT OFF, Pruned DDL) → ~44%."""
        return cls(use_rag=True, use_ddl_comment=False, use_schema_pruning=True)

    @classmethod
    def for_finetuned(cls) -> "PipelineConfig":
        """파인튜닝(v46) 권장 설정 (깔끔한 DDL만) → ~83%."""
        return cls(use_rag=False, use_ddl_comment=False, use_schema_pruning=True)


# ---------------------------------------------------------------------------
# MySQL 평가 DB 접속 (TYPE_A 보정용 실행 검증)
# ---------------------------------------------------------------------------
@dataclass
class MySQLConfig:
    host: str = os.environ.get("NL2SQL_DB_HOST", "127.0.0.1")
    port: int = int(os.environ.get("NL2SQL_DB_PORT", "3306"))
    user: str = os.environ.get("NL2SQL_DB_USER", "root")
    password: str = os.environ.get("NL2SQL_DB_PASSWORD", "")
    database: str = os.environ.get("NL2SQL_DB_NAME", "society_db")


LORA = LoRAConfig
TRAIN = TrainConfig
GEN = GenConfig
MYSQL = MySQLConfig
