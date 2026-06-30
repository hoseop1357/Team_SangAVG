const chat = document.getElementById("chat");
const input = document.getElementById("input");
const sendBtn = document.getElementById("sendBtn");
const SESSION = "s_" + Math.random().toString(36).slice(2);
const SQL_KW = /\b(SELECT|FROM|WHERE|JOIN|INNER|LEFT|RIGHT|ON|GROUP BY|ORDER BY|LIMIT|AND|OR|AS|COUNT|SUM|AVG|MAX|MIN|DISTINCT|IS|NULL|NOT|IN|BETWEEN|LIKE|DESC|ASC|CURDATE|YEAR|MONTH|INTERVAL)\b/gi;

function el(html) { const d = document.createElement("div"); d.innerHTML = html.trim(); return d.firstElementChild; }
function esc(s) { return String(s).replace(/[&<>]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c])); }
function highlightSql(sql) { return esc(sql).replace(SQL_KW, m => `<span class="kw">${m}</span>`); }

function addTurn() { const t = el(`<div class="turn"></div>`); chat.appendChild(t); chat.scrollTop = chat.scrollHeight; return t; }
function scroll() { chat.scrollTop = chat.scrollHeight; }

function renderResult(turn, q, data) {
  turn.appendChild(el(`<div class="question"><span class="ico">👤</span><span>${esc(q)}</span></div>`));

  if (data.rejected) {
    turn.appendChild(el(`<div class="reject">🚫 DB와 무관한 질문으로 차단되었습니다.</div>`));
    turn.appendChild(el(`<div class="meta">${esc(data.reason || "")}</div>`));
    scroll(); return;
  }

  // 생성된 SQL
  turn.appendChild(el(`<div class="sec-head">🔍 생성된 SQL</div>`));
  turn.appendChild(el(`<pre class="sql">${highlightSql(data.sql)}</pre>`));

  // 검증/후처리 안내
  const v = (data.steps && data.steps.validator) || {};
  if (v.added_limit)
    turn.appendChild(el(`<div class="note">ℹ️ LIMIT가 없어 자동으로 LIMIT 100을 추가했습니다.</div>`));
  if (v.removed_columns && v.removed_columns.length)
    turn.appendChild(el(`<div class="note">⚠️ 스키마에 없는 컬럼 조건을 제거했습니다: ${esc(v.removed_columns.join(", "))}</div>`));

  // 실행 결과
  if (data.exec_error) {
    turn.appendChild(el(`<div class="err">⚠ SQL 실행 오류: ${esc(data.exec_error)}</div>`));
    scroll(); return;
  }
  const chart = data.chart || { type: "table" };
  if (chart.type === "scalar")
    turn.appendChild(el(`<div class="scalar"><div class="v">${esc(chart.value)}</div><div class="l">${esc(chart.label)}</div></div>`));
  else if (chart.type === "bar") {
    const cv = el(`<div class="chartwrap"><canvas></canvas></div>`);
    turn.appendChild(cv); drawBar(cv.querySelector("canvas"), chart);
  }

  turn.appendChild(el(`<div class="sec-head">📊 실행 결과</div>`));
  turn.appendChild(renderTable(data.columns, data.rows, data.row_count));

  const tables = (data.steps && data.steps.pruning) || [];
  const fu = data.steps && data.steps.followup;
  turn.appendChild(el(`<div class="meta">
    <span class="tag">참조 테이블: ${tables.length ? esc(tables.join(", ")) : "-"}</span>
    ${fu ? '<span class="tag">후속 질문</span>' : ""}
    <span class="tag">총 ${data.row_count}행</span></div>`));
  scroll();
}

function renderTable(cols, rows, total) {
  if (!cols || !cols.length || !rows.length)
    return el(`<div class="meta">결과 행이 없습니다.</div>`);
  const head = `<th class="idx">#</th>` + cols.map(c => `<th>${esc(c)}</th>`).join("");
  const body = rows.slice(0, 100).map((r, i) =>
    `<tr><td class="idx">${i}</td>${r.map(v => `<td>${v === null ? "<i>NULL</i>" : esc(v)}</td>`).join("")}</tr>`).join("");
  const more = total > 100 ? `<div class="meta">… 외 ${total - 100}행 (상위 100행 표시)</div>` : "";
  const w = document.createElement("div");
  w.innerHTML = `<div class="tablewrap"><table><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table></div>${more}`;
  return w;
}

function drawBar(canvas, chart) {
  new Chart(canvas, {
    type: "bar",
    data: { labels: chart.labels, datasets: [{ label: chart.y, data: chart.values, backgroundColor: "#3b82f6", borderRadius: 4 }] },
    options: {
      plugins: { legend: { display: false }, title: { display: !!chart.y, text: `${chart.x} 별 ${chart.y}`, color: "#6b7280" } },
      scales: { x: { ticks: { color: "#8a94a3" }, grid: { display: false } },
                y: { ticks: { color: "#8a94a3" }, grid: { color: "#eef0f2" }, beginAtZero: true } }
    }
  });
}

async function send(text) {
  const q = (text || input.value).trim();
  if (!q) return;
  input.value = "";
  const turn = addTurn();
  turn.appendChild(el(`<div class="question"><span class="ico">👤</span><span>${esc(q)}</span></div>`));
  const loading = el(`<div class="meta"><span class="spinner"></span> SQL 생성 중…</div>`);
  turn.appendChild(loading); scroll();
  sendBtn.disabled = true;
  try {
    const res = await fetch("/api/query", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question: q, session_id: SESSION })
    });
    const data = await res.json();
    turn.innerHTML = "";
    if (!res.ok) {
      turn.appendChild(el(`<div class="question"><span class="ico">👤</span><span>${esc(q)}</span></div>`));
      turn.appendChild(el(`<div class="err">${esc(data.error || "요청 실패")}</div>`));
    } else { renderResult(turn, q, data); }
  } catch (e) {
    turn.innerHTML = "";
    turn.appendChild(el(`<div class="question"><span class="ico">👤</span><span>${esc(q)}</span></div>`));
    turn.appendChild(el(`<div class="err">네트워크 오류: ${esc(e.message)}</div>`));
  } finally {
    sendBtn.disabled = false; input.focus();
  }
}

sendBtn.onclick = () => send();
input.addEventListener("keydown", e => { if (e.key === "Enter") send(); });
document.addEventListener("click", e => { if (e.target.classList.contains("ex")) send(e.target.textContent); });

document.getElementById("resetBtn").onclick = async () => {
  try {
    await fetch("/api/reset", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id: SESSION })
    });
  } catch (e) { /* 무시 */ }
  chat.innerHTML = "";                          // 화면 대화 비우기
  input.focus();
};
