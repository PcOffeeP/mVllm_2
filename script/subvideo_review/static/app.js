/* Human-only decisions. Source references never populate the label controls. */
"use strict";
(() => {
  const byId = (id) => document.getElementById(id);
  const names = ["断裂状态", "断裂模式", "断裂位置", "异常情况.未夹紧", "异常情况.视频异常", "异常情况.爆炸性断裂", "断裂现象.伸长", "断裂现象.颈缩", "断裂现象.开裂", "断裂现象.界面分离", "断裂现象.断后脱夹"];
  const statusNames = {unreviewed: "未审核", draft: "草稿", confirmed: "已确认", returned: "已退回", question: "有疑问"};
  const state = {data: null, selected: null, latest: null, dirty: false, loading: false, sequence: 0};
  const controls = new Map();
  const setVideoState = (value) => {
    const frame = byId("video-player").closest(".video-frame");
    if (!frame) return;
    frame.dataset.state = value;
    const title = frame.querySelector(".video-placeholder strong");
    if (title) title.textContent = value === "error" ? "媒体无法播放" : "正在载入视频";
  };
  const message = (text, error = false) => {
    const node = byId("app-message");
    node.textContent = text;
    node.setAttribute("role", error ? "alert" : "status");
    node.dataset.kind = error ? "error" : "info";
  };
  async function request(path, options) {
    const response = await fetch(path, {cache: "no-store", ...options});
    const value = await response.json();
    if (!response.ok) throw new Error(value.error || `请求失败 (${response.status})`);
    return value;
  }
  function filtered() {
    const source = byId("source-filter").value;
    const status = byId("status-filter").value;
    const search = byId("candidate-search").value.trim().toLowerCase();
    return state.data.candidates.filter((c) =>
      (!source || source === "all" || source === c.source_type || source === `source:${c.source_id}`) &&
      (!status || status === "all" || status === c.review_status) &&
      (!search || `${c.candidate_id} ${c.source_id}`.toLowerCase().includes(search)));
  }
  function addOption(select, value, label) {
    const option = document.createElement("option");
    option.value = value;
    option.textContent = label;
    select.append(option);
  }
  function renderFilters() {
    const source = byId("source-filter");
    source.replaceChildren();
    addOption(source, "", "全部来源");
    addOption(source, "real", "真实来源");
    addOption(source, "virtual", "虚拟来源");
    [...new Set(state.data.candidates.map((c) => c.source_id))].sort().forEach((id) => addOption(source, `source:${id}`, id));
    const status = byId("status-filter");
    status.replaceChildren();
    addOption(status, "", "全部状态");
    Object.entries(statusNames).forEach(([value, label]) => addOption(status, value, label));
  }
  function renderList() {
    const list = byId("candidate-list");
    list.replaceChildren();
    const candidates = filtered();
    candidates.forEach((candidate) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "candidate-item";
      button.dataset.candidateId = candidate.candidate_id;
      button.setAttribute("aria-current", String(candidate.candidate_id === state.selected?.candidate_id));
      button.textContent = `${candidate.candidate_id} · ${statusNames[candidate.review_status] || candidate.review_status}`;
      button.addEventListener("click", () => selectCandidate(candidate));
      list.append(button);
    });
    if (!candidates.length) {
      const empty = document.createElement("p");
      empty.textContent = "当前筛选没有候选。";
      list.append(empty);
    }
    const count = byId("candidate-count");
    if (count) count.textContent = `${candidates.length} / ${state.data.candidates.length}`;
    updateNavigation();
  }
  function updateNavigation() {
    const list = filtered();
    const index = list.findIndex((c) => c.candidate_id === state.selected?.candidate_id);
    byId("previous-candidate").disabled = state.loading || index <= 0;
    byId("next-candidate").disabled = state.loading || index < 0 || index >= list.length - 1;
  }
  function renderPending() {
    const node = byId("pending-list");
    node.replaceChildren();
    const pending = state.data.pending_sources.filter((s) => s.status === "pending");
    const held = state.data.pending_sources.filter((s) => s.status === "held");
    const title = document.createElement("p");
    title.textContent = `${pending.length} 个待处理来源；${held.length} 个暂留来源。这里只展示已有原因，不会触发生成。`;
    node.append(title);
    state.data.pending_sources.forEach((source) => {
      const item = document.createElement("p");
      item.textContent = `${source.source_id} · ${source.status === "held" ? "暂留" : "待处理"} · ${source.reason || "原因未记录"}`;
      if (source.source_preview_available) {
        const button = document.createElement("button");
        button.type = "button";
        button.className = "button button-secondary";
        button.textContent = "查看原视频与源标注";
        button.addEventListener("click", () => previewSource(source));
        item.append(" ", button);
      }
      node.append(item);
    });
  }
  function renderReference(reference) {
    const aside = byId("source-reference");
    let content = aside.querySelector(".reference-empty");
    if (!content) { content = document.createElement("div"); content.className = "reference-empty"; aside.append(content); }
    content.replaceChildren();
    if (!reference || !Object.keys(reference).length) { content.textContent = "源标注未记录。"; return; }
    const list = document.createElement("dl");
    Object.entries(reference).forEach(([key, value]) => {
      if (value === "" || value === null || value === undefined) return;
      const term = document.createElement("dt");
      const detail = document.createElement("dd");
      term.textContent = key;
      detail.textContent = typeof value === "object" ? JSON.stringify(value) : String(value);
      list.append(term, detail);
    });
    content.append(list);
  }
  function previewSource(source) {
    if (state.loading) return;
    if (state.dirty && !window.confirm("有尚未保存的判断，查看原视频将丢弃这些输入。继续？")) return;
    state.selected = null;
    state.latest = null;
    state.dirty = false;
    setControls();
    byId("review-note").value = "";
    byId("decision-reason").value = "";
    byId("clip-title").textContent = `原视频 · ${source.source_id}`;
    byId("clip-meta").textContent = `待处理来源 · ${source.reason || "原因未记录"}`;
    byId("timeline-info").textContent = "当前播放完整源视频，仅供人工复看；不会修改源标注、生成候选或保存片段审核。";
    renderReference(source.source_reference);
    byId("review-status").textContent = "原视频只读查看";
    byId("revision-history").textContent = "请从候选列表选择片段后填写审核。";
    const video = byId("video-player");
    video.pause();
    setVideoState("loading");
    video.src = `/source-media?source_id=${encodeURIComponent(source.source_id)}`;
    video.load();
    setBusy(false);
    renderList();
    message("仅查看当前开发来源。源标注显示为参考，不会写入候选审核。" );
  }
  function labelsFromControls() {
    const labels = {"异常情况": {}, "断裂现象": {}};
    names.forEach((name) => {
      const parts = name.split(".");
      if (parts.length === 1) labels[name] = controls.get(name).value;
      else labels[parts[0]][parts[1]] = controls.get(name).value;
    });
    return labels;
  }
  function setControls(labels = {}) {
    names.forEach((name) => {
      const parts = name.split(".");
      const value = parts.length === 1 ? labels[name] : labels[parts[0]]?.[parts[1]];
      controls.get(name).value = value || "";
    });
  }
  function renderHistory(review) {
    const node = byId("revision-history");
    node.replaceChildren();
    const append = (row, isolated) => {
      const details = document.createElement("details");
      const summary = document.createElement("summary");
      summary.textContent = `${isolated ? "已隔离旧身份 · " : ""}${statusNames[row.review_status]} · ${row.created_at} · ${row.review_id}`;
      const content = document.createElement("pre");
      content.textContent = JSON.stringify(row, null, 2);
      details.append(summary, content);
      node.append(details);
    };
    [...review.history].reverse().forEach((row) => append(row, false));
    [...review.isolated_history].reverse().forEach((row) => append(row, true));
    if (!review.history.length && !review.isolated_history.length) node.textContent = "尚无人工修订。";
  }
  function setBusy(busy) {
    state.loading = busy;
    ["save-draft", "confirm-review", "return-review", "question-review"].forEach((id) => { byId(id).disabled = busy || !state.selected; });
    controls.forEach((node) => { node.disabled = busy || !state.selected; });
    byId("review-note").disabled = busy || !state.selected;
    byId("decision-reason").disabled = busy || !state.selected;
    updateNavigation();
  }
  async function selectCandidate(candidate, {force = false, autoplay = false} = {}) {
    if (state.loading) return;
    if (!force && state.dirty && !window.confirm("有尚未保存的判断，切换将丢弃这些输入。继续切换？")) return;
    const sequence = ++state.sequence;
    state.selected = candidate;
    state.latest = null;
    state.dirty = false;
    setControls();
    byId("review-note").value = "";
    byId("decision-reason").value = "";
    byId("clip-title").textContent = candidate.candidate_id;
    byId("clip-meta").textContent = `${candidate.source_id} · ${candidate.source_type === "virtual" ? "虚拟" : "真实"} · 批次 ${candidate.generation_batch_id || "未记录"} · SHA256 ${candidate.clip_sha256}`;
    const w = candidate.window;
    byId("timeline-info").textContent = `窗口 ${w.window_role || "未记录"} · 源帧 [${w.start_frame ?? "?"}, ${w.end_frame ?? "?"}) · 源时间 ${w.source_start_pts ?? w.start_time ?? "?"}–${w.source_end_pts ?? w.end_time ?? "?"} 秒 · 时长 ${w.duration ?? "?"} 秒\n帧映射：${JSON.stringify(candidate.frame_mapping)}`;
    renderReference(candidate.source_reference);
    byId("review-status").textContent = "正在读取人工修订…";
    const video = byId("video-player");
    video.pause();
    setVideoState("loading");
    video.src = `/media?candidate_id=${encodeURIComponent(candidate.candidate_id)}`;
    video.load();
    setBusy(true);
    renderList();
    try {
      const review = await request(`/api/reviews?candidate_id=${encodeURIComponent(candidate.candidate_id)}`);
      if (sequence !== state.sequence) return;
      state.latest = review.latest;
      if (review.latest) {
        setControls(review.latest.labels);
        byId("review-note").value = review.latest.note || "";
        byId("decision-reason").value = review.latest.reason || "";
      }
      byId("review-status").textContent = statusNames[review.latest?.review_status || "unreviewed"];
      renderHistory(review);
      message(review.isolated_history.length ? `发现 ${review.isolated_history.length} 条其他身份的旧修订，已隔离且未继承。` : "依据当前片段逐项填写；源标签只作参考。", Boolean(review.isolated_history.length));
      if (autoplay) video.play().catch(() => message("浏览器暂停了自动播放，请点击播放器继续。"));
    } catch (error) {
      message(error.message, true);
    } finally {
      setBusy(false);
    }
  }
  async function move(offset, autoplay = false) {
    const candidates = filtered();
    const index = candidates.findIndex((c) => c.candidate_id === state.selected?.candidate_id);
    if (index >= 0 && candidates[index + offset]) await selectCandidate(candidates[index + offset], {autoplay});
  }
  async function save(status) {
    if (!state.selected || state.loading) return;
    const labels = labelsFromControls();
    if (status === "confirmed" && names.some((name) => !controls.get(name).value)) {
      message("确认须完成全部 11 项；无法确定或无法判断可明确选择。留空请保存草稿或疑问。", true);
      return;
    }
    const reason = byId("decision-reason").value;
    if (["returned", "question"].includes(status) && !reason.trim()) {
      message("请填写退回或疑问原因。", true);
      byId("decision-reason").focus();
      return;
    }
    setBusy(true);
    try {
      const row = await request("/api/reviews", {
        method: "POST", headers: {"Content-Type": "application/json", "X-Review-Token": state.data.token},
        body: JSON.stringify({candidate_id: state.selected.candidate_id, manifest_sha256: state.data.manifest_sha256,
          clip_sha256: state.selected.clip_sha256, expected_review_id: state.latest?.review_id || null,
          review_status: status, labels, reason, note: byId("review-note").value})
      });
      state.latest = row;
      state.selected.review_status = row.review_status;
      state.selected.review_id = row.review_id;
      state.dirty = false;
      byId("review-status").textContent = statusNames[row.review_status];
      renderHistory(await request(`/api/reviews?candidate_id=${encodeURIComponent(state.selected.candidate_id)}`));
      renderList();
      message(`已保存${statusNames[row.review_status]}；新修订 ${row.review_id}。这不是数据发布。`);
    } catch (error) {
      message(error.message, true);
    } finally {
      setBusy(false);
    }
  }
  async function start() {
    const required = ["source-filter", "status-filter", "candidate-search", "candidate-list", "pending-sources", "pending-list", "video-player", "clip-title", "clip-meta", "timeline-info", "source-reference", "label-fields", "review-note", "decision-reason", "save-draft", "confirm-review", "return-review", "question-review", "previous-candidate", "next-candidate", "review-status", "app-message", "revision-history"];
    const missing = required.filter((id) => !byId(id));
    names.forEach((name) => {
      const node = [...document.querySelectorAll("#label-fields select[name]")].find((item) => item.name === name);
      if (node) controls.set(name, node); else missing.push(`select[name="${name}"]`);
    });
    if (missing.length) throw new Error(`页面缺少必要控件：${missing.join("、")}`);
    state.data = await request("/api/bootstrap");
    renderFilters();
    renderPending();
    renderList();
    ["source-filter", "status-filter"].forEach((id) => byId(id).addEventListener("change", renderList));
    byId("candidate-search").addEventListener("input", renderList);
    ["save-draft", "confirm-review", "return-review", "question-review"].forEach((id, index) => byId(id).addEventListener("click", () => save(["draft", "confirmed", "returned", "question"][index])));
    byId("previous-candidate").addEventListener("click", () => move(-1));
    byId("next-candidate").addEventListener("click", () => move(1, true));
    controls.forEach((node) => node.addEventListener("change", () => { state.dirty = true; }));
    ["review-note", "decision-reason"].forEach((id) => byId(id).addEventListener("input", () => { state.dirty = true; }));
    byId("video-player").addEventListener("ended", () => {
      if (!state.selected) message("源原视频播放结束；可重播或从列表选择候选。" );
      else message(state.dirty ? "当前片段播放结束，输入尚未保存。请保存或明确切换；可重播核对。" : "当前片段播放结束。请填写并确认、记录疑问或退回；可重播核对，或主动选择下一候选。" );
    });
    byId("video-player").addEventListener("error", () => { setVideoState("error"); message("媒体无法播放；请核对原工作区路径及片段身份。不会自动生成或修复媒体。", true); });
    window.addEventListener("beforeunload", (event) => { if (state.dirty) { event.preventDefault(); event.returnValue = ""; } });
    const exportButton = byId("export-reviews");
    if (exportButton && exportButton.tagName !== "A") exportButton.addEventListener("click", () => { window.location.href = "/api/export"; });
    byId("video-player").addEventListener("loadeddata", () => setVideoState("loaded"));
    if (state.data.candidates.length) await selectCandidate(state.data.candidates[0]);
    else { setBusy(false); message("清单没有可审核候选；可查看待处理来源。" ); }
  }
  document.addEventListener("DOMContentLoaded", () => start().catch((error) => {
    const node = byId("app-message");
    if (node) message(error.message, true);
    else document.body.textContent = error.message;
  }));
})();
