-- =====================================================================
-- schema.sql — 학회 관리 DB (6개 테이블)
-- 출처: 테이블명세_씽크온웹_v2.xlsx (실제 명세) + 도메인 규칙 COMMENT
--
-- 실제 명세의 전체 컬럼/타입을 반영했다. DDL COMMENT는 모델 힌트용 도메인
-- 규칙을 담는다(특히 membership_date 만료 규칙, camelCase 컬럼, fee.type의
-- MUST/OPTIONAL, annual_fee 정회원 판별 등).
--
-- 주의: season 저장 값은 영문(spring/fall/winter/summer)으로 운용한다.
-- sc_conf_conference의 날짜 컬럼은 명세상 VARCHAR(30)(ISO 문자열)이다.
-- =====================================================================

-- ---------------------------------------------------------------------
-- 1) sc_users — 회원 정보 (17 컬럼)
-- ---------------------------------------------------------------------
CREATE TABLE sc_users (
    ACOMS_USER_ID VARCHAR(30) COMMENT 'ACOMS 사용자 ID',
    USER_NO VARCHAR(20) NOT NULL COMMENT '사용자 번호 (PK)',
    SOCIETY_ID INT UNSIGNED NOT NULL COMMENT '학회 ID',
    reg_date DATETIME COMMENT '등록일시(가입 시각)',
    class INT COMMENT '회원 등급/분류 ID. sc_class.id 참조. 숫자 등급 자체 질의는 JOIN 없이 WHERE class = N',
    status INT COMMENT '회원 상태',
    mileage INT COMMENT '마일리지',
    user_no_admin VARCHAR(20) COMMENT '관리자용 사용자 번호',
    approved TINYINT(1) NOT NULL COMMENT '승인 여부. 0: 미승인, 1: 승인',
    approve_ready TINYINT(1) NOT NULL COMMENT '승인 준비 여부. 0: 준비 안 됨, 1: 승인 대기',
    USER_ID INT UNSIGNED COMMENT '공통 사용자 테이블 ID',
    membership_date DATETIME COMMENT '회원 만료일(회비). >= CURDATE()이면 유효, < CURDATE()이면 만료. 곧 만료=BETWEEN CURDATE() AND CURDATE()+INTERVAL 1 MONTH',
    membership_date_check TINYINT(1) NOT NULL COMMENT '가입일 확인 여부',
    confirm_date DATETIME COMMENT '확인일시',
    email_return TINYINT(1) NOT NULL COMMENT '이메일 반송 여부',
    post_return TINYINT(1) NOT NULL COMMENT '우편 반송 여부',
    enabled TINYINT(1) NOT NULL COMMENT '사용 여부. 0: 비활성, 1: 활성',
    PRIMARY KEY (USER_NO)
) COMMENT='회원 정보';

-- ---------------------------------------------------------------------
-- 2) sc_class — 회원 등급/분류 (9 컬럼)
-- ---------------------------------------------------------------------
CREATE TABLE sc_class (
    id INT NOT NULL COMMENT '분류 ID (PK). sc_users.class와 JOIN',
    society_id INT UNSIGNED NOT NULL COMMENT '학회 ID',
    name_kor VARCHAR(20) COMMENT '분류명(한글): 정회원, 준회원, 종신회원 등',
    name_eng VARCHAR(50) COMMENT '분류명(영문)',
    `use` CHAR(1) NOT NULL COMMENT '사용 여부',
    `group` CHAR(1) COMMENT '그룹 구분',
    number INT COMMENT '정렬 번호 또는 표시 순번',
    type VARCHAR(10) COMMENT '분류 유형: BASIC, EXEMPT, LIFETIME',
    priority INT UNSIGNED COMMENT '우선순위',
    PRIMARY KEY (id)
) COMMENT='회원 등급/분류';

