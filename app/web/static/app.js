"use strict";
const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
const esc = value => String(value ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const state = {view:"calls", calls:[], selected:new Set(), searchId:null, callPage:1, callQuery:null, adminPage:1, taskPage:1, adminRows:[], editing:null, deleting:null, detailId:null, polling:null, bindingsScene:null, bindingsSceneName:null, bindingsRows:[]};
const terminal = ["COMPLETED", "REVIEW_REQUIRED", "SKIPPED"];
const labels = {PENDING:"待执行",QUEUED:"排队中",RUNNING:"执行中",DOWNLOADING:"下载录音",ASR_PROCESSING:"ASR 转写中",ASR_COMPLETED:"转写已完成",LLM_PROCESSING:"LLM 评判中",COMPLETED:"已完成",DONE:"已结束",REVIEW_REQUIRED:"待人工复核",SKIPPED:"已跳过",FAILED:"执行失败",PASS:"合规",FAIL:"不合规",REVIEW:"待复核",NOT_APPLICABLE:"不适用",REQUIRED:"必须表达",FORBIDDEN:"禁止表达",CONDITIONAL_REQUIRED:"条件必说",CRITICAL:"致命",HIGH:"高",MEDIUM:"中",LOW:"低"};
const titles = {calls:"通话质检",tasks:"任务与结果",scenes:"营销场景",rules:"话术规则",bindings:"场景规则关联"};
const descriptions = {scenes:"维护业务场景信息，将源通话中的场景 ID 与质检规则关联。",rules:"把话术标准转化为可评判的规则，设置权重、严重程度与生效时间。",bindings:"为不同营销场景配置适用规则，按场景覆盖评分权重。",tasks:"跟踪执行进度，查看转写文本、规则命中与合规证据。"};
let toastTimer, callRequest = 0, adminRequest = 0, taskRequest = 0, detailRequest = 0;

async function api(path, options = {}) {
  const response = await fetch(path, {...options, headers:{"Content-Type":"application/json", "x-qc-request":"1", ...(options.headers || {})}});
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : `请求失败（${response.status}）`);
  return data;
}
function toast(message, error = false) {
  clearTimeout(toastTimer);
  $("#toast").textContent = message;
  $("#toast").className = `toast${error ? " error" : ""}`;
  toastTimer = setTimeout(() => $("#toast").classList.add("hidden"), error ? 8000 : 4000);
}
function dateLabel(value) {
  if (!value) return "—";
  const d = new Date(value);
  return Number.isNaN(d.getTime()) ? String(value) : d.toLocaleString("zh-CN", {hour12:false,timeZone:"Asia/Shanghai"});
}
function localDate(value) {
  const d = new Date(value), pad = x => String(x).padStart(2,"0");
  return `${d.getFullYear()}-${pad(d.getMonth()+1)}-${pad(d.getDate())}`;
}
function datetimeInput(value) {
  if (!value) return "";
  const d = new Date(new Date(value).getTime() + 8*60*60*1000);
  return d.toISOString().slice(0,16);
}
function badge(value) {
  const color = ["PASS","COMPLETED","DONE"].includes(value) ? "green" : ["FAIL","FAILED"].includes(value) ? "red" : ["REVIEW","REVIEW_REQUIRED"].includes(value) ? "amber" : ["DOWNLOADING","ASR_PROCESSING","ASR_COMPLETED","LLM_PROCESSING","RUNNING","QUEUED","PENDING"].includes(value) ? "purple" : "";
  return `<span class="badge ${color}">${esc(labels[value] || value || "未评判")}</span>`;
}
const enabledBadge = value => `<span class="badge ${value ? "green" : ""}">${value ? "已启用" : "已停用"}</span>`;
const emptyRow = (columns, title, message) => `<tr><td colspan="${columns}"><div class="empty"><span>◇</span><h3>${esc(title)}</h3><p>${esc(message)}</p></div></td></tr>`;
const errorRow = (columns, message) => `<tr><td colspan="${columns}" class="error-row">${esc(message)}</td></tr>`;
function viewTaskButton(task) { return task ? `<button class="link-button" data-detail="${esc(task.id)}">查看明细</button>` : `<span class="muted small">待评判</span>`; }

