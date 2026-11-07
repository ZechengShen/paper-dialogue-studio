const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];

const state = { jobId: null, pollTimer: null, result: null, codexPrompt: "", reconnecting: false, files: [], view: "new" };
const phaseNames = {
  waiting_codex: "等待 Codex", claimed: "Codex 已领取", queued: "准备任务",
  extract: "读取原文", research: "公开版本检索",
  analysis: "论文精读", script: "教学编剧", voice: "自然人声",
  mix: "音频拼接", report: "报告与推进", review: "验收交付", complete: "制作完成", error: "任务出错"
};
const stages = [["intake", "收件读取"], ["evidence", "全文证据"], ["analysis", "精读综合"], ["report", "研究报告"], ["teaching", "教学设计"], ["media", "音频动画"], ["review", "验收交付"]];

function showToast(message) {
  const toast = $("#toast");
  toast.textContent = message;
  toast.classList.remove("hidden");
  window.setTimeout(() => toast.classList.add("hidden"), 6500);
}

function fieldError(selector, message) {
  const input = $(selector);
  let note = document.getElementById(input.id + '-error');
  if (!note) {
    note = el('p', 'inline-error'); note.id = input.id + '-error'; note.setAttribute('role', 'alert');
    (input.type === 'checkbox' ? input.closest('label') : input).insertAdjacentElement('afterend', note);
    input.setAttribute('aria-describedby', [input.getAttribute('aria-describedby'), note.id].filter(Boolean).join(' '));
  }
  note.textContent = message; note.classList.remove('hidden');
  input.setAttribute('aria-invalid', 'true'); input.focus();
  input.scrollIntoView({block:'center',behavior:'instant'});
}

function updateSelectionSummary() {
  const type = $('#source-type').value;
  const count = state.files.length;
  const links = $('#additional-urls').value.split('\n').filter(line => line.trim()).length;
  const main = type === 'file' ? (count ? `${count} 个文件 · ${(state.files.reduce((n,f)=>n+f.size,0)/1024/1024).toFixed(1)} MB` : '请先添加文件') :
    $({url:'#url-input',notion:'#notion-input',html:'#html-input'}[type]).value.trim() ? {url:'文章网址已填写',notion:'Notion 链接已填写',html:'HTML 内容已填写'}[type] : '请先填写材料';
  const summary = main + (links ? ` · ${links} 个补充链接` : '');
  if ($('#selection-summary').textContent !== summary) $('#selection-summary').textContent = summary;
}

function initEfficiency() {
  $('#paper-form').addEventListener('input', event => {
    if (event.target.getAttribute('aria-invalid') === 'true') {
      event.target.removeAttribute('aria-invalid');
      document.getElementById(event.target.id + '-error')?.classList.add('hidden');
    }
    updateSelectionSummary();
  });
  $$('[data-jump]').forEach(button => button.addEventListener('click', () => {
    const heading = $(button.dataset.jump); heading.tabIndex=-1;
    heading.scrollIntoView({block:'start',behavior:'instant'}); heading.focus({preventScroll:true});
  }));
  $('#history-search').addEventListener('input', renderRecent);
  $('#history-filter').addEventListener('change', renderRecent);
  $('#history-reset').addEventListener('click', () => {$('#history-search').value='';$('#history-filter').value='all';renderRecent();$('#history-search').focus();});
  updateSelectionSummary();
}

function setView(view, { navigate = false, focus = false } = {}) {
  if (view === "task" && !state.jobId) view = "new";
  state.view = view;
  [["new", "#create-view"], ["recent", "#recent"], ["task", "#task-view"]].forEach(([name, selector]) => {
    $(selector).classList.toggle("hidden", name !== view);
  });
  $("#current-task-link").classList.toggle("hidden", !state.jobId);
  if (state.jobId) $("#current-task-link").href = `?job=${encodeURIComponent(state.jobId)}`;
  $$(".workspace-nav [data-view]").forEach(link => {
    if (link.dataset.view === view) link.setAttribute("aria-current", "page");
    else link.removeAttribute("aria-current");
  });
  // Navigation preserves the in-memory draft and never cancels an existing job.
  if (view !== "task") $("#audio-player").pause();
  if (navigate) {
    const url = view === "task" ? `?job=${encodeURIComponent(state.jobId)}` : `#${view === "recent" ? "recent" : "workspace"}`;
    history.pushState(null, "", location.pathname + url);
  }
  document.title = `${{new:"新建研究", recent:"研究记录", task:"当前任务"}[view]} · 论文开讲`;
  if (focus) {
    const heading = $(view === "new" ? "#create-view h1" : view === "recent" ? "#recent h1" : "#task-heading");
    heading.tabIndex = -1;
    heading.focus({ preventScroll: true });
    window.scrollTo({ top: 0, behavior: "instant" });
  }
}

