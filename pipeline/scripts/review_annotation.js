(() => {
  "use strict";

  const byId = (id) => document.getElementById(id);
  const csvInput = byId("csv-file");
  const videoInput = byId("video-files");
  const player = byId("video-player");
  const csvStatus = byId("file-status");
  const videoStatus = byId("video-status");
  const saveStatus = byId("save-status");
  const ruleHint = byId("rule-hint");
  const applyRuleButton = byId("apply-rule");
  const previous = byId("prev");
  const next = byId("next");
  const jump = byId("row-jump");
  const jumpButton = byId("jump-btn");
  const exportButton = byId("export-csv");
  const confirmSaveButton = byId("confirm-save");

  const stateColumn = "断裂状态";
  const gripColumn = "异常_未夹紧";
  const mechanismColumn = "断裂模式";
  const siteColumn = "断裂位置";
  const timeColumn = "断裂时间点";
  const fractureColumns = [mechanismColumn, siteColumn];
  const gripColumns = [...fractureColumns, timeColumn];
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
    [byId("frame-before"), "断裂帧_前"],
    [byId("frame-after"), "断裂帧_后"],
    [byId("annotation-status"), "标注状态"],
    [byId("annotation-note"), "标注备注"],
    ...multiFields,
  ]);
  const newColumns = [stateColumn, ...multiFields.map(([, name]) => name)];
  const stateOptions = new Set([...byId("state").options].map((option) => option.value).filter(Boolean));

  let table = null;
  let rowIndex = 0;
  let dirty = false;
  let importSequence = 0;
  let videos = [];
  let videoUrl = "";
  let playingFile = null;

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
    return { headers, rows, columns, ...references, originals: new WeakMap(), reviewTimes: new WeakSet() };
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

  function setDirty(value, message) {
    dirty = value;
    saveStatus.textContent = message;
    if (confirmSaveButton) confirmSaveButton.hidden = true;
    if (dirty) {
      window.addEventListener("beforeunload", preventLoss);
    } else {
      window.removeEventListener("beforeunload", preventLoss);
    }
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

  function ruleTargets(state, grip) {
    if (grip === "是") return gripColumns;
    if (state === "未断裂") return fractureColumns;
    return [];
  }

  function activeRuleTargets(row) {
    return ruleTargets(value(row, stateColumn), value(row, gripColumn));
  }

  function changeRule(row, trigger, nextValue) {
    const previousTargets = activeRuleTargets(row);
    const state = trigger === stateColumn ? nextValue : value(row, stateColumn);
    const grip = trigger === gripColumn ? nextValue : value(row, gripColumn);
    const targets = ruleTargets(state, grip);
    const applying = !trigger || targets !== previousTargets ? targets : [];
    const updates = applying.filter((name) => value(row, name) !== "无");
    const conflicts = updates.filter((name) => value(row, name) !== "");
    if (conflicts.length) {
      const prior = conflicts.map((name) => `${name}「${value(row, name)}」`).join("\n");
      if (!window.confirm("按固定组合填写“无”将替换以下原值。取消将保留本条记录当前值。\n\n" + prior)) {
        return false;
      }
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
      control.disabled = !row || !table.columns.has(column) || targets.includes(column);
    }

    renderRuleHint(row, targets);
  }

  function renderRuleHint(row, targets) {
    const hints = [];
    const inconsistent = row && targets.some((name) => value(row, name) !== "无");
    const review = row && !targets.length && stateOptions.has(value(row, stateColumn))
      ? fractureColumns.filter((name) => value(row, name) === "无")
      : [];
    if (row && table.reviewTimes.has(row) && !targets.includes(timeColumn) && value(row, timeColumn) === "无") {
      review.push(timeColumn);
    }
    if (inconsistent) {
      hints.push("此行已有值与固定组合不一致，原值已保留。可点击应用固定组合。");
    } else if (targets.length) {
      hints.push(targets.join("、") + "按固定组合填写“无”。");
      if (table.originals.has(row)) hints.push("解除条件可恢复本页覆盖前的值。");
    }
    if (review.length) hints.push(review.join("、") + "仍为“无”，请按画面手动复核。");
    ruleHint.textContent = hints.join("");
    applyRuleButton.hidden = !inconsistent;
    applyRuleButton.disabled = applyRuleButton.hidden;
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

  function releaseVideo() {
    if (!videoUrl) return;
    player.pause();
    player.removeAttribute("src");
    player.load();
    URL.revokeObjectURL(videoUrl);
    videoUrl = "";
    playingFile = null;
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
        if (gripColumns.includes(column)) renderRuleHint(row, activeRuleTargets(row));
      }
      setDirty(true, "本次修改已保存在当前页面，请导出 CSV。");
      if (column === stateColumn) updateProgress();
    });
  }

  applyRuleButton.addEventListener("click", () => {
    const row = table?.rows[rowIndex];
    if (!row || applyRuleButton.disabled || !changeRule(row, null, "")) return;
    renderFields();
    setDirty(true, "本次修改已保存在当前页面，请导出 CSV。");
  });

  csvInput.addEventListener("change", async () => {
    const file = csvInput.files[0];
    csvInput.value = "";
    if (!file) return;
    const sequence = ++importSequence;
    csvStatus.textContent = "正在读取 · " + file.name;
    try {
      const bytes = await file.arrayBuffer();
      if (sequence !== importSequence) return;
      const csv = new TextDecoder("utf-8", { fatal: true, ignoreBOM: true }).decode(bytes);
      const imported = parseCsv(csv);
      if (dirty && !window.confirm("当前有未导出的修改。打开新 CSV 将丢弃这些修改，是否继续？")) {
        csvStatus.textContent = "已取消导入，继续使用 · " + table.filename;
        return;
      }
      if (table) videos = [];
      table = { ...imported, filename: file.name };
      rowIndex = 0;
      csvStatus.textContent = "已载入 · " + file.name;
      setDirty(false, "修改只保存在当前页面，导出后可继续标注。");
      renderRow();
    } catch (error) {
      const reason = error instanceof TypeError ? "请确认 CSV 使用 UTF-8 编码且文件可读。" : error.message;
      const retained = table ? " 仍在使用 · " + table.filename : "";
      if (sequence === importSequence) csvStatus.textContent = "导入失败 · " + reason + retained;
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
  });
  player.addEventListener("error", () => {
    if (playingFile && player.error && player.src === videoUrl) {
      videoStatus.textContent = matchedVideoStatus("无法播放") + "请检查视频是否损坏或编码是否受浏览器支持。";
    }
  });
  window.addEventListener("pagehide", releaseVideo);
  window.addEventListener("pageshow", (event) => {
    if (event.persisted) renderVideo();
  });

  function showRow(index) {
    if (index === rowIndex || !table || index < 0 || index >= table.rows.length) return;
    rowIndex = index;
    renderRow();
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
    saveStatus.textContent = "已发起新文件下载 · " + filename + "。请在浏览器中确认保存位置和下载结果。";
    if (dirty && confirmSaveButton) confirmSaveButton.hidden = false;
  });
  confirmSaveButton?.addEventListener("click", () => {
    if (!confirmSaveButton.hidden) {
      setDirty(false, "你已确认本次下载完成。继续标注后可再次导出。");
    }
  });

  renderRow();
})();
