"""
app.py — NL2SQL 챗봇 웹 서버 (Flask).

질문(자연어) → NL2SQL 파이프라인으로 SQL 생성 → MariaDB(ml_eval)에서 실행
→ {SQL, 결과 테이블, 차트}를 프론트엔드로 반환.

실행:
  # 평가 DB(3307/ml_eval)와 학습 어댑터를 환경변수로 지정(기본값 내장)
  python app.py # http://127.0.0.1:5000
  set NL2SQL_ADAPTER=outputs/v46_full (또는 outputs/smoke)

GPU가 학습으로 점유 중이면 모델 로드가 OOM 날 수 있으니, 학습이 끝난 뒤 실행하세요.
"""
from __future__ import annotations

import datetime
import decimal
import os

# config 임포트 전에 평가 DB/어댑터 기본값을 지정(없을 때만)
os.environ.setdefault("NL2SQL_DB_HOST", "127.0.0.1")
os.environ.setdefault("NL2SQL_DB_PORT", "3307")
os.environ.setdefault("NL2SQL_DB_USER", "root")
os.environ.setdefault("NL2SQL_DB_PASSWORD", "")
os.environ.setdefault("NL2SQL_DB_NAME", "ml_eval")
os.environ.setdefault("NL2SQL_ADAPTER", "outputs/v46_full")

from flask import Flask, jsonify, request, send_from_directory # noqa: E402

import config # noqa: E402

app = Flask(__name__, static_folder="frontend", static_url_path="")

_pipe = None
_sessions: dict = {}


# ---------------------------------------------------------------------------
def get_pipe():
    """파이프라인(+모델) 지연 로딩 — 첫 질문 때 1회만 로드."""
    global _pipe
    if _pipe is None:
        from inference import NL2SQLPipeline
        cfg = config.PipelineConfig.for_finetuned()
        cfg.multi_turn = True # 챗봇: 후속 질문 컨텍스트 참조
        _pipe = NL2SQLPipeline(cfg, load_model=True)
    return _pipe


def _cell(v):
    """JSON 직렬화 가능한 형태로 변환."""
    if isinstance(v, decimal.Decimal):
        return float(v)
    if isinstance(v, (datetime.datetime, datetime.date)):
        return v.isoformat(sep=" ")
    if isinstance(v, (bytes, bytearray)):
        return v.decode("utf-8", "replace")
    return v


def run_sql(sql: str):
    import mysql.connector
    c = config.MYSQL
    con = mysql.connector.connect(host=c.host, port=c.port, user=c.user,
                                  password=c.password, database=c.database)
    cur = con.cursor()
    cur.execute(sql.rstrip("; "))
    cols = [d[0] for d in cur.description] if cur.description else []
    rows = [[_cell(v) for v in r] for r in cur.fetchall()]
    cur.close()
    con.close()
    return cols, rows


def suggest_chart(cols, rows):
    """결과 모양에 따라 시각화 방식 추천."""
    if not rows or not cols:
        return {"type": "empty"}
    # 단일 값(COUNT/SUM/AVG 등) → 숫자 카드
    if len(rows) == 1 and len(cols) == 1:
        return {"type": "scalar", "label": cols[0], "value": rows[0][0]}
    # 2열 + 두번째 열이 숫자(GROUP BY 집계) → 막대그래프
    if len(cols) == 2 and len(rows) >= 2:
        vals = [r[1] for r in rows]
        if all(isinstance(v, (int, float)) for v in vals):
            labels = [str(r[0]) for r in rows][:30]
            return {"type": "bar", "labels": labels, "values": [float(v) for v in vals][:30],
                    "x": cols[0], "y": cols[1]}
    return {"type": "table"}


# ---------------------------------------------------------------------------
@app.route("/api/query", methods=["POST"])
def api_query():
    from src.conversation import ConversationSession

    data = request.get_json(force=True) or {}
    question = (data.get("question") or "").strip()
    sid = data.get("session_id") or "default"
    if not question:
        return jsonify({"error": "질문이 비어있습니다."}), 400

    session = _sessions.setdefault(sid, ConversationSession())
    try:
        return _do_query(question, session)
    except Exception:  # noqa: BLE001
        import traceback
        tb = traceback.format_exc()
        print(tb, flush=True)
        return jsonify({"error": tb}), 500


def _do_query(question, session):
    result = get_pipe().run(question, session=session)

    if result.rejected:
        return jsonify({"rejected": True, "reason": result.reject_reason,
                        "steps": result.steps})

    sql = result.sql
    cols, rows, exec_err = [], [], None
    try:
        cols, rows = run_sql(sql)
    except Exception as e: # noqa: BLE001
        exec_err = str(e)

    return jsonify({
        "sql": sql,
        "columns": cols,
        "rows": rows[:200],
        "row_count": len(rows),
        "exec_error": exec_err,
        "chart": suggest_chart(cols, rows) if not exec_err else {"type": "error"},
        "steps": {
            "pruning": result.steps.get("pruning", {}).get("tables"),
            "followup": bool(result.steps.get("multi_turn")),
            "validator": result.steps.get("validator"),
        },
    })


@app.route("/api/reset", methods=["POST"])
def api_reset():
    sid = (request.get_json(force=True) or {}).get("session_id") or "default"
    _sessions.pop(sid, None)
    return jsonify({"ok": True})


@app.route("/api/health")
def api_health():
    return jsonify({"ok": True, "db": config.MYSQL.database,
                    "adapter": config.ADAPTER_DIR,
                    "model_loaded": _pipe is not None})


@app.route("/")
def index():
    return send_from_directory("frontend", "index.html")


if __name__ == "__main__":
    print(f"[app] DB={config.MYSQL.host}:{config.MYSQL.port}/{config.MYSQL.database} "
          f"adapter={config.ADAPTER_DIR}")
    print("[app] http://127.0.0.1:5000 (첫 질문 시 모델 로드 — 수십 초 소요)")
    app.run(host="127.0.0.1", port=5000, debug=False, threaded=True)