async function checkHealth() {
  const button = $("#connection"); button.disabled = true;
  try {
    const h = await api("/api/health");
    button.textContent = "● 数据库已连接"; button.className = "connection online";
    if (h.demo) button.textContent = "● 离线演示数据库";
    $("#demo-banner").classList.toggle("hidden", !h.demo);
    $("#connection-error").classList.add("hidden");
    $("#metric-threshold").textContent = h.pass_score;
    $("#gate-hint").textContent = `已接通 · 有录音 · 通话 ≥ ${h.min_talk_seconds} 秒`;
  } catch (error) {
    button.textContent = "○ 数据库未连接 · 重试"; button.className = "connection offline";
    $("#connection-error").textContent = error.message;
    $("#connection-error").classList.remove("hidden");
  } finally { button.disabled = false; }
}
function navigate(view) {
  if (!titles[view]) view = "calls";
  state.view = view; clearTimeout(state.polling);
  $$("[data-view]").forEach(button => button.classList.toggle("active", button.dataset.view === view));
  $("#breadcrumb").textContent = titles[view];
  $("#page-title").textContent = view === "calls" ? "让每一通沟通，都有据可评" : titles[view];
  $("#page-description").textContent = descriptions[view] || "筛选通话、选择录音，一站完成话术合规评判。";
  $("#eyebrow").textContent = view === "calls" ? "CALL QUALITY REVIEW" : view === "tasks" ? "TASKS & REPORTS" : "QUALITY CONFIGURATION";
  $("#page-tag").textContent = view === "calls" ? "人工选择 · 自动评判" : view === "tasks" ? "全过程可追溯" : "参数即时保存";
  $("#view-calls").classList.toggle("hidden", view !== "calls");
  $("#view-tasks").classList.toggle("hidden", view !== "tasks");
  $("#view-admin").classList.toggle("hidden", ["calls","tasks"].includes(view));
  if (view === "tasks") loadTasks();
  else if (!["calls","tasks"].includes(view)) {
    state.adminPage = 1;
    // 先恢复布局，再设置文本内容（避免从 bindings 切换时元素不存在）
    const adminSection = $("#view-admin");
    if (!adminSection.querySelector("#add-record") || adminSection.querySelector(".bindings-layout")) {
      adminSection.innerHTML = ADMIN_TEMPLATE;
      $("#admin-filter").addEventListener("submit", event => {event.preventDefault(); state.adminPage=1; loadAdmin();});
      $("#admin-prev").addEventListener("click", () => {state.adminPage--; loadAdmin();});
      $("#admin-next").addEventListener("click", () => {state.adminPage++; loadAdmin();});
      $("#add-record").addEventListener("click", () => openEditor());
    }
    $("#admin-search").value = "";
    const helpText = {scenes:"场景 ID 必须与源通话 act_scene_id 一致。停用场景后，该场景不再加载规则。删除前须先移除场景规则关联。",rules:"按通话发生时间匹配规则生效区间（开始包含、结束不含）。致命规则不通过会直接判定不合规。修改规则不会重跑已完成任务。",bindings:"选择一个营销场景，在右侧管理该场景关联的规则（添加、编辑、删除、启停）。",tasks:"跟踪执行进度，查看转写文本、规则命中与合规证据。"}[view];
    if ($("#admin-title")) $("#admin-title").textContent = titles[view];
    if ($("#admin-help")) $("#admin-help").textContent = helpText;
    loadAdmin();
  }
}

function selectable(call) { return call.qualifiable && !terminal.includes(call.task?.status); }
function updateSelection() {
  ["#selection-count", "#metric-selected"].forEach(id => $(id).textContent = state.selected.size);
  $("#run-selected").disabled = !state.selected.size;
  const possible = state.calls.filter(selectable);
  $("#select-all").disabled = !possible.length;
  $("#select-all").checked = possible.length > 0 && possible.every(c => state.selected.has(c.key));
  $("#select-all").indeterminate = state.selected.size > 0 && state.selected.size < possible.length;
  $$("[data-select]").forEach(box => box.checked = state.selected.has(box.dataset.select));
}
async function loadCalls(page = 1, newQuery = false) {
  const request = ++callRequest;
  if (newQuery || !state.callQuery) {
    const form = new FormData($("#call-filter"));
    state.callQuery = {start:form.get("start"),end:form.get("end"),scene:form.get("scene").trim(),seat:form.get("seat").trim(),only_qualifiable:form.has("only_qualifiable")};
  }
  state.selected.clear(); state.calls = []; state.searchId = null; updateSelection();
  $("#calls-body").innerHTML = emptyRow(7,"正在查询通话…","按日期从新到旧排列");
  $("#calls-prev").disabled = $("#calls-next").disabled = true;
  const queryButton = $("#call-filter button"); queryButton.disabled = true;
  try {
    const result = await api(`/api/calls?${new URLSearchParams({...state.callQuery,page,size:30})}`);
    if (request !== callRequest) return;
    state.calls = result.items; state.searchId = result.search_id; state.callPage = page;
    $("#metric-calls").textContent = result.items.length;
    $("#metric-qualified").textContent = result.items.filter(c => c.qualifiable).length;
    $("#call-count").textContent = `${result.items.length} 条`;
    $("#calls-body").innerHTML = result.items.length ? result.items.map(c => `<tr>
      <td class="check-cell"><input type="checkbox" data-select="${esc(c.key)}" aria-label="选择订单 ${esc(c.order_id)}" ${selectable(c) ? "" : "disabled"}></td>
      <td><strong>${esc(dateLabel(c.start_time))}</strong><small class="cell-id">${esc(c.order_id || c.key)}</small><small>${esc(c.phone)}</small></td>
      <td><strong>${esc(c.scene_name || "未命名场景")}</strong><small>${esc(c.scene_id)}</small></td>
      <td>${esc(c.seat_name || "—")}<small>${esc(c.seat_id)}</small></td>
      <td>${esc(c.talk_seconds)} 秒<small>${c.has_recording ? "有录音" : "无录音"} · ${esc(c.call_result)}</small></td>
      <td>${c.qualifiable ? badge(c.task?.status) : '<span class="badge">不具备质检资格</span>'}</td><td>${viewTaskButton(c.task)}</td></tr>`).join("") : emptyRow(7,"没有找到符合条件的通话","请调整日期、场景或坐席筛选条件。");
    $("#calls-page-label").textContent = `第 ${page} 页 · 每页 30 条 · 已完成记录可查看原结果`;
    $("#calls-prev").disabled = page === 1; $("#calls-next").disabled = !result.has_more;
    updateSelection();
  } catch(error) {
    if (request !== callRequest) return;
    $("#calls-body").innerHTML = errorRow(7,error.message);
    $("#call-count").textContent = "查询失败";
    $("#metric-calls").textContent = $("#metric-qualified").textContent = "—";
  } finally { if (request === callRequest) queryButton.disabled = false; }
}
async function runSelected() {
  const button = $("#run-selected"); button.disabled = true; button.textContent = "正在提交…";
  try {
    await api("/api/jobs", {method:"POST", body:JSON.stringify({search_id:state.searchId,call_keys:[...state.selected]})});
    state.selected.clear(); updateSelection(); location.hash = "tasks";
    toast("已提交评判，执行进度将在任务页自动更新");
  } catch(error) { toast(error.message,true); }
  finally { button.textContent = "▷ 开始评判"; updateSelection(); }
}

