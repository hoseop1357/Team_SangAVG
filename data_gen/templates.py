"""
templates.py — 도메인/패턴별 질문-SQL 생성 함수.

각 함수는 rng로 슬롯을 뽑아 1개의 레코드 {question, sql, tables}를 만든다.
SQL 컬럼명은 schema.sql과 정확히 일치하며, 도메인 규칙을 반영한다:
  · membership_date >= CURDATE() = 유효 / < CURDATE() = 만료
  · annual_fee = 1 → 정회원(연회비) 판별
  · 숫자 등급 → WHERE class = N (JOIN 없음, catastrophic forgetting 방지 counter-example)
  · 등급 한글명 → sc_class JOIN
  · manuscript_submit_id IS NULL / IS NOT NULL 대조쌍
  · camelCase 컬럼(conferenceStartDate, nameKor, season, year)
"""
from __future__ import annotations

import random

from data_gen import pools as P

LIMIT = P.LIMIT


def rec(question: str, sql: str, tables: list[str], **extra) -> dict:
    r = {"question": question, "sql": " ".join(sql.split()), "tables": tables}
    r.update(extra)
    return r


# ===========================================================================
# 회원 도메인 (sc_users, sc_class, sc_user_orders)
# ===========================================================================
def t_member_membership(rng):
    valid = rng.random() < 0.5
    cond = "membership_date >= CURDATE()" if valid else "membership_date < CURDATE()"
    subj = "현재 회비가 유효한 회원" if valid else "회비가 만료된 회원"
    if rng.random() < 0.5:
        return rec(P.q_count(rng, subj),
                   f"SELECT COUNT(*) AS cnt FROM sc_users WHERE {cond} {LIMIT};", ["sc_users"])
    return rec(P.q_list(rng, subj),
               f"SELECT USER_NO FROM sc_users WHERE {cond} {LIMIT};", ["sc_users"])


def t_member_state(rng):
    col, val, label = rng.choice([
        ("approved", 1, "승인된 회원"), ("approved", 0, "미승인 회원"),
        ("approve_ready", 1, "승인 대기 중인 회원"),
        ("enabled", 1, "활성 회원"), ("enabled", 0, "비활성 회원"),
    ])
    if rng.random() < 0.5:
        return rec(P.q_count(rng, label),
                   f"SELECT COUNT(*) AS cnt FROM sc_users WHERE {col} = {val} {LIMIT};", ["sc_users"])
    return rec(P.q_list(rng, label),
               f"SELECT USER_NO FROM sc_users WHERE {col} = {val} {LIMIT};", ["sc_users"])


def t_member_mileage(rng):
    th = rng.choice(P.MILEAGES)
    subj = f"마일리지가 {th}점 이상인 회원"
    if rng.random() < 0.4:
        return rec(P.q_show(rng, "회원 평균 마일리지"),
                   f"SELECT AVG(mileage) AS avg_mileage FROM sc_users {LIMIT};", ["sc_users"])
    return rec(P.q_count(rng, subj),
               f"SELECT COUNT(*) AS cnt FROM sc_users WHERE mileage >= {th} {LIMIT};", ["sc_users"])


def t_member_regyear(rng):
    y = rng.choice(P.YEARS)
    subj = f"{y}년에 가입한 회원"
    return rec(P.q_count(rng, subj),
               f"SELECT COUNT(*) AS cnt FROM sc_users WHERE YEAR(reg_date) = {y} {LIMIT};", ["sc_users"])


def t_member_class_num(rng):
    """숫자 등급 → JOIN 없이 WHERE class = N (counter-example). 표현 다양화."""
    n = rng.choice(P.CLASS_NUMS)
    subj = rng.choice([f"{n}등급 회원", f"등급이 {n}인 회원", f"{n}등급인 회원",
                       f"회원 등급이 {n}인 사람"])
    if rng.random() < 0.5:
        return rec(P.q_count(rng, subj),
                   f"SELECT COUNT(*) AS cnt FROM sc_users WHERE class = {n} {LIMIT};", ["sc_users"])
    return rec(P.q_list(rng, subj),
               f"SELECT USER_NO FROM sc_users WHERE class = {n} {LIMIT};", ["sc_users"])


def t_count_distinct(rng):
    """'서로 다른 X 수' → COUNT(DISTINCT X) (의미 있는 컬럼만)."""
    table, col, label = rng.choice([
        ("sc_conf_registrant", "institution", "소속 기관"),
        ("sc_user_orders", "pay_type", "결제 수단"),
        ("sc_conf_conference", "season", "행사 계절"),
        ("sc_conf_conference", "`year`", "행사 개최 연도"),
        ("sc_conf_registrant", "pay_type", "등록자 결제 방식"),
    ])
    return rec(P.q_count_rows(rng, f"서로 다른 {label}"),
               f"SELECT COUNT(DISTINCT {col}) AS cnt FROM {table} {LIMIT};", [table])


