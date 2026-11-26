/* Human-only decisions. Source labels remain references; candidate labels prefill drafts only. */
"use strict";
(() => {
  const byId = (id) => document.getElementById(id);
  const names = ["断裂状态", "断裂模式", "断裂位置", "异常情况.未夹紧", "异常情况.视频异常", "异常情况.爆炸性断裂", "断裂现象.伸长", "断裂现象.颈缩", "断裂现象.开裂", "断裂现象.界面分离", "断裂现象.断后脱夹"];
  const statusNames = {unreviewed: "未审核", draft: "草稿", confirmed: "已确认", returned: "已退回", question: "有疑问"};
  const state = {data: null, selected: null, latest: null, dirty: false, loading: false, sequence: 0, activeScope: "", exporting: false, lastSaveAt: 0};
  const batchMembers = new Map();
  let activeBatch = "";
  const controls = new Map();
  /* 历史标注/旧清单里的旧词只在显示层统一为「无法判断」；已存记录与源标注字节均不改写。 */
  const legacyUncertain = new Map([["无法确定", "无法判断"], ["无法识别", "无法判断"]]);
  const unifiedTerm = (value) => {
    if (typeof value !== "string") return value;
    const term = value.trim();
    return legacyUncertain.get(term) || value;
  };
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
    if (error && typeof node.scrollIntoView === "function") node.scrollIntoView({block: "nearest"});
  };
  async function request(path, options) {
    const response = await fetch(path, {cache: "no-store", ...options});
    const value = await response.json();
    if (!response.ok) throw new Error(value.error || `请求失败 (${response.status})`);
    return value;
  }
  function queryFlag(name) {
    const raw = typeof window.location?.search === "string" && window.location.search
      ? window.location.search
      : (typeof window.location?.href === "string" && window.location.href.includes("?")
        ? window.location.href.slice(window.location.href.indexOf("?")).split("#")[0]
        : "");
    const pairs = raw.replace(/^\?/, "").split("&").filter(Boolean);
    for (const pair of pairs) {
      const eq = pair.indexOf("=");
      let key, value;
      try {
        key = decodeURIComponent(eq >= 0 ? pair.slice(0, eq) : pair);
        value = decodeURIComponent(eq >= 0 ? pair.slice(eq + 1) : "").trim().toLowerCase();
      } catch {
        continue;
      }
      if (key !== name) continue;
      return value === "1" || value === "true" || value === "yes";
    }
    return false;
  }
  function renderDec007Banner(candidate) {
    const banner = byId("dec007-banner");
    if (!banner) return;
    if (!candidate?.dec007_excluded) {
      banner.hidden = true;
      banner.textContent = "";
      return;
    }
    const reasonText = candidate.dec007_reason === "near_duplicate_of_test_source"
      ? "与测试集来源近重复"
      : (candidate.dec007_reason || "DEC-007 排除开发源");
    const matched = candidate.dec007_matched_test_source_id
      ? `（对应测试源 ${candidate.dec007_matched_test_source_id}）`
      : "";
    banner.hidden = false;
    banner.textContent = `DEC-007 排除源提示：来源 ${candidate.source_id} 已按 DEC-007 排除（${reasonText}${matched}），无需人工审核，不进入训练或评测子集；本提示不阻塞查看。`;
  }
  function filtered() {
    const scope = byId("scope-filter").value;
    const source = byId("source-filter").value;
    const fold = byId("fold-filter").value;
    const [foldId, foldPartition] = (fold || "all").split(":");
    const status = byId("status-filter").value;
    const attention = byId("attention-filter").value;
    const hideExcluded = Boolean(byId("hide-excluded-filter")?.checked);
    const search = byId("candidate-search").value.trim().toLowerCase();
    return state.data.candidates.filter((c) =>
      (!activeBatch || batchMembers.get(activeBatch).has(c.candidate_id)) &&
      (!hideExcluded || !c.dec007_excluded) &&
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
    return option;
  }
  async function loadBatches() {
    const select = byId("batch-filter");
    if (!select) return;
    select.replaceChildren();
    addOption(select, "", "不按批次筛选");
    try {
      const catalog = await request("/api/batches");
      for (const batch of catalog.batches) {
        const excludedSuffix = batch.selectable && batch.excluded_candidate_count > 0
          ? `（有效待审 ${batch.clean_unreviewed_count}，DEC-007 排除 ${batch.excluded_candidate_count}）`
          : "";
        const suffix = batch.selectable ? excludedSuffix : `（待定，三折池 ${Object.values(batch.fold_pool_counts).join("/")}）`;
        const option = addOption(select, batch.batch_id, `${batch.batch_id} · ${batch.name}${suffix}`);
        option.disabled = !batch.selectable;
        if (batch.selectable) batchMembers.set(batch.batch_id, new Set(batch.candidate_ids));
      }
    } catch (error) {
      message(`批次加载失败：${error.message}。仍可按原方式审核。`, true);
      return;
    }
    select.addEventListener("change", async () => {
      if (state.dirty && !window.confirm("有尚未保存的判断，切换批次将丢弃这些输入。继续？")) {
        select.value = activeBatch;
        return;
      }
      activeBatch = select.value;
      byId("scope-filter").value = state.activeScope = "all";
      byId("fold-filter").value = "all";
      await selectFirstFiltered();
    });
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
      if (candidate.review_status === "confirmed") button.classList.add("is-confirmed");
      if (candidate.dec007_excluded) button.classList.add("is-dec007-excluded");
      const title = document.createElement("span");
      title.className = "candidate-item__title";
      title.textContent = candidate.candidate_id;
      const meta = document.createElement("span");
      meta.className = "candidate-item__meta";
      const status = statusNames[candidate.review_status] || candidate.review_status;
      meta.textContent = `来源 ${candidate.source_id} · ${status}${candidate.dec007_excluded ? " · DEC-007 排除" : ""}`;
      const badge = document.createElement("span");
      badge.className = "candidate-item__status";
      badge.textContent = status;
      button.append(title, meta, badge);
      if (candidate.dec007_excluded) {
        const excludedBadge = document.createElement("span");
        excludedBadge.className = "candidate-item__excluded";
        excludedBadge.textContent = "DEC-007 排除";
        button.append(excludedBadge);
      }
      if (candidate.candidate_id === state.selected?.candidate_id && typeof button.scrollIntoView === "function") button.scrollIntoView({block: "nearest"});
      button.addEventListener("click", () => selectCandidate(candidate));
      list.append(button);
    });
    if (!candidates.length) {
      const empty = document.createElement("p");
      empty.textContent = "当前筛选没有候选。";
      list.append(empty);
    }
    const summary = byId("batch-summary");
    if (summary) {
      summary.hidden = !activeBatch;
      if (activeBatch) {
        const ids = batchMembers.get(activeBatch);
        const batchItems = state.data.candidates.filter((c) => ids.has(c.candidate_id));
        const confirmed = batchItems.filter((c) => c.review_status === "confirmed").length;
        const excludedItems = batchItems.filter((c) => c.dec007_excluded);
        if (excludedItems.length > 0) {
          const cleanUnreviewed = batchItems.filter((c) => !c.dec007_excluded && c.review_status === "unreviewed").length;
          const excludedUnreviewed = excludedItems.filter((c) => c.review_status === "unreviewed").length;
          summary.textContent = `本批已审 ${confirmed} / 共 ${ids.size} · 有效待审 ${cleanUnreviewed} / DEC-007 排除待审 ${excludedUnreviewed}（共排除 ${excludedItems.length}）`;
        } else {
          summary.textContent = `本批已审 ${confirmed} / 共 ${ids.size}`;
        }
      }
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
  const sourceKeys = {
    "断裂状态": "断裂状态", "断裂模式": "断裂模式", "断裂位置": "断裂位置",
    "异常情况.未夹紧": "异常_未夹紧", "异常情况.视频异常": "异常_视频异常", "异常情况.爆炸性断裂": "异常_爆炸性断裂",
    "断裂现象.伸长": "现象_伸长", "断裂现象.颈缩": "现象_颈缩", "断裂现象.开裂": "现象_开裂", "断裂现象.界面分离": "现象_界面分离", "断裂现象.断后脱夹": "现象_断后脱夹"
  };
  const extraKeys = ["id", "video_path", "断裂时间点", "材料类型", "清晰度", "断裂帧数", "视频时长", "视频帧率", "视频总帧数", "has_fracture", "is_abnormal", "标注状态", "断裂帧_前", "断裂帧_后", "标注备注", "断裂时间范围_下界", "断裂时间范围_上界"];
  function renderReference(reference = {}) {
    reference = reference || {};
    const hints = new Map([...document.querySelectorAll("[data-source-hint]")].map((node) => [node.dataset.sourceHint, node]));
    Object.entries(sourceKeys).forEach(([name, key]) => {
      const value = reference[key];
      const mapped = unifiedTerm(value);
      const text = value == null || value === "" ? "未标注" : mapped === value ? String(value) : `${mapped}（原值：${value}）`;
      if (hints.has(name)) hints.get(name).textContent = `源视频：${text}`;
    });
    const content = byId("source-extras-body");
    content.replaceChildren();
    const list = document.createElement("dl");
    extraKeys.forEach((key) => {
      const term = document.createElement("dt"), detail = document.createElement("dd");
      term.textContent = key;
      const value = reference[key];
      detail.textContent = value == null || value === "" ? "未记录" : typeof value === "object" ? JSON.stringify(value) : String(value);
      list.append(term, detail);
    });
    content.append(list);
  }
  function renderTimeline(candidate = {}) {
    const w = candidate.window || {};
    const range = (start, end) => start == null && end == null ? "未记录" : `${start ?? "未记录"} – ${end ?? "未记录"}`;
    const rows = [["窗口角色", w.window_role || "未记录"], ["源帧区间", range(w.start_frame, w.end_frame)], ["源时间", range(w.source_start_pts ?? w.start_time, w.source_end_pts ?? w.end_time)], ["时长", w.duration ?? "未记录"], ["生成时建议关注", candidate.review_focus?.length ? candidate.review_focus.join("、") : "未记录"], ["标签组合待复核", candidate.audit_issues?.length ? candidate.audit_issues.join("；") : "未记录"]];
    const list = byId("timeline-list");
    list.replaceChildren();
    rows.forEach(([label, value]) => { const dt = document.createElement("dt"), dd = document.createElement("dd"); dt.textContent = label; dd.textContent = String(value); list.append(dt, dd); });
    if (candidate.frame_mapping && Object.keys(candidate.frame_mapping).length) {
      const details = document.createElement("details"), summary = document.createElement("summary"), content = document.createElement("pre");
      summary.textContent = "帧映射";
      content.textContent = JSON.stringify(candidate.frame_mapping, null, 2);
      details.append(summary, content);
      list.append(details);
    }
  }
  const fps = () => { const value = state.selected?.output?.media?.fps; return Number.isFinite(value) && value > 0 ? value : null; };
  function resetProgress() {
    const video = byId("video-player");
    video.currentTime = 0;
    byId("clip-progress").value = "0";
    byId("clip-time").textContent = "0.00s / 0.00s";
    ["step-back", "step-forward"].forEach((id) => { byId(id).title = fps() ? "按素材帧率逐帧步进" : "无帧率信息，按 1/30 秒步进"; });
  }
  function syncProgress() {
    const video = byId("video-player"), duration = video.duration;
    if (!Number.isFinite(duration) || duration <= 0) { byId("clip-progress").value = "0"; byId("clip-time").textContent = "0.00s / 0.00s"; return; }
    const time = Number.isFinite(video.currentTime) ? video.currentTime : 0;
    byId("clip-progress").value = String(Math.round(time / duration * 1000));
    const rate = fps();
    byId("clip-time").textContent = `${time.toFixed(2)}s / ${duration.toFixed(2)}s` + (rate ? ` · 帧 ${Math.round(time * rate)} / ${Math.round(duration * rate)}` : "");
  }
  function previewSource(source) {
    if (state.loading) return;
    if (state.dirty && !window.confirm("有尚未保存的判断，查看原视频将丢弃这些输入。继续？")) return;
    state.selected = null;
    state.latest = null;
    state.dirty = false;
    byId("view-source").disabled = true;
    setControls();
    renderDec007Banner(state.data?.candidates?.find((c) => c.source_id === source.source_id && c.dec007_excluded) || null);
    byId("prefill-notice").hidden = true;
    byId("review-note").value = "";
    byId("decision-reason").value = "";
    byId("clip-title").textContent = `原视频 · ${source.source_id}`;
    byId("clip-meta").textContent = source.status === "pending" || source.status === "held" ? `待处理来源 · ${source.reason || "原因未记录"}` : "来源画面复看";
    renderTimeline();
    byId("clip-sha-value").textContent = "";
    renderReference(source.source_reference);
    byId("review-status").textContent = "原视频只读查看";
    byId("revision-history").textContent = "请从候选列表选择片段后填写审核。";
    const video = byId("video-player");
    video.pause();
    setVideoState("loading");
    video.src = `/source-media?source_id=${encodeURIComponent(source.source_id)}`;
    video.load();
    resetProgress();
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
  const prefillSource = (candidate) => candidate.candidate_reference_display || candidate.candidate_labels || candidate.candidate_reference || {};
  const hasAnyPrefill = (labels) => names.some((name) => {
    const parts = name.split(".");
    const value = parts.length === 1 ? labels[name] : labels[parts[0]]?.[parts[1]];
    return typeof value === "string" && value.trim() !== "";
  });
  function setControls(labels = {}) {
    names.forEach((name) => {
      const parts = name.split(".");
      const value = parts.length === 1 ? labels[name] : labels[parts[0]]?.[parts[1]];
      controls.get(name).value = (value === "无" && (name === "断裂模式" || name === "断裂位置") ? "无法判断" : unifiedTerm(value)) || "";
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
    if (byId("batch-filter")) byId("batch-filter").disabled = busy;
    if (byId("hide-excluded-filter")) byId("hide-excluded-filter").disabled = busy;
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
    const prefill = prefillSource(candidate);
    setControls(prefill);
    renderDec007Banner(candidate);

    byId("prefill-notice").textContent = "已按生成标签预填为草稿；每项下方注明源视频标注，仅供参考。空白表示未判断。" + (candidate.prefill_note ? ` ${candidate.prefill_note}` : "");
    byId("prefill-notice").hidden = !hasAnyPrefill(prefill);
    byId("review-note").value = "";
    byId("decision-reason").value = "";
    byId("clip-title").textContent = candidate.candidate_id;
    const folds = Object.entries(candidate.folds || {}).map(([key, value]) => `第${key}折=${({val: "验证", train: "训练", test: "测试"})[value] || value}`).join(" / ") || "未记录";
    byId("clip-meta").textContent = `来源 ${candidate.source_id} · ${candidate.scope === "test" ? "测试集" : "开发集"} · ${candidate.source_type === "virtual" ? "虚拟来源" : "真实来源"} · 三折：${folds}`;
    byId("clip-sha-value").textContent = candidate.clip_sha256 || "";
    renderTimeline(candidate);
    byId("view-source").disabled = !candidate.source_preview_available;
    renderReference(candidate.source_reference, candidate.candidate_reference_display || candidate.candidate_reference);
    byId("review-status").textContent = "正在读取人工修订…";
    const video = byId("video-player");
    video.pause();
    setVideoState("loading");
    video.src = `/media?candidate_id=${encodeURIComponent(candidate.candidate_id)}`;
    video.load();
    resetProgress();
    setBusy(true);
    renderList();
    let historyFailed = false;
    try {
      const review = await request(`/api/reviews?candidate_id=${encodeURIComponent(candidate.candidate_id)}`);
      if (sequence !== state.sequence) return;
      state.latest = review.latest;
      if (review.latest) {
        setControls(review.latest.labels);
        byId("prefill-notice").hidden = true;
        byId("review-note").value = review.latest.note || "";
        byId("decision-reason").value = review.latest.reason || "";
      }
      byId("review-status").textContent = statusNames[review.latest?.review_status || "unreviewed"];
      renderHistory(review);
      message(review.isolated_history.length ? `发现 ${review.isolated_history.length} 条其他身份的旧修订，已隔离且未继承。` : "依据当前片段逐项填写；源标签只作参考。", Boolean(review.isolated_history.length));
    } catch (error) {
      historyFailed = true;
      message(error.message, true);
    } finally {
      if (autoplay && sequence === state.sequence && state.selected === candidate) video.play().catch(() => message("浏览器暂停了自动播放，请点击播放器继续。"));
      setBusy(false);
    }
    return {historyFailed};
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
    await selectFirstFiltered();
  }
  async function selectFirstFiltered() {
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
    renderDec007Banner(null);
    byId("prefill-notice").hidden = true;
    byId("review-note").value = "";
    byId("decision-reason").value = "";
    byId("view-source").disabled = true;
    byId("video-player").pause();
    byId("video-player").removeAttribute("src");
    byId("video-player").load();
    resetProgress();
    renderTimeline();
    renderReference();
    byId("clip-sha-value").textContent = "";
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
      message("确认须完成全部 11 项；无法判断可明确选择。留空请保存草稿或疑问。", true);
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
      byId("prefill-notice").hidden = true;
      byId("review-status").textContent = statusNames[row.review_status];
      let historyFailed = false;
      try {
        renderHistory(await request(`/api/reviews?candidate_id=${encodeURIComponent(state.selected.candidate_id)}`));
      } catch {
        historyFailed = true;
      }
      renderList();
      state.lastSaveAt = Date.now();
      message(`已保存${statusNames[row.review_status]}；新修订 ${row.review_id}。${historyFailed ? "历史记录未能刷新，可重载页面核对。" : "这不是数据发布。"}`);
      return {historyFailed};
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
    const required = ["scope-filter", "fold-filter", "source-filter", "status-filter", "attention-filter", "audit-info", "candidate-search", "candidate-list", "candidate-count", "pending-sources", "pending-list", "video-player", "clip-title", "clip-meta", "timeline-info", "source-reference", "view-source", "prefill-notice", "label-fields", "review-note", "decision-reason", "save-draft", "confirm-review", "return-review", "question-review", "previous-candidate", "next-candidate", "review-status", "app-message", "revision-history", "export-reviews", "export-all-revisions", "main-content", "toggle-candidates", "candidate-panel-body", "clip-progress", "clip-time", "step-back", "step-forward", "timeline-list", "source-extras-body", "clip-sha", "clip-sha-value"];
    const missing = required.filter((id) => !byId(id));
    names.forEach((name) => {
      const node = [...document.querySelectorAll("#label-fields select[name]")].find((item) => item.name === name);
      if (node) controls.set(name, node); else missing.push(`select[name="${name}"]`);
    });
    if (missing.length) throw new Error(`页面缺少必要控件：${missing.join("、")}`);
    const applyCollapse = (collapsed) => {
      byId("main-content").classList.toggle("is-collapsed", collapsed);
      byId("candidate-panel-body").hidden = collapsed;
      byId("toggle-candidates").setAttribute("aria-expanded", String(!collapsed));
      byId("toggle-candidates").setAttribute("aria-label", collapsed ? "展开候选列表" : "收起候选列表");
      byId("toggle-candidates").textContent = collapsed ? "展开列表" : "收起列表";
    };
    let collapsed = false;
    try { collapsed = window.localStorage.getItem("subvideo-review:collapsed") === "true"; } catch {}
    applyCollapse(collapsed);
    byId("toggle-candidates").addEventListener("click", () => { collapsed = !collapsed; applyCollapse(collapsed); try { window.localStorage.setItem("subvideo-review:collapsed", String(collapsed)); } catch {} });
    const video = byId("video-player");
    ["timeupdate", "seeking", "seeked", "loadedmetadata", "emptied"].forEach((event) => video.addEventListener(event, syncProgress));
    byId("clip-progress").addEventListener("input", () => { if (Number.isFinite(video.duration)) video.currentTime = video.duration ? Number(byId("clip-progress").value) / 1000 * video.duration : 0; });
    [["step-back", -1], ["step-forward", 1]].forEach(([id, direction]) => byId(id).addEventListener("click", () => {
      if (Number.isFinite(video.duration) && video.duration >= 0) {
        const base = Number.isFinite(video.currentTime) ? video.currentTime : 0;
        video.currentTime = Math.max(0, Math.min(video.duration, base + direction / (fps() || 30)));
      }
    }));
    state.data = await request("/api/bootstrap");
    state.activeScope = byId("scope-filter").value;
    byId("attention-filter").disabled = !state.data.audit_current;
    byId("audit-info").textContent = state.data.audit_message || (state.data.audit_current ? "标签组合检查提示已载入；技术核验不替代人工审核。" : "标签组合检查尚未匹配当前清单；不能据此判断没有待复核问题。");
    renderFilters();
    renderPending();
    const hideExcluded = byId("hide-excluded-filter");
    if (hideExcluded) {
      hideExcluded.checked = queryFlag("hide_excluded");
      hideExcluded.addEventListener("change", async () => {
        renderList();
        const visible = filtered();
        if (state.selected && !visible.some((c) => c.candidate_id === state.selected.candidate_id) && !state.dirty) {
          await selectFirstFiltered();
        } else if (!state.selected && visible.length) {
          await selectFirstFiltered();
        }
      });
    }
    renderList();
    byId("scope-filter").addEventListener("change", changeScope);
    ["fold-filter", "source-filter", "status-filter", "attention-filter"].forEach((id) => byId(id).addEventListener("change", renderList));
    byId("candidate-search").addEventListener("input", renderList);
    ["save-draft", "return-review", "question-review"].forEach((id, index) => byId(id).addEventListener("click", () => save(["draft", "returned", "question"][index])));
    byId("confirm-review").addEventListener("click", async () => {
      const candidates = filtered();
      const index = candidates.findIndex((candidate) => candidate.candidate_id === state.selected?.candidate_id);
      const next = index >= 0 ? candidates[index + 1] : null;
      const result = await save("confirmed");
      if (!result) return;
      const selection = next ? await selectCandidate(next, {force: true, autoplay: true}) : null;
      const warning = result.historyFailed || selection?.historyFailed ? "历史记录未能刷新，可重载页面核对。" : "";
      if (next) message(`已保存已确认；已进入下一个候选。${warning}`);
      else message(`已保存已确认；已是当前筛选的最后一个候选；可切换筛选继续。${warning}`);
    });
    byId("previous-candidate").addEventListener("click", () => move(-1));
    byId("next-candidate").addEventListener("click", () => move(1, true));
    byId("view-source").addEventListener("click", () => {
      if (state.selected?.source_preview_available) previewSource({source_id: state.selected.source_id, source_reference: state.selected.source_reference});
    });
    controls.forEach((node) => node.addEventListener("change", () => { state.dirty = true; }));
    ["review-note", "decision-reason"].forEach((id) => byId(id).addEventListener("input", () => { state.dirty = true; }));
    byId("video-player").addEventListener("ended", () => {
      if (Date.now() - state.lastSaveAt < 3000) return;
      if (!state.selected) message("源原视频播放结束；可重播或从列表选择候选。" );
      else message(state.dirty ? "当前片段播放结束，输入尚未保存。请保存或明确切换；可重播核对。" : "片段播放结束。核对后点『确认完成，进入下一个』，或保存草稿／记录疑问。" );
    });
    byId("video-player").addEventListener("error", () => { setVideoState("error"); message("媒体无法播放；请核对当前工作区路径及片段身份。不会自动生成或修复媒体。", true); });
    window.addEventListener("beforeunload", (event) => { if (state.dirty) { event.preventDefault(); event.returnValue = ""; } });
    byId("export-reviews").addEventListener("click", () => exportReviews(false));
    byId("export-all-revisions").addEventListener("click", () => exportReviews(true));
    byId("video-player").addEventListener("loadeddata", () => setVideoState("loaded"));
    if (filtered().length) await selectCandidate(filtered()[0]);
    else { setBusy(false); message("清单没有可审核候选；可查看待处理来源。" ); }
    await loadBatches();
  }
  document.addEventListener("DOMContentLoaded", () => start().catch((error) => {
    const node = byId("app-message");
    if (node) message(error.message, true);
    else document.body.textContent = error.message;
  }));
})();
