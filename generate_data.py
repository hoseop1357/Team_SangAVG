"""
generate_data.py — 학습/평가 데이터 + seed_data.sql 생성 진입점.

목표 규모로 재생성:
  python generate_data.py
규모 조정/시드 변경:
  python generate_data.py --train 4412 --blind 214 --coverage 680 --targeted 300 --seed 42
seed_data.sql만 따로:
  python -m data_gen.seed # (참고: build가 함께 생성)

생성 결과:
  data/train_pairs.json, data/blind_test_all6_tables.json,
  data/column_coverage_test_v2.json, data/targeted_test_v2.json, seed_data.sql

보장: 학습/평가 데이터 간 질문 중복 없음, 평가 DB 더미데이터로 TYPE_A/TYPE_C 구분 가능.
"""
from data_gen.build import main

if __name__ == "__main__":
    raise SystemExit(main())