def t_reg_inst_conf(rng):
    """'소속'은 등록자(r.institution) 컬럼임을 학습 (행사 JOIN 시에도 r에 붙임)."""
    inst = rng.choice(P.INSTITUTIONS)
    if rng.random() < 0.65:
        # 특정 행사 지정 없음 → JOIN 불필요, registrant 단독 (소속=institution)
        subj = rng.choice([
            f"학술대회 등록자 중 {inst} 소속인 사람",
            f"학술대회 중 {inst} 소속인 사람",
            f"행사 등록자 중 {inst} 소속인 사람",
            f"{inst} 소속 참가자",
            f"{inst} 소속 등록자",
        ])
        return rec(P.q_list(rng, subj),
                   f"SELECT name FROM sc_conf_registrant WHERE institution = '{inst}' {LIMIT};",
                   ["sc_conf_registrant"])
    # 계절/연도 지정 → 행사 JOIN, 단 institution은 r에
    se = rng.choice(list(P.SEASONS)); y = rng.choice(P.YEARS); sp = P.season_phrase(rng, se)
    subj = f"{y}년 {sp} 학술대회 등록자 중 {inst} 소속인 사람"
    return rec(P.q_list(rng, subj),
               "SELECT r.name FROM sc_conf_registrant r JOIN sc_conf_conference c ON r.conf_id = c.id "
               f"WHERE c.season = '{se}' AND c.year = {y} AND r.institution = '{inst}' {LIMIT};",
               ["sc_conf_registrant", "sc_conf_conference"])


def t_conf_hosting(rng):
    """hostingInstitution=주최기관 학습 ('소속'(r.institution)과 구분)."""
    org = rng.choice(["한국정보처리학회", "한국정보보호학회", "한국통신학회",
                      "한국정보과학회", "대한산업경영학회"])
    subj = f"{org}가 주최한 학술대회"
    return rec(P.q_list(rng, subj),
               f"SELECT nameKor FROM sc_conf_conference WHERE hostingInstitution = '{org}' {LIMIT};",
               ["sc_conf_conference"])


def t_orders_minmax(rng):
    """'결제 금액이 가장 큰/작은 주문' → ORDER BY price LIMIT 1 (테이블 혼동 방지)."""
    biggest = rng.random() < 0.5
    direction = "DESC" if biggest else "ASC"
    word = rng.choice(["가장 큰", "가장 비싼", "최고 금액의"] if biggest
                      else ["가장 작은", "가장 적은", "최저 금액의"])
    if rng.random() < 0.3: # top-N 변형
        n = rng.choice([3, 5, 10])
        ord_word = "높은" if biggest else "낮은"
        return rec(P.q_list(rng, f"결제 금액이 {ord_word} 주문 {n}건"),
                   f"SELECT id, user_no, price FROM sc_user_orders ORDER BY price {direction} LIMIT {n};",
                   ["sc_user_orders"])
    return rec(P.q_show(rng, f"결제 금액이 {word} 주문"),
               f"SELECT id, user_no, price FROM sc_user_orders ORDER BY price {direction} LIMIT 1;",
               ["sc_user_orders"])


def t_member_class_name(rng):
    """등급 한글명 → sc_class JOIN."""
    name = rng.choice(P.CLASS_NAMES)
    subj = f"{name} 등급의 회원"
    if rng.random() < 0.5:
        return rec(P.q_count(rng, subj),
                   f"SELECT COUNT(*) AS cnt FROM sc_users u JOIN sc_class c ON u.class = c.id "
                   f"WHERE c.name_kor = '{name}' {LIMIT};", ["sc_users", "sc_class"])
    return rec(P.q_list(rng, subj),
               f"SELECT u.USER_NO FROM sc_users u JOIN sc_class c ON u.class = c.id "
               f"WHERE c.name_kor = '{name}' {LIMIT};", ["sc_users", "sc_class"])


def t_member_class_type(rng):
    t = rng.choice(P.CLASS_TYPES)
    subj = f"{t} 유형 등급의 회원"
    return rec(P.q_count(rng, subj),
               f"SELECT COUNT(*) AS cnt FROM sc_users u JOIN sc_class c ON u.class = c.id "
               f"WHERE c.type = '{t}' {LIMIT};", ["sc_users", "sc_class"])