function openJob(jobId, navigate = true) {
  window.clearTimeout(state.pollTimer);
  showProgress(jobId);
  if (navigate) history.pushState(null, "", `?job=${encodeURIComponent(jobId)}`);
  pollJob();
}

function restoreLocation(focus = true) {
  const jobId = new URLSearchParams(location.search).get("job");
  if (jobId && jobId !== state.jobId) openJob(jobId, false);
  else setView(jobId ? "task" : location.hash === "#recent" ? "recent" : "new", { focus });
}

function initNavigation() {
  $$('[data-view]').forEach(link => link.addEventListener('click', event => {
    if (event.button !== 0 || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
    event.preventDefault();
    setView(link.dataset.view, { navigate: true, focus: true });
    if (link.dataset.view === 'recent') loadRecent();
  }));
  window.addEventListener('popstate', () => restoreLocation());
  $$('[data-dialog]').forEach(button => button.addEventListener('click', () => {
    const dialog = document.getElementById(button.dataset.dialog);
    dialog.showModal();
    // Start at the heading/close action, not a field that opens a mobile keyboard.
    $('[data-close-dialog]', dialog).focus();
  }));
  $$('[data-close-dialog]').forEach(button => button.addEventListener('click', () => button.closest('dialog').close()));
  $$('.settings-dialog').forEach(dialog => dialog.addEventListener('close', () => {
    $(`[data-dialog="${dialog.id}"]`).focus({ preventScroll: true });
  }));
}

function keepServiceWhilePageIsOpen() {
  if (!("EventSource" in window)) return;
  let clientId = sessionStorage.getItem("paper-dialogue-client-id");
  if (!clientId) {
    clientId = (crypto.randomUUID?.() || `${Date.now()}-${Math.random()}`).replace(/[^A-Za-z0-9_-]/g, "");
    sessionStorage.setItem("paper-dialogue-client-id", clientId);
  }
  state.serviceEvents?.close();
  state.serviceEvents = new EventSource(`/api/client/events?client_id=${encodeURIComponent(clientId)}`);
}

async function requestJson(url, options = {}) {
  const controller = new AbortController(), timer = setTimeout(() => controller.abort(), 30000);
  let response;
  try { response = await fetch(url, {...options, signal: controller.signal}); }
  catch (error) { if (error.name === "AbortError") throw new Error("网络请求超时，请稍后重试。"); throw error; }
  finally { clearTimeout(timer); }
  let data = {};
  try { data = await response.json(); } catch (_) { /* non-json server failure */ }
  if (!response.ok) { const error = new Error(data.error || `请求失败（${response.status}）`); error.status = response.status; throw error; }
  return data;
}

async function checkHealth() {
  const pill = $("#api-pill");
  try {
    const health = await requestJson("/api/health");
    state.health = health;
    pill.classList.remove("ready", "missing");
    pill.classList.add(health.audio_project_ready ? "ready" : "missing");
    $("b", pill).textContent = health.audio_project_ready ? `V${health.workflow_version || 1} 项目已连接` : "未找到音频生成项目";
    $("#pending-count").textContent = `${health.pending_count || 0} 个任务`;
  } catch (_) {
    pill.classList.add("missing");
    $("b", pill).textContent = "服务连接失败";
  }
}

function setSource(source) {
  $("#source-type").value = source;
  $$(".source-tab").forEach((tab) => { const active=tab.dataset.source === source; tab.classList.toggle("active", active); tab.setAttribute("aria-selected", String(active)); tab.tabIndex=active?0:-1; });
  $$(".source-panel").forEach((panel) => { const active=panel.dataset.panel === source;panel.classList.toggle("active", active);$$("input,textarea",panel).forEach(input=>input.disabled=!active); });
  updateSelectionSummary();
}

function initInputs() {
  $$(".source-tab").forEach((tab) => tab.addEventListener("click", () => setSource(tab.dataset.source)));
  const input = $("#file-input");
  const zone = $("#drop-zone");
  zone.addEventListener("keydown", event => { if (["Enter", " "].includes(event.key) && event.target === zone) { event.preventDefault(); input.click(); } });
  $$(".source-tab").forEach((tab, index, tabs) => {
    tab.setAttribute("role", "tab"); tab.id=`source-tab-${tab.dataset.source}`;
    tab.setAttribute("aria-controls", `source-panel-${tab.dataset.source}`);
    tab.addEventListener("keydown", event => { if (["ArrowLeft", "ArrowRight"].includes(event.key)) { event.preventDefault(); const next=tabs[(index+(event.key==="ArrowRight"?1:tabs.length-1))%tabs.length]; setSource(next.dataset.source); next.focus(); } });
  });
  $$(".source-panel").forEach(panel => {panel.id=`source-panel-${panel.dataset.panel}`;panel.setAttribute("role", "tabpanel");panel.setAttribute("aria-labelledby", `source-tab-${panel.dataset.panel}`);});
  setSource("file");
  input.addEventListener("change", () => {
    addFiles(input.files); input.value = "";
  });
  ["dragenter", "dragover"].forEach((name) => zone.addEventListener(name, (event) => {
    event.preventDefault(); zone.classList.add("dragging");
  }));
  ["dragleave", "drop"].forEach((name) => zone.addEventListener(name, (event) => {
    event.preventDefault(); zone.classList.remove("dragging");
  }));
  zone.addEventListener("drop", (event) => {
    if (!event.dataTransfer.files.length) return;
    addFiles(event.dataTransfer.files);
  });
}

function addFiles(files) {
  for (const file of files) {
    if (!/\.(pdf|html|htm)$/i.test(file.name)) { showToast(`不支持 ${file.name}，请使用 PDF / HTML。`); continue; }
    if (!file.size || file.size > 36 * 1024 * 1024) { showToast(`${file.name} 为空或超过 36 MB。`); continue; }
    if (state.files.some(item => item.name === file.name && item.size === file.size && item.lastModified === file.lastModified)) continue;
    if (state.files.length >= 12) { showToast("最多添加 12 个文件。"); break; }
    state.files.push(file);
  }
  renderFiles();
}

function renderFiles() {
  const root = $("#file-list"); root.replaceChildren();
  state.files.forEach((file, index) => {
    const item = el("li"), remove = el("button", "", "移除"); remove.type = "button";
    remove.setAttribute("aria-label", `移除 ${file.name}`);
    remove.addEventListener("click", () => { state.files.splice(index, 1); renderFiles(); });
    item.append(el("span", "", `${file.name} · ${(file.size / 1024 / 1024).toFixed(2)} MB`), remove); root.append(item);
  });
  $("#file-label").textContent = state.files.length ? `已选 ${state.files.length} 个文件，点击继续添加` : "拖入 PDF / HTML，或点击选择";
  if (state.files.length) { $('#drop-zone').removeAttribute('aria-invalid'); $('#drop-zone-error')?.classList.add('hidden'); }
  updateSelectionSummary();
}

async function loadRecent() {
  try {
    const data = await requestJson("/api/jobs"); state.jobs = data.jobs; renderRecent();
  } catch (_) { $("#recent-jobs").textContent = "暂时无法读取任务记录。"; }
}

function renderRecent() {
    const root = $('#recent-jobs'); root.replaceChildren();
    const query = $('#history-search').value.trim().toLocaleLowerCase(), filter = $('#history-filter').value;
    const all = state.jobs || [];
    const jobs = all.filter(job => `${job.title} ${job.id}`.toLocaleLowerCase().includes(query) && (filter === 'all' || (filter === 'active' ? !['complete','error'].includes(job.status) : job.status === filter)));
    $('#history-count').textContent = `${jobs.length} / ${all.length} 项研究`;
    if (!jobs.length) root.append(el('p','history-empty', all.length ? '没有匹配的研究。换个关键词，或重置筛选。' : '还没有研究。点击“新建研究”，从一份材料开始。'));
    jobs.forEach(job => {
      const item = el("a", "recent-job"); item.href = `?job=${job.id}`;
      if (job.id === state.jobId) item.setAttribute("aria-current", "page");
      item.addEventListener("click", event => {
        if (event.button !== 0 || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
        event.preventDefault(); openJob(job.id);
      });
      item.append(el("b", "", job.title), el("small", "", `${phaseNames[job.status] || (job.status === "running" ? "处理中" : job.status)} · ${job.progress}%`));
      root.append(item);
    });
}

function showHandoff(prompt) {
  state.codexPrompt = prompt || "";
  $("#codex-prompt").textContent = state.codexPrompt;
  $("#handoff-box").classList.toggle("hidden", !state.codexPrompt);
}

async function copyCodexPrompt() {
  if (!state.codexPrompt) return;
  try {
    await navigator.clipboard.writeText(state.codexPrompt);
    $("#copy-prompt").textContent = "已复制";
    window.setTimeout(() => { $("#copy-prompt").textContent = "复制 Codex 指令"; }, 1800);
  } catch (_) {
    showToast("无法自动复制，请手动选中上面的指令复制。");
  }
}

function showProgress(jobId, prompt = "") {
  state.jobId = jobId;
  state.result = null;
  state.reconnecting = false;
  $("#audio-player").pause();
  $("#task-heading").textContent = "任务进度";
  setView("task", { focus: true });
  $("#progress-card").classList.remove("hidden");
  $("#results").classList.add("hidden");
  $("#progress-phase").textContent = "准备任务";
  $("#progress-message").textContent = "正在创建任务";
  $("#progress-value").textContent = "0%";
  $("#progress-bar").style.width = "0%";
  showHandoff(prompt);
  $("#retry-job").classList.add("hidden");
  $("#stop-api-job").classList.add("hidden");
  $("#stage-progress").replaceChildren();
  $("#intake-summary").textContent = "";
}

async function submitPaper(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const openSettings = $('dialog[open]', form);
  if (openSettings) { openSettings.close(); return; }
  const type = $("#source-type").value;
  if (type === "file" && !state.files.length) return fieldError('#drop-zone', "请选择一个或多个 PDF / HTML 文件。");
  if (state.files.reduce((sum, f) => sum + f.size, 0) > 99 * 1024 * 1024) return showToast("文件总量接近 100 MB 上限，请分成两个任务。");
  if (type === "url" && !$("#url-input").value.trim()) return fieldError('#url-input', "请输入文章网址。");
  if (type === "notion" && !$("#notion-input").value.trim()) return fieldError('#notion-input', "请输入 Notion 页面链接。");
  if (type === "html" && !$("#html-input").value.trim()) return fieldError('#html-input', "请粘贴 HTML 内容。");
  const formData = new FormData(form);
  const audience = $('#audience-select').value;
  if (audience === 'custom' && !$('#audience-input').value.trim()) return fieldError('#audience-input','请填写自定义读者基础。');
  formData.set('audience', audience === 'custom' ? $('#audience-input').value.trim() : audience);
  const apiMode = $('#execution-mode').value === 'api';
  if (apiMode && !$('#api-consent').checked) return fieldError('#api-consent','请先确认 API 材料传输和按量计费说明。');
  formData.set('api_consent', String(apiMode && $('#api-consent').checked));
  formData.delete("files");
  if (type === "file") state.files.forEach(file => formData.append("files", file));
  formData.set("source_type", type);
  formData.set("synthesize_audio", $("#audio-toggle").checked ? "true" : "false");
  const submit = $("button[type=submit]", form); submit.disabled = true;
  try {
    if (apiMode) await saveApiSettings();
    const data = await requestJson("/api/jobs", { method: "POST", body: formData });
    history.pushState(null, "", `?job=${encodeURIComponent(data.job_id)}`);
    showProgress(data.job_id, data.codex_prompt); pollJob(); checkHealth(); loadRecent();
  } catch (error) {
    showToast(error.message);
  } finally { submit.disabled = false; }
}

async function startDemo() {
  try {
    const data = await requestJson("/api/jobs/demo", { method: "POST" });
    history.pushState(null, "", `?job=${encodeURIComponent(data.job_id)}`);
    showProgress(data.job_id); pollJob();
  } catch (error) { showToast(error.message); }
}

async function pollJob() {
  window.clearTimeout(state.pollTimer);
  const expectedId = state.jobId;
  try {
    const job = await requestJson(`/api/jobs/${state.jobId}`);
    if (expectedId !== state.jobId) return;
    if (state.reconnecting) {
      state.reconnecting = false;
      showToast("本地服务已重新连接，任务状态已恢复。" );
    }
    const progress = Math.max(0, Math.min(100, job.progress || 0));
    $("#progress-phase").textContent = phaseNames[job.phase] || job.phase;
    $("#progress-message").textContent = job.message || "正在处理";
    $("#progress-value").textContent = `${progress}%`;
    $("#progress-bar").style.width = `${progress}%`;
    const stageRoot = $("#stage-progress"); stageRoot.replaceChildren();
    const stageIndex = stages.findIndex(item => item[0] === job.stage);
    stages.forEach(([key, name], index) => stageRoot.append(el("li", index < stageIndex ? "done" : index === stageIndex ? "current" : "", name)));
    $("#intake-summary").textContent = (job.intake_summary || []).join("\n");
    $("#retry-job").classList.toggle("hidden", !job.can_retry);
    const apiMode = job.request?.execution_mode === 'api';
    $('#retry-job').textContent = apiMode ? '保留已有产物，继续 API 制作' : '保留已有产物，交给 Codex 继续';
    $('#stop-api-job').classList.toggle('hidden', !job.api_running);
    $('#progress-help').textContent = apiMode ? 'API 正在按阶段执行。关闭全部页面约一分钟后会停止本地服务及 API 任务；重新启动后可保留缓存继续。' : '把指令发到本项目的 Codex 对话后，网页会自动刷新进度。';
    if (apiMode) showHandoff('');
    else if (!state.codexPrompt && job.request?.task_prompt) showHandoff(job.request.task_prompt);
    if (job.status === "complete") {
      state.result = job.result;
      renderResult(job.result, job.id); loadRecent();
      return;
    }
    if (job.status === 'error') {
      $('#progress-phase').textContent = '任务出错';
      $('#progress-message').textContent = job.error || job.message || '任务失败';
      if (job.api_running) state.pollTimer = setTimeout(pollJob, 2000);
      return;
    }
    state.pollTimer = window.setTimeout(pollJob, 1400);
  } catch (error) {
    if (expectedId !== state.jobId) return;
    if (/failed to fetch|networkerror|网络|无法连接/i.test(error.message) || [502,503,504].includes(error.status)) {
      $("#progress-phase").textContent = "正在重连";
      $("#progress-message").textContent = "本地服务暂时不可用，页面会自动重试，任务文件不会丢失";
      if (!state.reconnecting) showToast("本地服务连接中断，正在自动重连……");
      state.reconnecting = true;
      state.pollTimer = window.setTimeout(pollJob, 2500);
      return;
    }
    $("#progress-phase").textContent = "任务出错";
    $("#progress-message").textContent = error.message;
    showToast(error.message);
  }
}

async function retryJob() {
  const button = $("#retry-job"); button.disabled = true;
  try {
    const data = await requestJson(`/api/jobs/${state.jobId}/retry`, {method: "POST"});
    showProgress(data.job_id, data.codex_prompt); pollJob(); loadRecent();
  } catch(error) { showToast(error.message); }
  finally { button.disabled = false; }
}

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined && text !== null) node.textContent = text;
  return node;
}

