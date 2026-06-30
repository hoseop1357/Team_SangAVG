"""
exec_check.py — SQL 실행 결과 기반 자동 검증(경고만).

생성된 SQL을 실제로 실행해 결과 건수를 보고, 의심 신호를 경고로 남긴다.
SQL 자체를 수정하거나 차단하지 않는다(Validator의 역할과 분리).

  결과 0건 → "조건이 너무 좁을 수 있음" (BOTH_EMPTY 후보)
  결과 N건 초과 → "조건이 너무 넓음, LIMIT 확인"

평가(evaluate.py)에서는 이 신호로 BOTH_EMPTY 케이스를 자동 분류하는 데 쓸 수 있다.
"""
from __future__ import annotations

from dataclasses import dataclass

import config


@dataclass
class ExecCheck:
    ran: bool
    row_count: int = 0
    warnings: list[str] = None
    error: str = ""

    def __post_init__(self):
        if self.warnings is None:
            self.warnings = []


class ExecutionChecker:
    def __init__(self, mysql_cfg: config.MySQLConfig | None = None, warn_max_rows: int = 10000):
        self.cfg = mysql_cfg or config.MYSQL
        self.warn_max_rows = warn_max_rows
        self._conn = None

    def connect(self) -> "ExecutionChecker":
        import mysql.connector

        self._conn = mysql.connector.connect(
            host=self.cfg.host, port=self.cfg.port, user=self.cfg.user,
            password=self.cfg.password, database=self.cfg.database,
        )
        return self

    def check(self, sql: str) -> ExecCheck:
        if self._conn is None:
            return ExecCheck(ran=False, error="DB 미연결")
        try:
            cur = self._conn.cursor()
            cur.execute(sql.rstrip("; "))
            rows = cur.fetchall()
            cur.close()
        except Exception as e: # noqa: BLE001
            return ExecCheck(ran=False, error=str(e))

        n = len(rows)
        warnings: list[str] = []
        if n == 0:
            warnings.append("결과 0건 — 조건이 너무 좁을 수 있음")
        elif n > self.warn_max_rows:
            warnings.append(f"결과 {n}건 — 조건이 너무 넓음, LIMIT 확인 권장")
        return ExecCheck(ran=True, row_count=n, warnings=warnings)
