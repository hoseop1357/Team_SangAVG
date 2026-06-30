"""
data_gen — 학습/평가 데이터 생성기.

원본 4,412 페어/평가셋은 유실됐으므로, schema.sql의 도메인 규칙을 코드로
인코딩한 템플릿 생성기로 목표 규모의 데이터를 재구성한다.

  pools 슬롯 값 풀(연도/계절/등급/금액 등) + 패러프레이즈 헬퍼
  templates 도메인/패턴별 질문-SQL 생성 함수
  build train/blind/coverage/targeted 조립·중복제거·검증·저장
"""
