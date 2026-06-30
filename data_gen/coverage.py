"""
coverage.py — 컬럼 커버리지 평가셋 (실무용 재작성).

각 "업무상 의미 있는" 컬럼을 자연스러운 실무 질문으로 검증한다.
내부/기술 컬럼(ACOMS_USER_ID, USER_ID, tid, cdn, mlConfId 등)과 무의미한
쿼리(PK에 COUNT DISTINCT 등)는 제외한다. 질문은 사람이 실제로 물어볼 법한
형태로만 생성한다.

각 probe = (table, column, fn). fn(rng)는 해당 컬럼을 검증하는 실무 질문
1건을 반환한다. build_coverage가 컬럼 라운드로빈으로 수집한다.
"""
from __future__ import annotations

import random

from data_gen import pools as P
from data_gen.templates import qc, rec

LIMIT = P.LIMIT


def _r(q, sql, table, col):
    d = rec(q, sql, [table])
    d["table"] = table
    d["column"] = col
    return d


def _rj(q, sql, tables, table, col):
    d = rec(q, sql, tables)
    d["table"] = table
    d["column"] = col
    return d


# ---------------------------------------------------------------------------
# 빌더 — 컬럼 의미별 자연스러운 실무 질문 생성
# ---------------------------------------------------------------------------
def num_probe(table, col, label, entity, pool):
    """수치 컬럼: 'OO이 N 이상인 <entity> 수' / '<entity>의 OO 평균/최대/최소'."""
    def fn(rng):
        if rng.random() < 0.55:
            th = rng.choice(pool)
            subj = f"{label}{P.part(label,'이','가')} {th} 이상인 {entity}"
            return _r(P.q_count(rng, subj),
                      f"SELECT COUNT(*) AS cnt FROM {table} WHERE {qc(col)} >= {th} {LIMIT};", table, col)
        fn_, kor = rng.choice([("AVG", "평균"), ("MAX", "최대"), ("MIN", "최소")])
        return _r(P.q_show(rng, f"{entity}의 {label} {kor}"),
                  f"SELECT {fn_}({qc(col)}) AS val FROM {table} {LIMIT};", table, col)
    return (table, col, fn)


def flag_probe(table, col, yes_subj, no_subj, entity):
    """플래그(0/1): '<yes_subj> 수' / '<no_subj> 수'."""
    def fn(rng):
        if no_subj and rng.random() < 0.5:
            return _r(P.q_count(rng, no_subj),
                      f"SELECT COUNT(*) AS cnt FROM {table} WHERE {qc(col)} = 0 {LIMIT};", table, col)
        return _r(P.q_count(rng, yes_subj),
                  f"SELECT COUNT(*) AS cnt FROM {table} WHERE {qc(col)} = 1 {LIMIT};", table, col)
    return (table, col, fn)


def year_probe(table, col, action, entity):
    """날짜 컬럼: '{y}년에 <action>한 <entity> 수'."""
    def fn(rng):
        y = rng.choice(P.YEARS)
        return _r(P.q_count(rng, f"{y}년에 {action} {entity}"),
                  f"SELECT COUNT(*) AS cnt FROM {table} WHERE YEAR({qc(col)}) = {y} {LIMIT};", table, col)
    return (table, col, fn)


def confdate_probe(col, action):
    """학술행사 날짜(varchar): '{y}년에 <action>하는 행사 목록'."""
    def fn(rng):
        y = rng.choice(P.YEARS)
        return _r(P.q_list(rng, f"{y}년에 {action}하는 행사"),
                  f"SELECT nameKor, {col} FROM sc_conf_conference "
                  f"WHERE {col} BETWEEN '{y}-01-01' AND '{y}-12-31' {LIMIT};",
                  "sc_conf_conference", col)
    return ("sc_conf_conference", col, fn)


def isnull_probe(table, col, has_subj, no_subj):
    """IS (NOT) NULL 의미 컬럼."""
    def fn(rng):
        if rng.random() < 0.5:
            return _r(P.q_count(rng, has_subj),
                      f"SELECT COUNT(*) AS cnt FROM {table} WHERE {qc(col)} IS NOT NULL {LIMIT};", table, col)
        return _r(P.q_count(rng, no_subj),
                  f"SELECT COUNT(*) AS cnt FROM {table} WHERE {qc(col)} IS NULL {LIMIT};", table, col)
    return (table, col, fn)


def value_probe(table, col, label, pool, entity):
    """범주형: '<값>인 <entity> 수' (SELECT * 투영 모호성 제거 → COUNT 고정)."""
    def fn(rng):
        val = rng.choice(pool)
        return _r(P.q_count(rng, f"{label}{P.part(label,'이','가')} '{val}'인 {entity}"),
                  f"SELECT COUNT(*) AS cnt FROM {table} WHERE {qc(col)} = '{val}' {LIMIT};", table, col)
    return (table, col, fn)