function tile(label, text, wide = false) {
  const item = el("div", `info-tile${wide ? " wide" : ""}`);
  item.append(el("small", "", label), el("p", "", text || "—"));
  return item;
}

function addListSection(root, title, values) {
  if (!values?.length) return;
  root.append(el("h3", "section-title", title));
  const tags = el("div", "tag-list");
  values.forEach((value) => tags.append(el("span", "tag", value)));
  root.append(tags);
}

function renderMap(analysis) {
  const root = $("#map-panel"); root.replaceChildren();
  root.append(el("p", "overview", analysis.plain_language_overview));
  if (analysis.papers?.length) {
    root.append(el("h3", "section-title", `逐篇速览 · ${analysis.papers.length} 篇`));
    analysis.papers.forEach((paper, index) => {
      const card = el("article", "paper-summary");
      const metadata = paper.metadata || {};
      card.append(
        el("small", "paper-index", `PAPER ${String(index + 1).padStart(2, "0")}`),
        el("h3", "", metadata.title || `论文 ${index + 1}`),
        el("p", "paper-meta", [Array.isArray(metadata.authors) ? metadata.authors.join("、") : metadata.authors, metadata.year, metadata.venue].filter(Boolean).join(" · "))
      );
      const paperGrid = el("div", "map-grid");
      paperGrid.append(
        tile("背景", paper.background, true),
        tile("研究问题", paper.question_or_goal),
        tile("做了什么", paper.what_they_did),
        tile("主要结论", paper.conclusions, true)
      );
      card.append(paperGrid); root.append(card);
    });
    const synthesis = analysis.cross_paper_synthesis || {};
    addListSection(root, "跨论文共识", synthesis.common_ground);
    addListSection(root, "关键分歧", synthesis.differences);
    if (synthesis.open_question) root.append(tile("仍未解决的问题", synthesis.open_question, true));
    return;
  }
  const map = analysis.research_map || {};
  const grid = el("div", "map-grid");
  grid.append(
    tile("研究问题", map.question, true), tile("为什么重要", map.why_it_matters),
    tile("过去怎么想", map.prior_belief), tile("研究缺口", map.gap),
    tile("核心假设", map.core_hypothesis), tile("真正贡献", map.contribution, true)
  );
  root.append(grid);
  const critique = analysis.critique || {};
  addListSection(root, "值得肯定", critique.strengths);
  addListSection(root, "局限与替代解释", [...(critique.limitations || []), ...(critique.alternative_explanations || [])]);
}