def t_member_multi_and(rng):
    subj = "승인되고 활성 상태이며 회비가 유효한 회원"
    return rec(P.q_count(rng, subj),
               "SELECT COUNT(*) AS cnt FROM sc_users "
               f"WHERE approved = 1 AND enabled = 1 AND membership_date >= CURDATE() {LIMIT};",
               ["sc_users"])


def t_orders_refund(rng):
    refunded = rng.random() < 0.5
    val = 1 if refunded else 0
    subj = "환불된 주문" if refunded else "환불되지 않은 주문"
    return rec(P.q_count_rows(rng, subj),
               f"SELECT COUNT(*) AS cnt FROM sc_user_orders WHERE refund = {val} {LIMIT};",
               ["sc_user_orders"])


def t_orders_sum(rng):
    if rng.random() < 0.5:
        return rec(P.q_show(rng, "결제 확인된 주문의 총 금액"),
                   "SELECT SUM(price) AS total FROM sc_user_orders WHERE confirm = 1 AND refund = 0 "
                   f"{LIMIT};", ["sc_user_orders"])
    return rec(P.q_show(rng, "결제 확인된 주문의 평균 금액"),
               f"SELECT AVG(price) AS avg_price FROM sc_user_orders WHERE confirm = 1 {LIMIT};",
               ["sc_user_orders"])


def t_orders_price_threshold(rng):
    th = rng.choice(P.PRICES)
    subj = f"결제 금액이 {th}원을 초과한 주문"
    return rec(P.q_count_rows(rng, subj),
               f"SELECT COUNT(*) AS cnt FROM sc_user_orders WHERE price > {th} {LIMIT};",
               ["sc_user_orders"])


def t_orders_max(rng):
    return rec(P.q_show(rng, "결제 금액이 가장 큰 주문"),
               f"SELECT id, user_no, price FROM sc_user_orders ORDER BY price DESC LIMIT 1;",
               ["sc_user_orders"])


def t_orders_join_member(rng):
    th = rng.choice(P.PRICES)
    subj = f"결제 금액이 {th}원을 초과한 회원"
    return rec(P.q_list(rng, subj),
               "SELECT DISTINCT u.USER_NO FROM sc_users u JOIN sc_user_orders o ON u.USER_NO = o.user_no "
               f"WHERE o.price > {th} AND o.confirm = 1 {LIMIT};", ["sc_users", "sc_user_orders"])


# ===========================================================================
# 학술대회 도메인 (sc_conf_conference, sc_conf_fee, sc_conf_registrant)
# ===========================================================================
def t_conf_by_season_year(rng):
    se = rng.choice(list(P.SEASONS))
    y = rng.choice(P.YEARS)
    sp = P.season_phrase(rng, se)
    subj = f"{y}년 {sp} 학술대회"
    return rec(P.q_show(rng, f"{subj} 이름"),
               f"SELECT nameKor FROM sc_conf_conference WHERE season = '{se}' AND year = {y} {LIMIT};",
               ["sc_conf_conference"])


def t_conf_location(rng):
    se = rng.choice(list(P.SEASONS))
    sp = P.season_phrase(rng, se)
    return rec(P.q_show(rng, f"{sp} 학술대회의 개최 장소"),
               f"SELECT nameKor, location FROM sc_conf_conference WHERE season = '{se}' {LIMIT};",
               ["sc_conf_conference"])


def t_conf_daterange(rng):
    y = rng.choice(P.YEARS)
    subj = f"{y}년에 시작하는 학술대회"
    return rec(P.q_list(rng, subj),
               "SELECT nameKor, conferenceStartDate FROM sc_conf_conference "
               f"WHERE conferenceStartDate BETWEEN '{y}-01-01' AND '{y}-12-31' {LIMIT};",
               ["sc_conf_conference"])


def t_conf_period_current(rng):
    col, label = rng.choice([
        (("generalPreRegStartDate", "generalPreRegEndDate"), "일반 사전등록이 진행 중인 학술행사"),
        (("speakerPreRegStartDate", "speakerPreRegEndDate"), "발표자 사전등록이 진행 중인 학술행사"),
        (("absStartDate", "absEndDate"), "초록 접수 기간 중인 학술행사"),
        (("submissionStartDate", "submissionEndDate"), "논문 투고 기간 중인 학술행사"),
    ])
    s, e = col
    return rec(P.q_show(rng, f"{label} 이름"),
               f"SELECT nameKor FROM sc_conf_conference WHERE CURDATE() BETWEEN {s} AND {e} {LIMIT};",
               ["sc_conf_conference"])


