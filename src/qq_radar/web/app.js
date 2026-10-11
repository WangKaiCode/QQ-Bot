"use strict";
const $ = (id) => document.getElementById(id);
const state = { conversations: [], topics: [], view: "reading", feedVersion: 0, jobsVersion: 0, feedOffset: 0, feedNext: null, digestVersion: 0, payloadVersion: 0, retentionVersion: 0, retentionOffset: 0, retentionNext: null, retentionAsOf: null, offset: 0, next: null, selected: null, listVersion: 0, detailVersion: 0, importVersion: 0, keyword: "" };
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
  } catch (error) { if (version === state.listVersion && state.view === "reading") { blank($("message-list"), "读取失败", "请再次搜索，或检查本机服务。"); showError(error); } }
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
  } catch (error) { if (version === state.detailVersion && state.view === "reading") { blank($("detail"), "来源暂时不可用", "请重试；没有读取到的内容不会被补写。 "); showError(error); } }
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
  const version = ++state.digestVersion; ++state.payloadVersion; $("payload-result").replaceChildren();
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
const sourceStates = {available: "来源有效", expired: "来源已到期，摘录不再显示", missing: "来源暂时不可用", changed: "来源已变化，摘录不再显示"};
async function loadFeed() {
  const version = ++state.feedVersion; ++state.jobsVersion; $("jobs-list").replaceChildren();
  clearError(); $("feed-previous").disabled = true; $("feed-next").disabled = true;
  blank($("feed-list"), "正在读取信息流…", "读取当前群最新成功的本地 Mock 作业。");
  const current = scope();
  if (!current.account || !current.group) { blank($("feed-list"), "暂无摘要范围", "先导入合成演示。"); return; }
  try {
    const result = await api("/api/v1/feed?" + new URLSearchParams({...current, offset: state.feedOffset, limit: 20}));
    if (version !== state.feedVersion || state.view !== "feed") return;
    state.feedNext = result.next_offset;
    $("feed-previous").disabled = state.feedOffset === 0; $("feed-next").disabled = result.next_offset === null;
    $("feed-page").textContent = `第 ${Math.floor(state.feedOffset / 20) + 1} 页`;
    if (!result.items.length) { blank($("feed-list"), "暂无已生成的摘要", "运行 demo 可生成一次合成作业；已有库可通过 CLI 入队并执行。此页面不会自动生成。"); return; }
    $("feed-list").replaceChildren(...result.items.map(digest => {
      const card = el("article", undefined, "digest-card");
      card.append(el("h2", digest.topic.name), el("p", `${digest.window_start} 至 ${digest.window_end} · Mock 文字摘录`, "batch-id"));
      card.append(el("p", `卡片到期 ${digest.expires_at} · ${digest.state === "expired" ? "卡片已到期" : "引用已保存"}`, "boundary-note"));
      if (digest.input_changed) card.append(el("p", digest.points.some(point => point.source_state === "available") ? "输入已变化：等待重新生成。" : "来源已变化或到期，当前只保留证据引用。", "coverage"));
      if (digest.update_pending) card.append(el("p", "新版本尚未成功，当前保留上一成功版本。", "coverage"));
      for (const point of digest.points) {
        const evidence = digest.evidence.find(item => item.evidence_id === point.evidence_id);
        const block = el("div", undefined, "digest-point");
        if (point.source_state === "available" && point.excerpt) {
          block.append(el("p", point.excerpt, "text-segment"));
          const button = el("button", "查看摘要来源", "secondary"); button.type = "button";
          button.addEventListener("click", () => { setView("reading"); loadDetail(evidence.message_id); }); block.append(button);
        } else block.append(el("p", sourceStates[point.source_state] || "来源状态未知", "boundary-note"));
        card.append(block);
      }
      const sources = el("details", undefined, "original-json"); sources.append(el("summary", `核对 ${digest.evidence.length} 个来源状态`));
      for (const item of digest.evidence) sources.append(el("p", `${item.path} · ${sourceStates[item.source_state] || "未知"}`, "batch-id"));
      card.append(sources); return card;
    }));
  } catch (error) { if (version === state.feedVersion && state.view === "feed") { blank($("feed-list"), "信息流读取失败", "检查本机作业库或重试。"); showError(error); } }
}
async function showJobs() {
  const version = ++state.jobsVersion;
  blank($("jobs-list"), "正在读取作业…", "只查看，不触发生成。");
  try {
    const rows = await api("/api/v1/jobs?" + new URLSearchParams({...scope(), limit: 50}));
    if (version !== state.jobsVersion || state.view !== "feed") return;
    if (!rows.length) { blank($("jobs-list"), "暂无作业", "先通过命令行生成合成窗口。"); return; }
    const statuses = {pending: "等待执行", running: "正在执行或租约未结束", succeeded: "成功", failed: "失败，可重试", failed_terminal: "重试次数用尽", superseded: "输入版本已替代", expired: "有效输入或卡片已到期"};
    $("jobs-list").replaceChildren(...rows.map(row => el("p", `${row.kind === "daily" ? "每日" : "小时"}窗口 ${time(new Date(row.window_start).toISOString(), true)} · ${statuses[row.status] || row.status} · 尝试 ${row.attempts} 次${row.error_code ? " · " + row.error_code : ""}`, "batch-id")));
  } catch (error) { if (version === state.jobsVersion && state.view === "feed") { blank($("jobs-list"), "作业读取失败", "请重试。"); showError(error); } }
}
$("jobs-refresh").addEventListener("click", showJobs);
$("feed-previous").addEventListener("click", () => { state.feedOffset = Math.max(0, state.feedOffset - 20); loadFeed(); });
$("feed-next").addEventListener("click", () => { if (state.feedNext !== null) { state.feedOffset = state.feedNext; loadFeed(); } });
async function inspectPayload() {
  const version = ++state.payloadVersion;
  clearError(); blank($("payload-result"), "正在本地检查…", "不发起外部请求。");
  try {
    const params = new URLSearchParams({...scope(), topic: $("topic").value, keywords: $("digest-keywords").value});
    const result = await api("/api/v1/outbound/preview?" + params);
    if (version !== state.payloadVersion || state.view !== "digest") return;
    const report = result.report;
    const box = el("div");
    box.append(el("p", `已检查 ${report.selected_evidence} 个命中段 · 候选 ${report.candidate_evidence} 段 · ${report.empty_after_redaction} 段屏蔽后无可读文字`, "boundary-note"));
    if (report.blocked) {
      const reasons = {AMBIGUOUS_SHORT_IDENTITY: "短身份字符串与普通词难以区分", RESIDUAL_KNOWN_IDENTITY: "仍检测到已知身份字符串", SENSITIVE_KEYWORD: "关注词本身包含敏感身份或联系方式", OUTBOUND_EVIDENCE_LIMIT: "命中段数量超限", OUTBOUND_TEXT_LIMIT: "文字量超限", NO_REVIEWABLE_EVIDENCE: "没有可供复核的文字"};
      box.append(el("p", "本次已阻断候选载荷：" + (reasons[report.blocked_reason] || "检查未通过") + "。计数可能只覆盖阻断前已检查的部分。", "batch-error"));
    } else {
      box.append(el("p", "已知信息屏蔽完成 · 未发送 · 仍需人工复核", "coverage"));
      for (const item of result.payload.evidence) box.append(el("p", item.sanitized_text, "text-segment"));
    }
    $("payload-result").replaceChildren(box);
  } catch (error) { if (version === state.payloadVersion && state.view === "digest") { blank($("payload-result"), "载荷检查失败", "不会发送任何内容；检查当前关键词或重试。"); showError(error); } }
}
$("payload-preview").addEventListener("click", inspectPayload);
async function loadRetention() {
  const version = ++state.retentionVersion;
  clearError(); $("retention-coverage").textContent = "";
  $("retention-previous").disabled = true; $("retention-next").disabled = true;
  blank($("retention-list"), "正在检查保留范围…", "只核对计数和到期元数据，不读取正文。");
  const current = scope();
  if (!current.account || !current.group) { blank($("retention-list"), "暂无可检查的消息", "先导入合成数据。"); return; }
  try {
    const params = new URLSearchParams({...current, offset: state.retentionOffset, limit: 20});
    if (state.retentionAsOf) params.set("as_of", state.retentionAsOf);
    const result = await api("/api/v1/retention/preview?" + params);
    if (version !== state.retentionVersion || state.view !== "retention") return;
    state.retentionAsOf = result.as_of; state.retentionNext = result.next_offset;
    const c = result.counts;
    $("retention-coverage").textContent = `检查于 ${result.as_of} · 共 ${c.total_messages} 条 · 到期待清理 ${c.due_messages} 条 · 已不可用 ${c.already_unavailable_messages} 条 · 关联 ${c.due_segments} 段 / ${c.due_observations} 次导入观测（含 ${c.due_raw_observations} 份原始观测）`;
    $("retention-page").textContent = `第 ${Math.floor(state.retentionOffset / 20) + 1} 页 · 只读`;
    $("retention-previous").disabled = state.retentionOffset === 0;
    $("retention-next").disabled = result.next_offset === null;
    if (!result.items.length) { blank($("retention-list"), "当前范围无到期待清理消息", "这不表示清理已经执行；可以指定将来的检查时间预览。"); return; }
    $("retention-list").replaceChildren(...result.items.map(item => {
      const card = el("article", undefined, "digest-card");
      card.append(el("h2", item.external_id), el("p", `到期时间 ${item.expires_at}`, "batch-id"), el("p", `${item.segment_count} 个结构段 · ${item.observation_count} 次观测 · 正文尚在库内，未执行清理`, "boundary-note"));
      const button = el("button", "回看这条合成原文", "secondary"); button.type = "button";
      button.addEventListener("click", () => { setView("reading"); loadDetail(item.id); }); card.append(button); return card;
    }));
  } catch (error) { if (version === state.retentionVersion && state.view === "retention") { blank($("retention-list"), "保留范围检查失败", "检查时间需含时区；失败时不会执行任何清理。"); showError(error); } }
}
function setView(view) {
  ++state.importVersion; ++state.digestVersion; ++state.retentionVersion; ++state.payloadVersion; ++state.feedVersion; ++state.jobsVersion; state.view = view;
  for (const name of ["reading", "imports", "digest", "retention", "feed"]) {
    $(name + "-view").hidden = name !== view;
    const button = $(name + "-tab"); button.classList.toggle("active", name === view);
    if (name === view) button.setAttribute("aria-current", "page"); else button.removeAttribute("aria-current");
  }
  $("filters").hidden = view === "imports";
  document.querySelector("#filters .search-label").hidden = view !== "reading";
  $("page-title").textContent = {reading: "原文阅读", imports: "导入记录", digest: "摘要预览", retention: "保留预览", feed: "信息流"}[view];
  $("page-description").textContent = {reading: "保留消息的来处，也保留讨论的脉络。", imports: "看清已处理的内容，也看清失败的原因。", digest: "先聚合命中的讨论，再回到每一条来源。", retention: "看清保存期限和到期范围，再决定清理流程。", feed: "按窗口阅读，追踪变化，随时核对来源。"}[view];
  document.title = "QQ 信息雷达 · " + $("page-title").textContent;
  clearError(); if (view === "imports") showImports(); else if (view === "digest") loadDigests(); else if (view === "retention") loadRetention(); else if (view === "feed") loadFeed();
}
for (const name of ["reading", "imports", "digest", "retention", "feed"]) $(name + "-tab").addEventListener("click", () => setView(name));
function scopeChanged() { state.offset = 0; loadMessages(); if (state.view === "digest") loadDigests(); if (state.view === "retention") { state.retentionOffset = 0; loadRetention(); } if (state.view === "feed") { state.feedOffset = 0; loadFeed(); } }
$("account").addEventListener("change", () => { setGroups(); scopeChanged(); }); $("group").addEventListener("change", scopeChanged);
$("digest-keywords").addEventListener("input", () => { ++state.payloadVersion; ++state.digestVersion; $("payload-result").replaceChildren(); $("digest-coverage").textContent = ""; blank($("digest-list"), "关注词已修改", "点击生成预览应用新关键词。"); });
$("digest-kind").addEventListener("change", () => { ++state.digestVersion; $("digest-coverage").textContent = ""; blank($("digest-list"), "归组方式已修改", "点击生成预览应用新窗口。"); });
$("topic").addEventListener("change", () => { selectTopic(); loadDigests(); });
$("digest-settings").addEventListener("submit", event => { event.preventDefault(); loadDigests(); });
$("filters").addEventListener("submit", event => { event.preventDefault(); state.offset = 0; state.keyword = $("keyword").value; loadMessages(); });
$("previous").addEventListener("click", () => { state.offset = Math.max(0, state.offset - 20); loadMessages(); }); $("next").addEventListener("click", () => { if (state.next !== null) { state.offset = state.next; loadMessages(); } });
$("retention-settings").addEventListener("submit", event => { event.preventDefault(); state.retentionOffset = 0; state.retentionAsOf = $("retention-as-of").value.trim() || null; loadRetention(); });
$("retention-previous").addEventListener("click", () => { state.retentionOffset = Math.max(0, state.retentionOffset - 20); loadRetention(); });
$("retention-next").addEventListener("click", () => { if (state.retentionNext !== null) { state.retentionOffset = state.retentionNext; loadRetention(); } });
async function initialize() { try { [state.conversations, state.topics] = await Promise.all([api("/api/v1/conversations"), api("/api/v1/topics")]); const accounts = [...new Set(state.conversations.map(c => c.account_id))]; $("account").replaceChildren(...accounts.map(value => { const option = el("option", display(value)); option.value = value; return option; })); $("topic").replaceChildren(...state.topics.map(topic => { const option = el("option", topic.name); option.value = topic.id; return option; })); selectTopic(); setGroups(); loadMessages(); } catch (error) { showError(error); blank($("message-list"), "无法连接本机服务", "启动服务后刷新页面。"); } }
initialize();