function renderLogic(analysis) {
  const root = $("#logic-panel"); root.replaceChildren();
  const chain = el("div", "logic-chain");
  const steps = analysis.papers?.length
    ? analysis.papers.flatMap((paper, paperIndex) => (paper.logic_chain || []).map((step) => ({step, paper, paperIndex})))
    : (analysis.logic_chain || []).map((step) => ({step, paper: null, paperIndex: null}));
  steps.forEach(({step, paper, paperIndex}, index) => {
    const row = el("article", "logic-step");
    row.append(el("div", "logic-num", String(index + 1).padStart(2, "0")));
    const body = el("div", "logic-body");
    const normalized = typeof step === "string" ? {author_claim: step} : step;
    const claim = normalized.claim || normalized.author_claim || normalized.codex_inference || normalized.move || "";
    const evidence = normalized.evidence_or_move || normalized.paper_evidence || normalized.evidence || "";
    const paperLabel = paper ? `${paper.metadata?.title || `论文 ${paperIndex + 1}`} · ` : "";
    body.append(el("h3", "", `${paperLabel}${normalized.stage || "逻辑步骤"} · ${claim}`), el("p", "", evidence));
    const detail = el("div", "logic-detail");
    const assumptions = el("div"); assumptions.append(el("b", "", "隐含假设"), document.createTextNode((normalized.hidden_assumptions || []).join("；") || "—"));
    const next = el("div"); next.append(el("b", "", "为什么走到下一步"), document.createTextNode(normalized.why_next || "—"));
    detail.append(assumptions, next); body.append(detail); row.append(body); chain.append(row);
  });
  root.append(chain);
}

