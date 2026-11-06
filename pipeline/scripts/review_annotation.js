(() => {
  "use strict";

  const byId = (id) => document.getElementById(id);
  const csvInput = byId("csv-file");
  const openCsv = byId("open-csv");
  const reconnectCsv = byId("csv-reconnect");
  const videoInput = byId("video-files");
  const player = byId("video-player");
  const csvStatus = byId("file-status");
  const videoStatus = byId("video-status");
  const saveStatus = byId("save-status");
  const saveStatusFooter = byId("save-status-footer");
  const ruleHint = byId("rule-hint");
  const applyRuleButton = byId("apply-rule");
  const previous = byId("prev");
  const next = byId("next");
  const jump = byId("row-jump");
  const jumpButton = byId("jump-btn");
  const exportButton = byId("export-csv");
  const frameImage = byId("frame-image");
  const framePreview = byId("frame-preview");
  const frameStatus = byId("frame-status");
  const framePlay = byId("frame-play");
  const framePrevious = byId("frame-prev");
  const frameNext = byId("frame-next");
  const frameIndex = byId("frame-index");
  const frameGo = byId("frame-go");
  const frameBefore = byId("frame-use-before");
  const frameAfter = byId("frame-use-after");
  const frameBeforeField = byId("frame-before");
  const frameAfterField = byId("frame-after");
  const originalFields = byId("original-fields");
  const sessionToken = location.protocol === "http:" && location.hostname === "127.0.0.1"
    && /^[a-f0-9]{64}$/.test(location.hash.slice(1)) ? location.hash.slice(1) : "";

  const stateColumn = "断裂状态";
  const gripColumn = "异常_未夹紧";
  const mechanismColumn = "断裂模式";
  const siteColumn = "断裂位置";
  const timeColumn = "断裂时间点";
  const frameColumns = ["断裂帧_前", "断裂帧_后"];
  const fractureColumns = [mechanismColumn, siteColumn];
  const gripColumns = [...fractureColumns, timeColumn];
  const wholeVideoColumns = [...fractureColumns, ...frameColumns];
  const wholeVideoGripColumns = [...gripColumns, ...frameColumns];
  const multiFields = [...document.querySelectorAll('select[name="anomaly"], select[name="phenomenon"]')]
    .map((control) => {
      const prefix = control.name === "anomaly" ? "异常" : "现象";
      return [control, prefix + "_" + control.dataset.label];
    });
  const fields = new Map([
    [byId("state"), stateColumn],
    [byId("mechanism"), mechanismColumn],
    [byId("site"), siteColumn],
    [byId("time"), timeColumn],
    [frameBeforeField, frameColumns[0]],
    [frameAfterField, frameColumns[1]],
    [byId("annotation-status"), "标注状态"],
    [byId("annotation-note"), "标注备注"],
    ...multiFields,
  ]);
  const newColumns = [stateColumn, ...multiFields.map(([, name]) => name)];
  const displayedColumns = new Set(["id", "video_path", ...fields.values()]);
  const stateOptions = new Set([...byId("state").options].map((option) => option.value).filter(Boolean));

  let table = null;
  let rowIndex = 0;
  let draft = null;
  let journal = null;
  let editorReady = false;
  let openingCsv = false;
  let reconnecting = false;
  let saveTimer = null;
  let saving = null;
  let videos = [];
  let videoUrl = "";
  let playingFile = null;
  let frameSession = null;

  function parseCsv(text) {
    if (text.startsWith("\uFEFF")) text = text.slice(1);
    if (!text) throw new Error("文件为空。");

    const records = [];
    let record = [];
    let field = "";
    let mode = "unquoted";
    let endedRecord = false;
    for (let i = 0; i < text.length; i += 1) {
      const char = text[i];
      endedRecord = false;

      if (mode === "quoted") {
        if (char === '"' && text[i + 1] === '"') {
          field += '"';
          i += 1;
        } else if (char === '"') {
          mode = "afterQuote";
        } else {
          field += char;
        }
        continue;
      }
      if (char === "," || char === "\r" || char === "\n") {
        record.push(field);
        field = "";
        mode = "unquoted";
        if (char !== ",") {
          records.push(record);
          record = [];
          endedRecord = true;
          if (char === "\r" && text[i + 1] === "\n") i += 1;
        }
      } else if (char === '"' && mode === "unquoted" && field === "") {
        mode = "quoted";
      } else if (char === '"' || mode === "afterQuote") {
        throw new Error(`CSV 第 ${records.length + 1} 行的引号格式无效。`);
      } else {
        field += char;
      }
    }
    if (mode === "quoted") throw new Error(`CSV 第 ${records.length + 1} 行的引号未闭合。`);
    if (!endedRecord) records.push([...record, field]);

    const [headers, ...rows] = records;
    if (headers.some((name) => !name.trim())) throw new Error("CSV 包含空列名。");
    if (new Set(headers).size !== headers.length) throw new Error("CSV 包含重复列名。");
    const idIndex = headers.indexOf("id");
    if (idIndex === -1) throw new Error("CSV 缺少 id 列。");
    const missing = gripColumns.filter((name) => !headers.includes(name));
    if (missing.length) throw new Error("CSV 缺少固定组合所需的列 · " + missing.join("、"));
    for (const [i, row] of rows.entries()) {
      if (row.length !== headers.length) throw new Error(`CSV 第 ${i + 2} 行的列数与表头不符。`);
      if (!row[idIndex].trim()) throw new Error(`CSV 第 ${i + 2} 行的 id 为空。`);
    }
    for (const name of newColumns) {
      if (headers.includes(name)) continue;
      headers.push(name);
      for (const row of rows) row.push("");
    }
    const columns = new Map(headers.map((name, i) => [name, i]));
    const references = collectVideoReferences(rows, columns.get("video_path"), idIndex);
    return {
      headers, rows, columns, ...references,
      originals: new WeakMap(), reviewTimes: new WeakSet(), confirmedUnbrokenVideos: new WeakSet(),
    };
  }

  function serializeCsv({ headers, rows }) {
    function cell(value) {
      return /[",\r\n]/.test(value) ? '"' + value.replaceAll('"', '""') + '"' : value;
    }
    return "\uFEFF" + [headers, ...rows].map((row) => row.map(cell).join(",")).join("\r\n") + "\r\n";
  }

  function value(row, column) {
    return row[table.columns.get(column)] ?? "";
  }

  function preventLoss(event) {
    event.preventDefault();
    event.returnValue = "";
  }

  function saveMessage(state, message) {
    saveStatus.dataset.state = state;
    saveStatus.textContent = message;
    saveStatusFooter.dataset.state = state;
    saveStatusFooter.textContent = message;
  }

  function renderSaveStatus() {
    if (!editorReady) return;
    reconnectCsv.hidden = true;
    reconnectCsv.disabled = openingCsv || reconnecting || !!saving;
    window.removeEventListener("beforeunload", preventLoss);
    if (!draft) {
      saveMessage("idle", "请先打开 CSV。");
      return;
    }
    const pending = draft.revision > draft.savedRevision;
    const recovered = draft.localRevision >= draft.revision && !draft.journalFailed;
    if (pending) window.addEventListener("beforeunload", preventLoss);
    if (draft.journalFailed) {
      reconnectCsv.hidden = !draft.handle;
      saveMessage("error", "本地草稿保存失败。请导出 CSV 保留当前修改。");
    } else if (!draft.handle) {
      saveMessage("warning", recovered
        ? "当前 CSV 只能读取。草稿已保存在此浏览器地址，可导出 CSV。"
        : "当前 CSV 只能读取。请导出 CSV 保留修改。");
    } else if (draft.problem) {
      reconnectCsv.hidden = false;
      reconnectCsv.textContent = draft.permission === "granted" ? "重试写回" : "授权写回";
      saveMessage("warning", draft.problem + (recovered ? " 草稿已保存在此浏览器地址。" : ""));
    } else if (pending) {
      saveMessage("pending", recovered ? "草稿已保存，等待写回原 CSV…" : "正在保存标注…");
    } else {
      saveMessage("saved", draft.revision ? "已写回原 CSV。" : "自动保存已开启，修改将写回此 CSV。");
    }
  }

  function openJournal() {
    return new Promise((resolve, reject) => {
      const request = indexedDB.open("review-annotation", 1);
      request.onupgradeneeded = () => request.result.createObjectStore("drafts");
      request.onsuccess = () => resolve(request.result);
      request.onerror = () => reject(request.error);
      request.onblocked = () => reject(new Error("无法打开本地草稿。"));
    });
  }

  function readDraft() {
    return new Promise((resolve, reject) => {
      const request = journal.transaction("drafts").objectStore("drafts").get("active");
      request.onsuccess = () => resolve(request.result);
      request.onerror = () => reject(request.error);
    });
  }

  async function persistDraft(active) {
    if (!journal || active !== draft) return false;
    const revision = active.revision;
    try {
      const originals = [];
      const reviewTimes = [];
      const confirmedUnbrokenVideos = [];
      for (const [index, row] of table.rows.entries()) {
        const previousValues = table.originals.get(row);
        if (previousValues) originals.push([index, [...previousValues]]);
        if (table.reviewTimes.has(row)) reviewTimes.push(index);
        if (table.confirmedUnbrokenVideos.has(row)) confirmedUnbrokenVideos.push(index);
      }
      // Queue the transaction immediately so refresh recovery includes the latest edit.
      await new Promise((resolve, reject) => {
        const transaction = journal.transaction("drafts", "readwrite", { durability: "strict" });
        transaction.oncomplete = () => resolve();
        transaction.onabort = () => reject(transaction.error);
        transaction.objectStore("drafts").put({
          filename: table.filename,
          csv: serializeCsv(table),
          rowIndex,
          originals,
          reviewTimes,
          confirmedUnbrokenVideos,
          handle: active.handle,
          revision,
          savedRevision: active.savedRevision,
          diskHash: active.diskHash,
          pendingHash: active.pendingHash,
          pendingRevision: active.pendingRevision,
        }, "active");
      });
      active.localRevision = Math.max(active.localRevision, revision);
      active.journalFailed = false;
      return true;
    } catch {
      active.journalFailed = true;
      return false;
    } finally {
      if (active === draft) renderSaveStatus();
    }
  }

  async function digest(bytes) {
    const hash = await crypto.subtle.digest("SHA-256", bytes);
    return [...new Uint8Array(hash)].map((byte) => byte.toString(16).padStart(2, "0")).join("");
  }

  async function readFileHash(handle) {
    return digest(await (await handle.getFile()).arrayBuffer());
  }

  function clearPending(active) {
    active.pendingHash = null;
    active.pendingRevision = null;
  }

  async function writeOriginal(active) {
    if (active.revision === active.savedRevision && !active.pendingHash) return;
    active.permission = await active.handle.queryPermission({ mode: "readwrite" });
    if (active.permission !== "granted") {
      active.problem = "尚未授权写回原 CSV。";
      return;
    }
    const revision = active.revision;
    const bytes = new TextEncoder().encode(serializeCsv(table));
    const expected = await digest(bytes);
    const actual = await readFileHash(active.handle);
    if (active.pendingHash === actual) {
      // A refresh can interrupt the journal update after the file commit.
      active.diskHash = actual;
      active.savedRevision = active.pendingRevision;
      clearPending(active);
    }
    if (actual !== active.diskHash) {
      active.problem = "原 CSV 已被其他程序修改，已暂停写回。可导出当前标注另存。";
      return;
    }
    if (actual !== expected) {
      active.pendingHash = expected;
      active.pendingRevision = revision;
      if (!await persistDraft(active)) throw new Error("本地草稿不可用，已暂停写回。");
      const writable = await active.handle.createWritable({ mode: "exclusive" });
      try {
        await writable.write(bytes);
        // The file stream stages changes until close. Check the original before replacing it.
        if (await readFileHash(active.handle) !== actual) {
          throw new Error("原 CSV 在保存期间被其他程序修改，已暂停写回。可导出当前标注另存。");
        }
        await writable.close();
      } catch (error) {
        await writable.abort().catch(() => {});
        throw error;
      }
      if (await readFileHash(active.handle) !== expected) {
        throw new Error("写回后原 CSV 内容与当前标注不符，已暂停写回。");
      }
    }
    active.diskHash = expected;
    active.savedRevision = revision;
    clearPending(active);
    await persistDraft(active);
  }

  function flushSave() {
    window.clearTimeout(saveTimer);
    const active = draft;
    if (saving) return saving;
    if (!active?.handle || active.problem || !journal
      || (active.revision === active.savedRevision && !active.pendingHash)) return Promise.resolve();
    saving = writeOriginal(active).catch((error) => {
      if (error.name === "NotAllowedError") {
        active.permission = "prompt";
        active.problem = "尚未授权写回原 CSV。";
      } else {
        active.problem = error.name === "Error" && error.message
          ? error.message : "写回原 CSV 失败，请检查文件是否可写。";
      }
    }).finally(() => {
      saving = null;
      renderSaveStatus();
      if (active === draft && !active.journalFailed && active.revision > active.savedRevision) scheduleSave();
    });
    renderSaveStatus();
    return saving;
  }

  function scheduleSave() {
    window.clearTimeout(saveTimer);
    if (!openingCsv && draft?.handle && !draft.problem) saveTimer = window.setTimeout(flushSave, 250);
  }

  function noteChange() {
    draft.revision += 1;
    renderSaveStatus();
    void persistDraft(draft);
    scheduleSave();
  }

  function setControl(control, current) {
    const previousOption = control.querySelector("option[data-legacy]");
    if (previousOption) previousOption.remove();
    if (control.tagName === "SELECT" && ![...control.options].some((option) => option.value === current)) {
      const option = document.createElement("option");
      option.dataset.legacy = "";
      option.value = current;
      option.textContent = current ? "原值（待复核） · " + current : "未填写";
      control.append(option);
    }
    if (control.value !== current) control.value = current;
  }

  function ruleTargets(state, grip, wholeVideoUnbroken) {
    if (state === "未断裂" && wholeVideoUnbroken) {
      return grip === "是" ? wholeVideoGripColumns : wholeVideoColumns;
    }
    if (grip === "是") return gripColumns;
    if (state === "未断裂") return fractureColumns;
    return [];
  }

  function activeRuleTargets(row) {
    return ruleTargets(value(row, stateColumn), value(row, gripColumn), table.confirmedUnbrokenVideos.has(row));
  }

  function frameConfirmationAvailable(row) {
    return value(row, stateColumn) === "未断裂" && !table.confirmedUnbrokenVideos.has(row)
      && frameColumns.some((name) => value(row, name) !== "无");
  }

  function ensureFrameColumns() {
    for (const name of frameColumns) {
      if (table.columns.has(name)) continue;
      table.columns.set(name, table.headers.length);
      table.headers.push(name);
      for (const row of table.rows) row.push("");
    }
  }

  function changeRule(row, trigger, nextValue, { revokeFrameConfirmation = false } = {}) {
    const previousTargets = activeRuleTargets(row);
    const state = trigger === stateColumn ? nextValue : value(row, stateColumn);
    const grip = trigger === gripColumn ? nextValue : value(row, gripColumn);
    let wholeVideoUnbroken = !revokeFrameConfirmation
      && state === "未断裂" && table.confirmedUnbrokenVideos.has(row);
    if (!revokeFrameConfirmation && state === "未断裂" && !wholeVideoUnbroken
      && (trigger === stateColumn || (!trigger && frameConfirmationAvailable(row)))) {
      wholeVideoUnbroken = window.confirm("确认完整视频全程未发生断裂？确认后，断裂帧_前和断裂帧_后将填为“无”。");
      if (!wholeVideoUnbroken) {
        const hasOtherUpdates = ruleTargets(state, grip).some((name) => value(row, name) !== "无");
        if ((!trigger && !hasOtherUpdates)
          || !window.confirm("只按当前片段的“未断裂”应用标注规则，并保留完整视频的断裂前后帧？取消将保留本条当前标注。")) {
          return false;
        }
      }
    }
    const targets = ruleTargets(state, grip, wholeVideoUnbroken);
    const applying = !revokeFrameConfirmation && (!trigger || targets !== previousTargets) ? targets : [];
    const updates = applying.filter((name) => value(row, name) !== "无");
    const conflicts = updates.filter((name) => value(row, name) !== "");
    if (conflicts.length) {
      const prior = conflicts.map((name) => `${name}「${value(row, name)}」`).join("\n");
      if (!window.confirm("按固定组合填写“无”将替换以下原值。取消将保留本条记录当前值。\n\n" + prior)) {
        return false;
      }
    }

    if (wholeVideoUnbroken) {
      ensureFrameColumns();
      table.confirmedUnbrokenVideos.add(row);
    } else {
      table.confirmedUnbrokenVideos.delete(row);
    }

    // 保存实际被覆盖的值，使重叠规则解除时能按字段恢复。
    const originals = table.originals.get(row) ?? new Map();
    if (previousTargets.includes(timeColumn) && !targets.includes(timeColumn)
      && !originals.has(timeColumn) && value(row, timeColumn) === "无") {
      table.reviewTimes.add(row);
    }
    for (const [name, original] of originals) {
      if (targets.includes(name)) continue;
      row[table.columns.get(name)] = original;
      originals.delete(name);
    }
    for (const name of updates) {
      originals.set(name, value(row, name));
      row[table.columns.get(name)] = "无";
    }
    if (originals.size) {
      table.originals.set(row, originals);
    } else {
      table.originals.delete(row);
    }
    if (trigger) row[table.columns.get(trigger)] = nextValue;
    return true;
  }

  function renderFields() {
    const row = table?.rows[rowIndex];
    const targets = row ? activeRuleTargets(row) : [];
    for (const [control, column] of fields) {
      const current = row ? value(row, column) : "";
      setControl(control, current);
      control.disabled = !editorReady || openingCsv || reconnecting
        || !row || !table.columns.has(column) || targets.includes(column);
    }

    renderRuleHint(row, targets);
    updateFrameControls();
  }

  function renderOriginalFields(row) {
    const columns = row ? table.headers.filter((column) => !displayedColumns.has(column)) : [];
    const entries = columns.map((column) => [column, value(row, column) || "（空白）"]);
    if (!entries.length) {
      entries.push(["原表其他字段", row ? "此表没有其他字段。" : "导入 CSV 后显示。"]);
    }
    originalFields.replaceChildren(...entries.map(([column, current]) => {
      const group = document.createElement("div");
      const name = document.createElement("dt");
      const content = document.createElement("dd");
      name.textContent = column;
      content.textContent = current;
      group.append(name, content);
      return group;
    }));
  }

  function renderRuleHint(row, targets) {
    const hints = [];
    const canConfirmFrames = row && frameConfirmationAvailable(row);
    const canRevokeFrames = row && table.confirmedUnbrokenVideos.has(row);
    const inconsistent = row && targets.some((name) => value(row, name) !== "无");
    const review = row && !targets.length && stateOptions.has(value(row, stateColumn))
      ? fractureColumns.filter((name) => value(row, name) === "无")
      : [];
    if (row && table.reviewTimes.has(row) && !targets.includes(timeColumn) && value(row, timeColumn) === "无") {
      review.push(timeColumn);
    }
    if (row && stateOptions.has(value(row, stateColumn)) && value(row, stateColumn) !== "未断裂") {
      review.push(...frameColumns.filter((name) => value(row, name) === "无"));
    }
    if (inconsistent) {
      hints.push("此行已有值与固定组合不一致，原值已保留。");
    } else if (targets.length) {
      hints.push(targets.join("、") + "按固定组合填写“无”。");
      if (table.originals.has(row)) hints.push("解除条件可恢复本页覆盖前的值。");
    }
    if (canConfirmFrames) hints.push("若完整视频全程未断裂，可确认并补填断裂前后帧。");
    if (review.length) hints.push(review.join("、") + "仍为“无”，请按画面手动复核。");
    ruleHint.textContent = hints.join("");
    if (canRevokeFrames) {
      applyRuleButton.textContent = "撤销完整视频未断裂确认";
    } else {
      applyRuleButton.textContent = canConfirmFrames ? "确认完整视频未断裂" : "应用固定组合";
    }
    applyRuleButton.hidden = !inconsistent && !canConfirmFrames && !canRevokeFrames;
    applyRuleButton.disabled = !editorReady || openingCsv || reconnecting || applyRuleButton.hidden;
  }

  function updateProgress() {
    const total = table?.rows.length ?? 0;
    const labeled = table?.rows.filter((row) => stateOptions.has(value(row, stateColumn))).length ?? 0;
    byId("progress").textContent = total
      ? `第 ${rowIndex + 1} / ${total} 条 · 已填断裂状态 ${labeled} 条`
      : "暂无记录";
  }

  function basename(path) {
    return path.split(/[\\/]/).at(-1);
  }

  function collectVideoReferences(rows, pathIndex, idIndex) {
    const pathsByName = new Map();
    const idsWithoutPaths = new Set();
    for (const row of rows) {
      const path = row[pathIndex] ?? "";
      if (!path) {
        idsWithoutPaths.add(row[idIndex]);
        continue;
      }
      const name = basename(path);
      if (!name) continue;
      if (!pathsByName.has(name)) {
        pathsByName.set(name, path);
      } else if (pathsByName.get(name) !== path) {
        pathsByName.set(name, null);
      }
    }
    return { pathsByName, idsWithoutPaths };
  }

  function stem(name) {
    return name.replace(/\.[^.]+$/, "");
  }

  function videoCandidates(name, matchStem) {
    return videos.filter((file) => file.name === name || (matchStem && stem(file.name) === name));
  }

  function matchVideo(path, id) {
    const name = path ? basename(path) : id;
    if (path && table.pathsByName.get(name) === null) {
      throw new Error(`CSV 中有不同视频路径使用同一文件名“${name}”，无法唯一匹配，未播放。`);
    }
    const matches = videoCandidates(name, !path);
    const criterion = path ? `文件名“${name || path}”` : `id“${id}”`;
    if (!matches.length) throw new Error(`未找到视频（${criterion}），请检查所选目录。`);
    if (matches.length > 1) throw new Error(`发现多个匹配${criterion}的视频，请缩小视频目录范围。`);
    const [file] = matches;
    const aliases = new Set([file.name, stem(file.name)]);
    const matchingIds = [...aliases].filter((alias) => table.idsWithoutPaths.has(alias)
      && videoCandidates(alias, true).length === 1);
    if (matchingIds.length + Number(table.pathsByName.has(file.name)) > 1) {
      throw new Error(`CSV 中有不同记录指向同一候选视频“${file.webkitRelativePath}”，无法唯一匹配，未播放。`);
    }
    return file;
  }

  function matchedVideoStatus(status) {
    return `${status} · ${playingFile.webkitRelativePath}。按文件名匹配，请核对视频。`;
  }

  function frameMessage(state, message) {
    frameStatus.dataset.state = state;
    frameStatus.textContent = message;
  }

  function showPlaybackStatus() {
    if (!sessionToken) {
      frameMessage("idle", "请从本机标注工具打开此页，启用逐帧查看。");
    } else if (!playingFile) {
      frameMessage("idle", "匹配到视频后即可逐帧查看。");
    } else {
      frameMessage("idle", "可直接点击上一帧或下一帧。首次按播放位置粗定位，标注以解码帧为准。");
    }
  }

  function updateFrameControls() {
    const waiting = !!frameSession?.request;
    const displayed = frameSession?.index;
    const canDecode = !!sessionToken && !!playingFile && !waiting;
    const canAssign = canDecode && displayed != null && !frameImage.hidden;
    framePlay.disabled = !playingFile || !!player.error;
    framePlay.textContent = waiting || displayed != null ? "继续播放" : player.paused ? "播放" : "暂停";
    frameIndex.disabled = frameGo.disabled = !canDecode;
    framePrevious.disabled = !canDecode || displayed === 0;
    frameNext.disabled = !canDecode || (displayed != null && displayed + 1 >= frameSession.count);
    frameBefore.disabled = !canAssign || frameBeforeField.disabled;
    frameAfter.disabled = !canAssign || frameAfterField.disabled;
  }

  async function frameFetch(path, options = {}) {
    let response;
    try {
      response = await fetch(path, {
        ...options,
        headers: { "X-Annotation-Session": sessionToken, ...options.headers },
      });
    } catch (error) {
      if (error.name === "AbortError") throw error;
      throw new Error("无法连接本机逐帧服务，请重新启动标注工具。");
    }
    if (!response.ok) {
      const payload = await response.json().catch(() => ({}));
      throw new Error(payload.error || "无法连接本机逐帧服务，请重新启动标注工具。");
    }
    return response;
  }

  function clearFrameImage() {
    if (frameSession?.imageUrl) {
      URL.revokeObjectURL(frameSession.imageUrl);
      frameSession.imageUrl = "";
    }
    frameImage.hidden = true;
    frameImage.removeAttribute("src");
    framePreview.classList.remove("has-frame");
    player.hidden = false;
  }

  function releaseFrameReview() {
    const session = frameSession;
    session?.request?.abort();
    clearFrameImage();
    frameSession = null;
    frameIndex.value = "";
    frameIndex.removeAttribute("max");
    frameIndex.setCustomValidity("");
    if (session) {
      frameFetch(session.path, { method: "DELETE", keepalive: true }).catch(() => {});
    }
    showPlaybackStatus();
    updateFrameControls();
  }

  function activeFrameSession(session) {
    return frameSession === session && session.file === playingFile && session.row === table?.rows[rowIndex];
  }

  async function showFrame(index, fromPlayback = false) {
    const session = frameSession;
    if (!session?.count || !activeFrameSession(session) || session.request) return;
    if (!Number.isSafeInteger(index) || index < 0 || index >= session.count) {
      const message = `请输入 0 到 ${session.count - 1} 的整数帧索引。`;
      if (session.index == null) frameMessage("idle", message);
      frameIndex.setCustomValidity(message);
      frameIndex.reportValidity();
      return;
    }
    const request = new AbortController();
    session.request = request;
    frameIndex.setCustomValidity("");
    frameIndex.value = String(index);
    frameMessage("loading", `正在解码索引 ${index} 的画面…`);
    updateFrameControls();
    try {
      const response = await frameFetch(`${session.path}/frame/${index}`, { signal: request.signal });
      const blob = await response.blob();
      if (!activeFrameSession(session)) return;
      if (blob.type !== "image/png") throw new Error("未收到可核验的解码画面。");
      if (session.imageUrl) URL.revokeObjectURL(session.imageUrl);
      session.imageUrl = URL.createObjectURL(blob);
      frameImage.src = session.imageUrl;
      await frameImage.decode();
      if (!activeFrameSession(session)) return;
      frameImage.hidden = false;
      framePreview.classList.add("has-frame");
      player.hidden = true;
      session.index = index;
      const hint = fromPlayback ? " · 已按播放位置粗定位，请逐帧核对" : "";
      frameMessage("ready", `当前帧索引 ${index} / ${session.count - 1}（从 0 开始）${hint}`);
    } catch (error) {
      if (!activeFrameSession(session)) return;
      releaseFrameReview();
      frameMessage("error", error.message || "无法显示已解码的画面。");
    } finally {
      if (activeFrameSession(session)) {
        session.request = null;
        updateFrameControls();
      }
    }
  }

  function playbackFrame(count) {
    if (!Number.isFinite(player.duration) || player.duration <= 0) return 0;
    return Math.max(0, Math.min(count - 1, Math.floor(player.currentTime / player.duration * count)));
  }

  async function requestFrame({ index, step } = {}) {
    const row = table?.rows[rowIndex];
    if (!sessionToken || !playingFile || !row || frameSession?.request) return;
    player.pause();
    if (frameSession?.count && activeFrameSession(frameSession)) {
      const fromPlayback = index == null && frameSession.index == null;
      const target = index ?? stepFrame(frameSession, step);
      await showFrame(target, fromPlayback);
      return;
    }
    if (frameSession) releaseFrameReview();
    const request = new AbortController();
    const id = crypto.randomUUID().replaceAll("-", "");
    const session = { path: "/api/video/" + id, file: playingFile, row, request, index: null };
    frameSession = session;
    frameMessage("loading", "正在将当前视频交给本机服务读取并确认解码帧数…");
    updateFrameControls();
    try {
      const response = await frameFetch(session.path, {
        method: "POST",
        body: session.file,
        headers: { "Content-Type": "application/octet-stream" },
        signal: request.signal,
      });
      const payload = await response.json();
      if (!activeFrameSession(session)) return;
      if (!Number.isSafeInteger(payload.frame_count) || payload.frame_count < 1) {
        throw new Error("无法确认视频的解码帧数。");
      }
      session.count = payload.frame_count;
      session.request = null;
      frameIndex.max = String(session.count - 1);
      updateFrameControls();
      await showFrame(index ?? stepFrame(session, step), index == null);
    } catch (error) {
      if (!activeFrameSession(session)) return;
      session.request = null;
      frameMessage("error", error.message || "无法打开逐帧查看。");
      updateFrameControls();
    }
  }

  function stepFrame(session, step) {
    const base = session.index ?? playbackFrame(session.count);
    return Math.max(0, Math.min(session.count - 1, base + step));
  }

  function leaveFrameView() {
    if (frameSession?.request) {
      releaseFrameReview();
    } else if (frameSession) {
      clearFrameImage();
      frameSession.index = null;
      frameIndex.value = "";
      frameIndex.setCustomValidity("");
    }
  }

  async function togglePlayback() {
    if (!playingFile || player.error) return;
    if (!player.paused && !player.ended) {
      player.pause();
      return;
    }
    const file = playingFile;
    const row = table?.rows[rowIndex];
    const index = frameSession?.index;
    const count = frameSession?.count;
    leaveFrameView();
    showPlaybackStatus();
    if (index != null) {
      if (Number.isFinite(player.duration) && player.duration > 0) {
        player.currentTime = index / count * player.duration;
        frameMessage("idle", "已从解码帧附近继续播放，播放位置为近似，标注以解码帧为准。");
      } else {
        frameMessage("idle", "无法定位该帧的播放时间，将从原播放位置继续，标注以解码帧为准。");
      }
    }
    updateFrameControls();
    try {
      await player.play();
    } catch (error) {
      if (error.name !== "AbortError" && file === playingFile && row === table?.rows[rowIndex]
        && !frameSession?.request && frameSession?.index == null) {
        frameMessage("error", "无法继续播放，请检查视频格式，或使用逐帧按钮查看。");
      }
    } finally {
      updateFrameControls();
    }
  }

  function assignFrame(field) {
    const session = frameSession;
    if (!session || !activeFrameSession(session) || session.request || session.index == null
      || frameImage.hidden || field.disabled) return;
    const index = String(session.index);
    if (field.value && field.value !== index
      && !window.confirm(`将${fields.get(field)}从“${field.value}”改为“${index}”？`)) return;
    field.value = index;
    field.dispatchEvent(new Event("input", { bubbles: true }));
  }

  function releaseVideo() {
    if (videoUrl) {
      player.pause();
      player.removeAttribute("src");
      player.load();
      URL.revokeObjectURL(videoUrl);
      videoUrl = "";
      playingFile = null;
    }
    releaseFrameReview();
  }

  function renderVideo() {
    const row = table?.rows[rowIndex];
    try {
      if (!row) throw new Error("请先导入 CSV。");
      if (!videos.length) throw new Error("请选取包含源视频的目录。");
      const file = matchVideo(value(row, "video_path"), value(row, "id"));
      if (file === playingFile) return;
      releaseVideo();
      videoUrl = URL.createObjectURL(file);
      playingFile = file;
      videoStatus.textContent = matchedVideoStatus("正在打开");
      player.src = videoUrl;
      showPlaybackStatus();
      updateFrameControls();
    } catch (error) {
      releaseVideo();
      videoStatus.textContent = error.message;
    }
  }

  function renderRow() {
    const total = table?.rows.length ?? 0;
    const row = table?.rows[rowIndex];
    byId("item-id").textContent = row ? value(row, "id") : "—";
    byId("item-path").textContent = row ? value(row, "video_path") || "—" : "—";
    previous.disabled = rowIndex === 0;
    next.disabled = rowIndex + 1 >= total;
    jump.disabled = jumpButton.disabled = !total;
    jump.max = String(total);
    jump.value = row ? String(rowIndex + 1) : "";
    exportButton.disabled = !table;
    renderFields();
    renderOriginalFields(row);
    updateProgress();
    renderVideo();
  }

  for (const [control, column] of fields) {
    control.addEventListener(control.tagName === "SELECT" ? "change" : "input", () => {
      const row = table?.rows[rowIndex];
      if (!row || control.disabled || control.value === value(row, column)) return;
      if (column === stateColumn || column === gripColumn) {
        const changed = changeRule(row, column, control.value);
        renderFields();
        if (!changed) return;
      } else {
        row[table.columns.get(column)] = control.value;
        if (gripColumns.includes(column) || frameColumns.includes(column)) renderRuleHint(row, activeRuleTargets(row));
      }
      noteChange();
      if (column === stateColumn) updateProgress();
    });
  }

  applyRuleButton.addEventListener("click", () => {
    const row = table?.rows[rowIndex];
    if (!row || applyRuleButton.disabled) return;
    const revokeFrameConfirmation = table.confirmedUnbrokenVideos.has(row);
    if (!changeRule(row, null, "", { revokeFrameConfirmation })) return;
    renderFields();
    noteChange();
  });

  function setOpening(value) {
    openingCsv = value;
    openCsv.disabled = !editorReady || value || reconnecting;
    if (value) window.clearTimeout(saveTimer);
    renderFields();
    renderSaveStatus();
    if (!value && draft?.revision > draft?.savedRevision) scheduleSave();
  }

  async function loadCsv(file, handle, permission) {
    await flushSave();
    // An earlier in-flight write may have captured an older revision.
    await flushSave();
    const input = handle ? await handle.getFile() : file;
    csvStatus.textContent = "正在读取 · " + input.name;
    const bytes = await input.arrayBuffer();
    const csv = new TextDecoder("utf-8", { fatal: true, ignoreBOM: true }).decode(bytes);
    const imported = parseCsv(csv);
    const diskHash = handle ? await digest(bytes) : null;
    if (draft?.revision > draft?.savedRevision
      && !window.confirm("当前草稿有未写回原 CSV 的修改。打开另一份 CSV 将替换草稿，是否继续？")) {
      csvStatus.textContent = "已取消打开，继续使用 · " + table.filename;
      return;
    }
    if (table) videos = [];
    table = { ...imported, filename: input.name };
    draft = {
      handle,
      diskHash,
      revision: 0,
      savedRevision: 0,
      localRevision: -1,
      permission,
      problem: handle && permission !== "granted" ? "尚未授权写回原 CSV。" : null,
    };
    rowIndex = 0;
    csvStatus.textContent = "已载入 · " + table.filename;
    renderRow();
    await persistDraft(draft);
  }

  function reportOpenError(error) {
    if (error.name === "AbortError") return;
    const reason = error instanceof TypeError ? "请确认 CSV 使用 UTF-8 编码且文件可读。" : error.message;
    const retained = table ? " 仍在使用 · " + table.filename : "";
    csvStatus.textContent = "打开失败 · " + reason + retained;
  }

  async function askWriteAccess(handle) {
    try {
      return await handle.requestPermission({ mode: "readwrite" });
    } catch {
      // A browser may require a fresh click after the native picker returns.
      return "prompt";
    }
  }

  openCsv.addEventListener("click", async () => {
    if (!editorReady || openingCsv || reconnecting) return;
    if (!journal || typeof window.showOpenFilePicker !== "function") {
      csvInput.click();
      return;
    }
    setOpening(true);
    try {
      const [handle] = await window.showOpenFilePicker({
        types: [{ description: "CSV 文件", accept: { "text/csv": [".csv"] } }],
        multiple: false,
      });
      const permission = await askWriteAccess(handle);
      await loadCsv(null, handle, permission);
    } catch (error) {
      reportOpenError(error);
    } finally {
      setOpening(false);
    }
  });

  csvInput.addEventListener("change", async () => {
    const file = csvInput.files[0];
    csvInput.value = "";
    if (!editorReady || !file || openingCsv || reconnecting) return;
    setOpening(true);
    try {
      await loadCsv(file, null, null);
    } catch (error) {
      reportOpenError(error);
    } finally {
      setOpening(false);
    }
  });

  reconnectCsv.addEventListener("click", async () => {
    const active = draft;
    if (openingCsv || reconnecting || saving || !active?.handle) return;
    reconnecting = true;
    openCsv.disabled = true;
    renderFields();
    renderSaveStatus();
    try {
      active.permission = await askWriteAccess(active.handle);
      active.problem = active.permission === "granted" ? null : "尚未授权写回原 CSV。";
      if (!active.problem) await checkCleanSource(active);
      if (active.journalFailed) await persistDraft(active);
      if (!active.journalFailed) await flushSave();
    } finally {
      reconnecting = false;
      openCsv.disabled = false;
      renderFields();
      renderSaveStatus();
    }
  });

  videoInput.addEventListener("change", () => {
    const selection = [...videoInput.files];
    videoInput.value = "";
    if (!selection.length) return;
    videos = [];
    releaseVideo();
    const candidates = selection.filter((file) => file.type.startsWith("video/")
      || /\.(mp4|mov|m4v|webm|avi|mkv|ogv|mpeg|mpg|mts|m2ts|wmv|3gp|flv)$/i.test(file.name));
    if (!candidates.length) {
      videoStatus.textContent = "所选目录未找到可识别的视频文件。";
      return;
    }
    const folders = new Set(candidates.map((file) => file.webkitRelativePath?.split("/")[0]));
    if (folders.size !== 1 || candidates.some((file) => !file.webkitRelativePath?.includes("/"))) {
      videoStatus.textContent = "无法取得同一目录下的视频相对路径，请重新选择一个视频文件夹。";
      return;
    }
    const folder = [...folders][0];
    const csvName = table ? `标注表“${table.filename}”` : "即将导入的标注表";
    if (!window.confirm(`浏览器按文件名匹配视频，无法核验 CSV 记录的原路径。请确认“${folder}”是${csvName}对应的源视频文件夹。`)) {
      videoStatus.textContent = "未确认所选视频文件夹，未播放视频。";
      return;
    }
    videos = candidates;
    renderVideo();
  });

  player.addEventListener("loadedmetadata", () => {
    if (playingFile && player.currentSrc === videoUrl) videoStatus.textContent = matchedVideoStatus("已载入");
    updateFrameControls();
  });
  player.addEventListener("error", () => {
    if (playingFile && player.error && player.src === videoUrl) {
      videoStatus.textContent = matchedVideoStatus("无法播放") + "请检查视频是否损坏或编码是否受浏览器支持。";
    }
    updateFrameControls();
  });
  player.addEventListener("play", () => {
    if (!player.paused && (frameSession?.request || frameSession?.index != null)) {
      leaveFrameView();
      showPlaybackStatus();
    }
    updateFrameControls();
  });
  player.addEventListener("pause", updateFrameControls);
  player.addEventListener("ended", updateFrameControls);
  window.addEventListener("pagehide", releaseVideo);
  window.addEventListener("pageshow", (event) => {
    if (event.persisted) renderVideo();
  });

  framePlay.addEventListener("click", togglePlayback);
  framePrevious.addEventListener("click", () => {
    if (!framePrevious.disabled) requestFrame({ step: -1 });
  });
  frameNext.addEventListener("click", () => {
    if (!frameNext.disabled) requestFrame({ step: 1 });
  });
  function jumpToFrame() {
    if (frameGo.disabled) return;
    const index = frameIndex.value.trim() ? Number(frameIndex.value) : NaN;
    if (!Number.isSafeInteger(index) || index < 0) {
      frameIndex.setCustomValidity("请输入从 0 开始的整数帧索引。");
      frameIndex.reportValidity();
      return;
    }
    requestFrame({ index });
  }
  frameGo.addEventListener("click", jumpToFrame);
  frameIndex.addEventListener("input", () => frameIndex.setCustomValidity(""));
  frameIndex.addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
      event.preventDefault();
      jumpToFrame();
    }
  });
  frameBefore.addEventListener("click", () => assignFrame(frameBeforeField));
  frameAfter.addEventListener("click", () => assignFrame(frameAfterField));

  function showRow(index) {
    if (openingCsv || reconnecting || index === rowIndex || !table || index < 0 || index >= table.rows.length) return;
    releaseFrameReview();
    rowIndex = index;
    renderRow();
    void persistDraft(draft);
    void flushSave();
  }

  function jumpToRow() {
    const number = Number(jump.value);
    if (!table || !Number.isInteger(number) || number < 1 || number > table.rows.length) {
      jump.setCustomValidity("请输入有效的记录序号。");
      jump.reportValidity();
      return;
    }
    showRow(number - 1);
  }

  previous.addEventListener("click", () => showRow(rowIndex - 1));
  next.addEventListener("click", () => showRow(rowIndex + 1));
  jumpButton.addEventListener("click", jumpToRow);
  jump.addEventListener("input", () => jump.setCustomValidity(""));
  jump.addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
      event.preventDefault();
      jumpToRow();
    }
  });

  exportButton.addEventListener("click", () => {
    if (!table) return;
    const filename = table.filename.replace(/\.csv$/i, "") + "-标注.csv";
    const url = URL.createObjectURL(new Blob([serializeCsv(table)], { type: "text/csv;charset=utf-8" }));
    const link = document.createElement("a");
    link.href = url;
    link.download = filename;
    document.body.append(link);
    link.click();
    link.remove();
    window.setTimeout(() => URL.revokeObjectURL(url), 30000);
    // Exporting a copy does not confirm that pending edits reached the original.
    csvStatus.textContent = "已发起下载 · " + filename + "。请检查浏览器的下载结果。";
  });

  function restoreDraft(stored) {
    table = { ...parseCsv(stored.csv), filename: stored.filename };
    for (const [index, originals] of stored.originals) {
      table.originals.set(table.rows[index], new Map(originals));
    }
    for (const index of stored.reviewTimes) table.reviewTimes.add(table.rows[index]);
    for (const index of stored.confirmedUnbrokenVideos ?? []) table.confirmedUnbrokenVideos.add(table.rows[index]);
    rowIndex = Math.max(0, Math.min(stored.rowIndex, table.rows.length - 1));
    draft = {
      handle: stored.handle,
      diskHash: stored.diskHash,
      pendingHash: stored.pendingHash,
      pendingRevision: stored.pendingRevision,
      revision: stored.revision,
      savedRevision: stored.savedRevision,
      localRevision: stored.revision,
    };
    csvStatus.textContent = "已恢复上次标注 · " + table.filename;
    renderRow();
  }

  function acquireEditor() {
    return new Promise((resolve, reject) => {
      navigator.locks.request("review-annotation-editor", { ifAvailable: true }, (lock) => {
        resolve(!!lock);
        if (lock) return new Promise(() => {});
      }).catch(reject);
    });
  }

  async function checkCleanSource(active) {
    if (active.revision !== active.savedRevision || active.pendingHash) return;
    try {
      const file = await active.handle.getFile();
      const bytes = await file.arrayBuffer();
      const hash = await digest(bytes);
      if (hash === active.diskHash) return;
      const csv = new TextDecoder("utf-8", { fatal: true, ignoreBOM: true }).decode(bytes);
      table = { ...parseCsv(csv), filename: file.name };
      rowIndex = Math.max(0, Math.min(rowIndex, table.rows.length - 1));
      active.diskHash = hash;
      csvStatus.textContent = "原 CSV 有更新，已读取最新内容 · " + table.filename;
      renderRow();
      await persistDraft(active);
    } catch {
      active.problem = "无法核对原 CSV 的最新内容，已暂停写回。可导出恢复的标注。";
    }
  }

  async function initializeEditor() {
    openCsv.disabled = true;
    renderRow();
    if (sessionToken && typeof indexedDB !== "undefined" && navigator.locks && crypto.subtle) {
      try {
        if (!await acquireEditor()) {
          saveMessage("warning", "此地址已有一个标注页面。请关闭另一页后刷新。");
          return;
        }
        journal = await openJournal();
        const stored = await readDraft();
        if (stored) restoreDraft(stored);
      } catch {
        journal?.close();
        journal = null;
        saveMessage("error", "无法读取本地草稿，可打开 CSV 并手动导出。");
      }
    }
    if (draft?.handle) {
      try {
        draft.permission = await draft.handle.queryPermission({ mode: "readwrite" });
        await checkCleanSource(draft);
        if (!draft.problem && draft.permission !== "granted") {
          draft.problem = "草稿已恢复，需要重新授权写回原 CSV。";
        }
      } catch {
        draft.problem = "暂时无法访问原 CSV。请重新授权或导出当前标注。";
      }
      void flushSave();
    }
    editorReady = true;
    openCsv.disabled = false;
    renderFields();
    if (journal || !sessionToken) renderSaveStatus();
  }

  void initializeEditor();
})();