async function loadTasks() {
  clearTimeout(state.polling);
  const request = ++taskRequest;
  try {
    const params = new URLSearchParams({page:state.taskPage,size:30});
    if ($("#task-status").value) params.set("status",$("#task-status").value);
    const [jobs, history] = await Promise.all([api("/api/jobs"),api(`/api/tasks?${params}`)]);
    if (request !== taskRequest || state.view !== "tasks") return;
    $("#jobs-list").innerHTML = jobs.items.length ? jobs.items.map(job => {
      const finished = job.items.filter(i => ["DONE","FAILED"].includes(i.state)).length;
      return `<article class="job-card"><div class="job-heading"><div><h3>评判批次 <span class="muted small">${esc(job.id.slice(0,8))}</span></h3><p class="muted small">${esc(dateLabel(job.created_at))} · 共 ${job.items.length} 条</p></div><div class="inline"><progress value="${finished}" max="${job.items.length}" aria-label="批次完成进度"></progress><span class="small muted">${finished} / ${job.items.length}</span></div></div><div class="job-list">${job.items.map(item => {
        const status = item.state === "RUNNING" ? item.task?.current_stage || "RUNNING" : item.state === "DONE" ? item.task?.status || item.outcome : item.state;
        return `<div class="job-item"><span class="job-name">${esc(item.scene_name || "未命名场景")} · ${esc(item.seat_name || "未命名坐席")}<small>${esc(item.order_id || item.key)}</small></span>${badge(status)}${item.error ? `<span class="small muted">${esc(item.error)} · 可重新选择通话重试</span>` : ""}${viewTaskButton(item.task)}</div>`;
      }).join("")}</div></article>`;
    }).join("") : '<div class="notice">暂无提交批次。前往「通话质检」选择录音开始评判；服务重启前的记录可在下方历史任务中查看。</div>';
    $("#task-count").textContent = `${history.total} 条`;
    $("#tasks-body").innerHTML = history.items.length ? history.items.map(t => `<tr><td><strong>#${esc(t.id)}</strong><small>${esc(dateLabel(t.created_at))}</small><small class="cell-id">${esc(t.order_id)}</small></td><td>${esc(t.scene_name || t.scene_id)}</td><td>${esc(t.seat_name || t.seat_id || "—")}</td><td>${badge(t.status)}<small>${esc(t.error_code || labels[t.current_stage] || "")}</small></td><td>${t.overall_status ? `${badge(t.overall_status)} <strong>${esc(t.score)} 分</strong>` : '<span class="muted">—</span>'}</td><td>${viewTaskButton(t)}</td></tr>`).join("") : emptyRow(6,"暂无历史任务","完成的评判结果会保存到数据库，服务重启后仍可查询。");
    $("#tasks-page-label").textContent = `第 ${state.taskPage} 页 · 共 ${history.total} 条`;
    $("#tasks-prev").disabled = state.taskPage === 1; $("#tasks-next").disabled = state.taskPage * 30 >= history.total;
    if ($("#detail").open && state.detailId && state.detailLive) loadDetail(state.detailId,false);
  } catch(error) {
    if (request === taskRequest && state.view === "tasks") {
      $("#jobs-list").innerHTML = `<div class="notice danger">${esc(error.message)}</div>`;
      $("#tasks-body").innerHTML = errorRow(6,"暂时无法刷新任务，请检查连接。");
    }
  } finally { if (request === taskRequest && state.view === "tasks") state.polling = setTimeout(loadTasks,3000); }
}