function renderScript(script) {
  const root = $("#script-panel"); root.replaceChildren();
  let chapter = null;
  (script.turns || []).forEach((turn) => {
    if (turn.chapter !== chapter) {
      chapter = turn.chapter;
      root.append(el("div", "chapter-label", chapter || "未分章"));
    }
    const row = el("article", `dialogue ${turn.speaker}`);
    const isHost = turn.speaker === "host";
    const isNarrator = turn.speaker === "narrator";
    row.append(el("div", "avatar", isNarrator ? "播" : (isHost ? "知" : "问")));
    const bubble = el("div", "bubble");
    const head = el("header");
    const speakerName = isNarrator
      ? (script.speakers?.narrator_name || "简报")
      : (isHost ? (script.speakers?.host_name || "主讲") : (script.speakers?.learner_name || "提问者"));
    head.append(el("b", "", speakerName), el("small", "", turn.delivery));
    bubble.append(head, el("p", "", turn.text));
    if (turn.source_refs?.length) { const refs=el("details","script-sources");refs.append(el("summary","","查看依据"),el("p","",turn.source_refs.join("；")));bubble.append(refs); }
    row.append(bubble); root.append(row);
  });
}

function safeUrl(url) {
  try { const parsed = new URL(url); return ["http:", "https:"].includes(parsed.protocol) ? parsed.href : null; }
  catch (_) { return null; }
}

