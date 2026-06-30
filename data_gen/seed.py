"""
seed.py — MySQL 더미 데이터(seed_data.sql) 생성. (테이블명세_씽크온웹_v2 스키마 기준)

평가 시 TYPE_A(실행 결과 일치) vs TYPE_C(실행 결과 불일치)를 구분하려면 평가 DB에
충분한 양의 일관된 데이터가 있어야 한다. 6개 테이블에 schema.sql과 정합한 더미
행을 생성한다(회비 유효/만료/임박 혼재, annual_fee 정회원, 무통장/뱅큇, IS NULL 혼재 등).

NOT NULL 컬럼은 모두 채우고, 질문이 참조하는 컬럼을 populate한다.
sc_conf_conference 날짜는 명세대로 VARCHAR(ISO 문자열)로 저장한다.
"""
from __future__ import annotations

import random
from datetime import date, timedelta

from data_gen import pools as P

REF_DATE = date(2026, 6, 23)
SEASON_MONTH = {"spring": 4, "summer": 7, "fall": 10, "winter": 1}
LOCATIONS = ["서울 코엑스", "부산 벡스코", "대전 컨벤션센터", "광주 김대중컨벤션센터",
             "제주 ICC", "인천 송도컨벤시아", "대구 엑스코"]
SOCIETY = 1


def _d(d: date) -> str:
    return d.strftime("%Y-%m-%d")


def _dt(d: date) -> str:
    return d.strftime("%Y-%m-%d %H:%M:%S")


def _sql(v) -> str:
    if v is None:
        return "NULL"
    if isinstance(v, str):
        return "'" + v.replace("\\", "\\\\").replace("'", "''") + "'"
    return str(v)


def _insert(table: str, columns: list[str], rows: list[tuple]) -> str:
    if not rows:
        return ""
    cols = ", ".join(f"`{c}`" for c in columns)
    body = ",\n".join(" (" + ", ".join(_sql(v) for v in r) + ")" for r in rows)
    return f"INSERT INTO {table} ({cols}) VALUES\n{body};\n"


