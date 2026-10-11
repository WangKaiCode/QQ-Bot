"use strict";
const $ = (id) => document.getElementById(id);
const state = { conversations: [], topics: [], view: "reading", digestVersion: 0, offset: 0, next: null, selected: null, listVersion: 0, detailVersion: 0, importVersion: 0, keyword: "" };
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
function selectTopic() {
  const topic = state.topics.find(item => item.id === $("topic").value);
  $("digest-keywords").value = topic ? topic.keywords.join(",") : "";
}
async function loadDigests() {
  const version = ++state.digestVersion;
  clearError(); $("digest-coverage").textContent = "";
  blank($("digest-list"), "正在生成本地预览…", "按当前关键词核对文本与来源。");
  const current = scope();
  if (!current.account || !current.group) { blank($("digest-list"), "暂无可分析的原文", "先导入合成消息。"); return; }
  try {
    const query = new URLSearchParams({...current, topic: $("topic").value, kind: $("digest-kind").value, keywords: $("digest-keywords").value});
    const result = await api("/api/v1/analysis/preview?" + query);
    if (version !== state.digestVersion || state.view !== "digest") return;
    const coverage = result.coverage;
    $("digest-coverage").textContent = `已导入 ${coverage.messages} 条 · 命中 ${coverage.matched_messages} 条 · 图片 ${coverage.image_segments} 段未处理 · 未知格式 ${coverage.unsupported_segments} 段 · 无文字 ${coverage.empty_text_messages} 条`;
    if (!result.digests.length) { blank($("digest-list"), "没有命中的文字讨论", "可以修改关键词；图片和未知格式仍可在原文阅读里查看，这不代表没有相关信息。"); return; }
    $("digest-list").replaceChildren(...result.digests.map(digest => {
      const card = el("article", undefined, "digest-card");
      const heading = el("div", undefined, "source-header");
      heading.append(el("h2", digest.topic.name), el("span", "Mock · 文字摘录", "small-tag"));
      card.append(heading, el("p", `${digest.window_start} 至 ${digest.window_end}（不含结束时间）`, "batch-id"));
      card.append(el("p", `关注关键词：${digest.topic.keywords.join("、")} · ${digest.evidence.length} 个文本来源，最多展示 3 条摘录`, "boundary-note"));
      for (const point of digest.points) {
        const evidence = digest.evidence.find(item => item.evidence_id === point.evidence_id);
        const block = el("div", undefined, "digest-point");
        block.append(el("p", point.excerpt, "text-segment"), el("span", "命中：" + evidence.terms.join("、"), "source-chip"));
        const button = el("button", "查看原文", "secondary"); button.type = "button";
        button.addEventListener("click", () => { setView("reading"); loadDetail(evidence.message_id); });
        block.append(button); card.append(block);
      }
      const sources = el("details", undefined, "original-json"); sources.append(el("summary", `查看全部 ${digest.evidence.length} 个来源与转发路径`));
      for (const [index, evidence] of digest.evidence.entries()) {
        const row = el("div", undefined, "evidence-row");
        const button = el("button", `来源 ${index + 1} · 查看原文`, "secondary"); button.type = "button";
        button.addEventListener("click", () => { setView("reading"); loadDetail(evidence.message_id); });
        row.append(button, el("span", evidence.path + " · " + evidence.terms.join("、"), "batch-id")); sources.append(row);
      }
      card.append(sources); return card;
    }));
  } catch (error) { if (version === state.digestVersion && state.view === "digest") { blank($("digest-list"), "预览未生成", "检查关键词（1–20 个，每个最多 40 字符）或重试。失败时不会展示未经核对的摘录。"); showError(error); } }
}
function setView(view) {
  ++state.importVersion; ++state.digestVersion; state.view = view;
  for (const name of ["reading", "imports", "digest"]) {
    $(name + "-view").hidden = name !== view;
    const button = $(name + "-tab"); button.classList.toggle("active", name === view);
    if (name === view) button.setAttribute("aria-current", "page"); else button.removeAttribute("aria-current");
  }
  $("filters").hidden = view === "imports";
  document.querySelector("#filters .search-label").hidden = view !== "reading";
  $("page-title").textContent = {reading: "原文阅读", imports: "导入记录", digest: "摘要预览"}[view];
  $("page-description").textContent = {reading: "保留消息的来处，也保留讨论的脉络。", imports: "看清已处理的内容，也看清失败的原因。", digest: "先聚合命中的讨论，再回到每一条来源。"}[view];
  clearError(); if (view === "imports") showImports(); else if (view === "digest") loadDigests();
}
for (const name of ["reading", "imports", "digest"]) $(name + "-tab").addEventListener("click", () => setView(name));
function scopeChanged() { state.offset = 0; loadMessages(); if (state.view === "digest") loadDigests(); }
$("account").addEventListener("change", () => { setGroups(); scopeChanged(); }); $("group").addEventListener("change", scopeChanged);
$("topic").addEventListener("change", () => { selectTopic(); loadDigests(); });
$("digest-settings").addEventListener("submit", event => { event.preventDefault(); loadDigests(); });
$("filters").addEventListener("submit", event => { event.preventDefault(); state.offset = 0; state.keyword = $("keyword").value; loadMessages(); });
$("previous").addEventListener("click", () => { state.offset = Math.max(0, state.offset - 20); loadMessages(); }); $("next").addEventListener("click", () => { if (state.next !== null) { state.offset = state.next; loadMessages(); } });
async function initialize() { try { [state.conversations, state.topics] = await Promise.all([api("/api/v1/conversations"), api("/api/v1/topics")]); const accounts = [...new Set(state.conversations.map(c => c.account_id))]; $("account").replaceChildren(...accounts.map(value => { const option = el("option", display(value)); option.value = value; return option; })); $("topic").replaceChildren(...state.topics.map(topic => { const option = el("option", topic.name); option.value = topic.id; return option; })); selectTopic(); setGroups(); loadMessages(); } catch (error) { showError(error); blank($("message-list"), "无法连接本机服务", "启动服务后刷新页面。"); } }
initialize();
