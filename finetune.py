"""
finetune.py — QLoRA 도메인 파인튜닝.

defog/sqlcoder-7b-2 를 4-bit NF4로 고정하고 LoRA 어댑터만 학습한다.
  W (4-bit NF4, ~4GB 고정) + LoRA 어댑터(~0.3GB 학습)
  → RTX A6000 단일 GPU로 훈련 가능

하이퍼파라미터:
  lora_r=16, lora_alpha=32, lora_dropout=0.05
  target_modules = q,k,v,o,gate,up,down proj
  lr=2e-4 (cosine), batch 4×4(grad accum)=16, early_stopping patience=3
  max_length=4096

학습 데이터 형식(train_pairs.sample.json):
  [{"question": "...", "sql": "...", "tables": ["sc_users", ...]}, ...]
프롬프트는 inference와 동일 템플릿(PromptBuilder())을 사용해 분포를 맞춘다.
v46은 "예제 없는 프롬프트"로만 학습 → 추론 시 RAG가 분포 이탈(-3.8%p).
(RAG-aware Fine-tuning): 훈련 데이터를 혼합 구성한다.
  70%: 기존 형식 (예제 없음) — 도메인 지식 학습
  30%: RAG 형식 (유사 예제 2~3개 포함) — 예제 활용 학습
  → Fine-tuning + RAG 시너지로 Blind+RAG 79.4% → 88~90% 기대.

사용:
  python finetune.py --data data/train_pairs.sample.json --output outputs/v46
  python finetune.py --data ... --rag-aware --rag-ratio 0.3 --output outputs/v47
"""
from __future__ import annotations

import argparse
import json
import random
from pathlib import Path

import config
from src import schema_utils
from src.prompt_builder import PromptBuilder
from src.schema_pruning import SchemaPruner


# ---------------------------------------------------------------------------
def build_dataset(
    data_path: Path,
    tokenizer,
    with_comment: bool,
    rag_aware: bool = False,
    rag_ratio: float = 0.3,
    rag_top_k: int = 2,
    seed: int = 42,
    max_length: int = config.MAX_LENGTH,
    limit: int = 0,
):
    """
    질문-SQL 페어를 (프롬프트 + 정답 SQL + [/SQL]) 시퀀스로 토크나이즈.
    rag_aware=True면 rag_ratio 비율의 샘플을 RAG 형식(유사 예제 포함)으로 구성한다.
    limit>0이면 앞 limit개만 사용(스모크용 서브셋).
    """
    from datasets import Dataset

    raw = json.loads(Path(data_path).read_text(encoding="utf-8"))
    if limit and limit > 0:
        raw = raw[:limit]
    pruner = SchemaPruner(with_comment=with_comment)
    prompter = PromptBuilder()

    # ④ RAG-aware: 일부 샘플을 RAG 형식으로 만들기 위한 검색기 (훈련셋 자체에서 검색)
    retriever = None
    rag_idx: set[int] = set()
    if rag_aware and len(raw) > rag_top_k + 1:
        from src.rag import RagRetriever

        retriever = RagRetriever(pairs_path=str(data_path))
        rng = random.Random(seed)
        n_rag = int(len(raw) * rag_ratio)
        rag_idx = set(rng.sample(range(len(raw)), n_rag))

    texts: list[str] = []
    for i, item in enumerate(raw):
        question, sql = item["question"], item["sql"]
        tables = item.get("tables")
        if tables:
            ddl = schema_utils.render_ddl(tables, with_comment=with_comment)
        else:
            ddl = pruner.prune(question).ddl

        examples = []
        if i in rag_idx and retriever is not None:
            # top-k 검색 후 자기 자신(같은 질문) 제외
            from src.rag import _tables_in_sql as _tin
            cand = retriever.retrieve(question, _tin(sql), top_k=rag_top_k + 1)
            examples = [(ex, s) for ex, s in cand if ex.question != question][:rag_top_k]

        built = prompter.build(question, ddl, examples=examples)
        texts.append(prompter.format_training_example(built.text, sql))

    if rag_aware:
        print(f"[finetune] RAG-aware: 전체 {len(raw)} 중 {len(rag_idx)}개를 RAG 형식으로 구성")

    ds = Dataset.from_dict({"text": texts})

    def tokenize(batch):
        out = tokenizer(
            batch["text"],
            truncation=True,
            max_length=max_length,
            padding=False,
        )
        out["labels"] = [ids.copy() for ids in out["input_ids"]] # causal LM: 전체 시퀀스 라벨
        return out

    return ds.map(tokenize, batched=True, remove_columns=["text"])