function renderVersions(analysis) {
  const root = $("#versions-panel"); root.replaceChildren();
  const versions = analysis.public_versions || [];
  if (!versions.length) return root.append(el("p", "empty-state", "没有找到能够可靠核验的公开版本。"));
  versions.forEach((version) => {
    const card = el("article", "version-card");
    const body = el("div");
    body.append(el("h3", "", version.label), el("p", "", `${version.version_type} · ${version.relationship}`), el("p", "", version.verification_note));
    card.append(body);
    const href = safeUrl(version.url);
    if (href) { const link = el("a", "", "打开来源 ↗"); link.href = href; link.target = "_blank"; link.rel = "noopener noreferrer"; card.append(link); }
    root.append(card);
  });
}

function renderDownloads(result, jobId) {
  const row = $("#download-row"); row.replaceChildren();
  const labels = { report: "精读报告 HTML", reading_report: "精读报告 Markdown", research: "证据底稿", followups: "研究推进计划", learning_cards: "学习卡", visual: "离线逻辑动画", analysis: "兼容精读 JSON", script: "脚本 JSON", transcript: "文字稿", audio: "完整 MP3", validation: "结构检查", release: "内容复核", audio_review: "音频检查", audio_release: "音频验收", intake: "读取清单" };
  Object.entries(result.artifacts || {}).forEach(([kind, filename]) => {
    if (!filename) return;
    const link = el("a", "", labels[kind] || kind);
    link.href = `/api/jobs/${jobId}/artifact/${kind}`;
    row.append(link);
  });
}