def groupby_probe(table, col, subj):
    def fn(rng):
        return _r(P.q_list(rng, subj),
                  f"SELECT {qc(col)}, COUNT(*) AS cnt FROM {table} GROUP BY {qc(col)} ORDER BY cnt DESC {LIMIT};",
                  table, col)
    return (table, col, fn)


# ---------------------------------------------------------------------------
# 특수(JOIN/도메인) probe
# ---------------------------------------------------------------------------
def _classname_fn(rng):
    name = rng.choice(P.CLASS_NAMES)
    return _rj(P.q_count(rng, f"{name} 등급의 회원"),
               "SELECT COUNT(*) AS cnt FROM sc_users u JOIN sc_class c ON u.class = c.id "
               f"WHERE c.name_kor = '{name}' {LIMIT};", ["sc_users", "sc_class"], "sc_class", "name_kor")


def _classtype_fn(rng):
    t = rng.choice(P.CLASS_TYPES)
    return _r(P.q_list(rng, f"유형이 '{t}'인 등급"),
              f"SELECT name_kor, type FROM sc_class WHERE type = '{t}' {LIMIT};", "sc_class", "type")


def _membership_fn(rng):
    valid = rng.random() < 0.5
    cond = "membership_date >= CURDATE()" if valid else "membership_date < CURDATE()"
    subj = "회비가 유효한 회원" if valid else "회비가 만료된 회원"
    return _r(P.q_count(rng, subj),
              f"SELECT COUNT(*) AS cnt FROM sc_users WHERE {cond} {LIMIT};", "sc_users", "membership_date")


def _fee_period_fn(rng):
    return _r(P.q_list(rng, "현재 결제 가능한 등록비 항목"),
             "SELECT name, amount FROM sc_conf_fee WHERE CURDATE() BETWEEN start_date AND end_date "
             f"{LIMIT};", "sc_conf_fee", "start_date")


def _conf_loc_fn(rng):
    se = rng.choice(list(P.SEASONS)); sp = P.season_phrase(rng, se)
    return _r(P.q_show(rng, f"{sp} 학술행사의 개최 장소"),
             f"SELECT nameKor, location FROM sc_conf_conference WHERE season = '{se}' {LIMIT};",
             "sc_conf_conference", "location")


def _conf_name_fn(rng):
    y = rng.choice(P.YEARS)
    return _r(P.q_show(rng, f"{y}년에 개최된 행사 이름"),
             f"SELECT nameKor FROM sc_conf_conference WHERE year = {y} {LIMIT};",
             "sc_conf_conference", "nameKor")


def _reg_inst_name_fn(rng):
    inst = rng.choice(P.INSTITUTIONS)
    return _r(P.q_list(rng, f"{inst} 소속 등록자의 이름"),
             f"SELECT name FROM sc_conf_registrant WHERE institution = '{inst}' {LIMIT};",
             "sc_conf_registrant", "name")


def _reg_nameeng_fn(rng):
    se = rng.choice(list(P.SEASONS)); sp = P.season_phrase(rng, se)
    return _rj(P.q_list(rng, f"{sp} 행사 등록자의 영문명"),
               "SELECT r.name_eng FROM sc_conf_registrant r JOIN sc_conf_conference c ON r.conf_id = c.id "
               f"WHERE c.season = '{se}' {LIMIT};", ["sc_conf_registrant", "sc_conf_conference"],
               "sc_conf_registrant", "name_eng")


def _regdate_fn(rng):
    y = rng.choice(P.YEARS)
    return _r(P.q_count(rng, f"{y}년 이후에 가입한 회원"),
              f"SELECT COUNT(*) AS cnt FROM sc_users WHERE reg_date >= '{y}-01-01' {LIMIT};",
              "sc_users", "reg_date")


def _optfee_fn(rng):
    if rng.random() < 0.5:
        return _r(P.q_count(rng, "선택 등록비(뱅큇 등)를 신청한 등록자"),
                  "SELECT COUNT(*) AS cnt FROM sc_conf_registrant "
                  f"WHERE optional_fee_code IS NOT NULL {LIMIT};", "sc_conf_registrant", "optional_fee_code")
    return _r(P.q_count(rng, "선택 등록비를 신청하지 않은 등록자"),
              "SELECT COUNT(*) AS cnt FROM sc_conf_registrant "
              f"WHERE optional_fee_code IS NULL {LIMIT};", "sc_conf_registrant", "optional_fee_code")


