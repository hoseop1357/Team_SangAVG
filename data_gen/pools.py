"""
pools.py — 슬롯 값 풀 + 패러프레이즈 헬퍼.

도메인 규칙(schema.sql 기준)에 맞는 값들을 모아두고, 한국어 질문의 표현
다양성을 위해 여러 패러프레이즈 변형을 제공한다. 모든 무작위는 주입된
random.Random 인스턴스로 처리해 재현성을 보장한다.
"""
from __future__ import annotations

import random

# ---------------------------------------------------------------------------
# 슬롯 값 풀 — 고유 질문/SQL 공간을 충분히 확보하기 위해 범위를 넓게 둔다.
#
# ---------------------------------------------------------------------------
YEARS = list(range(2018, 2028)) # 10

# season 값(영문) ↔ 한국어 표현
SEASONS = {
    "spring": ["춘계", "봄"],
    "fall": ["추계", "가을"],
    "winter": ["동계", "겨울"],
    "summer": ["하계", "여름"],
}

# sc_class.name_kor ↔ type 매핑 (schema COMMENT 기준, seed_data.sql과 일치)
CLASS_NAMES = ["정회원", "준회원", "종신회원"]
CLASS_TYPES = ["BASIC", "EXEMPT", "LIFETIME"]
CLASS_NUMS = [1, 2, 3, 4, 5] # 숫자 등급 (counter-example용)

AMOUNTS = list(range(10000, 300001, 10000)) # 30
MILEAGES = [100, 300, 500, 1000, 1500, 2000, 3000, 5000, 7000, 10000]
PRICES = list(range(10000, 500001, 10000)) # 50
ROW_LIMITS = [5, 10, 20, 50, 100]

INSTITUTIONS = [
    "서울대학교", "한밭대학교", "KAIST", "연세대학교", "고려대학교",
    "포항공과대학교", "성균관대학교", "한양대학교", "경북대학교", "전남대학교",
    "중앙대학교", "이화여자대학교", "부산대학교", "충남대학교", "순천향대학교",
]

# sc_conf_registrant.pay_type / sc_user_orders.pay_type (명세 질문 예시: 무통장 입금)
PAY_TYPES = ["무통장입금", "신용카드", "계좌이체", "간편결제"]

# sc_conf_fee.type — MUST(필수) / OPTIONAL(선택, 예: 뱅큇)
FEE_TYPES = ["MUST", "OPTIONAL"]

MONTHS = list(range(1, 13))
MONTH_END = {1: 31, 2: 28, 3: 31, 4: 30, 5: 31, 6: 30,
             7: 31, 8: 31, 9: 30, 10: 31, 11: 30, 12: 31}

LIMIT = "LIMIT 100"


# ---------------------------------------------------------------------------
# 한국어 조사 처리 (받침 유무에 따라 은/는·을/를·이/가 선택)
# ---------------------------------------------------------------------------
def has_jongseong(word: str) -> bool:
    """단어 마지막 글자에 받침(종성)이 있는지."""
    if not word:
        return False
    ch = word[-1]
    if "가" <= ch <= "힣":
        return (ord(ch) - 0xAC00) % 28 != 0
    return False # 숫자/영문 등은 받침 없음으로 처리


def josa(word: str, with_jong: str, without_jong: str) -> str:
    return word + (with_jong if has_jongseong(word) else without_jong)


def part(word: str, with_jong: str, without_jong: str) -> str:
    """조사(파티클)만 반환 — 단어는 붙이지 않음. f-string에서 {word}{part(...)}로 사용."""
    return with_jong if has_jongseong(word) else without_jong


# ---------------------------------------------------------------------------
# 패러프레이즈 헬퍼
# ---------------------------------------------------------------------------
def pick(rng: random.Random, seq):
    return rng.choice(seq)


def q_count(rng: random.Random, subject: str) -> str:
    """'<subject> 수는?' 류 집계 질문의 다양한 표현."""
    eun = josa(subject, "은", "는")
    variants = [
        f"{subject} 수는?",
        f"{eun} 몇 명인가요?",
        f"{eun} 몇 명이야?",
        f"{subject} 수를 알려줘",
        f"{subject}의 수는?",
        f"{subject} 인원은 몇 명이야?",
        f"{eun} 총 몇 명이지?",
    ]
    return rng.choice(variants)


def q_count_rows(rng: random.Random, subject: str) -> str:
    """'몇 건/개' 류 (사람이 아닌 대상)."""
    eun = josa(subject, "은", "는")
    variants = [
        f"{subject} 수는?",
        f"{eun} 몇 건이야?",
        f"{subject} 건수를 알려줘",
        f"{eun} 몇 개인가요?",
        f"{subject}의 개수는?",
    ]
    return rng.choice(variants)


def q_list(rng: random.Random, subject: str) -> str:
    """'<subject> 목록을 보여줘' 류 조회 질문."""
    eul = josa(subject, "을", "를")
    variants = [
        f"{subject} 목록을 보여줘",
        f"{eul} 알려줘",
        f"{eul} 보여줘",
        f"{subject} 리스트를 보여줘",
        f"{eul} 조회해줘",
        f"{eul} 찾아줘",
    ]
    return rng.choice(variants)


def q_show(rng: random.Random, subject: str) -> str:
    """'<subject>는?' 류 단일/소량 조회."""
    eun = josa(subject, "은", "는")
    eul = josa(subject, "을", "를")
    iga = josa(subject, "이", "가")
    variants = [
        f"{eun}?",
        f"{eul} 알려줘",
        f"{eun} 무엇인가요?",
        f"{eul} 보여줘",
        f"{iga} 궁금해",
    ]
    return rng.choice(variants)


def season_phrase(rng: random.Random, season_en: str) -> str:
    return rng.choice(SEASONS[season_en])