function renderEmbedded(panel, title, url, explanation) {
  const root = $(panel); root.replaceChildren();
  if (!url) { root.append(el("p", "empty-state", explanation)); return; }
  const link = el("a", "artifact-link", `${title} · 在新标签打开 ↗`);
  link.href = url; link.target = "_blank"; link.rel = "noopener";
  const frame = el("iframe", "artifact-frame"); frame.title = title;
  frame.setAttribute("sandbox", "allow-scripts allow-downloads allow-popups allow-popups-to-escape-sandbox"); frame.loading = "lazy"; frame.src = url;
  root.append(link, frame);
}

function renderResearch(result, jobId) {
  const data = result.research || {}, prefix = `/api/jobs/${jobId}/view/`;
  renderEmbedded("#report-panel", "精读报告", result.demo_v3 ? "/api/demo/report.html" : result.artifacts?.report ? prefix + "report.html" : null, "此历史节目尚未生成 V3 报告。新任务将自动提供。");
  renderEmbedded("#visual-panel", "逻辑链动画", result.demo_v3 ? "/api/demo/visuals/logic-chain.html" : result.artifacts?.visual ? prefix + "visuals/logic-chain.html" : null, data.teaching?.visual?.reason || "本任务没有生成动画；动画按解释需要与任务选择启用。");
  const followups = $("#followups-panel"); followups.replaceChildren();
  (data.followups || []).forEach(item => {
    const card = el("article", "followup-card");
    card.append(el("h3", "", item.question), el("p", "", item.action), el("p", "", `完成条件：${item.done_when}`), el("small", "", `优先级 ${item.priority} · ${item.status} · 预期产物：${item.expected_artifact}`)); followups.append(card);
  });
  if (!followups.children.length) followups.append(el("p", "empty-state", "此历史节目没有 V3 后续研究计划。"));
  const cards = $("#cards-panel"); cards.replaceChildren();
  (data.teaching?.cards || []).forEach(item => {
    const card = el("details", "learning-card"); card.append(el("summary", "", item.question), el("p", "", item.answer), el("small", "", `关联论断：${(item.claim_ids || []).join("、")}`)); cards.append(card);
  });
  if (!cards.children.length) cards.append(el("p", "empty-state", "此历史节目没有 V3 学习卡。"));
  const review = result.review || {}, audio = result.audio_review || {};
  $("#review-summary").textContent = result.demo_v3 ? "V3 流程示例，不代表真实论文研究；没有生成音频。" : [
    review.scientific_review === "passed" ? `内容复核：${review.review_note}` : "历史节目：没有 V3 内容复核记录。",
    review.limitations ? `保留限制：${review.limitations}` : "",
    result.audio_available ? `音频：${audio.technical_decode === "passed" ? "技术检查通过" : "历史产物"}；${audio.listening_review === "passed" ? "已记录听感审听" : "未记录听感审听"}` : "",
    ...(result.warnings || [])].filter(Boolean).join("\n");
}

function renderResult(result, jobId) {
  const analysis = result.analysis || {}, script = result.script || {}, metadata = analysis.metadata || {};
  $("#episode-title").textContent = script.episode_title || metadata.title || "论文教学播客";
  const formatLabel = script.format === "single_narrator" ? "单人讲述" : "双人教学对话";
  $("#paper-meta").textContent = [metadata.title, metadata.year, metadata.venue, formatLabel, `${result.target_minutes || "—"} 分钟目标`].filter(Boolean).join(" · ");
  const player = $("#audio-player"), empty = $("#audio-empty");
  if (result.audio_available) {
    player.src = `/api/jobs/${jobId}/artifact/audio`; player.classList.remove("hidden"); empty.classList.add("hidden");
  } else { player.removeAttribute("src"); player.classList.add("hidden"); empty.classList.remove("hidden"); }
  renderDownloads(result, jobId); renderMap(analysis); renderLogic(analysis); renderScript(script); renderVersions(analysis);
  renderResearch(result, jobId);
  const preferredTab = result.artifacts?.report || result.demo_v3 ? "report" : "map";
  $(`.result-tab[data-result=${preferredTab}]`).click();
  $("#progress-card").classList.add("hidden");
  $("#results").classList.remove("hidden");
  $("#task-heading").textContent = "研究结果";
  // Finishing in the background must not pull the reader out of another view.
  if (state.view === "task") window.scrollTo({ top: 0, behavior: "instant" });
}

function initResultTabs() {
  $$(".result-tab").forEach((tab) => tab.addEventListener("click", () => {
    const name = tab.dataset.result;
    $$(".result-tab").forEach((item) => {item.classList.toggle("active", item === tab);item.setAttribute("aria-pressed",String(item === tab));});
    $$(".result-panel").forEach((panel) => panel.classList.toggle("active", panel.dataset.resultPanel === name));
    // A selected artifact should load even when its lazy iframe starts below the viewport.
    $$(`.result-panel[data-result-panel=${name}] iframe`).forEach(frame => frame.loading = "eager");
  }));
}