async function loadDetail(id, open = true) {
  state.detailId = id;
  const request = ++detailRequest;
  if (open) {
    $("#detail-title").textContent = `任务 #${id} · 评判明细`;
    $("#detail-content").textContent = "正在加载…";
    if (!$("#detail").open) $("#detail").showModal();
  }
  try {
    const data = await api(`/api/tasks/${encodeURIComponent(id)}`);
    if (request !== detailRequest || !$("#detail").open) return;
    const {task,result,rules,transcript} = data;
    state.detailLive = ![...terminal,"FAILED"].includes(task.status);
    const canRerun = ["COMPLETED","REVIEW_REQUIRED","SKIPPED","FAILED"].includes(task.status);
    const errors = {SCENE_RULE_NOT_CONFIGURED:"该场景在通话时间没有有效规则，请检查场景、关联、启用状态及生效日期。",AsrError:"ASR 转写失败，请检查内网连接、接口凭据和音频格式后重试。",RecordingDownloadError:"录音下载失败，请检查源录音地址及内网连接后重试。"};
    $("#detail-content").innerHTML = `<div class="result-overview"><div class="score">${result ? esc(result.score) : "—"}<small>分</small></div><div><strong>${esc(task.scene_name || "未命名场景")} · ${esc(task.seat_name || "未命名坐席")}</strong><div class="report-meta">${esc(dateLabel(task.created_at))} · ${badge(task.status)} ${result ? badge(result.overall_status) : ""}</div></div>${result ? `<span class="muted small">${result.total_rules} 条规则 · ${result.passed_rules} 合规 · ${result.failed_rules} 不合规 · ${result.review_rules} 待复核</span>` : ""}</div>
      ${task.error_code ? `<div class="notice ${task.status === "FAILED" ? "danger" : ""}">${esc(errors[task.error_code] || `异常类型：${task.error_code}。检查服务配置后，可在通话页重新选择失败记录执行。`)}</div>` : ""}
      ${canRerun ? `<div class="notice"><div class="inline" style="justify-content:space-between"><span>使用最新规则重新评判此通话</span><button class="primary" data-rerun="${esc(task.id)}">↻ 重新评判</button></div></div>` : ""}
      <div class="report-columns"><section><h3>ASR 转写原文</h3><div class="transcript">${esc(transcript || "尚无转写文本。任务执行后将在这里展示。")}</div></section><section><h3>逐条规则与证据</h3>${rules.length ? rules.map(rule => {
        let evidence = []; try { const parsed = JSON.parse(rule.evidence_json || "[]"); if (Array.isArray(parsed)) evidence = parsed; } catch {}
        return `<article class="rule-card"><header><div><strong>${esc(rule.rule_name || rule.rule_code)}</strong><small>${esc(rule.rule_code)} · ${esc(labels[rule.severity] || rule.severity)}风险 · 权重 ${esc(rule.weight)}</small></div>${badge(rule.status)}</header><p>${esc(rule.reason)}</p>${evidence.map(e => `<blockquote>${esc(e)}</blockquote>`).join("")}<div class="muted small">${rule.evidence_verified ? "证据校验通过" : "证据校验未通过，需复核"} · 置信度 ${rule.confidence == null ? "—" : `${Math.round(Number(rule.confidence)*100)}%`}</div></article>`;
      }).join("") : '<div class="notice">暂无逐规则结果。执行中任务请稍候；跳过的任务不会产生合规评分。</div>'}</section></div>`;
  } catch(error) { if (request === detailRequest) $("#detail-content").textContent = error.message; }
}

const ADMIN_TEMPLATE = `<div class="notice" id="admin-help"></div><section class="panel"><div class="panel-heading"><div class="inline"><h2 id="admin-title">营销场景</h2><span class="count" id="admin-count">—</span></div><button id="add-record" class="primary">＋ 新增</button></div><form id="admin-filter" class="admin-filter"><input id="admin-search" placeholder="搜索名称或编号" maxlength="200" aria-label="搜索名称或编号"><button type="submit">⌕ 搜索</button></form><div class="table-wrap"><table><thead id="admin-head"></thead><tbody id="admin-body"></tbody></table></div><div class="table-footer"><span id="admin-page-label" class="muted small"></span><div class="inline"><button id="admin-prev">上一页</button><button id="admin-next">下一页</button></div></div></section>`;

