"""
schema_utils.py — schema.sql 파싱 및 DDL 렌더링.

Schema Pruning / Validator / PromptBuilder가 공통으로 사용한다.
정규식 기반의 가벼운 DDL 파서로, CREATE TABLE 블록에서 테이블명·컬럼명·
타입·COMMENT를 추출한다(full SQL 파서는 불필요).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import config


@dataclass
class Column:
    name: str
    type: str
    comment: str = ""


@dataclass
class Table:
    name: str
    comment: str = ""
    columns: list[Column] = field(default_factory=list)

    @property
    def column_names(self) -> list[str]:
        return [c.name for c in self.columns]


# CREATE TABLE <name> ( ... 헤더만 매칭. 본문 괄호는 깊이 카운팅으로 처리한다
# (컬럼 타입 VARCHAR(20)이나 COMMENT '...(...)...' 안의 괄호 때문에 단순 정규식 불가).
_TABLE_HEAD_RE = re.compile(r"CREATE\s+TABLE\s+`?(?P<name>\w+)`?\s*\(", re.IGNORECASE)
# 컬럼 라인: `col` TYPE ... COMMENT '...'
_COL_RE = re.compile(
    r"^\s*`?(?P<name>\w+)`?\s+(?P<type>[A-Za-z]+(?:\(\d+(?:,\d+)?\))?)"
    r"(?P<rest>.*)$"
)
_COMMENT_RE = re.compile(r"COMMENT\s+'(?P<c>(?:[^']|'')*)'", re.IGNORECASE)
# 컬럼 정의가 아닌 라인 (제약조건 등)
_NON_COL = re.compile(r"^\s*(PRIMARY|FOREIGN|UNIQUE|KEY|CONSTRAINT|INDEX)\b", re.IGNORECASE)


def _split_balanced(text: str, open_idx: int) -> tuple[str, int]:
    """open_idx의 '(' 와 짝이 맞는 ')' 까지를 본문으로 반환. 따옴표 안 괄호는 무시."""
    depth = 0
    in_str = False
    i = open_idx
    while i < len(text):
        ch = text[i]
        if ch == "'" and (i == 0 or text[i - 1] != "\\"):
            in_str = not in_str
        elif not in_str:
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
                if depth == 0:
                    return text[open_idx + 1:i], i
        i += 1
    return text[open_idx + 1:], len(text)


def parse_schema(sql_text: str) -> dict[str, Table]:
    tables: dict[str, Table] = {}
    for m in _TABLE_HEAD_RE.finditer(sql_text):
        name = m.group("name")
        tbl = Table(name=name)

        body, close_idx = _split_balanced(sql_text, m.end() - 1)
        tail = sql_text[close_idx + 1:].split(";", 1)[0] # ) 와 ; 사이 = 테이블 옵션
        tail_comment = _COMMENT_RE.search(tail)
        if tail_comment:
            tbl.comment = tail_comment.group("c")

        for raw_line in body.splitlines():
            line = raw_line.strip().rstrip(",")
            if not line or line.startswith("--") or _NON_COL.match(line):
                continue
            col_m = _COL_RE.match(line)
            if not col_m:
                continue
            comment = ""
            cm = _COMMENT_RE.search(col_m.group("rest"))
            if cm:
                comment = cm.group("c")
            tbl.columns.append(
                Column(name=col_m.group("name"), type=col_m.group("type"), comment=comment)
            )
        tables[name] = tbl
    return tables


@lru_cache(maxsize=1)
def load_schema(path: str | None = None) -> dict[str, Table]:
    schema_path = Path(path) if path else config.SCHEMA_PATH
    return parse_schema(schema_path.read_text(encoding="utf-8"))


def render_table_ddl(table: Table, *, with_comment: bool) -> str:
    """단일 테이블을 컴팩트 DDL 문자열로 렌더링."""
    lines = [f"CREATE TABLE {table.name} ("]
    for i, col in enumerate(table.columns):
        tail = "," if i < len(table.columns) - 1 else ""
        if with_comment and col.comment:
            lines.append(f" {col.name} {col.type}{tail} -- {col.comment}")
        else:
            lines.append(f" {col.name} {col.type}{tail}")
    lines.append(");")
    return "\n".join(lines)


def render_ddl(table_names: list[str], *, with_comment: bool, path: str | None = None) -> str:
    """선택된 테이블 목록을 하나의 DDL 블록으로 렌더링(프롬프트 입력용)."""
    schema = load_schema(path)
    blocks = [
        render_table_ddl(schema[t], with_comment=with_comment)
        for t in table_names
        if t in schema
    ]
    return "\n\n".join(blocks)


def all_columns(path: str | None = None) -> dict[str, set[str]]:
    """테이블별 컬럼 집합 (Validator의 환각 컬럼 검사용)."""
    schema = load_schema(path)
    return {name: set(t.column_names) for name, t in schema.items()}


def all_table_names(path: str | None = None) -> list[str]:
    return list(load_schema(path).keys())