def t_fee_amount(rng):
    th = rng.choice(P.AMOUNTS)
    subj = f"등록비가 {th}원 이상인 항목"
    return rec(P.q_list(rng, subj),
               f"SELECT name, amount FROM sc_conf_fee WHERE amount >= {th} {LIMIT};", ["sc_conf_fee"])


def t_fee_flag(rng):
    col, label = rng.choice([
        ("annual_fee", "연회비"), ("manuscript_fee", "논문 등록비"),
    ])
    return rec(P.q_show(rng, f"{label} 항목의 명칭과 금액"),
               f"SELECT name, amount FROM sc_conf_fee WHERE {col} = 1 {LIMIT};", ["sc_conf_fee"])


def t_fee_period(rng):
    return rec(P.q_list(rng, "현재 유효한 등록비 항목"),
               "SELECT name, amount FROM sc_conf_fee WHERE CURDATE() BETWEEN start_date AND end_date "
               f"{LIMIT};", ["sc_conf_fee"])


def t_fee_join_conf(rng):
    y = rng.choice(P.YEARS)
    subj = f"{y}년 학술대회의 등록비 항목과 금액"
    return rec(P.q_list(rng, subj),
               "SELECT f.name, f.amount FROM sc_conf_fee f JOIN sc_conf_conference c ON f.conf_id = c.id "
               f"WHERE c.year = {y} {LIMIT};", ["sc_conf_fee", "sc_conf_conference"])


def t_reg_manuscript_null(rng):
    """IS NULL / IS NOT NULL 대조쌍."""
    submitted = rng.random() < 0.5
    cond = "manuscript_submit_id IS NOT NULL" if submitted else "manuscript_submit_id IS NULL"
    subj = "논문을 제출한 등록자" if submitted else "논문을 제출하지 않은 등록자"
    if rng.random() < 0.5:
        return rec(P.q_count(rng, subj),
                   f"SELECT COUNT(*) AS cnt FROM sc_conf_registrant WHERE {cond} {LIMIT};",
                   ["sc_conf_registrant"])
    return rec(P.q_list(rng, f"{subj}의 영문명"),
               f"SELECT name_eng FROM sc_conf_registrant WHERE {cond} {LIMIT};", ["sc_conf_registrant"])


def t_reg_order_confirm(rng):
    confirmed = rng.random() < 0.5
    cond = "order_confirm_date IS NOT NULL" if confirmed else "order_confirm_date IS NULL"
    subj = "결제가 확인된 등록자" if confirmed else "결제가 확인되지 않은 등록자"
    return rec(P.q_count(rng, subj),
               f"SELECT COUNT(*) AS cnt FROM sc_conf_registrant WHERE {cond} {LIMIT};",
               ["sc_conf_registrant"])


def t_reg_institution_group(rng):
    return rec(P.q_list(rng, "소속 기관별 등록자 수를 많은 순"),
               "SELECT institution, COUNT(*) AS cnt FROM sc_conf_registrant "
               f"GROUP BY institution ORDER BY cnt DESC {LIMIT};", ["sc_conf_registrant"])


def t_reg_join_conf(rng):
    se = rng.choice(list(P.SEASONS))
    sp = P.season_phrase(rng, se)
    subj = f"{sp} 학술대회 등록자의 소속 기관"
    return rec(P.q_list(rng, subj),
               "SELECT DISTINCT r.institution FROM sc_conf_registrant r "
               "JOIN sc_conf_conference c ON r.conf_id = c.id "
               f"WHERE c.season = '{se}' {LIMIT};", ["sc_conf_registrant", "sc_conf_conference"])


# ===========================================================================
# 크로스 도메인 (회원 + 학술대회)
# ===========================================================================
def t_member_expiring_soon(rng):
    """회비 만료 임박 (명세 힌트 SQL: BETWEEN CURDATE() AND CURDATE()+INTERVAL 1 MONTH)."""
    months = rng.choice([1, 2, 3])
    subj = f"{months}개월 내에 회비가 만료되는 회원"
    if rng.random() < 0.5:
        return rec(P.q_count(rng, subj),
                   "SELECT COUNT(*) AS cnt FROM sc_users "
                   f"WHERE membership_date >= CURDATE() AND membership_date < CURDATE() + INTERVAL {months} MONTH {LIMIT};",
                   ["sc_users"])
    return rec(P.q_list(rng, subj),
               "SELECT USER_NO FROM sc_users "
               f"WHERE membership_date >= CURDATE() AND membership_date < CURDATE() + INTERVAL {months} MONTH {LIMIT};",
               ["sc_users"])


