"""
targeted.py — 10개 패턴 집중 평가셋 생성.

의 Targeted 10 패턴을 각각 생성한다.
"""
from __future__ import annotations

import random

from data_gen import pools as P
from data_gen.templates import rec

LIMIT = P.LIMIT


# 패턴 1 — 날짜 범위 (기간 조회)
def p1_daterange(rng):
    y = rng.choice(P.YEARS)
    col, label = rng.choice([
        ("conferenceStartDate", "개최"), ("absEndDate", "초록 마감"),
        ("submissionEndDate", "논문 마감"), ("generalPreRegEndDate", "사전등록 마감"),
    ])
    if rng.random() < 0.5:
        m = rng.choice(P.MONTHS); end = P.MONTH_END[m]
        subj = f"{y}년 {m}월에 {label}하는 학술대회"
        cond = f"{col} BETWEEN '{y}-{m:02d}-01' AND '{y}-{m:02d}-{end:02d}'"
    else:
        subj = f"{y}년에 {label}하는 학술대회"
        cond = f"{col} BETWEEN '{y}-01-01' AND '{y}-12-31'"
    return rec(P.q_list(rng, subj),
               f"SELECT nameKor, {col} FROM sc_conf_conference WHERE {cond} {LIMIT};",
               ["sc_conf_conference"])


# 패턴 2 — 집계 (COUNT, SUM, AVG)
_P2 = [
    ("전체 회원의 평균 마일리지", "SELECT AVG(mileage) AS avg_mileage FROM sc_users", ["sc_users"], "show"),
    ("전체 회원의 최대 마일리지", "SELECT MAX(mileage) AS max_mileage FROM sc_users", ["sc_users"], "show"),
    ("결제 확인된 주문의 총 금액", "SELECT SUM(price) AS total FROM sc_user_orders WHERE confirm = 1", ["sc_user_orders"], "show"),
    ("주문의 평균 금액", "SELECT AVG(price) AS avg_price FROM sc_user_orders", ["sc_user_orders"], "show"),
    ("주문의 최대 금액", "SELECT MAX(price) AS max_price FROM sc_user_orders", ["sc_user_orders"], "show"),
    ("등록비의 평균 금액", "SELECT AVG(amount) AS avg_amount FROM sc_conf_fee", ["sc_conf_fee"], "show"),
    ("전체 등록자", "SELECT COUNT(*) AS cnt FROM sc_conf_registrant", ["sc_conf_registrant"], "count"),
    ("전체 회원", "SELECT COUNT(*) AS cnt FROM sc_users", ["sc_users"], "count"),
    ("전체 학술대회", "SELECT COUNT(*) AS cnt FROM sc_conf_conference", ["sc_conf_conference"], "rows"),
    ("전체 등록비 항목", "SELECT COUNT(*) AS cnt FROM sc_conf_fee", ["sc_conf_fee"], "rows"),
    ("서로 다른 소속 기관", "SELECT COUNT(DISTINCT institution) AS cnt FROM sc_conf_registrant", ["sc_conf_registrant"], "rows"),
]


def p2_aggregate(rng):
    subj, sql, tables, kind = rng.choice(_P2)
    if kind == "count":
        q = P.q_count(rng, subj) # 사람: '몇 명'
    elif kind == "rows":
        q = P.q_count_rows(rng, subj) # 사물: '몇 개/건'
    else:
        q = P.q_show(rng, subj)
    return rec(q, f"{sql} {LIMIT};", tables)


# 패턴 3 — 다중 조건 AND
_AND_CONDS = [
    ("approved = 1", "승인된"), ("enabled = 1", "활성"),
    ("membership_date >= CURDATE()", "회비가 유효한"), ("approve_ready = 1", "승인 대기 중인"),
]


def p3_multi_and(rng):
    conds = rng.sample(_AND_CONDS, k=rng.choice([2, 3]))
    sql_parts = [c for c, _ in conds]
    kor = " ".join(k for _, k in conds) # 형용사형 라벨은 공백으로 연결
    if rng.random() < 0.5:
        th = rng.choice(P.MILEAGES)
        sql_parts.append(f"mileage >= {th}")
        kor += f" 마일리지 {th} 이상인"
    where = " AND ".join(sql_parts)
    subj = f"{kor} 회원"
    return rec(P.q_count(rng, subj),
               f"SELECT COUNT(*) AS cnt FROM sc_users WHERE {where} {LIMIT};", ["sc_users"])


# 패턴 4 — sc_class JOIN (등급명 조회)
def p4_class_join(rng):
    name = rng.choice(P.CLASS_NAMES)
    subj = f"{name} 등급의 회원"
    if rng.random() < 0.5:
        return rec(P.q_count(rng, subj),
                   "SELECT COUNT(*) AS cnt FROM sc_users u JOIN sc_class c ON u.class = c.id "
                   f"WHERE c.name_kor = '{name}' {LIMIT};", ["sc_users", "sc_class"])
    return rec(P.q_list(rng, subj),
               "SELECT u.USER_NO FROM sc_users u JOIN sc_class c ON u.class = c.id "
               f"WHERE c.name_kor = '{name}' {LIMIT};", ["sc_users", "sc_class"])


# 패턴 5 — sc_user_orders JOIN (결제 이력)
def p5_orders_join(rng):
    th = rng.choice(P.PRICES)
    subj = f"결제 금액이 {th}원을 초과한 회원"
    return rec(P.q_list(rng, subj),
               "SELECT DISTINCT u.USER_NO FROM sc_users u JOIN sc_user_orders o ON u.USER_NO = o.user_no "
               f"WHERE o.price > {th} AND o.confirm = 1 {LIMIT};", ["sc_users", "sc_user_orders"])