def _confirmdt_fn(rng):
    y = rng.choice(P.YEARS)
    return _r(P.q_count_rows(rng, f"{y}년에 결제가 확인된 주문"),
              f"SELECT COUNT(*) AS cnt FROM sc_user_orders WHERE YEAR(confirm_datetime) = {y} {LIMIT};",
              "sc_user_orders", "confirm_datetime")


# ---------------------------------------------------------------------------
# probe 레지스트리 (업무 의미 있는 컬럼만)
# ---------------------------------------------------------------------------
COVERAGE_PROBES = [
    # 회원
    num_probe("sc_users", "mileage", "마일리지", "회원", P.MILEAGES),
    flag_probe("sc_users", "approved", "승인된 회원", "미승인 회원", "회원"),
    flag_probe("sc_users", "approve_ready", "승인 대기 중인 회원", None, "회원"),
    flag_probe("sc_users", "enabled", "활성 회원", "비활성 회원", "회원"),
    year_probe("sc_users", "reg_date", "가입한", "회원"),
    ("sc_users", "membership_date", _membership_fn),
    groupby_probe("sc_users", "class", "등급별 회원 수"),
    # 등급
    ("sc_class", "name_kor", _classname_fn),
    ("sc_class", "type", _classtype_fn),
    # 주문/결제
    num_probe("sc_user_orders", "price", "결제 금액", "주문", P.PRICES),
    flag_probe("sc_user_orders", "confirm", "결제 확인된 주문", "결제 미확인 주문", "주문"),
    flag_probe("sc_user_orders", "refund", "환불된 주문", "환불되지 않은 주문", "주문"),
    year_probe("sc_user_orders", "order_datetime", "발생한", "주문"),
    ("sc_user_orders", "confirm_datetime", _confirmdt_fn),
    ("sc_users", "reg_date", _regdate_fn),
    ("sc_conf_registrant", "optional_fee_code", _optfee_fn),
    value_probe("sc_user_orders", "pay_type", "결제 수단", P.PAY_TYPES, "주문"),
    groupby_probe("sc_user_orders", "pay_type", "결제 수단별 주문 수"),
    # 학술행사
    ("sc_conf_conference", "nameKor", _conf_name_fn),
    value_probe("sc_conf_conference", "season", "계절", list(P.SEASONS), "학술행사"),
    year_probe("sc_conf_conference", "year", "개최된", "행사"),
    ("sc_conf_conference", "location", _conf_loc_fn),
    confdate_probe("conferenceStartDate", "개최"),
    confdate_probe("conferenceEndDate", "종료"),
    confdate_probe("absEndDate", "초록 마감"),
    confdate_probe("absStartDate", "초록 접수를 시작"),
    confdate_probe("submissionEndDate", "논문 마감"),
    confdate_probe("submissionStartDate", "논문 투고를 시작"),
    confdate_probe("generalPreRegEndDate", "사전등록 마감"),
    confdate_probe("generalPreRegStartDate", "사전등록을 시작"),
    groupby_probe("sc_conf_conference", "season", "계절별 행사 수"),
    # 등록비
    num_probe("sc_conf_fee", "amount", "등록비", "항목", P.AMOUNTS),
    value_probe("sc_conf_fee", "type", "등록비 유형", P.FEE_TYPES, "항목"),
    flag_probe("sc_conf_fee", "annual_fee", "연회비 항목", None, "항목"),
    flag_probe("sc_conf_fee", "manuscript_fee", "논문 등록비 항목", None, "항목"),
    ("sc_conf_fee", "start_date", _fee_period_fn),
    # 등록자
    value_probe("sc_conf_registrant", "institution", "소속기관", P.INSTITUTIONS, "등록자"),
    value_probe("sc_conf_registrant", "payment_institution", "결제자 소속기관", P.INSTITUTIONS, "등록자"),
    value_probe("sc_conf_registrant", "pay_type", "결제 방식", P.PAY_TYPES, "등록자"),
    isnull_probe("sc_conf_registrant", "manuscript_submit_id", "논문을 제출한 등록자", "논문을 제출하지 않은 등록자"),
    isnull_probe("sc_conf_registrant", "order_confirm_date", "결제가 확인된 등록자", "결제가 확인되지 않은 등록자"),
    flag_probe("sc_conf_registrant", "refund", "환불된 등록", "환불되지 않은 등록", "등록"),
    ("sc_conf_registrant", "name", _reg_inst_name_fn),
    ("sc_conf_registrant", "name_eng", _reg_nameeng_fn),
    groupby_probe("sc_conf_registrant", "institution", "기관별 등록자 수"),
    groupby_probe("sc_conf_registrant", "pay_type", "결제 방식별 등록자 수"),
]