def t_reg_pay_type(rng):
    """결제 방식별 등록자 (명세 질문 예시: 무통장 입금한 사람들)."""
    pt = rng.choice(P.PAY_TYPES)
    subj = f"{pt}으로 결제한 등록자"
    if rng.random() < 0.5:
        return rec(P.q_count(rng, subj),
                   f"SELECT COUNT(*) AS cnt FROM sc_conf_registrant WHERE pay_type = '{pt}' {LIMIT};",
                   ["sc_conf_registrant"])
    return rec(P.q_list(rng, f"{subj}의 이름"),
               f"SELECT name FROM sc_conf_registrant WHERE pay_type = '{pt}' {LIMIT};",
               ["sc_conf_registrant"])


def t_fee_optional(rng):
    """선택 등록비(OPTIONAL) 항목 (명세 질문 예시: 뱅큇 등 선택 항목)."""
    if rng.random() < 0.5:
        return rec(P.q_list(rng, "선택 등록비 항목"),
                   f"SELECT name, amount FROM sc_conf_fee WHERE type = 'OPTIONAL' {LIMIT};",
                   ["sc_conf_fee"])
    return rec(P.q_list(rng, "필수 등록비 항목"),
               f"SELECT name, amount FROM sc_conf_fee WHERE type = 'MUST' {LIMIT};",
               ["sc_conf_fee"])


def t_reg_payment_institution(rng):
    inst = rng.choice(P.INSTITUTIONS)
    subj = f"결제자 소속기관이 {inst}인 등록자"
    return rec(P.q_count(rng, subj),
               f"SELECT COUNT(*) AS cnt FROM sc_conf_registrant WHERE payment_institution = '{inst}' {LIMIT};",
               ["sc_conf_registrant"])


def t_cross_member_registrant(rng):
    name = rng.choice(P.CLASS_NAMES)
    y = rng.choice(P.YEARS)
    subj = f"{name}이면서 {y}년 학술대회에 등록한 사람"
    return rec(P.q_count(rng, subj),
               "SELECT COUNT(DISTINCT u.USER_NO) AS cnt FROM sc_users u "
               "JOIN sc_class cl ON u.class = cl.id "
               "JOIN sc_conf_registrant r ON u.USER_NO = r.user_no "
               "JOIN sc_conf_conference c ON r.conf_id = c.id "
               f"WHERE cl.name_kor = '{name}' AND c.year = {y} {LIMIT};",
               ["sc_users", "sc_class", "sc_conf_registrant", "sc_conf_conference"])


def t_orders_price_between(rng):
    a, b = sorted(rng.sample(P.PRICES, 2))
    subj = f"결제 금액이 {a}원 이상 {b}원 이하인 주문"
    return rec(P.q_count_rows(rng, subj),
               f"SELECT COUNT(*) AS cnt FROM sc_user_orders WHERE price BETWEEN {a} AND {b} {LIMIT};",
               ["sc_user_orders"])


def t_member_mileage_between(rng):
    a, b = sorted(rng.sample(P.MILEAGES, 2))
    subj = f"마일리지가 {a} 이상 {b} 이하인 회원"
    return rec(P.q_count(rng, subj),
               f"SELECT COUNT(*) AS cnt FROM sc_users WHERE mileage BETWEEN {a} AND {b} {LIMIT};",
               ["sc_users"])


def t_fee_amount_between(rng):
    a, b = sorted(rng.sample(P.AMOUNTS, 2))
    subj = f"등록비가 {a}원 이상 {b}원 이하인 항목"
    return rec(P.q_list(rng, subj),
               f"SELECT name, amount FROM sc_conf_fee WHERE amount BETWEEN {a} AND {b} {LIMIT};",
               ["sc_conf_fee"])


def t_member_regmonth(rng):
    y = rng.choice(P.YEARS)
    m = rng.choice(P.MONTHS)
    subj = f"{y}년 {m}월에 가입한 회원"
    return rec(P.q_count(rng, subj),
               f"SELECT COUNT(*) AS cnt FROM sc_users WHERE YEAR(reg_date) = {y} AND MONTH(reg_date) = {m} {LIMIT};",
               ["sc_users"])


def t_reg_institution_filter(rng):
    inst = rng.choice(P.INSTITUTIONS)
    subj = f"{inst} 소속 등록자"
    if rng.random() < 0.5:
        return rec(P.q_count(rng, subj),
                   f"SELECT COUNT(*) AS cnt FROM sc_conf_registrant WHERE institution = '{inst}' {LIMIT};",
                   ["sc_conf_registrant"])
    return rec(P.q_list(rng, f"{subj}의 영문명"),
               f"SELECT name_eng FROM sc_conf_registrant WHERE institution = '{inst}' {LIMIT};",
               ["sc_conf_registrant"])