async function loadAdmin() {
  const resource = state.view, request = ++adminRequest;
  if (resource === "bindings") return loadBindingsView();
  // 恢复标准 admin 布局（loadBindingsView 会替换 #view-admin 内容）
  const section = $("#view-admin");
  // 只要不是标准布局（从 bindings 切换过来），就强制恢复
  if (!section.querySelector("#add-record") || section.querySelector(".bindings-layout")) {
    section.innerHTML = ADMIN_TEMPLATE;
    // 重新绑定事件
    $("#admin-filter").addEventListener("submit", event => {event.preventDefault(); state.adminPage=1; loadAdmin();});
    $("#admin-prev").addEventListener("click", () => {state.adminPage--; loadAdmin();});
    $("#admin-next").addEventListener("click", () => {state.adminPage++; loadAdmin();});
    $("#add-record").addEventListener("click", () => openEditor());
  }
  const headers = {scenes:["场景名称 / 源场景 ID","场景描述","状态","更新时间","操作"],rules:["规则名称 / 编码","规则类型","严重程度 / 权重","生效区间","状态","操作"]};
  $("#admin-head").innerHTML = `<tr>${headers[resource].map(h => `<th>${h}</th>`).join("")}</tr>`;
  $("#admin-body").innerHTML = emptyRow(headers[resource].length,"正在读取配置…","");
  try {
    const data = await api(`/api/admin/${resource}?${new URLSearchParams({q:$("#admin-search").value.trim(),page:state.adminPage,size:30})}`);
    if (request !== adminRequest || state.view !== resource) return;
    state.adminRows = data.items;
    $("#admin-count").textContent = `${data.total} 条`;
    $("#admin-body").innerHTML = data.items.length ? data.items.map(row => {
      let cells;
      if (resource === "scenes") cells = `<td><strong>${esc(row.scene_name)}</strong><small class="cell-id">${esc(row.source_scene_id)}</small></td><td class="description-cell">${esc(row.description || "—")}</td><td>${enabledBadge(row.enabled)}</td><td class="small">${esc(dateLabel(row.updated_at))}</td>`;
      else cells = `<td><strong>${esc(row.rule_name)}</strong><small class="cell-id">${esc(row.rule_code)}</small></td><td>${esc(labels[row.rule_type])}</td><td>${esc(labels[row.severity])}风险<small>权重 ${esc(row.weight)}</small></td><td class="small">${esc(row.effective_from ? dateLabel(row.effective_from) : "不限开始")}<small>至 ${esc(row.effective_to ? dateLabel(row.effective_to) : "长期有效")}</small></td><td>${enabledBadge(row.enabled)}</td>`;
      return `<tr>${cells}<td><div class="inline"><button class="link-button" data-edit="${esc(row.id)}">编辑</button><button class="link-button delete" data-delete="${esc(row.id)}">删除</button></div></td></tr>`;
    }).join("") : emptyRow(headers[resource].length,"暂无匹配配置","点击「新增」添加，或调整搜索条件。");
    $("#admin-page-label").textContent = `第 ${state.adminPage} 页 · 共 ${data.total} 条`;
    $("#admin-prev").disabled = state.adminPage === 1; $("#admin-next").disabled = state.adminPage * 30 >= data.total;
    if (data.total && !data.items.length && state.adminPage > 1) {state.adminPage--; loadAdmin();}
  } catch(error) { if (request === adminRequest) $("#admin-body").innerHTML = errorRow(headers[resource].length,error.message); }
}

// ---- 场景规则关联（以场景为单位配置） ----
async function loadBindingsView() {
  const request = ++adminRequest;
  // 左侧场景列表
  const adminSection = $("#view-admin");
  adminSection.innerHTML = `<div class="notice" id="admin-help">选择一个营销场景，在右侧管理该场景关联的规则（添加、编辑、删除、启停）。</div>
    <div class="bindings-layout">
      <section class="panel bindings-left">
        <div class="panel-heading"><div class="inline"><h2>营销场景</h2><span class="count" id="admin-count">—</span></div></div>
        <form id="admin-filter" class="admin-filter"><input id="admin-search" placeholder="搜索场景名称或 ID" maxlength="200" aria-label="搜索场景"><button type="submit">⌕ 搜索</button></form>
        <div class="table-wrap"><table><thead id="admin-head"></thead><tbody id="admin-body"></tbody></table></div>
        <div class="table-footer"><span id="admin-page-label" class="muted small"></span><div class="inline"><button id="admin-prev">上一页</button><button id="admin-next">下一页</button></div></div>
      </section>
      <section class="panel bindings-right" id="bindings-detail">
        <div class="empty"><span>⇄</span><h3>选择左侧场景</h3><p>选择一个营销场景后，在此管理其关联的话术规则。</p></div>
      </section>
    </div>`;
  // 重新绑定事件
  $("#admin-filter").addEventListener("submit", event => {event.preventDefault(); state.adminPage=1; loadBindingsSceneList();});
  $("#admin-prev").addEventListener("click", () => {state.adminPage--; loadBindingsSceneList();});
  $("#admin-next").addEventListener("click", () => {state.adminPage++; loadBindingsSceneList();});
  // 渲染场景列表
  await loadBindingsSceneList();
}

async function loadBindingsSceneList() {
  const request = adminRequest;
  const headers = ["场景名称 / ID","状态"];
  $("#admin-head").innerHTML = `<tr>${headers.map(h => `<th>${h}</th>`).join("")}</tr>`;
  $("#admin-body").innerHTML = emptyRow(headers.length,"正在读取场景…","");
  try {
    const data = await api(`/api/admin/scenes?${new URLSearchParams({q:$("#admin-search").value.trim(),page:state.adminPage,size:30})}`);
    if (request !== adminRequest || state.view !== "bindings") return;
    state.adminRows = data.items;
    $("#admin-count").textContent = `${data.total} 条`;
    $("#admin-body").innerHTML = data.items.length ? data.items.map(row => {
      const selected = state.bindingsScene === row.id ? " selected-row" : "";
      return `<tr class="scene-row${selected}" data-bindings-scene="${esc(row.id)}"><td><strong>${esc(row.scene_name)}</strong><small class="cell-id">${esc(row.source_scene_id)}</small></td><td>${enabledBadge(row.enabled)}</td></tr>`;
    }).join("") : emptyRow(headers.length,"暂无场景","请先在「营销场景」中创建场景。");
    $("#admin-page-label").textContent = `第 ${state.adminPage} 页 · 共 ${data.total} 条`;
    $("#admin-prev").disabled = state.adminPage === 1; $("#admin-next").disabled = state.adminPage * 30 >= data.total;
  } catch(error) { if (request === adminRequest) $("#admin-body").innerHTML = errorRow(headers.length,error.message); }
}