# 패턴 6 — sc_conf_conference 단독
def p6_conf_only(rng):
    se = rng.choice(list(P.SEASONS)); sp = P.season_phrase(rng, se)
    if rng.random() < 0.5:
        phr = rng.choice([
            f"{sp} 학술대회를 개최일 순으로 보여줘",
            f"{sp} 학술대회를 개최일 순으로 정렬해줘",
            f"개최일 순으로 {sp} 학술대회 목록을 보여줘",
        ])
        return rec(phr,
                   "SELECT nameKor, conferenceStartDate FROM sc_conf_conference "
                   f"WHERE season = '{se}' ORDER BY conferenceStartDate {LIMIT};", ["sc_conf_conference"])
    y = rng.choice(P.YEARS)
    return rec(P.q_show(rng, f"{y}년 {sp} 학술대회의 개최 장소"),
               f"SELECT nameKor, location FROM sc_conf_conference WHERE season = '{se}' AND year = {y} {LIMIT};",
               ["sc_conf_conference"])


# 패턴 7 — sc_conf_fee JOIN
def p7_fee_join(rng):
    y = rng.choice(P.YEARS)
    if rng.random() < 0.5:
        subj = f"{y}년 학술대회의 등록비 항목과 금액"
        return rec(P.q_list(rng, subj),
                   "SELECT f.name, f.amount FROM sc_conf_fee f JOIN sc_conf_conference c ON f.conf_id = c.id "
                   f"WHERE c.year = {y} {LIMIT};", ["sc_conf_fee", "sc_conf_conference"])
    subj = f"{y}년 학술대회 중 논문 등록비가 책정된 대회"
    return rec(P.q_list(rng, subj),
               "SELECT c.nameKor FROM sc_conf_conference c JOIN sc_conf_fee f ON c.id = f.conf_id "
               f"WHERE c.year = {y} AND f.manuscript_fee = 1 {LIMIT};",
               ["sc_conf_conference", "sc_conf_fee"])


# 패턴 8 — sc_conf_registrant JOIN
def p8_reg_join(rng):
    se = rng.choice(list(P.SEASONS)); sp = P.season_phrase(rng, se)
    y = rng.choice(P.YEARS)
    subj = f"{y}년 {sp} 학술대회 등록자의 소속 기관"
    return rec(P.q_list(rng, subj),
               "SELECT DISTINCT r.institution FROM sc_conf_registrant r "
               "JOIN sc_conf_conference c ON r.conf_id = c.id "
               f"WHERE c.season = '{se}' AND c.year = {y} {LIMIT};",
               ["sc_conf_registrant", "sc_conf_conference"])


# 패턴 9 — 크로스 도메인 (회원 + 학술대회)
def p9_cross(rng):
    name = rng.choice(P.CLASS_NAMES); y = rng.choice(P.YEARS)
    subj = f"{name}이면서 {y}년 학술대회에 등록한 사람"
    return rec(P.q_count(rng, subj),
               "SELECT COUNT(DISTINCT u.USER_NO) AS cnt FROM sc_users u "
               "JOIN sc_class cl ON u.class = cl.id "
               "JOIN sc_conf_registrant r ON u.USER_NO = r.user_no "
               "JOIN sc_conf_conference c ON r.conf_id = c.id "
               f"WHERE cl.name_kor = '{name}' AND c.year = {y} {LIMIT};",
               ["sc_users", "sc_class", "sc_conf_registrant", "sc_conf_conference"])


# 패턴 10 — IS NULL / IS NOT NULL
def p10_isnull(rng):
    target = rng.choice(["manuscript", "order_confirm"])
    not_null = rng.random() < 0.5
    if target == "manuscript":
        cond = "manuscript_submit_id IS NOT NULL" if not_null else "manuscript_submit_id IS NULL"
        subj = "논문을 제출한 등록자" if not_null else "논문을 제출하지 않은 등록자"
    else:
        cond = "order_confirm_date IS NOT NULL" if not_null else "order_confirm_date IS NULL"
        subj = "결제가 확인된 등록자" if not_null else "결제가 확인되지 않은 등록자"
    if rng.random() < 0.5:
        return rec(P.q_count(rng, subj),
                   f"SELECT COUNT(*) AS cnt FROM sc_conf_registrant WHERE {cond} {LIMIT};",
                   ["sc_conf_registrant"])
    return rec(P.q_list(rng, f"{subj}의 영문명"),
               f"SELECT name_eng FROM sc_conf_registrant WHERE {cond} {LIMIT};", ["sc_conf_registrant"])


PATTERNS = [
    (1, "날짜 범위 (기간 조회)", p1_daterange),
    (2, "집계 (COUNT, SUM, AVG)", p2_aggregate),
    (3, "다중 조건 AND", p3_multi_and),
    (4, "sc_class JOIN (등급명 조회)", p4_class_join),
    (5, "sc_user_orders JOIN (결제 이력)", p5_orders_join),
    (6, "sc_conf_conference 단독", p6_conf_only),
    (7, "sc_conf_fee JOIN", p7_fee_join),
    (8, "sc_conf_registrant JOIN", p8_reg_join),
    (9, "크로스 도메인 (회원+학술대회)", p9_cross),
    (10, "IS NULL / IS NOT NULL 패턴", p10_isnull),
]
