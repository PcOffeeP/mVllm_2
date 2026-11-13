/* Human-only decisions. Source references never populate the label controls. */
"use strict";
(() => {
  const byId = (id) => document.getElementById(id);
  const names = ["断裂状态", "断裂模式", "断裂位置", "异常情况.未夹紧", "异常情况.视频异常", "异常情况.爆炸性断裂", "断裂现象.伸长", "断裂现象.颈缩", "断裂现象.开裂", "断裂现象.界面分离", "断裂现象.断后脱夹"];
  const statusNames = {unreviewed: "未审核", draft: "草稿", confirmed: "已确认", returned: "已退回", question: "有疑问"};
  const state = {data: null, selected: null, latest: null, dirty: false, loading: false, sequence: 0, activeScope: "", exporting: false};
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
    const scope = byId("scope-filter").value;
    const source = byId("source-filter").value;
    const fold = byId("fold-filter").value;
    const [foldId, foldPartition] = (fold || "all").split(":");
    const status = byId("status-filter").value;
    const attention = byId("attention-filter").value;
    const search = byId("candidate-search").value.trim().toLowerCase();
    return state.data.candidates.filter((c) =>
      (!scope || scope === "all" || scope === c.scope) &&
      (!fold || fold === "all" || (c.scope === "development" && c.folds?.[foldId] === foldPartition)) &&
      (!attention || attention === "all" || (attention === "attention" && c.audit_issues?.length)) &&
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
  function renderReference(reference, candidateReference = {}) {
    const aside = byId("source-reference");
    let content = aside.querySelector(".reference-empty");
    if (!content) { content = document.createElement("div"); content.className = "reference-empty"; aside.append(content); }
    content.replaceChildren();
    const appendReference = (title, values) => {
      const heading = document.createElement("strong");
      heading.textContent = title;
      content.append(heading);
      if (!values || !Object.keys(values).length) { const empty = document.createElement("p"); empty.textContent = "未记录"; content.append(empty); return; }
      const list = document.createElement("dl");
      Object.entries(values).forEach(([key, value]) => {
        if (value === "" || value === null || value === undefined) return;
        const term = document.createElement("dt");
        const detail = document.createElement("dd");
        term.textContent = key;
        detail.textContent = typeof value === "object" ? JSON.stringify(value) : String(value);
        list.append(term, detail);
      });
      content.append(list);
    };
    appendReference("源视频标注", reference);
    if (candidateReference && Object.keys(candidateReference).length) appendReference("候选标签初值", candidateReference);
  }
  function previewSource(source) {
    if (state.loading) return;
    if (state.dirty && !window.confirm("有尚未保存的判断，查看原视频将丢弃这些输入。继续？")) return;
    state.selected = null;
    state.latest = null;
    state.dirty = false;
    byId("view-source").disabled = true;
    setControls();
    byId("review-note").value = "";
    byId("decision-reason").value = "";
    byId("clip-title").textContent = `原视频 · ${source.source_id}`;
    byId("clip-meta").textContent = source.status === "pending" || source.status === "held" ? `待处理来源 · ${source.reason || "原因未记录"}` : "来源画面复看";
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
    message("仅查看当前来源。源标注显示为参考，不会写入候选审核。" );
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
    byId("scope-filter").disabled = busy;
    byId("fold-filter").disabled = busy;
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
    byId("clip-meta").textContent = `${candidate.source_id} · ${candidate.scope === "test" ? "测试集" : "开发集"} · ${candidate.source_type === "virtual" ? "虚拟" : "真实"} · 三折 ${JSON.stringify(candidate.folds)} · SHA256 ${candidate.clip_sha256}`;
    const w = candidate.window;
    byId("timeline-info").textContent = `窗口 ${w.window_role || "未记录"} · 源帧 [${w.start_frame ?? "?"}, ${w.end_frame ?? "?"}) · 源时间 ${w.source_start_pts ?? w.start_time ?? "?"}–${w.source_end_pts ?? w.end_time ?? "?"} 秒 · 时长 ${w.duration ?? "?"} 秒\n帧映射：${JSON.stringify(candidate.frame_mapping)}\n生成时建议关注：${candidate.review_focus?.length ? candidate.review_focus.join("、") : "无指定重点"}${candidate.audit_issues?.length ? `\n标签组合待复核：${candidate.audit_issues.join("；")}` : ""}`;
    byId("view-source").disabled = !candidate.source_preview_available;
    renderReference(candidate.source_reference, candidate.candidate_reference);
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
  async function changeScope() {
    const scope = byId("scope-filter");
    if (state.dirty && !window.confirm("有尚未保存的判断，切换数据划分将丢弃这些输入。继续？")) {
      scope.value = state.activeScope;
      return;
    }
    state.activeScope = scope.value;
    byId("source-filter").value = "";
    renderList();
    const candidates = filtered();
    if (candidates.length) {
      await selectCandidate(candidates[0], {force: true});
      return;
    }
    ++state.sequence;
    state.selected = state.latest = null;
    state.dirty = false;
    setControls();
    byId("review-note").value = "";
    byId("decision-reason").value = "";
    byId("view-source").disabled = true;
    byId("video-player").pause();
    byId("video-player").removeAttribute("src");
    byId("video-player").load();
    byId("clip-title").textContent = "当前划分没有符合筛选条件的候选";
    byId("clip-meta").textContent = "请调整筛选条件。";
    byId("review-status").textContent = "未选择候选";
    setBusy(false);
    renderList();
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
  async function exportReviews(allRevisions) {
    if (state.exporting) return;
    const filename = allRevisions ? "subvideo-reviews-history.jsonl" : "subvideo-reviews.jsonl";
    state.exporting = true;
    byId("export-reviews").disabled = true;
    byId("export-all-revisions").disabled = true;
    try {
      const response = await fetch(allRevisions ? "/api/export?all_revisions=1" : "/api/export", {cache: "no-store"});
      if (!response.ok) {
        let detail = "";
        try {
          const value = await response.json();
          detail = typeof value?.error === "string" ? value.error : typeof value?.message === "string" ? value.message : "";
        } catch {}
        detail = typeof detail === "string" ? detail.trim().replace(/[。！？；.!?;]+$/u, "") : "";
        throw new Error(`导出失败 (${response.status})${detail ? `：${detail}` : ""}；未生成 ${filename}，审核记录未改动。`);
      }
      const href = URL.createObjectURL(await response.blob());
      try {
        const link = document.createElement("a");
        link.href = href;
        link.download = filename;
        document.body.append(link);
        try {
          link.click();
        } finally {
          link.remove();
        }
      } finally {
        setTimeout(() => URL.revokeObjectURL(href), 0);
      }
      message(`已导出${allRevisions ? "全部修订" : "最新修订"}到 ${filename}；这不是数据发布。`);
    } catch (error) {
      message(error && typeof error.message === "string" && error.message ? error.message : `导出失败：未知错误；未生成 ${filename}，审核记录未改动。`, true);
    } finally {
      state.exporting = false;
      byId("export-reviews").disabled = false;
      byId("export-all-revisions").disabled = false;
    }
  }
  async function start() {
    const required = ["scope-filter", "fold-filter", "source-filter", "status-filter", "attention-filter", "audit-info", "candidate-search", "candidate-list", "pending-sources", "pending-list", "video-player", "clip-title", "clip-meta", "timeline-info", "source-reference", "view-source", "label-fields", "review-note", "decision-reason", "save-draft", "confirm-review", "return-review", "question-review", "previous-candidate", "next-candidate", "review-status", "app-message", "revision-history", "export-reviews", "export-all-revisions"];
    const missing = required.filter((id) => !byId(id));
    names.forEach((name) => {
      const node = [...document.querySelectorAll("#label-fields select[name]")].find((item) => item.name === name);
      if (node) controls.set(name, node); else missing.push(`select[name="${name}"]`);
    });
    if (missing.length) throw new Error(`页面缺少必要控件：${missing.join("、")}`);
    state.data = await request("/api/bootstrap");
    state.activeScope = byId("scope-filter").value;
    byId("attention-filter").disabled = !state.data.audit_current;
    byId("audit-info").textContent = state.data.audit_message || (state.data.audit_current ? "标签组合检查提示已载入；技术核验不替代人工审核。" : "标签组合检查尚未匹配当前清单；不能据此判断没有待复核问题。");
    renderFilters();
    renderPending();
    renderList();
    byId("scope-filter").addEventListener("change", changeScope);
    ["fold-filter", "source-filter", "status-filter", "attention-filter"].forEach((id) => byId(id).addEventListener("change", renderList));
    byId("candidate-search").addEventListener("input", renderList);
    ["save-draft", "confirm-review", "return-review", "question-review"].forEach((id, index) => byId(id).addEventListener("click", () => save(["draft", "confirmed", "returned", "question"][index])));
    byId("previous-candidate").addEventListener("click", () => move(-1));
    byId("next-candidate").addEventListener("click", () => move(1, true));
    byId("view-source").addEventListener("click", () => {
      if (state.selected?.source_preview_available) previewSource({source_id: state.selected.source_id, source_reference: state.selected.source_reference});
    });
    controls.forEach((node) => node.addEventListener("change", () => { state.dirty = true; }));
    ["review-note", "decision-reason"].forEach((id) => byId(id).addEventListener("input", () => { state.dirty = true; }));
    byId("video-player").addEventListener("ended", () => {
      if (!state.selected) message("源原视频播放结束；可重播或从列表选择候选。" );
      else message(state.dirty ? "当前片段播放结束，输入尚未保存。请保存或明确切换；可重播核对。" : "当前片段播放结束。请填写并确认、记录疑问或退回；可重播核对，或主动选择下一候选。" );
    });
    byId("video-player").addEventListener("error", () => { setVideoState("error"); message("媒体无法播放；请核对当前工作区路径及片段身份。不会自动生成或修复媒体。", true); });
    window.addEventListener("beforeunload", (event) => { if (state.dirty) { event.preventDefault(); event.returnValue = ""; } });
    byId("export-reviews").addEventListener("click", () => exportReviews(false));
    byId("export-all-revisions").addEventListener("click", () => exportReviews(true));
    byId("video-player").addEventListener("loadeddata", () => setVideoState("loaded"));
    if (filtered().length) await selectCandidate(filtered()[0]);
    else { setBusy(false); message("清单没有可审核候选；可查看待处理来源。" ); }
  }
  document.addEventListener("DOMContentLoaded", () => start().catch((error) => {
    const node = byId("app-message");
    if (node) message(error.message, true);
    else document.body.textContent = error.message;
  }));
})();
