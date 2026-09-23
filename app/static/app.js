/* 地址匹配服务前端（原生 JS，无构建步骤） */
"use strict";

const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g,
  (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

const STATUS_LABEL = {
  auto_matched: "自动匹配", needs_review: "待确认", no_match: "无匹配",
  confirmed: "已确认", rejected: "已判定无匹配",
};

function toast(msg) {
  const t = $("toast");
  t.textContent = msg;
  t.classList.add("show");
  setTimeout(() => t.classList.remove("show"), 2200);
}

async function api(method, url, body) {
  const opts = { method, headers: {} };
  if (body instanceof FormData) opts.body = body;
  else if (body !== undefined) {
    opts.headers["Content-Type"] = "application/json";
    opts.body = JSON.stringify(body);
  }
  const resp = await fetch(url, opts);
  if (!resp.ok) {
    let detail = resp.statusText;
    try { detail = (await resp.json()).detail || detail; } catch (e) {}
    throw new Error(detail);
  }
  return resp.json();
}

// ---------------- Tab 切换 ----------------
document.querySelectorAll("nav button").forEach((btn) => {
  btn.onclick = () => {
    document.querySelectorAll("nav button").forEach((b) => b.classList.remove("active"));
    btn.classList.add("active");
    ["match", "batch", "review", "standard"].forEach((name) => {
      $("tab-" + name).classList.toggle("hidden", name !== btn.dataset.tab);
    });
    if (btn.dataset.tab === "review") loadResults(currentFilter);
    if (btn.dataset.tab === "standard") loadStandards();
  };
});

// ---------------- 统计 ----------------
async function loadStats() {
  try {
    const s = await api("GET", "/api/stats");
    const sc = s.status_counts || {};
    $("stats").innerHTML = `
      <div class="stat"><div class="num">${s.standard_count}</div><div class="lab">标准地址</div></div>
      <div class="stat"><div class="num" style="color:var(--green)">${sc.auto_matched || 0}</div>
        <div class="lab">自动匹配</div></div>
      <div class="stat"><div class="num" style="color:var(--amber)">${sc.needs_review || 0}</div>
        <div class="lab">待确认</div></div>
      <div class="stat"><div class="num" style="color:var(--red)">${sc.no_match || 0}</div>
        <div class="lab">无匹配</div></div>
      <div class="stat"><div class="num">${s.result_count}</div><div class="lab">匹配结果总数</div></div>`;
  } catch (e) { /* 忽略 */ }
}

// ---------------- 候选渲染 ----------------
function renderCandidate(c, rank) {
  const pct = Math.round(c.score * 100);
  const barColor = c.score >= 0.8 ? "var(--green)" : c.score >= 0.6 ? "var(--d97706,#d97706)" : "var(--red)";
  const tokens = (c.matched_tokens || []).map(
    (t) => `<span class="chip">${esc(t)}</span>`).join("");
  const fuzzy = (c.fuzzy_pairs || []).map(
    ([a, b]) => `<span class="chip fuzzy" title="模糊命中">${esc(a)}≈${esc(b)}</span>`).join("");
  const conflicts = (c.conflicts || []).map(
    (x) => `<div class="conflict">⚠️ ${esc(x)}</div>`).join("");
  return `<div class="cand ${rank === 0 ? "best" : ""}">
    <div class="cand-head">
      <div><strong>#${rank + 1} ${esc(c.ext_id)}</strong>
        <div class="sub">${esc(c.std_text)}${c.std_city ? " · " + esc(c.std_city) : ""}
          ${c.std_postcode ? " · " + esc(c.std_postcode) : ""}</div>
        ${c.std_house_number ? `<div class="sub">门牌号：<span class="mono">${esc(c.std_house_number)}</span></div>` : ""}
      </div>
      <div style="text-align:right;min-width:110px">
        <div class="score" style="color:${barColor}">${pct}</div>
        <div class="bar"><div style="width:${pct}%;background:${barColor}"></div></div>
        <div class="sub">词元 ${Math.round(c.token_score * 100)} /
          门牌号 ${Math.round(c.number_score * 100)}</div>
      </div>
    </div>
    ${tokens || fuzzy ? `<div style="margin-top:7px">
      <div class="sub">命中词元：</div>${tokens}${fuzzy}</div>` : ""}
    ${conflicts}
  </div>`;
}

function renderMatchResult(r, withReview) {
  const badge = `<span class="badge b-${r.status === "auto_matched" ? "auto"
    : r.status === "needs_review" ? "review"
    : r.status === "confirmed" ? "confirmed"
    : r.status === "rejected" ? "rejected" : "nomatch"}">${STATUS_LABEL[r.status] || r.status}</span>`;
  const reasons = (r.reasons || []).map((x) => `<div class="reason">🔍 ${esc(x)}</div>`).join("");
  const reviewBtns = withReview && !r.reviewed ? `
    <div class="actions">
      ${r.best_candidate ? `<button class="btn small" onclick="review(${r.id},'confirm')">
        ✅ 确认首选 #1（${esc(r.best_candidate.ext_id)}）</button>` : ""}
      ${(r.candidates || []).slice(1).map((c, i) =>
        `<button class="btn secondary small" onclick="review(${r.id},'choose',${c.standard_id})">
        改选 #${i + 2}（${esc(c.ext_id)} ${Math.round(c.score * 100)}分）</button>`).join("")}
      <button class="btn ghost small" onclick="review(${r.id},'reject')">✕ 判定无匹配</button>
    </div>` : (r.reviewed ? `<p class="muted">已复核：${esc(r.reviewed_action || "")}</p>` : "");
  return `<div class="card">
    <div class="cand-head"><h2 style="margin:0">匹配结果 ${badge}</h2>
      <span class="muted mono">${esc(r.house_number ? "门牌号：" + r.house_number : "")}</span></div>
    <div class="sub" style="margin-top:6px">输入：${esc(r.input)}
      ${r.normalized ? `<br>归一化：<span class="mono">${esc(r.normalized)}</span>` : ""}</div>
    ${reasons}
    ${(r.candidates || []).map(renderCandidate).join("") ||
      `<p class="muted" style="margin-top:10px">没有候选结果。</p>`}
    ${reviewBtns}
  </div>`;
}

// ---------------- 单条匹配 ----------------
$("m-run").onclick = async () => {
  const address = $("m-address").value.trim();
  if (!address) return toast("请输入地址");
  const body = {
    address,
    city: $("m-city").value.trim(), state: $("m-state").value.trim(),
    postcode: $("m-postcode").value.trim(), persist: $("m-persist").checked,
  };
  const t = parseFloat($("m-threshold").value);
  if (!isNaN(t)) body.threshold = t;
  const m = parseFloat($("m-margin").value);
  if (!isNaN(m)) body.margin = m;
  $("m-run").disabled = true;
  try {
    const r = await api("POST", "/api/match", body);
    lastMatchResultId = r.id || null;
    $("m-result").innerHTML = renderMatchResult(r, body.persist);
    loadStats();
  } catch (e) { toast("匹配失败：" + e.message); }
  $("m-run").disabled = false;
};

$("m-sample").onclick = () => {
  $("m-address").value = "123 MAIN ST., Apt 4b, Springfield, IL";
  $("m-city").value = "Springfield";
  $("m-state").value = "IL";
};

window.review = async (resultId, action, standardId) => {
  try {
    await api("POST", `/api/match-results/${resultId}/review`,
      { action, standard_id: standardId || null, note: "" });
    toast("复核已保存");
    // 刷新当前展示中的结果卡片与列表
    if (lastMatchResultId === resultId) {
      const r = await api("GET", `/api/match-results/${resultId}`);
      r.input = r.raw_input;
      $("m-result").innerHTML = renderMatchResult(r, true);
    }
    if (!$("tab-review").classList.contains("hidden")) await loadResults(currentFilter);
    loadStats();
  } catch (e) { toast("操作失败：" + e.message); }
};

let lastMatchResultId = null;

// ---------------- 批量 ----------------
let batchFile = null;
$("b-file").onchange = (e) => {
  batchFile = e.target.files[0];
  $("b-file-name").textContent = batchFile ? batchFile.name : "选择一个 CSV 文件";
  $("b-run").disabled = !batchFile;
};
$("b-run").onclick = async () => {
  if (!batchFile) return;
  const fd = new FormData();
  fd.append("file", batchFile);
  try {
    const r = await api("POST", "/api/match/upload", fd);
    renderBatch(r);
    loadStats();
  } catch (e) { toast("批量匹配失败：" + e.message); }
};
$("b-lines-run").onclick = async () => {
  const addresses = $("b-lines").value.split("\n").map((s) => s.trim()).filter(Boolean);
  if (!addresses.length) return toast("请粘贴至少一条地址");
  try {
    const r = await api("POST", "/api/match/batch", { addresses });
    renderBatch(r);
    loadStats();
  } catch (e) { toast("批量匹配失败：" + e.message); }
};

function renderBatch(r) {
  const s = r.summary || {};
  const summary = `<div class="card">
    <h2>批量结果（共 ${r.count} 条）</h2>
    <span class="badge b-auto">自动匹配 ${s.auto_matched || 0}</span>
    <span class="badge b-review">待确认 ${s.needs_review || 0}</span>
    <span class="badge b-nomatch">无匹配 ${s.no_match || 0}</span>
  </div>`;
  const items = r.results.map((x) => {
    const c = x.best_candidate;
    return `<tr>
      <td>${x.id || ""}</td>
      <td>${esc(x.input)}</td>
      <td><span class="badge b-${x.status === "auto_matched" ? "auto"
        : x.status === "needs_review" ? "review" : "nomatch"}">${STATUS_LABEL[x.status]}</span>
        ${x.reasons && x.reasons.length ? `<div class="sub">${esc(x.reasons.join("；"))}</div>` : ""}</td>
      <td>${c ? `${esc(c.ext_id)}<div class="sub mono">${Math.round(c.score * 100)}分 ·
        词元 ${Math.round(c.token_score * 100)}/门牌号 ${Math.round(c.number_score * 100)}</div>
        ${c.conflicts && c.conflicts.length ? `<div class="sub" style="color:var(--red)">
          ${esc(c.conflicts.join("；"))}</div>` : ""}` : "—"}</td>
      <td><button class="btn secondary small" onclick="showResult(${x.id})">查看/复核</button></td>
    </tr>`;
  }).join("");
  $("b-result").innerHTML = summary +
    `<div class="card"><table><thead><tr><th>结果ID</th><th>输入地址</th><th>状态</th>
      <th>首选候选</th><th></th></tr></thead><tbody>${items}</tbody></table></div>`;
}

window.showResult = async (id) => {
  const r = await api("GET", `/api/match-results/${id}`);
  $("b-result").innerHTML = renderMatchResult(r, true) +
    `<div class="actions"><button class="btn secondary small" onclick="location.reload()">← 返回列表</button></div>`;
};

// ---------------- 复核队列 ----------------
let currentFilter = "";
document.querySelectorAll(".r-filter").forEach((btn) => {
  btn.onclick = () => loadResults(btn.dataset.f);
});
$("r-refresh").onclick = () => loadResults(currentFilter);

async function loadResults(filter) {
  currentFilter = filter;
  document.querySelectorAll(".r-filter").forEach((b) =>
    b.classList.toggle("active", b.dataset.f === filter));
  const url = "/api/match-results?limit=100" + (filter ? `&status=${encodeURIComponent(filter)}` : "");
  const r = await api("GET", url);
  if (!r.items.length) {
    $("r-list").innerHTML = `<p class="muted">暂无记录。</p>`;
    return;
  }
  $("r-list").innerHTML = `<table><thead><tr><th>ID</th><th>输入地址</th><th>状态</th>
    <th>首选候选 / 冲突</th><th>操作</th></tr></thead><tbody>${
    r.items.map((x) => {
      const c = x.best_candidate;
      const reviewed = x.reviewed ? `<div class="sub">复核动作：${esc(x.reviewed_action)}</div>` : "";
      return `<tr>
        <td>${x.id}</td>
        <td>${esc(x.raw_input)}${x.source_id ? `<div class="sub">来源：${esc(x.source_id)}</div>` : ""}</td>
        <td><span class="badge b-${x.status === "auto_matched" ? "auto"
          : x.status === "needs_review" ? "review" : x.status === "confirmed" ? "confirmed"
          : x.status === "rejected" ? "rejected" : "nomatch"}">${STATUS_LABEL[x.status] || x.status}</span>
          ${x.reasons && x.reasons.length ? `<div class="sub">${esc(x.reasons.join("；"))}</div>` : ""}
          ${reviewed}</td>
        <td>${c ? `${esc(c.ext_id)} <span class="mono sub">${Math.round(c.score * 100)}分</span>
          <div class="sub">${esc(c.std_text)}</div>
          ${c.conflicts && c.conflicts.length ? `<div class="sub" style="color:var(--red)">
            ${esc(c.conflicts.join("；"))}</div>` : ""}` : "—"}</td>
        <td><button class="btn secondary small" onclick="showReviewDetail(${x.id})">查看/复核</button></td>
      </tr>`;
    }).join("")}</tbody></table>`;
}

window.showReviewDetail = async (id) => {
  const r = await api("GET", `/api/match-results/${id}`);
  r.input = r.raw_input;
  $("r-list").innerHTML = renderMatchResult(r, true) +
    `<div class="actions"><button class="btn secondary small"
      onclick="loadResults(currentFilter)">← 返回列表</button></div>`;
};

// ---------------- 标准地址管理 ----------------
$("s-add").onclick = async () => {
  const body = {
    ext_id: $("s-id").value.trim(), address: $("s-address").value.trim(),
    city: $("s-city").value.trim(), state: $("s-state").value.trim(),
    postcode: $("s-postcode").value.trim(),
  };
  if (!body.ext_id || !body.address) return toast("编号和地址必填");
  try {
    await api("POST", "/api/standard-addresses", body);
    ["s-id", "s-address", "s-city", "s-state", "s-postcode"].forEach((k) => ($(k).value = ""));
    toast("已保存");
    loadStandards();
    loadStats();
  } catch (e) { toast("保存失败：" + e.message); }
};

let stdFile = null;
$("s-file").onchange = (e) => {
  stdFile = e.target.files[0];
  $("s-file-name").textContent = stdFile ? stdFile.name : "选择一个 CSV 文件";
  $("s-upload").disabled = !stdFile;
};
$("s-upload").onclick = async () => {
  if (!stdFile) return;
  const fd = new FormData();
  fd.append("file", stdFile);
  try {
    const r = await api("POST", "/api/standard-addresses/upload", fd);
    toast(`导入完成：新增 ${r.imported}，更新 ${r.updated}，共 ${r.total}`);
    loadStandards();
    loadStats();
  } catch (e) { toast("导入失败：" + e.message); }
};

let stdOffset = 0;
let stdQuery = "";
let stdTotal = 0;
async function loadStandards(reset = true) {
  if (reset) stdOffset = 0;
  const r = await api("GET",
    `/api/standard-addresses?limit=${stdOffset + 50}&offset=0&q=${encodeURIComponent(stdQuery)}`);
  stdTotal = r.total;
  const rows = r.items.map((x) => `<tr>
    <td>${esc(x.ext_id)}</td><td>${esc(x.address)}</td>
    <td>${esc(x.city || "")}</td><td>${esc(x.state || "")}</td>
    <td>${esc(x.postcode || "")}</td>
    <td>${x.house_number ? `<span class="mono">${esc(x.house_number)}</span>` : ""}</td>
    <td><button class="btn ghost small" onclick="delStandard(${x.id})">删除</button></td>
  </tr>`).join("");
  $("s-list").innerHTML = `<p class="muted">共 ${r.total} 条</p>
    <table><thead><tr><th>编号</th><th>地址</th><th>城市</th><th>州/省</th><th>邮编</th>
      <th>门牌号</th><th></th></tr></thead><tbody>${rows}</tbody></table>`;
  $("s-more").style.visibility = stdOffset + 50 < stdTotal ? "visible" : "hidden";
}
$("s-more").onclick = () => { stdOffset += 50; loadStandards(false); };
let searchTimer;
$("s-q").oninput = () => {
  clearTimeout(searchTimer);
  searchTimer = setTimeout(() => { stdQuery = $("s-q").value.trim(); loadStandards(); }, 300);
};
window.delStandard = async (id) => {
  if (!confirm("确认删除该标准地址？历史匹配结果中的引用会被置空。")) return;
  try {
    await api("DELETE", `/api/standard-addresses/${id}`);
    toast("已删除");
    loadStandards();
    loadStats();
  } catch (e) { toast("删除失败：" + e.message); }
};

// 初始化
loadStats();
setInterval(loadStats, 15000);