def t_conf_month_range(rng):
    y = rng.choice(P.YEARS)
    m = rng.choice(P.MONTHS)
    end = P.MONTH_END[m]
    subj = f"{y}년 {m}월에 시작하는 학술대회"
    return rec(P.q_list(rng, subj),
               "SELECT nameKor, conferenceStartDate FROM sc_conf_conference "
               f"WHERE conferenceStartDate BETWEEN '{y}-{m:02d}-01' AND '{y}-{m:02d}-{end:02d}' {LIMIT};",
               ["sc_conf_conference"])


def t_orders_year(rng):
    y = rng.choice(P.YEARS)
    subj = f"{y}년에 발생한 주문"
    return rec(P.q_count_rows(rng, subj),
               f"SELECT COUNT(*) AS cnt FROM sc_user_orders WHERE YEAR(order_datetime) = {y} {LIMIT};",
               ["sc_user_orders"])


def t_cross_annual_fee_registrant(rng):
    """대표 예제: 특정 계절/연도 등록 정회원 수 (annual_fee 서브쿼리)."""
    se = rng.choice(list(P.SEASONS))
    y = rng.choice(P.YEARS)
    sp = P.season_phrase(rng, se)
    subj = f"{y}년 {sp} 학술대회에 등록한 정회원"
    return rec(P.q_count(rng, subj),
               "SELECT COUNT(*) AS cnt FROM sc_conf_registrant r "
               "JOIN sc_conf_conference c ON r.conf_id = c.id "
               f"WHERE c.season = '{se}' AND c.year = {y} "
               f"AND r.fee_code IN (SELECT code FROM sc_conf_fee WHERE annual_fee = 1) {LIMIT};",
               ["sc_conf_registrant", "sc_conf_conference", "sc_conf_fee"])


_RESERVED = {"year", "use", "group"}


def qc(name: str) -> str:
    return f"`{name}`" if name in _RESERVED else name


# === 재균형용 보강 템플릿 (약한 패턴: GROUP BY / 집계 / IS NULL / 등급JOIN / 크로스) ===

_GROUP_SPECS = [
    ("sc_conf_conference", "season", "계절별 학술대회"),
    ("sc_conf_conference", "year", "연도별 학술대회"),
    ("sc_conf_conference", "type", "유형별 학술대회"),
    ("sc_conf_fee", "type", "유형별 등록비 항목"),
    ("sc_user_orders", "pay_type", "결제수단별 주문"),
    ("sc_conf_registrant", "pay_type", "결제방식별 등록자"),
    ("sc_conf_registrant", "institution", "기관별 등록자"),
    ("sc_users", "class", "등급별 회원"),
]


def t_groupby_count(rng):
    table, col, subj = rng.choice(_GROUP_SPECS)
    c = qc(col)
    if rng.random() < 0.5:
        return rec(P.q_list(rng, f"{subj} 수를 많은 순"),
                   f"SELECT {c}, COUNT(*) AS cnt FROM {table} GROUP BY {c} ORDER BY cnt DESC LIMIT 100;",
                   [table])
    return rec(P.q_list(rng, f"{subj} 수"),
               f"SELECT {c}, COUNT(*) AS cnt FROM {table} GROUP BY {c} LIMIT 100;", [table])


_AGG = {"SUM": "총", "AVG": "평균", "MAX": "최대", "MIN": "최소"}


def t_agg_orders_byyear(rng):
    fn = rng.choice(list(_AGG)); y = rng.choice(P.YEARS)
    subj = f"{y}년 주문의 {_AGG[fn]} 금액"
    return rec(P.q_show(rng, subj),
               f"SELECT {fn}(price) AS val FROM sc_user_orders WHERE YEAR(order_datetime) = {y} LIMIT 100;",
               ["sc_user_orders"])


def t_agg_mileage(rng):
    fn = rng.choice(list(_AGG))
    if rng.random() < 0.5:
        return rec(P.q_show(rng, f"전체 회원 마일리지의 {_AGG[fn]}"),
                   f"SELECT {fn}(mileage) AS val FROM sc_users LIMIT 100;", ["sc_users"])
    name = rng.choice(P.CLASS_NAMES)
    return rec(P.q_show(rng, f"{name} 등급 회원 마일리지의 {_AGG[fn]}"),
               f"SELECT {fn}(u.mileage) AS val FROM sc_users u JOIN sc_class c ON u.class = c.id "
               f"WHERE c.name_kor = '{name}' LIMIT 100;", ["sc_users", "sc_class"])