-- ---------------------------------------------------------------------
-- 3) sc_user_orders — 회원 주문/결제 (25 컬럼)
-- ---------------------------------------------------------------------
CREATE TABLE sc_user_orders (
    id INT NOT NULL COMMENT '주문 고유 ID (PK)',
    order_code VARCHAR(32) NOT NULL COMMENT '주문 코드',
    society_id INT UNSIGNED COMMENT '학회 ID',
    user_no VARCHAR(20) COMMENT '사용자 번호. sc_users.USER_NO와 JOIN',
    price BIGINT COMMENT '주문 금액',
    order_stat INT COMMENT '주문 상태 (실DB 관찰 컬럼, 명세 외)',
    cashby INT COMMENT '입금 구분 (실DB 관찰 컬럼, 명세 외)',
    ready_datetime DATETIME COMMENT '주문 준비일시/생성일시',
    order_datetime DATETIME COMMENT '실제 주문일시',
    confirm_datetime DATETIME COMMENT '승인/결제 확인일시',
    ready_name VARCHAR(50) COMMENT '주문 준비자명',
    memo VARCHAR(500) COMMENT '메모',
    account_no VARCHAR(50) COMMENT '계좌번호',
    order_name VARCHAR(100) COMMENT '주문명/주문 항목명',
    fee_code_list VARCHAR(1000) COMMENT '수수료/비용 코드 목록',
    tid VARCHAR(50) COMMENT '거래 TID/PG 거래번호',
    pay_type VARCHAR(100) COMMENT '결제 유형 (예: 무통장입금, 카드)',
    response_code VARCHAR(50) COMMENT '결제 응답 코드',
    response_msg VARCHAR(500) COMMENT '결제 응답 메시지',
    later_payer_name VARCHAR(200) COMMENT '후불/추후 입금자명',
    later_date DATETIME COMMENT '추후 입금 예정일',
    reason TEXT COMMENT '사유',
    confirm TINYINT(1) COMMENT '확인 여부. 0: 미확인, 1: 확인',
    available TINYINT(1) COMMENT '사용 가능/유효 여부',
    currency_code VARCHAR(5) NOT NULL COMMENT '통화 코드 (기본 KRW)',
    refund TINYINT(1) COMMENT '환불 여부. 0: 정상, 1: 환불',
    refund_datetime DATETIME COMMENT '환불 처리일시',
    PRIMARY KEY (id)
) COMMENT='회원 주문/결제';

-- ---------------------------------------------------------------------
-- 4) sc_conf_conference — 학술행사 (32 컬럼)
-- ※ 컬럼명이 camelCase. 날짜 컬럼은 VARCHAR(30)(ISO 문자열).
-- ---------------------------------------------------------------------
CREATE TABLE sc_conf_conference (
    id INT UNSIGNED NOT NULL COMMENT '학술행사 ID (PK)',
    societyId INT UNSIGNED NOT NULL COMMENT '학회 ID',
    mlConfId INT UNSIGNED COMMENT '내부 행사 매핑 ID (실DB 관찰 컬럼, 명세 외)',
    baseUrl VARCHAR(100) COMMENT '행사 베이스 URL',
    groupName VARCHAR(45) COMMENT '그룹명',
    nameId VARCHAR(100) COMMENT '행사 식별 ID (UNIQUE)',
    cdn VARCHAR(200) COMMENT 'CDN 경로',
    nameKor TEXT COMMENT '행사명(한글)',
    nameEng TEXT COMMENT '행사명(영문)',
    type VARCHAR(45) COMMENT '행사 유형',
    `year` INT UNSIGNED COMMENT '개최 연도',
    season VARCHAR(45) COMMENT '개최 시즌(영문): spring(춘계), fall(추계), winter, summer',
    hostingInstitution TEXT COMMENT '주최 기관',
    managingInstitution TEXT COMMENT '주관 기관',
    supportingInstitution TEXT COMMENT '후원 기관',
    location TEXT COMMENT '개최 장소',
    campus VARCHAR(120) COMMENT '캠퍼스/세부 장소',
    absStartDate VARCHAR(30) COMMENT '초록 접수 시작일',
    absEndDate VARCHAR(30) COMMENT '초록 접수 마감일',
    submissionStartDate VARCHAR(30) COMMENT '논문 투고 시작일',
    submissionEndDate VARCHAR(30) COMMENT '논문 투고 마감일',
    notificationDate VARCHAR(30) COMMENT '심사 결과 통보일',
    finalSubmissionStartDate VARCHAR(30) COMMENT '최종본 제출 시작일',
    finalSubmissionEndDate VARCHAR(30) COMMENT '최종본 제출 마감일',
    speakerPreRegStartDate VARCHAR(30) COMMENT '발표자 사전등록 시작일',
    speakerPreRegEndDate VARCHAR(30) COMMENT '발표자 사전등록 마감일',
    generalPreRegStartDate VARCHAR(30) COMMENT '일반 사전등록 시작일',
    generalPreRegEndDate VARCHAR(30) COMMENT '일반 사전등록 마감일',
    conferenceStartDate VARCHAR(30) COMMENT '행사 시작일',
    conferenceEndDate VARCHAR(30) COMMENT '행사 종료일',
    venueAddress TEXT COMMENT '개최지 주소',
    venueAddressDetailUrl TEXT COMMENT '개최지 상세 안내 URL',
    venueImgUrl VARCHAR(100) COMMENT '개최지 이미지 URL',
    PRIMARY KEY (id)
) COMMENT='학술행사';