async function loadSceneBindings(sceneId, sceneName) {
  const request = adminRequest;
  const panel = $("#bindings-detail");
  panel.innerHTML = `<div class="panel-heading"><div class="inline"><h2>${esc(sceneName)} · 关联规则</h2><button class="primary" data-add-binding="${esc(sceneId)}">＋ 添加规则</button></div></div><div class="table-wrap"><table><thead><tr><th>规则名称 / 编码</th><th>类型</th><th>严重程度 / 权重</th><th>状态</th><th>操作</th></tr></thead><tbody id="bindings-body"><tr><td colspan="5">${emptyRow(1,"正在加载…","").replace(/^<tr><td[^>]*>/,"").replace(/<\/td><\/tr>$/,"")}</td></tr></tbody></table></div>`;
  try {
    const data = await api(`/api/admin/scenes/${encodeURIComponent(sceneId)}/bindings`);
    if (request !== adminRequest || state.view !== "bindings") return;
    const items = data.items;
    state.bindingsScene = sceneId;
    state.bindingsSceneName = sceneName;
    state.bindingsRows = items;
    const body = $("#bindings-body");
    body.innerHTML = items.length ? items.map(row => `<tr>
      <td><strong>${esc(row.rule_name)}</strong><small class="cell-id">${esc(row.rule_code)}</small></td>
      <td>${esc(labels[row.rule_type] || row.rule_type)}</td>
      <td>${esc(labels[row.severity] || row.severity)}风险<small>权重 ${esc(row.weight_override ?? row.default_weight)}${row.weight_override == null ? "（默认）" : ""}</small></td>
      <td>${enabledBadge(row.enabled)}${row.rule_enabled === false ? '<small class="muted">规则已停用</small>' : ""}</td>
      <td><div class="inline"><button class="link-button" data-edit-binding="${esc(row.id)}">编辑</button><button class="link-button delete" data-delete-binding="${esc(row.id)}">删除</button></div></td>
    </tr>`).join("") : emptyRow(5,"该场景暂无关联规则","点击「添加规则」为该场景配置适用的评判规则。");
  } catch(error) { if (request === adminRequest) $("#bindings-body").innerHTML = errorRow(5,error.message); }
}
function inputField(name,label,value="",options={}) {
  const required = options.required ? "required" : "";
  return `<label class="${options.full ? "full" : ""}">${esc(label)}${options.area ? `<textarea name="${name}" maxlength="20000" ${required}>${esc(value)}</textarea>` : `<input name="${name}" value="${esc(value)}" type="${options.type || "text"}" ${required} ${options.type === "number" ? 'min="0" max="999.99" step="0.01"' : `maxlength="${options.max || 200}"`}>`}${options.hint ? `<span class="hint">${esc(options.hint)}</span>` : ""}</label>`;
}
function selectField(name,label,value,values) {
  return `<label>${esc(label)}<select name="${name}">${values.map(v => `<option value="${esc(v)}" ${v === value ? "selected" : ""}>${esc(labels[v])}</option>`).join("")}</select></label>`;
}
async function openEditor(id = null) {
  const resource = state.view;
  const row = id ? state.adminRows.find(r => String(r.id) === String(id)) : {};
  if (!row) return;
  state.editing = {resource,id};
  $("#editor-title").textContent = `${id ? "编辑" : "新增"}${titles[resource]}`;
  $("#editor-error").textContent = "";
  let fields;
  if (resource === "scenes") fields = inputField("source_scene_id","源场景 ID *",row.source_scene_id,{required:true,max:64,hint:"与通话表 act_scene_id 完全一致，保留完整数字。"}) + inputField("scene_name","场景名称 *",row.scene_name,{required:true}) + inputField("description","场景描述",row.description,{area:true,full:true});
  else if (resource === "rules") fields = inputField("rule_code","规则编码 *",row.rule_code,{required:true,max:128,hint:"稳定且唯一，例如 DISCLOSE_PRICE"}) + inputField("rule_name","规则名称 *",row.rule_name,{required:true}) + selectField("rule_type","规则类型",row.rule_type || "REQUIRED",["REQUIRED","FORBIDDEN","CONDITIONAL_REQUIRED"]) + selectField("severity","严重程度",row.severity || "MEDIUM",["LOW","MEDIUM","HIGH","CRITICAL"]) + inputField("weight","默认评分权重 *",row.weight ?? 10,{required:true,type:"number"}) + '<div></div>' + inputField("effective_from","开始生效时间（UTC+8）",datetimeInput(row.effective_from),{type:"datetime-local",hint:"留空表示不限开始时间"}) + inputField("effective_to","停止生效时间（UTC+8）",datetimeInput(row.effective_to),{type:"datetime-local",hint:"该时刻起不再适用；留空长期有效"}) + inputField("description","规则描述",row.description,{area:true,full:true}) + inputField("standard_expression","标准话术示例",row.standard_expression,{area:true,full:true}) + inputField("judge_instruction","LLM 评判指令",row.judge_instruction,{area:true,full:true,hint:"写明满足条件、禁止行为，以及何时应判断为不适用。"});
  else fields = `<label>营销场景 *<input data-option-search="scenes" placeholder="输入场景名称或 ID 搜索"><select name="scene_id" required aria-label="选择营销场景"><option value="">加载中…</option></select></label><label>话术规则 *<input data-option-search="rules" placeholder="输入规则名称或编码搜索"><select name="rule_id" required aria-label="选择话术规则"><option value="">加载中…</option></select></label>` + inputField("weight_override","覆盖评分权重",row.weight_override ?? "",{type:"number",full:true,hint:"留空沿用规则默认权重；0 是有效权重。"});
  $("#editor-fields").innerHTML = fields + `<label class="check full"><input type="checkbox" name="enabled" ${row.enabled !== false && row.enabled !== 0 ? "checked" : ""}> 启用此配置</label>`;
  $("#editor").showModal();
  if (resource === "bindings") {
    await Promise.all([loadOptions("scenes","",row.scene_id),loadOptions("rules","",row.rule_id)]);
  }
}
const optionRequests = {scenes:0,rules:0};
async function loadOptions(resource,q="",selected=null) {
  const select = $(`[name="${resource === "scenes" ? "scene_id" : "rule_id"}"]`,$("#editor-fields"));
  if (!select) return;
  const request = ++optionRequests[resource]; select.disabled = true;
  try {
    const data = await api(`/api/admin/${resource}?${new URLSearchParams({q,size:100})}`);
    if (selected && !data.items.some(r => String(r.id) === String(selected))) data.items.unshift(await api(`/api/admin/${resource}/${selected}`));
    if (request !== optionRequests[resource]) return;
    select.innerHTML = `<option value="">${data.total > 100 ? "请输入关键词缩小范围（最多显示100条）" : "请选择"}</option>` + data.items.map(row => `<option value="${esc(row.id)}" ${String(row.id) === String(selected) ? "selected" : ""}>${esc(resource === "scenes" ? `${row.scene_name} · ${row.source_scene_id}` : `${row.rule_name} · ${row.rule_code}`)}${row.enabled ? "" : "（已停用）"}</option>`).join("");
  } catch(error) { $("#editor-error").textContent = error.message; }
  finally { if (request === optionRequests[resource]) select.disabled = false; }
}