def t_agg_fee_bytype(rng):
    fn = rng.choice(list(_AGG)); ft = rng.choice(P.FEE_TYPES)
    label = "선택" if ft == "OPTIONAL" else "필수"
    return rec(P.q_show(rng, f"{label} 등록비의 {_AGG[fn]} 금액"),
               f"SELECT {fn}(amount) AS val FROM sc_conf_fee WHERE type = '{ft}' LIMIT 100;",
               ["sc_conf_fee"])


def t_reg_isnull_byconf(rng):
    se = rng.choice(list(P.SEASONS)); y = rng.choice(P.YEARS); sp = P.season_phrase(rng, se)
    submitted = rng.random() < 0.5
    cond = "r.manuscript_submit_id IS NOT NULL" if submitted else "r.manuscript_submit_id IS NULL"
    word = "논문을 제출한" if submitted else "논문을 제출하지 않은"
    subj = f"{y}년 {sp} 학술대회 등록자 중 {word} 사람"
    return rec(P.q_count(rng, subj),
               "SELECT COUNT(*) AS cnt FROM sc_conf_registrant r "
               "JOIN sc_conf_conference c ON r.conf_id = c.id "
               f"WHERE c.season = '{se}' AND c.year = {y} AND {cond} LIMIT 100;",
               ["sc_conf_registrant", "sc_conf_conference"])


def t_member_classname_cond(rng):
    name = rng.choice(P.CLASS_NAMES)
    cond, label = rng.choice([
        ("u.approved = 1", "승인된"), ("u.enabled = 1", "활성"),
        ("u.membership_date >= CURDATE()", "회비가 유효한"),
    ])
    subj = f"{name} 등급이면서 {label} 회원"
    return rec(P.q_count(rng, subj),
               "SELECT COUNT(*) AS cnt FROM sc_users u JOIN sc_class c ON u.class = c.id "
               f"WHERE c.name_kor = '{name}' AND {cond} LIMIT 100;", ["sc_users", "sc_class"])


def t_cross_classname_season(rng):
    name = rng.choice(P.CLASS_NAMES); se = rng.choice(list(P.SEASONS))
    y = rng.choice(P.YEARS); sp = P.season_phrase(rng, se)
    subj = f"{y}년 {sp} 학술대회에 등록한 {name}"
    return rec(P.q_count(rng, subj),
               "SELECT COUNT(DISTINCT u.USER_NO) AS cnt FROM sc_users u "
               "JOIN sc_class cl ON u.class = cl.id "
               "JOIN sc_conf_registrant r ON u.USER_NO = r.user_no "
               "JOIN sc_conf_conference c ON r.conf_id = c.id "
               f"WHERE cl.name_kor = '{name}' AND c.season = '{se}' AND c.year = {y} LIMIT 100;",
               ["sc_users", "sc_class", "sc_conf_registrant", "sc_conf_conference"])


# === coverage 약점 보강 템플릿 (날짜 컬럼 매핑 / 행사 JOIN / 선택 등록비) ===

# 학술행사 날짜 컬럼 ↔ 한국어 표현 (coverage probe와 동일 매핑)
_CONF_DATECOLS = [
    ("conferenceStartDate", "개최"), ("conferenceEndDate", "종료"),
    ("absStartDate", "초록 접수를 시작"), ("absEndDate", "초록 마감"),
    ("submissionStartDate", "논문 투고를 시작"), ("submissionEndDate", "논문 마감"),
    ("generalPreRegStartDate", "사전등록을 시작"), ("generalPreRegEndDate", "사전등록 마감"),
    ("speakerPreRegStartDate", "발표자 사전등록을 시작"), ("speakerPreRegEndDate", "발표자 사전등록 마감"),
]


def t_conf_datecol(rng):
    """행사 날짜 컬럼 매핑 학습: '{y}년에 초록 마감하는 행사' → absEndDate 등."""
    col, action = rng.choice(_CONF_DATECOLS)
    y = rng.choice(P.YEARS)
    subj = f"{y}년에 {action}하는 행사"
    return rec(P.q_list(rng, subj),
               f"SELECT nameKor, {col} FROM sc_conf_conference "
               f"WHERE {col} BETWEEN '{y}-01-01' AND '{y}-12-31' {LIMIT};", ["sc_conf_conference"])