function initProductionSummary() {
  const options = $('#production-options');
  const update = () => {
    const depth = {deep:'专业精读', standard:'标准分析', brief:'快速简报'}[$('#depth-select').value];
    const format = $('[name=presentation]').value === 'dialogue' ? '双人对话' : '单人讲述';
    const duration = $('[name=duration]:checked').value;
    $('#production-summary').textContent = [depth, format, duration === 'auto' ? '智能时长' : `${duration} 分钟`, $('#audio-toggle').checked ? '生成人声' : '不生成人声'].join(' · ');
  };
  options.addEventListener('change', update); update();
}

function setExecutionMode() {
  const apiMode = $('#execution-mode').value === 'api';
  $('#api-panel').classList.toggle('hidden', !apiMode);
  if (!apiMode) $('#api-dialog').close();
  $$('#api-panel input').forEach(input => input.disabled = !apiMode);
  $('#paper-form button[type=submit] span').textContent = apiMode ? '保存任务并通过 API 制作' : '保存任务并交给 Codex';
  $('#execution-help').textContent = apiMode ? '使用你的 API Key 按量计费；每阶段缓存，遇到证据、长度或媒体检查失败会停止，不伪报完成。' : 'Codex 模式不需要单独 API Key；保存后把指令发到本项目。所有音频均保留 AI 生成披露。';
}

function showApiSettings(data) {
  $('#api-base').value = data.base_url;
  $('#api-model').value = data.model;
  $('#api-max-calls').value = data.max_calls;
  $('#api-settings-status').textContent = `模型密钥：${data.key_configured ? '已配置（不回显）' : '未配置'}；Notion：${data.notion_configured ? '已配置' : '未配置'}。网页输入的密钥随服务退出清除。`;
  $('#api-connection-summary').textContent = `${data.model} · ${data.key_configured ? '密钥已配置' : '待填写 API Key'}`;
}

async function saveApiSettings(extra = {}) {
  const data = await requestJson('/api/settings', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({
    base_url: $('#api-base').value.trim(), model: $('#api-model').value.trim(), max_calls: Number($('#api-max-calls').value),
    api_key: $('#api-key').value.trim(), notion_token: $('#notion-token').value.trim(), ...extra
  })});
  $('#api-key').value = ''; $('#notion-token').value = '';
  showApiSettings(data);
  return data;
}

function initApiSettings() {
  $('#audience-select').addEventListener('change', () => $('#audience-custom').classList.toggle('hidden', $('#audience-select').value !== 'custom'));
  $('#execution-mode').addEventListener('change', setExecutionMode);
  setExecutionMode();
  requestJson('/api/settings').then(showApiSettings).catch(error => showToast(error.message));
  $('#api-save').addEventListener('click', () => saveApiSettings().then(() => showToast('本次 API 设置已保存')).catch(error => showToast(error.message)));
  $('#api-clear').addEventListener('click', () => saveApiSettings({clear_api_key: true, clear_notion_token: true}).catch(error => showToast(error.message)));
  $('#api-test').addEventListener('click', async event => {
    const button = event.currentTarget; button.disabled = true;
    try {
      await saveApiSettings();
      const result = await requestJson('/api/settings/test', {method: 'POST'});
      $('#api-settings-status').textContent = result.message + (result.model_available ? ' 当前模型在可用列表中。' : ' 当前模型不在列表中，请核对模型 ID。');
    } catch(error) { $('#api-settings-status').textContent = error.message; }
    finally { button.disabled = false; }
  });
  $('#stop-api-job').addEventListener('click', async () => {
    try { const data = await requestJson(`/api/jobs/${state.jobId}/stop`, {method: 'POST'}); showToast(data.message); }
    catch(error) { showToast(error.message); }
  });
}

document.addEventListener("DOMContentLoaded", () => {
  keepServiceWhilePageIsOpen(); checkHealth(); loadRecent(); initInputs(); initResultTabs(); initApiSettings(); initProductionSummary(); initNavigation(); initEfficiency();
  $("#paper-form").addEventListener("submit", submitPaper);
  $("#paper-form").addEventListener("invalid", event => {
    const dialog = event.target.closest('dialog');
    if (dialog && !dialog.open) dialog.showModal();
  }, true);
  $("#demo-btn").addEventListener("click", startDemo);
  $("#copy-prompt").addEventListener("click", copyCodexPrompt);
  $("#retry-job").addEventListener("click", retryJob);
  restoreLocation(false);
});
