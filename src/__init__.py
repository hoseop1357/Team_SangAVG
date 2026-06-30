"""
NL2SQL 추론 파이프라인 패키지.

Step 0 intent_classifier.IntentClassifier() — 비관련 질문 차단
Step 1 schema_pruning.SchemaPruner — 관련 테이블 DDL만 선택
Step 2 rag.RagRetriever — 유사 질문-SQL 예제 검색
Step 3 prompt_builder.PromptBuilder() — 프롬프트 구성
Step 4 model.SqlCoderModel — defog/sqlcoder-7b-2 + QLoRA 추론
Step 5 postprocess.postprocess_sql — 형식 정규화
Step 6 validator.SQLValidator — 안전 검사 + 환각 제거
"""