-- ---------------------------------------------------------------------
-- 5) sc_conf_fee — 등록비 항목 (15 컬럼)
-- ---------------------------------------------------------------------
CREATE TABLE sc_conf_fee (
    id INT UNSIGNED NOT NULL COMMENT 'PK, 자동증가',
    society_id INT UNSIGNED NOT NULL COMMENT '학회 ID',
    conf_id INT UNSIGNED NOT NULL COMMENT '행사 ID. sc_conf_conference.id와 JOIN',
    amount INT UNSIGNED NOT NULL COMMENT '등록비 금액',
    code VARCHAR(30) NOT NULL COMMENT '등록비 코드. registrant.fee_code와 매칭',
    custom VARCHAR(100) COMMENT '커스텀 항목 (실DB 관찰 컬럼, 명세 외)',
    type VARCHAR(10) COMMENT '등록비 유형. MUST(필수)/OPTIONAL(선택, 예: 뱅큇)',
    sc_class INT COMMENT '회원 등급(FK sc_class.id, 등급별 차등요금)',
    name VARCHAR(500) COMMENT '등록비 항목명',
    payment_info VARCHAR(500) COMMENT '결제 명세서 표시용 상품 정보',
    start_date DATETIME COMMENT '결제 가능 기간 시작',
    end_date DATETIME COMMENT '결제 가능 기간 종료',
    `use` TINYINT(1) NOT NULL COMMENT '사용 여부',
    manuscript_fee TINYINT(1) COMMENT '논문 등록비 여부 (기본 1)',
    currency_code VARCHAR(5) NOT NULL COMMENT '통화 코드 (기본 KRW)',
    annual_fee TINYINT(1) COMMENT '연회비 여부 (기본 0). 1이면 정회원(연회비) 판별에 사용',
    PRIMARY KEY (id)
) COMMENT='등록비 항목';

-- ---------------------------------------------------------------------
-- 6) sc_conf_registrant — 등록비 결제/등록자 (37 컬럼)
-- ---------------------------------------------------------------------
CREATE TABLE sc_conf_registrant (
    id INT UNSIGNED NOT NULL COMMENT 'PK, 자동증가',
    society_id INT UNSIGNED NOT NULL COMMENT '학회 ID',
    conf_id INT UNSIGNED NOT NULL COMMENT '행사 ID. sc_conf_conference.id와 JOIN',
    payment_name VARCHAR(100) COMMENT '결제자명',
    payment_institution VARCHAR(200) COMMENT '결제자 소속기관',
    payment_phone VARCHAR(50) COMMENT '결제자 연락처',
    payment_email VARCHAR(50) COMMENT '결제자 이메일',
    payment_user_no VARCHAR(20) COMMENT '결제자 회원번호',
    payment_user_no_admin VARCHAR(20) COMMENT '결제자 관리자 회원번호',
    name VARCHAR(100) COMMENT '등록자명(한글)',
    name_eng VARCHAR(100) COMMENT '등록자명(영문)',
    institution VARCHAR(200) COMMENT '소속기관(한글)',
    inst_id INT COMMENT '소속기관 ID',
    inst_eng VARCHAR(200) COMMENT '소속기관(영문)',
    email VARCHAR(150) COMMENT '이메일',
    phone VARCHAR(50) COMMENT '휴대전화',
    phone_office VARCHAR(45) COMMENT '사무실 전화',
    user_no VARCHAR(32) COMMENT '회원번호. sc_users.USER_NO와 JOIN',
    user_no_admin VARCHAR(20) COMMENT '관리자 회원번호',
    order_code VARCHAR(32) COMMENT '주문 코드',
    fee_code VARCHAR(30) COMMENT '등록비 코드. sc_conf_fee.code와 JOIN',
    optional_fee_code VARCHAR(1000) COMMENT '선택 등록비 코드 목록 (예: 뱅큇)',
    order_confirm_date DATETIME COMMENT '결제 확정 일시',
    order_tid VARCHAR(200) COMMENT 'PG 거래 ID',
    status VARCHAR(10) COMMENT '상태',
    user_id INT COMMENT '사용자 ID',
    sc_class INT COMMENT '회원 등급(FK sc_class.id)',
    pay_type VARCHAR(50) COMMENT '결제 방식 (예: 무통장입금, 카드, 계좌이체)',
    later_payer_name VARCHAR(200) COMMENT '추후 결제자명',
    later_date DATETIME COMMENT '추후 결제 예정일',
    later_reason TEXT COMMENT '추후 결제 사유',
    recommender TEXT COMMENT '추천인',
    manuscript_submit_id VARCHAR(100) COMMENT '논문 투고 ID. NULL이면 논문 미투고',
    manuscript_title VARCHAR(500) COMMENT '논문 제목',
    additional_information TEXT COMMENT '추가 정보',
    refund TINYINT(1) COMMENT '환불 여부 (기본 0)',
    refund_date DATETIME COMMENT '환불 일시',
    PRIMARY KEY (id)
) COMMENT='등록비 결제/등록자';

-- =====================================================================
-- 주요 JOIN 관계
-- sc_users.class = sc_class.id (등급명 조회)
-- sc_users.USER_NO = sc_user_orders.user_no (결제 이력)
-- sc_conf_conference.id = sc_conf_fee.conf_id (등록비 항목)
-- sc_conf_conference.id = sc_conf_registrant.conf_id
-- sc_conf_registrant.fee_code = sc_conf_fee.code (적용 등록비)
-- sc_conf_registrant.user_no = sc_users.USER_NO (교차 JOIN)
-- sc_conf_registrant.sc_class = sc_class.id
-- =====================================================================
