# 학회 관리 DB 대상 한국어 NL2SQL 시스템

자연어 질문을 학회 관리 DB(MySQL)용 SQL로 자동 변환하는 온프레미스 시스템.
`defog/sqlcoder-7b-2` 베이스 모델에 **QLoRA 도메인 파인튜닝**을 적용하고,
**추론 시점 7단계 파이프라인**(Intent → Schema Pruning → RAG → Prompt → 모델추론
→ Postprocess → Validator)으로 정확도를 높였습니다. 웹 챗봇 UI를 포함합니다.

## 성능 (v49, 3-layer 평가 · TYPE_A 보정)

| 평가셋 | 문항 | raw | **TYPE_A 보정** |
|--------|-----:|----:|---------------:|
| Blind (일반화) | 214 | 84.1% | **91.6%** |
| Coverage (컬럼별) | 680 | 80.0% | **87.5%** |
| Targeted (10패턴) | 300 | 82.0% | **84.0%** |

> TYPE_A 보정 = 문자열은 달라도 MySQL 실행 결과가 동일하면 정답으로 인정한 점수.

## 빠른 시작

### 0. 사전 준비
- Python 3.10, MySQL 8 또는 MariaDB 10.11+
- (학습 시) NVIDIA GPU. 12GB(RTX 3080 Ti)에서 QLoRA 학습 가능, 추론은 ~6GB.

### 1. 설치
```bash
python -m venv .venv && . .venv/bin/activate   # Windows: .\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

### 2. 학습 어댑터 받기
QLoRA 어댑터(`v49`, ~142MB)는 GitHub **Release 자산**으로 제공됩니다.
`v49_adapter.zip`을 받아 `outputs/v49/` 에 압축 해제하세요.
```
outputs/v49/adapter_model.safetensors, adapter_config.json, tokenizer*.json
```
(직접 재학습하려면 아래 5번 참고.)

### 3. 평가/실행용 DB 구축
```bash
mysql -u root -p -e "CREATE DATABASE ml CHARACTER SET utf8mb4;"
mysql -u root -p ml < schema.sql        # 6개 테이블 DDL
mysql -u root -p ml < seed_data.sql     # 더미 데이터(평가/데모용)
```
접속 정보는 `.env.example`을 참고해 환경변수로 설정합니다.

### 4. 챗봇 실행
```bash
export NL2SQL_ADAPTER=outputs/v49
export NL2SQL_DB_NAME=ml NL2SQL_DB_USER=root NL2SQL_DB_PASSWORD=...
python app.py            # http://127.0.0.1:5000
```
질문 → 생성 SQL + 결과 테이블/차트(숫자카드·막대그래프) 출력. 멀티턴·대화 초기화 지원.

### 5. (선택) 데이터 생성 · 재학습 · 평가
```bash
python generate_data.py                                   # data/*.json + seed_data.sql 생성
python finetune.py --data data/train_pairs.json --output outputs/v49 \
       --epochs 3 --max-length 2048 --batch-size 1 --grad-accum 16 --grad-checkpointing
python evaluate.py --layer all --exec --out results.json  # TYPE_A 보정 평가
```

## 디렉터리 구조
```
.
├── app.py                 # 웹 챗봇 백엔드(Flask) + 정적 UI 서빙
├── inference.py           # 추론 파이프라인 엔드투엔드 (CLI/라이브러리)
├── finetune.py            # QLoRA 파인튜닝
├── evaluate.py            # 3-layer 평가 + MySQL 실행 TYPE_A 보정
├── generate_data.py       # 학습/평가 데이터 + seed 생성 진입점
├── config.py              # 전역 설정(QLoRA/생성/파이프라인 하이퍼파라미터)
├── schema.sql             # 6개 테이블 DDL + 도메인 규칙 COMMENT
├── seed_data.sql          # 평가/데모용 더미 데이터
├── src/                   # 추론 파이프라인 7단계 모듈
│   ├── intent_classifier.py   schema_pruning.py   rag.py
│   ├── prompt_builder.py      model.py            postprocess.py
│   ├── validator.py           equivalence.py      conversation.py
│   ├── feedback.py            exec_check.py       schema_utils.py
├── data_gen/              # 데이터 생성기(템플릿/커버리지/타깃/seed/검증)
├── frontend/              # 챗봇 UI (HTML/JS/CSS, Chart.js)
├── data/                  # 생성된 train/test (train_pairs·blind·coverage·targeted)
└── docs/                  # 프로젝트 보고서 등
```

## 추론 파이프라인 (7단계)
```
질문 → [0]Intent(비관련 차단) → [1]Schema Pruning(관련 테이블만)
     → [2]RAG(선택) → [3]Prompt → [4]모델추론(sqlcoder+QLoRA)
     → [5]Postprocess(정규화) → [6]Validator(DML 차단·환각 제거·LIMIT) → SQL
```

## 데이터셋
`data_gen` 생성기가 schema의 도메인 규칙(회비 만료, 정회원 판별, 등급 JOIN,
IS NULL 대조, 날짜 컬럼 매핑 등)을 인코딩해 생성합니다.
- **학습/평가 질문 중복 없음**(띄어쓰기 변형까지 차단) — `python -m data_gen.verify_dedup`
- **모든 SQL이 실제 스키마 컬럼만 참조** — `python -m data_gen.validate_columns`
- 패턴 분포/컬럼 커버리지 분석 — `data_gen.analyze_dist`, `data_gen.column_coverage_report`

## 환경변수
`.env.example` 참조. `NL2SQL_ADAPTER`(어댑터 경로), `NL2SQL_DB_*`(MySQL 접속).

## 라이선스
MIT License — `LICENSE` 파일 참조. © 2026 양재형, 이유섭, 이상윤