// ---- 场景规则关联编辑器（以场景为单位） ----
async function openBindingEditor(id = null, sceneId = null, sceneName = "") {
  const row = id ? (state.bindingsRows || []).find(r => String(r.id) === String(id)) : {};
  state.editing = {resource:"bindings", id};
  $("#editor-title").textContent = id ? `编辑关联规则` : `为场景「${sceneName}」添加规则`;
  $("#editor-error").textContent = "";
  let fields = `<label>营销场景<select name="scene_id" required aria-label="选择营销场景"><option value="${esc(sceneId)}" selected>${esc(sceneName)}</option></select></label>`;
  fields += `<label>话术规则 *<input data-option-search="rules" placeholder="输入规则名称或编码搜索"><select name="rule_id" required aria-label="选择话术规则"><option value="">加载中…</option></select></label>`;
  fields += inputField("weight_override","覆盖评分权重",row.weight_override ?? "",{type:"number",full:true,hint:"留空沿用规则默认权重；0 是有效权重。"});
  $("#editor-fields").innerHTML = fields + `<label class="check full"><input type="checkbox" name="enabled" ${row.enabled !== false && row.enabled !== 0 ? "checked" : ""}> 启用此关联</label>`;
  $("#editor").showModal();
  // 如果编辑已有关联，预加载已选规则；否则只加载规则列表
  await loadOptions("rules", "", row.rule_id);
}

async function openBindingDelete(id) {
  const row = (state.bindingsRows || []).find(r => String(r.id) === String(id));
  if (!row) return;
  state.deleting = {resource:"bindings", id};
  $("#delete-description").textContent = `${state.bindingsSceneName || "场景"} → ${row.rule_name}`;
  $("#delete-error").textContent = ""; $("#delete-dialog").showModal();
}
async function saveEditor(event) {
  event.preventDefault();
  const {resource,id} = state.editing, form = event.currentTarget, button = $("button[type=submit]",form);
  const values = Object.fromEntries(new FormData(form)); values.enabled = form.elements.enabled.checked;
  if (resource === "rules") {
    values.weight = Number(values.weight); values.effective_from ||= null; values.effective_to ||= null;
  } else if (resource === "bindings") {
    values.scene_id = Number(values.scene_id); values.rule_id = Number(values.rule_id);
    values.weight_override = values.weight_override === "" ? null : Number(values.weight_override);
  }
  button.disabled = true; $("#editor-error").textContent = "";
  try {
    await api(`/api/admin/${resource}${id ? `/${id}` : ""}`, {method:id ? "PUT" : "POST",body:JSON.stringify(values)});
    $("#editor").close(); toast("配置已保存，新执行的任务将读取当前有效规则");
    if (state.view === resource && resource !== "bindings") loadAdmin();
    else if (state.view === "bindings" && resource === "bindings" && state.bindingsScene) loadSceneBindings(state.bindingsScene, state.bindingsSceneName);
  } catch(error) { $("#editor-error").textContent = error.message; }
  finally { button.disabled = false; }
}
function openDelete(id) {
  const row = state.adminRows.find(r => String(r.id) === String(id));
  if (!row) return;
  state.deleting = {resource:state.view,id};
  $("#delete-description").textContent = state.view === "bindings" ? `${row.scene_name} → ${row.rule_name}` : row.rule_name || row.scene_name;
  $("#delete-error").textContent = ""; $("#delete-dialog").showModal();
}
async function deleteRecord() {
  const {resource,id} = state.deleting, button = $("#confirm-delete"); button.disabled = true;
  try { await api(`/api/admin/${resource}/${id}`,{method:"DELETE"}); $("#delete-dialog").close(); toast("配置已删除");
    if (state.view === "bindings" && resource === "bindings" && state.bindingsScene) loadSceneBindings(state.bindingsScene, state.bindingsSceneName);
    else loadAdmin();
  }
  catch(error) { $("#delete-error").textContent = error.message; }
  finally { button.disabled = false; }
}