# ---------------------------------------------------------------------------
def main() -> int:
    ap = argparse.ArgumentParser(description="QLoRA 파인튜닝 (sqlcoder-7b-2)")
    ap.add_argument("--data", default=str(config.TRAIN_PAIRS_PATH))
    ap.add_argument("--output", default=config.ADAPTER_DIR)
    ap.add_argument("--epochs", type=int, default=config.TRAIN.num_epochs)
    ap.add_argument("--with-comment", action="store_true", help="DDL COMMENT 포함 학습")
    ap.add_argument("--val-ratio", type=float, default=0.05)
    ap.add_argument("--rag-aware", action="store_true", help="④ 일부 샘플을 RAG 형식으로 혼합 학습")
    ap.add_argument("--rag-ratio", type=float, default=0.3, help="RAG 형식 비율 (기본 0.3)")
    ap.add_argument("--rag-top-k", type=int, default=2, help="RAG 형식 예제 수")
    # --- 스모크/저VRAM 모드 (12GB GPU 대응) ---
    ap.add_argument("--max-steps", type=int, default=0, help=">0이면 step 수로 제한(epoch 무시)")
    ap.add_argument("--max-length", type=int, default=config.MAX_LENGTH, help="토큰 길이 상한(축소시 VRAM↓)")
    ap.add_argument("--batch-size", type=int, default=config.TRAIN.per_device_batch_size)
    ap.add_argument("--grad-accum", type=int, default=config.TRAIN.gradient_accumulation_steps)
    ap.add_argument("--grad-checkpointing", action="store_true", help="gradient checkpointing(VRAM↓, 속도↓)")
    ap.add_argument("--limit", type=int, default=0, help="학습 페어 서브셋 개수(스모크)")
    ap.add_argument("--eval-steps", type=int, default=config.TRAIN.eval_steps)
    args = ap.parse_args()

    import torch
    from transformers import (
        AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig,
        DataCollatorForLanguageModeling, EarlyStoppingCallback,
        Trainer, TrainingArguments,
    )
    from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training

    tcfg, lcfg = config.TRAIN, config.LORA

    # --- 토크나이저 ---
    tokenizer = AutoTokenizer.from_pretrained(config.BASE_MODEL)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token

    # --- 4-bit NF4 베이스 로드 ---
    quant_config = BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_quant_type="nf4",
        bnb_4bit_use_double_quant=True,
        bnb_4bit_compute_dtype=torch.bfloat16,
    )
    model = AutoModelForCausalLM.from_pretrained(
        config.BASE_MODEL,
        quantization_config=quant_config,
        device_map="auto",
        torch_dtype=torch.bfloat16,
    )
    # prepare가 use_gradient_checkpointing=True일 때 checkpointing + input_require_grads를
    # 모두 켜준다. Trainer에서 또 켜면 충돌하므로 TrainingArguments에서는 끈다.
    model = prepare_model_for_kbit_training(
        model, use_gradient_checkpointing=args.grad_checkpointing
    )
    model.config.use_cache = False

    # --- LoRA 어댑터 부착 ---
    lora = LoraConfig(
        r=lcfg.r,
        lora_alpha=lcfg.alpha,
        lora_dropout=lcfg.dropout,
        target_modules=list(lcfg.target_modules),
        bias=lcfg.bias,
        task_type=lcfg.task_type,
    )
    model = get_peft_model(model, lora)
    model.print_trainable_parameters() # ≈ 0.78% (131K / 16.7M per 4096×4096)

    # --- 데이터셋 (train/val 분할, early stopping용) ---
    full = build_dataset(
        Path(args.data), tokenizer, args.with_comment,
        rag_aware=args.rag_aware, rag_ratio=args.rag_ratio,
        rag_top_k=args.rag_top_k, seed=tcfg.seed,
        max_length=args.max_length, limit=args.limit,
    )
    split = full.train_test_split(test_size=args.val_ratio, seed=tcfg.seed)
    train_ds, val_ds = split["train"], split["test"]

    collator = DataCollatorForLanguageModeling(tokenizer, mlm=False)

    smoke = args.max_steps > 0
    eval_steps = min(args.eval_steps, args.max_steps) if smoke else args.eval_steps
    common = dict(
        output_dir=args.output,
        per_device_train_batch_size=args.batch_size,
        per_device_eval_batch_size=args.batch_size,
        gradient_accumulation_steps=args.grad_accum,
        learning_rate=tcfg.learning_rate,
        lr_scheduler_type=tcfg.lr_scheduler_type,
        warmup_ratio=tcfg.warmup_ratio,
        weight_decay=tcfg.weight_decay,
        bf16=True,
        gradient_checkpointing=False, # prepare_model_for_kbit_training에서 이미 처리
        logging_steps=tcfg.logging_steps,
        eval_strategy="steps",
        eval_steps=eval_steps,
        save_strategy="steps",
        save_steps=eval_steps,
        save_total_limit=1,
        seed=tcfg.seed,
        report_to="none",
    )
    if smoke:
        common["max_steps"] = args.max_steps # epoch 무시, step 수로 제한
    else:
        common["num_train_epochs"] = args.epochs
        common.update(load_best_model_at_end=True,
                      metric_for_best_model="eval_loss", greater_is_better=False)
    targs = TrainingArguments(**common)

    callbacks = []
    if not smoke:
        callbacks.append(EarlyStoppingCallback(early_stopping_patience=tcfg.early_stopping_patience))

    trainer = Trainer(
        model=model,
        args=targs,
        train_dataset=train_ds,
        eval_dataset=val_ds,
        data_collator=collator,
        callbacks=callbacks,
    )

    trainer.train()

    Path(args.output).mkdir(parents=True, exist_ok=True)
    model.save_pretrained(args.output) # LoRA 어댑터만 저장
    tokenizer.save_pretrained(args.output)
    print(f"[finetune] 어댑터 저장 완료 → {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
