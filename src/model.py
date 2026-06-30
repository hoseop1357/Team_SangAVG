"""
model.py — [Step 4] 모델 추론 (defog/sqlcoder-7b-2 + QLoRA 어댑터).

max_new_tokens=400, Greedy Decoding (do_sample=False)
  [/SQL] 토큰 감지 시 즉시 중단

4-bit NF4로 베이스 모델을 로드하고 PEFT 어댑터를 결합한다(어댑터가 없으면
순수 base 모델로 동작 — C0 기준선 재현 가능).
"""
from __future__ import annotations

import os
from dataclasses import dataclass

import config


@dataclass
class GenerationOutput:
    raw: str # [SQL]~[/SQL] 사이 디코딩 결과
    prompt_tokens: int
    new_tokens: int


class SqlCoderModel:
    def __init__(
        self,
        base_model: str | None = None,
        adapter_dir: str | None = None,
        load_in_4bit: bool = True,
    ):
        self.base_model = base_model or config.BASE_MODEL
        self.adapter_dir = adapter_dir if adapter_dir is not None else config.ADAPTER_DIR
        self.load_in_4bit = load_in_4bit
        self._model = None
        self._tokenizer = None

    # ------------------------------------------------------------------
    def load(self) -> "SqlCoderModel":
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig

        self._tokenizer = AutoTokenizer.from_pretrained(self.base_model)
        if self._tokenizer.pad_token is None:
            self._tokenizer.pad_token = self._tokenizer.eos_token

        quant_config = None
        if self.load_in_4bit:
            quant_config = BitsAndBytesConfig(
                load_in_4bit=True,
                bnb_4bit_quant_type="nf4", # NF4
                bnb_4bit_use_double_quant=True,
                bnb_4bit_compute_dtype=torch.bfloat16,
            )

        model = AutoModelForCausalLM.from_pretrained(
            self.base_model,
            quantization_config=quant_config,
            device_map="auto",
            torch_dtype=torch.bfloat16,
        )

        # QLoRA 어댑터 결합 (있을 때만 — 없으면 순수 base = C0 기준선)
        if self.adapter_dir and os.path.isdir(self.adapter_dir):
            from peft import PeftModel

            model = PeftModel.from_pretrained(model, self.adapter_dir)
            print(f"[model] QLoRA 어댑터 로드: {self.adapter_dir}")
        else:
            print(f"[model] 어댑터 없음 → 순수 base 모델 ({self.base_model})")

        model.eval()
        self._model = model
        return self

    # ------------------------------------------------------------------
    def generate(self, prompt: str, gen: config.GenConfig | None = None) -> GenerationOutput:
        import torch

        if self._model is None:
            self.load()
        gen = gen or config.GEN

        inputs = self._tokenizer(
            prompt, return_tensors="pt", truncation=True, max_length=config.MAX_LENGTH
        ).to(self._model.device)
        prompt_len = inputs["input_ids"].shape[1]

        stopping = self._build_stopping_criteria(prompt_len, gen.stop_token)
        with torch.no_grad():
            out = self._model.generate(
                **inputs,
                max_new_tokens=gen.max_new_tokens,
                do_sample=gen.do_sample,
                num_beams=gen.num_beams,
                pad_token_id=self._tokenizer.pad_token_id,
                eos_token_id=self._tokenizer.eos_token_id,
                stopping_criteria=stopping,
            )
        new_ids = out[0][prompt_len:]
        text = self._tokenizer.decode(new_ids, skip_special_tokens=True)
        text = text.split(gen.stop_token)[0] # [/SQL] 이후 절단
        return GenerationOutput(
            raw=text.strip(), prompt_tokens=prompt_len, new_tokens=len(new_ids)
        )

    # ------------------------------------------------------------------
    def _build_stopping_criteria(self, prompt_len: int, stop_token: str):
        """[/SQL] 시퀀스가 생성되면 즉시 중단."""
        from transformers import StoppingCriteria, StoppingCriteriaList

        stop_ids = self._tokenizer(stop_token, add_special_tokens=False)["input_ids"]
        tokenizer = self._tokenizer

        class StopOnSequence(StoppingCriteria):
            def __call__(self, input_ids, scores, **kwargs) -> bool: # noqa: D401
                gen_ids = input_ids[0][prompt_len:].tolist()
                if len(gen_ids) >= len(stop_ids) and gen_ids[-len(stop_ids):] == stop_ids:
                    return True
                # 토크나이즈 경계가 어긋날 수 있어 디코딩 폴백
                return stop_token in tokenizer.decode(gen_ids)

        return StoppingCriteriaList([StopOnSequence()])