def generate_seed(rng: random.Random, n_users=400, n_orders=700, n_registrants=900) -> str:
    out = [
        "-- =====================================================================",
        "-- seed_data.sql — 평가용 더미 데이터 (TYPE_A/TYPE_C 구분용)",
        "-- 실행 순서: schema.sql → seed_data.sql",
        "-- =====================================================================",
        "SET FOREIGN_KEY_CHECKS = 0;",
        "TRUNCATE TABLE sc_conf_registrant; TRUNCATE TABLE sc_conf_fee;",
        "TRUNCATE TABLE sc_conf_conference; TRUNCATE TABLE sc_user_orders;",
        "TRUNCATE TABLE sc_users; TRUNCATE TABLE sc_class;",
        "SET FOREIGN_KEY_CHECKS = 1;",
        "",
    ]

    # --- sc_class (5 고정 등급) ---
    classes = [
        (1, SOCIETY, "정회원", "Regular", "1", "A", 1, "BASIC", 1),
        (2, SOCIETY, "준회원", "Associate", "1", "A", 2, "BASIC", 2),
        (3, SOCIETY, "종신회원", "Lifetime", "1", "B", 3, "LIFETIME", 3),
        (4, SOCIETY, "명예회원", "Honorary", "1", "B", 4, "EXEMPT", 4),
        (5, SOCIETY, "학생회원", "Student", "1", "C", 5, "BASIC", 5),
    ]
    out.append(_insert("sc_class",
                       ["id", "society_id", "name_kor", "name_eng", "use", "group",
                        "number", "type", "priority"], classes))

    # --- sc_users ---
    user_rows, user_nos = [], []
    for i in range(1, n_users + 1):
        uno = f"U{i:05d}"
        user_nos.append(uno)
        cls = rng.choice(P.CLASS_NUMS)
        approved = 1 if rng.random() < 0.8 else 0
        approve_ready = 0 if approved else (1 if rng.random() < 0.5 else 0)
        enabled = 1 if rng.random() < 0.85 else 0
        # 회비 만료일: NULL / 과거(만료) / 미래(유효) / 임박(1~3개월 내) 혼재
        roll = rng.random()
        if roll < 0.15:
            membership = None
        elif roll < 0.45:
            membership = _dt(REF_DATE - timedelta(days=rng.randint(1, 700)))
        elif roll < 0.70:
            membership = _dt(REF_DATE + timedelta(days=rng.randint(1, 90))) # 임박
        else:
            membership = _dt(REF_DATE + timedelta(days=rng.randint(120, 700)))
        mileage = rng.choice([0, 100, 300, 500, 1000, 2000, 5000, 10000])
        reg = date(rng.choice(P.YEARS), rng.randint(1, 12), rng.randint(1, 28))
        user_rows.append((
            None, uno, SOCIETY, _dt(reg), cls, 1, mileage, None,
            approved, approve_ready, 1000 + i, membership, 1, None, 0, 0, enabled,
        ))
    out.append(_insert("sc_users",
                       ["ACOMS_USER_ID", "USER_NO", "SOCIETY_ID", "reg_date", "class", "status",
                        "mileage", "user_no_admin", "approved", "approve_ready", "USER_ID",
                        "membership_date", "membership_date_check", "confirm_date",
                        "email_return", "post_return", "enabled"], user_rows))

    # --- sc_user_orders ---
    order_rows = []
    for i in range(1, n_orders + 1):
        uno = rng.choice(user_nos)
        price = rng.choice(P.PRICES)
        confirm = 1 if rng.random() < 0.7 else 0
        refund = 1 if (confirm and rng.random() < 0.1) else 0
        od = date(rng.choice(P.YEARS), rng.randint(1, 12), rng.randint(1, 28))
        cd = _dt(od + timedelta(days=rng.randint(0, 5))) if confirm else None
        pay = rng.choice(P.PAY_TYPES)
        order_rows.append((
            i, f"ORD{i:07d}", SOCIETY, uno, price, 2, 2, _dt(od), _dt(od), cd,
            None, None, None, None, None, None, pay, None, None, None, None, None,
            confirm, 1, "KRW", refund, None,
        ))
    out.append(_insert("sc_user_orders",
                       ["id", "order_code", "society_id", "user_no", "price", "order_stat",
                        "cashby", "ready_datetime", "order_datetime", "confirm_datetime",
                        "ready_name", "memo", "account_no", "order_name", "fee_code_list", "tid",
                        "pay_type", "response_code", "response_msg", "later_payer_name",
                        "later_date", "reason", "confirm", "available", "currency_code",
                        "refund", "refund_datetime"], order_rows))

    # --- sc_conf_conference (날짜는 ISO 문자열 varchar) ---
    conf_rows, conf_ids = [], []
    cid = 0
    plan = [(y, se) for y in P.YEARS for se in ("spring", "fall")]
    plan += [(y, se) for y in (2025, 2026, 2027) for se in ("summer", "winter")]
    for y, se in plan:
        cid += 1
        conf_ids.append((cid, y))
        m = SEASON_MONTH[se]
        start = date(y, m, 10)
        sp = P.SEASONS[se][0]
        def s(dd):
            return _d(dd)
        conf_rows.append((
            cid, SOCIETY, cid, None, None, f"conf{y}{se}", None,
            f"{y} {sp} 학술대회", f"{y} {se} conference", rng.choice(["domestic", "international"]),
            y, se, "한국정보처리학회", "한국정보처리학회", None, rng.choice(LOCATIONS), None,
            s(start - timedelta(days=90)), s(start - timedelta(days=60)),
            s(start - timedelta(days=60)), s(start - timedelta(days=30)),
            s(start - timedelta(days=20)),
            s(start - timedelta(days=25)), s(start - timedelta(days=15)),
            s(start - timedelta(days=50)), s(start - timedelta(days=10)),
            s(start - timedelta(days=45)), s(start - timedelta(days=7)),
            s(start), s(start + timedelta(days=2)),
            None, None, None,
        ))
    out.append(_insert("sc_conf_conference",
                       ["id", "societyId", "mlConfId", "baseUrl", "groupName", "nameId", "cdn",
                        "nameKor", "nameEng", "type", "year", "season", "hostingInstitution",
                        "managingInstitution", "supportingInstitution", "location", "campus",
                        "absStartDate", "absEndDate", "submissionStartDate", "submissionEndDate",
                        "notificationDate", "finalSubmissionStartDate", "finalSubmissionEndDate",
                        "speakerPreRegStartDate", "speakerPreRegEndDate",
                        "generalPreRegStartDate", "generalPreRegEndDate",
                        "conferenceStartDate", "conferenceEndDate",
                        "venueAddress", "venueAddressDetailUrl", "venueImgUrl"], conf_rows))

    # --- sc_conf_fee (대회당 4종, 1종은 OPTIONAL 뱅큇) ---
    fee_rows, fee_by_conf, fid = [], {}, 0
    for cid, cyear in conf_ids:
        fee_by_conf[cid] = {"must": [], "optional": []}
        specs = [
            ("일반 등록비", "MUST", 0, 0, rng.choice([100000, 150000, 200000])),
            ("연회비", "MUST", 1, 0, rng.choice([50000, 70000, 100000])),
            ("논문 등록비", "MUST", 0, 1, rng.choice([30000, 50000, 70000])),
            ("Banquet (Lunch & Banquet Ticket)", "OPTIONAL", 0, 0, rng.choice([30000, 50000])),
        ]
        s_date = _dt(date(cyear, 1, 1)); e_date = _dt(date(cyear, 12, 31))
        for name, ftype, annual, manuscript, amount in specs:
            fid += 1
            code = f"SCF_{cid}_{fid}"
            fee_by_conf[cid]["optional" if ftype == "OPTIONAL" else "must"].append(code)
            fee_rows.append((
                fid, SOCIETY, cid, amount, code, None, ftype, 0, name,
                f"{cyear} {name}", s_date, e_date, 1, manuscript, "KRW", annual,
            ))
    out.append(_insert("sc_conf_fee",
                       ["id", "society_id", "conf_id", "amount", "code", "custom", "type",
                        "sc_class", "name", "payment_info", "start_date", "end_date", "use",
                        "manuscript_fee", "currency_code", "annual_fee"], fee_rows))

    # --- sc_conf_registrant ---
    reg_rows = []
    for i in range(1, n_registrants + 1):
        cid, _cy = rng.choice(conf_ids)
        uno = rng.choice(user_nos)
        fee_code = rng.choice(fee_by_conf[cid]["must"])
        opt = (rng.choice(fee_by_conf[cid]["optional"])
               if (fee_by_conf[cid]["optional"] and rng.random() < 0.3) else None)
        inst = rng.choice(P.INSTITUTIONS)
        pay = rng.choice(P.PAY_TYPES)
        confirm_date = _dt(REF_DATE - timedelta(days=rng.randint(1, 400))) if rng.random() < 0.8 else None
        manuscript_id = f"MS{rng.randint(1000, 9999)}" if rng.random() < 0.4 else None
        reg_rows.append((
            i, SOCIETY, cid, f"결제자{i}", inst, None, None, uno, None,
            f"등록자{i}", f"Registrant {i:04d}", inst, None, None, None, None, None,
            uno, None, f"ORD{i:07d}", fee_code, opt, confirm_date, None, "PAID", 1000 + i,
            rng.choice(P.CLASS_NUMS), pay, None, None, None, None, manuscript_id, None, None,
            0, None,
        ))
    out.append(_insert("sc_conf_registrant",
                       ["id", "society_id", "conf_id", "payment_name", "payment_institution",
                        "payment_phone", "payment_email", "payment_user_no", "payment_user_no_admin",
                        "name", "name_eng", "institution", "inst_id", "inst_eng", "email", "phone",
                        "phone_office", "user_no", "user_no_admin", "order_code", "fee_code",
                        "optional_fee_code", "order_confirm_date", "order_tid", "status", "user_id",
                        "sc_class", "pay_type", "later_payer_name", "later_date", "later_reason",
                        "recommender", "manuscript_submit_id", "manuscript_title",
                        "additional_information", "refund", "refund_date"], reg_rows))

    return "\n".join(out)
