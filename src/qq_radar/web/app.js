"use strict";
const $ = (id) => document.getElementById(id);
const state = { conversations: [], offset: 0, next: null, selected: null, listVersion: 0, detailVersion: 0, importVersion: 0, keyword: "" };
const labels = {"demo-account": "演示账号 A", "demo-second-account": "演示账号 B", "demo-tech": "技术交流 · 合成群", "demo-network": "网络讨论 · 合成群"};
const errorLabels = {IDENTITY_CONFLICT: "同一消息身份的内容冲突，原文保留", INVALID_JSON: "JSON 格式无效", INVALID_FIELD: "字段缺失或格式错误", INVALID_TIMESTAMP: "时间无效", UNSUPPORTED_SCHEMA: "输入版本不支持", DEPTH_LIMIT: "转发层级超限", LINE_LIMIT: "单行大小超限", SEGMENT_LIMIT: "消息段数量超限"};
function el(tag, text, className) { const node = document.createElement(tag); if (text !== undefined) node.textContent = text; if (className) node.className = className; return node; }
function display(value) { return labels[value] || value; }
function time(value, full = false) { if (!value) return "时间未提供"; const date = new Date(value); if (Number.isNaN(date.getTime())) return "时间未知"; return new Intl.DateTimeFormat("zh-CN", {timeZone: "Asia/Shanghai", ...(full ? {month: "2-digit", day: "2-digit"} : {}), hour: "2-digit", minute: "2-digit", hour12: false}).format(date); }
async function api(path) { const response = await fetch(path, {signal: AbortSignal.timeout(10000)}); const value = await response.json(); if (!response.ok) throw new Error(value.code || "REQUEST_FAILED"); return value; }
function showError(error) { $("global-error").textContent = "暂时无法读取内容，请重试或检查本机服务。错误：" + error.message; $("global-error").hidden = false; }
function clearError() { $("global-error").hidden = true; }
function blank(target, title, description) { const box = el("div", undefined, "empty-state"); box.append(el("h3", title), el("p", description)); target.replaceChildren(box); }
function scope() { return {account: $("account").value, group: $("group").value}; }
function setGroups() { const account = $("account").value; $("group").replaceChildren(...state.conversations.filter(c => c.account_id === account).sort((a, b) => b.message_count - a.message_count).map(c => { const option = el("option", display(c.group_id)); option.value = c.group_id; return option; })); }
function messageTop(row) { const top = el("div", undefined, "message-top"); const author = el("span", undefined, "message-author"); author.append(el("span", "合", "avatar"), el("span", row.sender_name || row.sender_id)); top.append(author, el("time", time(row.original_timestamp))); return top; }
function preview(row) { return row.text || "图片或未知格式消息 · 打开查看处理状态"; }
async function loadMessages() {
  const version = ++state.listVersion; ++state.detailVersion; clearError(); state.selected = null;
  $("previous").disabled = true; $("next").disabled = true;
  blank($("message-list"), "正在读取…", "加载当前群的消息。");
  blank($("detail"), "从一条消息开始", "选择左侧消息，查看原文、转发层级和前后讨论。");
  const current = scope(); const conversation = state.conversations.find(c => c.account_id === current.account && c.group_id === current.group);
  $("message-count").textContent = `群内共 ${conversation?.message_count || 0} 条`;
  $("page-number").textContent = `第 ${Math.floor(state.offset / 20) + 1} 页`;
  if (!current.account || !current.group) { blank($("message-list"), "还没有导入消息", "运行合成演示命令，或先用离线工具导入合成样本。"); return; }
  try {
    const params = new URLSearchParams({...current, keyword: state.keyword, offset: state.offset, limit: 20});
    const data = await api("/api/v1/messages?" + params);
    if (version !== state.listVersion) return;
    $("message-count").textContent = `群内 ${conversation?.message_count || 0} 条 · 本页 ${data.items.length} 条`;
    state.next = data.next_offset;
    $("previous").disabled = state.offset === 0; $("next").disabled = state.next === null;
    if (!data.items.length) { blank($("message-list"), "没有匹配的原文", "试试其他关键词或切换群。图片尚未提供可搜索的文字。"); return; }
    $("message-list").replaceChildren(...data.items.map(row => {
      const button = el("button", undefined, "message-card"); button.type = "button"; button.dataset.messageId = row.id;
      button.setAttribute("aria-pressed", "false"); button.append(messageTop(row), el("div", preview(row), "preview"), el("span", display(row.group_id) + " · " + row.external_id, "source-chip"));
      button.addEventListener("click", () => loadDetail(row.id)); return button;
    }));
  } catch (error) { if (version === state.listVersion) { blank($("message-list"), "读取失败", "请再次搜索，或检查本机服务。"); showError(error); } }
}
function segments(items, target) {
  for (const segment of items || []) {
    if (segment.type === "text") { target.append(el("p", segment.text, "text-segment")); }
    else if (segment.type === "forward") {
      const container = el("details", undefined, "forward"); container.open = true;
      container.append(el("summary", `合并转发 · ${segment.nodes.length} 个节点`)); const body = el("div", undefined, "forward-body");
      for (const node of segment.nodes) { const block = el("div", undefined, "forward-node"); block.append(el("div", (node.sender_name || node.sender_id || "来源身份未提供") + (node.timestamp ? " · " + time(node.timestamp, true) : ""), "node-author")); segments(node.segments, block); body.append(block); }
      container.append(body); target.append(container);
    } else if (segment.type === "image") {
      const box = el("div", undefined, "state-box"); box.append(el("strong", "图片 · 尚未获取"), el("span", "当前只保留资源引用，不加载图片或进行 OCR。")); target.append(box);
    } else if (segment.type === "link") { const link = el("div", segment.url, "reference"); link.append(el("small", "原文中的链接 · 未抓取网页")); target.append(link); }
    else { const box = el("div", undefined, "state-box unknown"); box.append(el("strong", "未知格式 · 内容已保留"), el("span", "类型：" + segment.type + "。可在原始结构中查看，尚未解析。")); target.append(box); }
  }
}
function metadata(row) { const node = el("dl", undefined, "source-meta"); for (const [label, value] of [["账号", display(row.account_id)], ["群", display(row.group_id)], ["发送者", row.sender_name ? row.sender_name + " / " + row.sender_id : row.sender_id], ["时间", row.original_timestamp + " · 显示按北京时间"], ["消息 ID", row.external_id]]) node.append(el("dt", label), el("dd", value)); return node; }
function contextRow(row) { const box = el("div", undefined, "context-message"); box.append(messageTop(row), el("p", preview(row))); const button = el("button", "查看这条原文", "secondary"); button.type = "button"; button.addEventListener("click", () => loadDetail(row.id)); box.append(button); return box; }
async function loadDetail(id) {
  const version = ++state.detailVersion; state.selected = id; clearError();
  document.querySelectorAll(".message-card").forEach(button => { const selected = button.dataset.messageId === id; button.classList.toggle("selected", selected); button.setAttribute("aria-pressed", String(selected)); });
  blank($("detail"), "正在读取来源…", "查找原文和同群前后文。");
  try {
    const data = await api("/api/v1/messages/" + encodeURIComponent(id) + "/context?radius=2");
    if (version !== state.detailVersion) return;
    const row = data.message; const body = el("div", undefined, "detail-content"); const heading = el("div", undefined, "source-header"); heading.append(el("h3", "原始消息"), el("time", time(row.original_timestamp, true))); body.append(heading, metadata(row)); segments(row.source.segments, body);
    const ctx = el("div", undefined, "context-title"); ctx.append(el("h3", "前后讨论"), el("span", "同账号 · 同群 · 前后各 2 条")); body.append(ctx);
    if (data.before.length) body.append(el("p", "这条消息之前", "context-gap"), ...data.before.map(contextRow)); else body.append(el("p", "当前已导入范围内没有更早的消息。", "context-gap"));
    body.append(el("p", "↑ 当前消息 ↑", "context-gap"));
    if (data.after.length) body.append(el("p", "这条消息之后", "context-gap"), ...data.after.map(contextRow)); else body.append(el("p", "当前已导入范围内没有更晚的消息。", "context-gap"));
    const original = el("details", undefined, "original-json"); original.append(el("summary", "查看原始结构"), el("pre", JSON.stringify(row.source, null, 2))); body.append(original); $("detail").replaceChildren(body);
    if (window.matchMedia("(max-width: 820px)").matches) document.querySelector(".detail-panel").scrollIntoView({behavior: "smooth", block: "start"});
  } catch (error) { if (version === state.detailVersion) { blank($("detail"), "来源暂时不可用", "请重试；没有读取到的内容不会被补写。 "); showError(error); } }
}
const batchStatuses = {completed: "处理完成", completed_with_errors: "处理完成 · 有错误", running: "未正常结束或仍在处理", interrupted: "处理已中断"};
async function showImports() {
  const version = ++state.importVersion;
  clearError(); blank($("import-list"), "正在读取…", "加载最近的导入记录。");
  try {
    const batches = await api("/api/v1/imports");
    if (version !== state.importVersion) return;
    if (!batches.length) { blank($("import-list"), "暂无导入记录", "先运行合成数据导入。"); return; }
    const cards = batches.map(batch => { const card = el("article", undefined, "import-card"); card.append(el("h3", batchStatuses[batch.status] || batch.status), el("div", `批次 ${batch.id} · ${time(batch.started_at, true)}`, "batch-id")); const button = el("button", "查看计数与错误", "secondary"); button.type = "button"; button.addEventListener("click", async () => {
      button.disabled = true;
      try { const result = await api("/api/v1/imports/" + encodeURIComponent(batch.id)); if (version !== state.importVersion) return; const grid = el("div", undefined, "count-grid"); for (const [key, name] of [["seen", "已处理"], ["inserted", "新增"], ["matched", "匹配"], ["failed", "失败"], ["excluded", "排除"]]) { const item = el("div"); item.append(el("strong", result.counts[key]), el("span", name)); grid.append(item); } card.append(grid, el("p", `已提交到第 ${result.committed_line} 行；已处理 = 新增 + 匹配 + 失败 + 排除。`, "batch-id"));
        if (result.errors.length) { const table = el("table"); const head = el("thead"); const header = el("tr"); for (const name of ["行号", "原因", "字段"]) header.append(el("th", name)); head.append(header); const rows = el("tbody"); for (const error of result.errors) { const tr = el("tr"); tr.append(el("td", error.line), el("td", errorLabels[error.error_code] || error.error_code, "batch-error"), el("td", error.field)); rows.append(tr); } table.append(head, rows); card.append(table); } else card.append(el("p", "此批次没有行错误。", "batch-id")); button.remove();
      } catch (error) { button.disabled = false; if (version === state.importVersion) showError(error); }
    }); card.append(button); return card; }); $("import-list").replaceChildren(...cards);
  } catch (error) { if (version === state.importVersion) { blank($("import-list"), "读取失败", "重新点击导入记录可重试。"); showError(error); } }
}
function setView(imports) { ++state.importVersion; $("reading-view").hidden = imports; $("imports-view").hidden = !imports; $("page-title").textContent = imports ? "导入记录" : "原文阅读"; $("page-description").textContent = imports ? "看清已处理的内容，也看清失败的原因。" : "保留消息的来处，也保留讨论的脉络。"; for (const [id, active] of [["reading-tab", !imports], ["imports-tab", imports]]) { $(id).classList.toggle("active", active); if (active) $(id).setAttribute("aria-current", "page"); else $(id).removeAttribute("aria-current"); } if (imports) showImports(); else clearError(); }
$("reading-tab").addEventListener("click", () => setView(false)); $("imports-tab").addEventListener("click", () => setView(true));
$("account").addEventListener("change", () => { setGroups(); state.offset = 0; loadMessages(); }); $("group").addEventListener("change", () => { state.offset = 0; loadMessages(); });
$("filters").addEventListener("submit", event => { event.preventDefault(); state.offset = 0; state.keyword = $("keyword").value; loadMessages(); });
$("previous").addEventListener("click", () => { state.offset = Math.max(0, state.offset - 20); loadMessages(); }); $("next").addEventListener("click", () => { if (state.next !== null) { state.offset = state.next; loadMessages(); } });
async function initialize() { try { state.conversations = await api("/api/v1/conversations"); const accounts = [...new Set(state.conversations.map(c => c.account_id))]; $("account").replaceChildren(...accounts.map(value => { const option = el("option", display(value)); option.value = value; return option; })); setGroups(); loadMessages(); } catch (error) { showError(error); blank($("message-list"), "无法连接本机服务", "启动服务后刷新页面。"); } }
initialize();