document.addEventListener("click", event => {
  const button = event.target.closest("button"); if (!button) return;
  if (button.dataset.view) { if (location.hash === `#${button.dataset.view}`) navigate(button.dataset.view); else location.hash = button.dataset.view; }
  if (button.dataset.close) $(`#${button.dataset.close}`).close();
  if (button.dataset.detail) loadDetail(button.dataset.detail);
  if (button.dataset.edit) openEditor(button.dataset.edit);
  if (button.dataset.delete) openDelete(button.dataset.delete);
  if (button.dataset.rerun) rerunTask(button.dataset.rerun);
  if (button.dataset.addBinding) openBindingEditor(null, Number(button.dataset.addBinding), state.bindingsSceneName);
  if (button.dataset.editBinding) openBindingEditor(Number(button.dataset.editBinding), state.bindingsScene, state.bindingsSceneName);
  if (button.dataset.deleteBinding) openBindingDelete(Number(button.dataset.deleteBinding));
  if (button.id === "add-record") {
    if (state.view === "bindings") {
      if (state.bindingsScene) openBindingEditor(null, state.bindingsScene, state.bindingsSceneName);
      else toast("请先选择一个营销场景");
    } else openEditor();
  }
});
// 场景行点击选中
document.addEventListener("click", event => {
  const row = event.target.closest("tr[data-bindings-scene]"); if (!row) return;
  const sceneId = Number(row.dataset.bindingsScene);
  const sceneRow = state.adminRows.find(r => String(r.id) === String(sceneId));
  const sceneName = sceneRow ? sceneRow.scene_name : "未命名场景";
  $$(".scene-row").forEach(r => r.classList.remove("selected-row"));
  row.classList.add("selected-row");
  loadSceneBindings(sceneId, sceneName);
});
async function rerunTask(taskId) {
  const button = $(`[data-rerun="${taskId}"]`); if (button) { button.disabled = true; button.textContent = "正在提交…"; }
  try {
    await api(`/api/tasks/${encodeURIComponent(taskId)}/rerun`, {method:"POST"});
    $("#detail").close();
    location.hash = "tasks";
    toast("已提交重新评判，执行进度将在任务页自动更新");
  } catch(error) { toast(error.message,true); if (button) { button.disabled = false; button.textContent = "↻ 重新评判"; } }
}
document.addEventListener("change", event => {
  if (event.target.dataset.select) { const key = event.target.dataset.select; event.target.checked ? state.selected.add(key) : state.selected.delete(key); updateSelection(); }
});
const optionTimers = {};
document.addEventListener("input", event => {
  const resource = event.target.dataset.optionSearch;
  if (resource) { clearTimeout(optionTimers[resource]); optionTimers[resource] = setTimeout(() => loadOptions(resource,event.target.value.trim()),300); }
});
$("#select-all").addEventListener("change", event => {state.selected = new Set(event.target.checked ? state.calls.filter(selectable).map(c => c.key) : []); updateSelection();});
$("#call-filter").addEventListener("submit", event => {event.preventDefault(); loadCalls(1,true);});
$("#run-selected").addEventListener("click",runSelected);
$("#calls-prev").addEventListener("click",() => loadCalls(state.callPage-1));
$("#calls-next").addEventListener("click",() => loadCalls(state.callPage+1));
$("#connection").addEventListener("click",checkHealth);
$("#refresh-tasks").addEventListener("click",loadTasks);
$("#tasks-prev").addEventListener("click",() => {state.taskPage--;loadTasks();});
$("#tasks-next").addEventListener("click",() => {state.taskPage++;loadTasks();});
$("#task-status").addEventListener("change",() => {state.taskPage=1;loadTasks();});
$("#admin-filter").addEventListener("submit",event => {event.preventDefault();state.adminPage=1;loadAdmin();});
$("#admin-prev").addEventListener("click",() => {state.adminPage--;loadAdmin();});
$("#admin-next").addEventListener("click",() => {state.adminPage++;loadAdmin();});
$("#editor-form").addEventListener("submit",saveEditor);
$("#confirm-delete").addEventListener("click",deleteRecord);
$("#detail").addEventListener("close",() => {state.detailId=null;++detailRequest;});
window.addEventListener("hashchange",() => navigate(location.hash.slice(1)));
const today = new Date(), weekAgo = new Date(today); weekAgo.setDate(today.getDate()-7);
$("#call-filter [name=start]").value = localDate(weekAgo); $("#call-filter [name=end]").value = localDate(today);
navigate(location.hash.slice(1) || "calls"); checkHealth();