def t_reg_join_proj(rng):
    """등록자→행사 JOIN 학습(season은 conference 컬럼임을 학습). 투영 다양화."""
    se = rng.choice(list(P.SEASONS)); y = rng.choice(P.YEARS); sp = P.season_phrase(rng, se)
    proj, label = rng.choice([("r.name_eng", "영문명"), ("r.name", "이름"),
                              ("r.institution", "소속 기관"), ("r.payment_institution", "결제자 소속기관")])
    subj = f"{y}년 {sp} 행사 등록자의 {label}"
    return rec(P.q_list(rng, subj),
               f"SELECT {proj} FROM sc_conf_registrant r JOIN sc_conf_conference c ON r.conf_id = c.id "
               f"WHERE c.season = '{se}' AND c.year = {y} {LIMIT};",
               ["sc_conf_registrant", "sc_conf_conference"])


def t_reg_optional(rng):
    """선택 등록비(뱅큇) 학습: optional_fee_code IS (NOT) NULL. season/year JOIN 변형 포함."""
    applied = rng.random() < 0.5
    word = "신청한" if applied else "신청하지 않은"
    if rng.random() < 0.5:
        cond = "optional_fee_code IS NOT NULL" if applied else "optional_fee_code IS NULL"
        subj = f"선택 등록비(뱅큇 등)를 {word} 등록자"
        return rec(P.q_count(rng, subj),
                   f"SELECT COUNT(*) AS cnt FROM sc_conf_registrant WHERE {cond} {LIMIT};",
                   ["sc_conf_registrant"])
    se = rng.choice(list(P.SEASONS)); y = rng.choice(P.YEARS); sp = P.season_phrase(rng, se)
    cond = "r.optional_fee_code IS NOT NULL" if applied else "r.optional_fee_code IS NULL"
    subj = f"{y}년 {sp} 행사에서 선택 등록비를 {word} 등록자"
    return rec(P.q_count(rng, subj),
               "SELECT COUNT(*) AS cnt FROM sc_conf_registrant r "
               "JOIN sc_conf_conference c ON r.conf_id = c.id "
               f"WHERE c.season = '{se}' AND c.year = {y} AND {cond} {LIMIT};",
               ["sc_conf_registrant", "sc_conf_conference"])


def t_member_regsince(rng):
    """가입일 범위 학습: reg_date >= 기준."""
    y = rng.choice(P.YEARS)
    return rec(P.q_count(rng, f"{y}년 이후에 가입한 회원"),
               f"SELECT COUNT(*) AS cnt FROM sc_users WHERE reg_date >= '{y}-01-01' {LIMIT};", ["sc_users"])


# 일반 학습/Blind용 템플릿 풀 (가중치는 등장 빈도)
GENERAL_TEMPLATES = [
    t_member_membership, t_member_state, t_member_mileage, t_member_regyear,
    t_member_class_num, t_member_class_name, t_member_class_type, t_member_multi_and,
    t_orders_refund, t_orders_sum, t_orders_price_threshold, t_orders_max, t_orders_join_member,
    t_conf_by_season_year, t_conf_location, t_conf_daterange, t_conf_period_current,
    t_fee_amount, t_fee_flag, t_fee_period, t_fee_join_conf,
    t_reg_manuscript_null, t_reg_order_confirm, t_reg_institution_group, t_reg_join_conf,
    t_reg_institution_filter, t_conf_month_range, t_orders_year,
    t_orders_price_between, t_member_mileage_between, t_fee_amount_between, t_member_regmonth,
    t_member_expiring_soon, t_reg_pay_type, t_fee_optional, t_reg_payment_institution,
    t_cross_member_registrant, t_cross_annual_fee_registrant,
    # 재균형 보강
    t_groupby_count, t_agg_orders_byyear, t_agg_mileage, t_agg_fee_bytype,
    t_reg_isnull_byconf, t_member_classname_cond, t_cross_classname_season,
    # coverage 약점 보강 (날짜 컬럼·행사 JOIN은 가중치↑ 위해 2회 등록)
    t_conf_datecol, t_conf_datecol, t_reg_join_proj, t_reg_join_proj,
    t_reg_optional, t_member_regsince,
    # v47 오답 보강 (숫자등급 counter-example·DISTINCT·min/max·소속=r.institution)
    t_member_class_num, t_member_class_num, t_count_distinct,
    t_orders_minmax, t_orders_minmax, t_reg_inst_conf, t_reg_inst_conf,
    # v48 오답 보강 (소속=r.institution 강화 + hostingInstitution=주최 구분)
    t_reg_inst_conf, t_conf_hosting,
]
