/* Synthetic DOM contract test, using Node's built-in runner and no media/network. */
const assert = require("node:assert/strict");
const test = require("node:test");
const vm = require("node:vm");
const fs = require("node:fs");
const path = require("node:path");

class Element {
  constructor(tagName = "div") {
    this.tagName = tagName.toUpperCase();
    this.children = [];
    this.listeners = {};
    this.dataset = {};
    this.attributes = {};
    this.textContent = "";
    this.value = "";
    this.clicks = 0;
    this.removed = 0;
    this.parent = null;
  }
  replaceChildren(...children) { children.forEach((child) => { if (child instanceof Element) child.parent = this; }); this.children = children; }
  append(...children) { children.forEach((child) => { if (child instanceof Element) child.parent = this; }); this.children.push(...children); }
  removeChild(child) { const index = this.children.indexOf(child); if (index >= 0) this.children.splice(index, 1); return child; }
  /* 真实解绑：空实现的 remove() 会让「下载锚点是否被清理」永远测不出来，并记录调用次数便于观察。 */
  remove() {
    this.removed += 1;
    if (!this.parent) return;
    const index = this.parent.children.indexOf(this);
    if (index >= 0) this.parent.children.splice(index, 1);
    this.parent = null;
  }
  click() { this.clicks += 1; if (this.failClick) throw new Error("合成下载点击失败"); }
  setAttribute(key, value) { this.attributes[key] = value; }
  removeAttribute(key) { delete this.attributes[key]; }
  addEventListener(name, listener) { this.listeners[name] = listener; }
  querySelector() { return null; }
  closest() { return this.frame || null; }
  pause() {}
  load() {}
  play() { return Promise.resolve(); }
}

async function createHarness(overrides = {}) {
  const ids = ["scope-filter", "fold-filter", "source-filter", "status-filter", "attention-filter", "audit-info", "candidate-search", "candidate-list", "pending-sources", "pending-list", "video-player", "clip-title", "clip-meta", "timeline-info", "source-reference", "view-source", "prefill-notice", "label-fields", "review-note", "decision-reason", "save-draft", "confirm-review", "return-review", "question-review", "previous-candidate", "next-candidate", "review-status", "app-message", "revision-history", "export-reviews", "export-all-revisions"];
  const tags = {"pending-sources": "details", "export-reviews": "button", "export-all-revisions": "button"};
  const elements = new Map(ids.map((id) => [id, new Element(tags[id] || "div")]));
  elements.get("scope-filter").value = overrides.scope || "development";
  /* 合成 DOM 不解析 index.html 的 hidden 属性，这里取「可见」作初值：浏览器里 hidden 会保留上一个候选
     留下的状态，所以 app.js 必须在每次选候选时显式设置提示的显隐，不能依赖 HTML 默认值。 */
  elements.get("prefill-notice").hidden = false;
  elements.get("fold-filter").value = "all";
  const videoFrame = new Element("div");
  elements.get("video-player").frame = videoFrame;
  const summary = new Element("summary");
  summary.textContent = "待处理来源及原因";
  const details = elements.get("pending-sources");
  const pendingList = elements.get("pending-list");
  details.append(summary, pendingList);
  const names = ["断裂状态", "断裂模式", "断裂位置", "异常情况.未夹紧", "异常情况.视频异常", "异常情况.爆炸性断裂", "断裂现象.伸长", "断裂现象.颈缩", "断裂现象.开裂", "断裂现象.界面分离", "断裂现象.断后脱夹"];
  const selects = names.map((name) => Object.assign(new Element("select"), {name}));
  let ready;
  let allowDiscard = false;
  const confirmTexts = [];
  const requests = [];
  const created = [];
  const requestedIds = new Set();
  const objectUrls = {created: 0, revoked: 0};
  /* Download anchors are appended to body before click; keep every append so append-then-remove stays observable. */
  const body = new Element("body");
  body.appended = [];
  body.append = (...children) => { children.forEach((child) => { if (child instanceof Element) child.parent = body; }); body.children.push(...children); body.appended.push(...children); };
  const reviewFor = (id) => overrides.reviews?.[id] || {latest: null, history: [], isolated_history: []};
  const candidates = overrides.candidates || ["candidate_one", "candidate_two", "candidate_test"].map((id) => ({candidate_id: id, source_id: "synthetic_source", source_type: "real", scope: id === "candidate_test" ? "test" : "development", folds: {}, clip_sha256: "0".repeat(64), review_status: "unreviewed", window: {}, frame_mapping: {}, source_reference: {}, candidate_reference: {"断裂状态": "已断裂"}}));
  const context = {
    document: {
      getElementById: (id) => { requestedIds.add(id); return elements.get(id); },
      querySelectorAll: () => selects,
      /* failDownloadClick 只作用于下载锚点（a），用来验证 a.click() 抛错时的清理路径。 */
      createElement: (tag) => { const node = new Element(tag); if (overrides.failDownloadClick && String(tag).toLowerCase() === "a") node.failClick = true; created.push(node); return node; },
      addEventListener: (event, callback) => { if (event === "DOMContentLoaded") ready = callback; },
      body,
    },
    window: {addEventListener() {}, confirm: (text) => { confirmTexts.push(String(text)); return allowDiscard; }, location: {href: ""}},
    /* Timers run inline: revoke timing (sync vs setTimeout) must not decide pass/fail, and a vm context has no timers of its own. */
    setTimeout: (callback, ...args) => { callback(...args); return 0; },
    clearTimeout: () => {},
    URL: {
      createObjectURL: () => { objectUrls.created += 1; return `blob:synthetic/${objectUrls.created}`; },
      revokeObjectURL: () => { objectUrls.revoked += 1; },
    },
    fetch: async (url, options = {}) => {
      requests.push({url, options});
      if (url.startsWith("/api/reviews?candidate_id=")) return {ok: true, json: async () => reviewFor(decodeURIComponent(url.split("=")[1]))};
      if (url === "/api/reviews") {
        if (overrides.saveResponse) return overrides.saveResponse;
        const body = JSON.parse(options.body);
        return {ok: true, json: async () => ({...body, review_id: "synthetic_revision"})};
      }
      if (url.startsWith("/api/export")) {
        /* exportPending 让测试把导出响应悬停在 in-flight 状态，用于观察重复点击是否产生第二个请求。 */
        if (overrides.exportPending) await overrides.exportPending;
        /* exportFailure: true keeps the generic default; an object supplies the server-shaped response verbatim. */
        if (overrides.exportFailure === true) return {ok: false, status: 500, blob: async () => ({}), json: async () => ({error: "导出失败"})};
        if (overrides.exportFailure) return overrides.exportFailure;
        return {ok: true, status: 200, blob: async () => ({size: 0}), json: async () => ({})};
      }
      assert.equal(url, "/api/bootstrap");
      return {ok: true, json: async () => ({audit_current: true, audit_status: "current", audit_message: "已匹配当前清单", audit_issue_candidate_count: 0, token: "synthetic-token", manifest_sha256: "1".repeat(64), candidates, pending_sources: [
        {source_id: "synthetic_pending", status: "pending", reason: "synthetic_reason", source_preview_available: true, source_reference: {"断裂状态": "无法确定"}},
      ], ...overrides.bootstrap})};
    },
  };
  const code = fs.readFileSync(path.join(__dirname, "../static/app.js"), "utf8");
  vm.runInNewContext(code, context);
  await ready();
  return {elements, selects, requests, videoFrame, summary, details, pendingList,
    created, requestedIds, objectUrls, body, confirmTexts,
    allowDiscard: (value) => { allowDiscard = value; }};
}

test("pending title survives, playback end keeps current candidate, explicit next plays, source preview is read only", async () => {
  const harness = await createHarness();
  const {elements, selects, requests, videoFrame, summary, details, pendingList} = harness;
  assert.equal(elements.get("clip-title").textContent, "candidate_one");
  /* 默认候选的候选标签初值只有 {"断裂状态": "已断裂"}：该字段预填，其余 10 项仍留空。 */
  assert.equal(selects[0].value, "已断裂",
    `候选标签初值应预填断裂状态为「已断裂」，实际为「${selects[0].value}」`);
  assert.ok(selects.slice(1).every((select) => select.value === ""),
    `预填源只给断裂状态，其余字段应保持空白，实际为 ${JSON.stringify(selects.map((node) => node.value))}`);
  selects[0].value = "无法判断";
  selects[0].listeners.change();
  elements.get("scope-filter").value = "test";
  await elements.get("scope-filter").listeners.change();
  assert.equal(elements.get("scope-filter").value, "development");
  assert.equal(elements.get("clip-title").textContent, "candidate_one");
  assert.equal(selects[0].value, "无法判断");
  harness.allowDiscard(true);
  assert.equal(videoFrame.dataset.state, "loading");
  elements.get("video-player").listeners.loadeddata();
  assert.equal(videoFrame.dataset.state, "loaded");
  elements.get("video-player").listeners.ended();
  assert.equal(elements.get("clip-title").textContent, "candidate_one");
  assert.ok(!requests.some(({url}) => url.includes("candidate_two")));
  assert.match(elements.get("app-message").textContent, /输入尚未保存/);
  await elements.get("next-candidate").listeners.click();
  assert.equal(elements.get("clip-title").textContent, "candidate_two");
  assert.equal(videoFrame.dataset.state, "loading");
  elements.get("video-player").listeners.loadeddata();
  assert.equal(videoFrame.dataset.state, "loaded");
  assert.ok(requests.some(({url}) => url.includes("candidate_two")));
  elements.get("scope-filter").value = "test";
  await elements.get("scope-filter").listeners.change();
  assert.equal(elements.get("clip-title").textContent, "candidate_test");
  assert.match(elements.get("clip-meta").textContent, /测试集/);
  assert.equal(elements.get("candidate-list").children.length, 1);
  assert.equal(selects[0].value, "已断裂",
    `切换候选后表单按新候选的候选标签预填断裂状态，实际为「${selects[0].value}」`);
  assert.ok(selects.slice(1).every((select) => select.value === ""),
    `新候选同样只预填断裂状态，实际为 ${JSON.stringify(selects.map((node) => node.value))}`);
  assert.equal(details.children[0], summary);
  assert.equal(details.children[1], pendingList);
  assert.equal(summary.textContent, "待处理来源及原因");
  assert.equal(pendingList.children.length, 2);
  const row = pendingList.children[1];
  assert.match(row.textContent, /synthetic_pending.*synthetic_reason/);
  const previewButton = row.children.find((child) => child instanceof Element && child.tagName === "BUTTON");
  assert.equal(previewButton.textContent, "查看原视频与源标注");
  previewButton.listeners.click();
  assert.equal(elements.get("video-player").src, "/source-media?source_id=synthetic_pending");
  assert.equal(videoFrame.dataset.state, "loading");
  elements.get("video-player").listeners.error();
  assert.equal(videoFrame.dataset.state, "error");
  assert.match(elements.get("app-message").textContent, /媒体无法播放/);
  /* 待处理来源的源标注仍是旧词「无法确定」：只读展示时映射为统一术语并保留原值，存储不动。 */
  assert.match(textOf(elements.get("source-reference")), /无法判断（原值：无法确定）/,
    `源标注里的历史旧值应显示为「无法判断（原值：无法确定）」，实际为「${textOf(elements.get("source-reference"))}」`);
  assert.equal(elements.get("review-status").textContent, "原视频只读查看");
  assert.equal(elements.get("confirm-review").disabled, true);
  assert.ok(selects.every((select) => select.disabled && select.value === ""));
  assert.equal(details.children[0], summary);
});

function candidate(id, changes = {}) {
  return {
    candidate_id: id, source_id: "synthetic_source", source_type: "real",
    scope: "development", folds: {"0": "val", "1": "train", "2": "train"},
    clip_sha256: "0".repeat(64), review_status: "unreviewed", window: {},
    frame_mapping: {}, source_reference: {"断裂状态": "发生断裂"},
    candidate_reference: {"断裂状态": "已断裂"}, review_focus: ["断裂位置"], audit_issues: [],
    ...changes,
  };
}
function visibleIds(elements) {
  return elements.get("candidate-list").children.filter((node) => node.dataset.candidateId).map((node) => node.dataset.candidateId);
}
function textOf(node) {
  return typeof node === "string" ? node : [node.textContent, ...node.children.map(textOf)].join(" ");
}
/* 表单 11 项的固定顺序，与 app.js 的 names 常量、index.html 的 select 顺序一致。 */
const LABEL_NAMES = ["断裂状态", "断裂模式", "断裂位置", "异常情况.未夹紧", "异常情况.视频异常", "异常情况.爆炸性断裂", "断裂现象.伸长", "断裂现象.颈缩", "断裂现象.开裂", "断裂现象.界面分离", "断裂现象.断后脱夹"];
function fullCandidateLabels() {
  return {
    "断裂状态": "已断裂", "断裂模式": "脆性断裂", "断裂位置": "标距内",
    "异常情况": {"未夹紧": "是", "视频异常": "否", "爆炸性断裂": "否"},
    "断裂现象": {"伸长": "是", "颈缩": "否", "开裂": "否", "界面分离": "否", "断后脱夹": "否"},
  };
}
function controlValues(selects) {
  return selects.map((node) => node.value);
}
/* 按字段名而不仅仅是「全部为空」比对：预填、残留、补「否」三类偏差都能定位到具体字段。 */
function assertLabels(selects, expected, label) {
  const actual = {};
  selects.forEach((node, index) => { actual[LABEL_NAMES[index]] = node.value; });
  assert.deepEqual(actual, expected, `${label}；实际值 ${JSON.stringify(controlValues(selects))}`);
}
function blankLabels() {
  return Object.fromEntries(LABEL_NAMES.map((name) => [name, ""]));
}

test("prefills the eleven label controls from the candidate labels and shows a draft prefill notice", async () => {
  /* 预填只是草稿初值：11 个字段都用候选标签初值起步，用户核对/修改后再确认。 */
  const {elements, selects} = await createHarness({candidates: [candidate("prefilled", {
    candidate_reference: fullCandidateLabels(),
  })]});

  assertLabels(selects, {
    "断裂状态": "已断裂", "断裂模式": "脆性断裂", "断裂位置": "标距内",
    "异常情况.未夹紧": "是", "异常情况.视频异常": "否", "异常情况.爆炸性断裂": "否",
    "断裂现象.伸长": "是", "断裂现象.颈缩": "否", "断裂现象.开裂": "否",
    "断裂现象.界面分离": "否", "断裂现象.断后脱夹": "否",
  }, "候选标签初值应逐项预填 11 个审核字段，不得留空");

  const notice = elements.get("prefill-notice");
  assert.equal(notice.hidden, false,
    "预填产生了非空值，#prefill-notice 必须可见");
  assert.match(notice.textContent, /预填/,
    `预填提示应说明这些是预填值，实际文案为「${notice.textContent}」`);
  assert.match(notice.textContent, /草稿/,
    `预填提示应说明这是草稿初值而非审核结果，实际文案为「${notice.textContent}」`);
});

test("keeps all eleven controls blank and hides the prefill notice when the candidate has no labels", async () => {
  const {elements, selects} = await createHarness({candidates: [candidate("no_labels", {
    candidate_reference: null,
  })]});

  assertLabels(selects, blankLabels(), "没有候选标签时 11 个字段必须留空");
  assert.equal(elements.get("prefill-notice").hidden, true,
    "预填源为空、没有任何有效值时 #prefill-notice 必须隐藏");
});

test("keeps missing multi-select leaves blank instead of 否 and preserves the confirm semantics", async () => {
  const {elements, selects, requests} = await createHarness({candidates: [candidate("partial", {
    candidate_reference: {"断裂状态": "已断裂", "异常情况": {"未夹紧": "是"}},
  })]});

  assertLabels(selects, {
    "断裂状态": "已断裂", "断裂模式": "", "断裂位置": "",
    "异常情况.未夹紧": "是", "异常情况.视频异常": "", "异常情况.爆炸性断裂": "",
    "断裂现象.伸长": "", "断裂现象.颈缩": "", "断裂现象.开裂": "", "断裂现象.界面分离": "", "断裂现象.断后脱夹": "",
  }, "预填源里缺失的字段必须保持空白");
  /* 空值与「否」在标注语义上不同：多选叶项缺失/为空时不得补「否」。 */
  selects.slice(4).forEach((node, offset) => assert.notEqual(node.value, "否",
    `${LABEL_NAMES[offset + 4]} 在预填源缺失时不得补「否」`));

  assert.equal(elements.get("review-status").textContent, "未审核",
    "预填不得把候选标成已审核");
  assert.ok(!requests.some(({options}) => options.method === "POST"),
    "预填本身不得发起任何 POST");

  await elements.get("confirm-review").listeners.click();

  assert.ok(!requests.some(({options}) => options.method === "POST"),
    "字段未填满时点击确认不得发出任何 POST");
  assert.match(elements.get("app-message").textContent, /11/,
    `确认提示应说明须完成 11 项，实际为「${elements.get("app-message").textContent}」`);
});

test("saved human revision overrides the candidate prefill and hides the notice", async () => {
  const latest = {review_id: "current-human", review_status: "draft", labels: {"断裂状态": "无法判断"}, note: "human note"};
  const {elements, selects} = await createHarness({candidates: [candidate("clip", {
    candidate_reference: fullCandidateLabels(),
  })], reviews: {clip: {latest, history: [latest], isolated_history: []}}});

  assertLabels(selects, {
    "断裂状态": "无法判断", "断裂模式": "", "断裂位置": "",
    "异常情况.未夹紧": "", "异常情况.视频异常": "", "异常情况.爆炸性断裂": "",
    "断裂现象.伸长": "", "断裂现象.颈缩": "", "断裂现象.开裂": "", "断裂现象.界面分离": "", "断裂现象.断后脱夹": "",
  }, "已保存修订优先：控件以 latest.labels 为准，latest 里没有的字段不得残留预填值");
  assert.equal(elements.get("prefill-notice").hidden, true,
    "已拉取到人工修订后 #prefill-notice 必须隐藏");
});

test("prefill is a draft initial value and does not count as an unsaved edit when switching candidates", async () => {
  const harness = await createHarness({candidates: [
    candidate("first", {candidate_reference: fullCandidateLabels()}), candidate("second"),
  ]});

  assert.equal(harness.elements.get("clip-title").textContent, "first");
  assert.equal(harness.selects[0].value, "已断裂",
    `首个候选应按候选标签预填，实际断裂状态为「${harness.selects[0].value}」`);

  await harness.elements.get("next-candidate").listeners.click();

  assert.deepEqual(harness.confirmTexts, [],
    `预填不算未保存输入，切换候选不应弹出未保存确认，实际弹出 ${JSON.stringify(harness.confirmTexts)}`);
  assert.equal(harness.elements.get("clip-title").textContent, "second",
    `预填后应能直接切到下一候选，实际停留在「${harness.elements.get("clip-title").textContent}」`);
});

test("saving a confirmed revision hides the draft prefill notice", async () => {
  /* 预填提示的含义是「这些值还是草稿」：人工保存已确认修订后，提示必须消失，否则用户会以为页面上的仍是生成标签。 */
  const {elements, requests} = await createHarness({candidates: [candidate("confirmed_after_prefill", {
    candidate_reference: fullCandidateLabels(),
  })]});
  const notice = elements.get("prefill-notice");

  assert.equal(notice.hidden, false,
    "完整候选标签预填后 #prefill-notice 应可见");

  await elements.get("confirm-review").listeners.click();

  const saved = requests
    .filter(({options}) => options.method === "POST")
    .map(({options}) => JSON.parse(options.body));
  assert.equal(saved.length, 1,
    `点击确认应恰好发出一次 /api/reviews POST，实际 ${saved.length} 次`);
  assert.equal(saved[0].review_status, "confirmed",
    `确认保存的 review_status 应为 confirmed，实际为「${saved[0].review_status}」`);
  assert.equal(notice.hidden, true,
    "已确认修订保存成功后 #prefill-notice 必须隐藏：预填只是草稿初值，不能继续留在已保存的人工修订旁");
  assert.equal(elements.get("review-status").textContent, "已确认",
    `保存已确认修订后审核状态应显示「已确认」，实际为「${elements.get("review-status").textContent}」`);
});

test("saving a draft revision after prefill also hides the draft prefill notice", async () => {
  /* 对称断言：草稿保存后控件里已是人工保存的值，预填提示同样不应再出现。 */
  const {elements, requests} = await createHarness({candidates: [candidate("draft_after_prefill", {
    candidate_reference: fullCandidateLabels(),
  })]});
  const notice = elements.get("prefill-notice");

  assert.equal(notice.hidden, false,
    "完整候选标签预填后 #prefill-notice 应可见");

  await elements.get("save-draft").listeners.click();

  const saved = requests
    .filter(({options}) => options.method === "POST")
    .map(({options}) => JSON.parse(options.body));
  assert.equal(saved.length, 1,
    `点击保存草稿应恰好发出一次 /api/reviews POST，实际 ${saved.length} 次`);
  assert.equal(saved[0].review_status, "draft",
    `保存草稿的 review_status 应为 draft，实际为「${saved[0].review_status}」`);
  assert.equal(notice.hidden, true,
    "草稿修订保存成功后 #prefill-notice 必须隐藏：控件里已是人工保存的值，不再是生成标签的草稿初值");
  assert.equal(elements.get("review-status").textContent, "草稿",
    `保存草稿后审核状态应显示「草稿」，实际为「${elements.get("review-status").textContent}」`);
});

test("coverage null references and focus keep all eleven human answers blank through draft save", async () => {
  const {elements, selects, requests} = await createHarness({candidates: [candidate("coverage", {
    candidate_reference: null, review_focus: null, window: {window_role: "coverage"},
  })]});
  assert.ok(selects.every((node) => node.value === ""));
  assert.match(elements.get("timeline-info").textContent, /无指定重点/);
  assert.match(textOf(elements.get("source-reference")), /发生断裂/);
  await elements.get("confirm-review").listeners.click();
  assert.ok(!requests.some(({options}) => options.method === "POST"));
  assert.match(elements.get("app-message").textContent, /11/);
  /* 确认前的提示只能提统一术语「无法判断」；出现旧词「无法确定」会让用户以为页面上有该选项。 */
  assert.doesNotMatch(elements.get("app-message").textContent, /无法确定/,
    `确认提示不应再出现旧词「无法确定」，实际为「${elements.get("app-message").textContent}」`);
  assert.match(elements.get("app-message").textContent, /无法判断/);
  await elements.get("save-draft").listeners.click();
  const saved = JSON.parse(requests.find(({options}) => options.method === "POST").options.body);
  assert.equal(saved.candidate_id, "coverage");
  assert.equal(saved.review_status, "draft");
  assert.equal(saved.expected_review_id, null);
  assert.deepEqual(saved.labels, {
    "断裂状态": "", "断裂模式": "", "断裂位置": "",
    "异常情况": {"未夹紧": "", "视频异常": "", "爆炸性断裂": ""},
    "断裂现象": {"伸长": "", "颈缩": "", "开裂": "", "界面分离": "", "断后脱夹": ""},
  });
  assert.ok(selects.every((node) => node.value === ""));
});

test("source and automatic labels stay visible references while candidate labels prefill drafts and the saved revision wins", async () => {
  const latest = {review_id: "current-human", review_status: "draft", labels: {"断裂状态": "无法确定"}, note: "human note"};
  const old = {review_id: "isolated-human", review_status: "confirmed", labels: {"断裂状态": "未断裂"}};
  const {elements, selects} = await createHarness({candidates: [candidate("clip")], reviews: {
    clip: {latest, history: [latest], isolated_history: [old]},
  }});
  /* latest.labels 是历史修订里的旧词「无法确定」：表单上必须映射为统一术语「无法判断」。 */
  assert.equal(selects[0].value, "无法判断",
    `历史修订的旧值「无法确定」应映射为表单值「无法判断」，实际为「${selects[0].value}」`);
  assert.ok(selects.slice(1).every((node) => node.value === ""),
    `latest.labels 只给断裂状态，其余字段应保持空白，实际为 ${JSON.stringify(controlValues(selects))}`);
  assert.equal(elements.get("prefill-notice").hidden, true,
    "已有已保存修订时控件以 latest.labels 为准，预填提示必须隐藏");
  assert.equal(elements.get("review-note").value, "human note");
  const reference = textOf(elements.get("source-reference"));
  assert.match(reference, /源视频标注.*发生断裂/);
  assert.match(reference, /候选标签初值.*已断裂/);
  assert.match(elements.get("timeline-info").textContent, /生成时建议关注.*断裂位置/);
  assert.match(textOf(elements.get("revision-history")), /已隔离旧身份/);
  const isolated = await createHarness({candidates: [candidate("clip")], reviews: {
    clip: {latest: null, history: [], isolated_history: [old]},
  }});
  /* 隔离的旧修订不继承，但候选标签预填仍照常生效：表单里只有候选的「已断裂」，不出现旧修订的「未断裂」。 */
  assert.equal(isolated.selects[0].value, "已断裂",
    `隔离旧修订不应进入表单；断裂状态应来自候选预填「已断裂」，实际为「${isolated.selects[0].value}」`);
  assert.equal(isolated.selects.slice(1).every((node) => node.value === ""), true,
    `除候选预填的断裂状态外不应有其他旧修订残留，实际为 ${JSON.stringify(controlValues(isolated.selects))}`);
  /* 旧标注/旧清单里的参考值只作显示：统一为「无法判断（原值：旧词）」，不预填表单也不改存储值。 */
  const legacy = await createHarness({candidates: [candidate("legacy", {
    source_reference: {"断裂状态": "无法确定"}, candidate_reference: {"断裂模式": "无法识别"},
  })]});
  const legacyReference = textOf(legacy.elements.get("source-reference"));
  assert.match(legacyReference, /源视频标注.*无法判断（原值：无法确定）/,
    `源标注里的旧值应显示为「无法判断（原值：无法确定）」，实际为「${legacyReference}」`);
  assert.match(legacyReference, /候选标签初值.*无法判断（原值：无法识别）/,
    `候选初值里的旧值应显示为「无法判断（原值：无法识别）」，实际为「${legacyReference}」`);
  /* 源标注仍只作参考、不预填；候选标签初值则作为草稿初值进入表单，旧词先映射为统一术语。 */
  assert.equal(legacy.selects[0].value, "",
    `源视频标注不得预填审核值，实际断裂状态为「${legacy.selects[0].value}」`);
  assert.equal(legacy.selects[1].value, "无法判断",
    `候选标签初值里的旧词「无法识别」应映射为「无法判断」后预填，实际为「${legacy.selects[1].value}」`);
  assert.ok(legacy.selects.filter((node, index) => index !== 1).every((node) => node.value === ""),
    `除预填的断裂模式外其余字段应保持空白，实际为 ${JSON.stringify(controlValues(legacy.selects))}`);
});

test("three fold filters inherit membership and compose with scope, source, status, attention and search", async () => {
  const candidates = [
    candidate("dev_a", {source_id: "source_a", audit_issues: ["synthetic attention"]}),
    candidate("dev_b", {source_id: "source_b", source_type: "virtual", review_status: "draft", folds: {"0": "train", "1": "val", "2": "train"}}),
    candidate("dev_c", {source_id: "source_c", folds: {"0": "train", "1": "train", "2": "val"}}),
    candidate("fixed_test", {scope: "test", folds: {"0": "test", "1": "test", "2": "test"}}),
  ];
  const {elements} = await createHarness({scope: "all", candidates});
  const cases = [
    ["0:train", ["dev_b", "dev_c"]], ["0:val", ["dev_a"]],
    ["1:train", ["dev_a", "dev_c"]], ["1:val", ["dev_b"]],
    ["2:train", ["dev_a", "dev_b"]], ["2:val", ["dev_c"]],
  ];
  for (const [filter, expected] of cases) {
    elements.get("fold-filter").value = filter;
    await elements.get("fold-filter").listeners.change();
    assert.deepEqual(visibleIds(elements), expected);
  }
  elements.get("fold-filter").value = "2:train";
  await elements.get("fold-filter").listeners.change();
  elements.get("source-filter").value = "virtual";
  await elements.get("source-filter").listeners.change();
  assert.deepEqual(visibleIds(elements), ["dev_b"]);
  elements.get("status-filter").value = "draft";
  await elements.get("status-filter").listeners.change();
  assert.deepEqual(visibleIds(elements), ["dev_b"]);
  elements.get("candidate-search").value = "source_b";
  await elements.get("candidate-search").listeners.input();
  assert.deepEqual(visibleIds(elements), ["dev_b"]);
  elements.get("attention-filter").value = "attention";
  await elements.get("attention-filter").listeners.change();
  assert.deepEqual(visibleIds(elements), []);
  elements.get("source-filter").value = "";
  elements.get("status-filter").value = "";
  elements.get("candidate-search").value = "";
  await elements.get("attention-filter").listeners.change();
  assert.deepEqual(visibleIds(elements), ["dev_a"]);
  elements.get("scope-filter").value = "test";
  await elements.get("scope-filter").listeners.change();
  assert.deepEqual(visibleIds(elements), []);
  elements.get("attention-filter").value = "all";
  await elements.get("attention-filter").listeners.change();
  elements.get("fold-filter").value = "all";
  await elements.get("fold-filter").listeners.change();
  assert.deepEqual(visibleIds(elements), ["fixed_test"]);
});

test("mismatched audit disables attention filtering and exposes its warning", async () => {
  const {elements} = await createHarness({candidates: [candidate("clip")], bootstrap: {
    audit_current: false, audit_status: "mismatch", audit_message: "核验记录与当前清单哈希不匹配；问题提示未映射。",
  }});
  assert.equal(elements.get("attention-filter").disabled, true);
  assert.match(elements.get("audit-info").textContent, /哈希不匹配/);
  assert.doesNotMatch(elements.get("timeline-info").textContent, /待复核/);
});

test("save conflict leaves human input available and never advances to another clip", async () => {
  const {elements, selects, requests} = await createHarness({
    candidates: [candidate("first"), candidate("second")],
    saveResponse: {ok: false, status: 409, json: async () => ({error: "存在其他修订；请重载后核对"})},
  });
  selects[0].value = "无法判断";
  selects[0].listeners.change();
  await elements.get("save-draft").listeners.click();
  assert.equal(elements.get("clip-title").textContent, "first");
  assert.equal(selects[0].value, "无法判断");
  assert.match(elements.get("app-message").textContent, /其他修订/);
  assert.equal(elements.get("app-message").attributes.role, "alert");
  assert.ok(!requests.some(({url}) => url.includes("candidate_id=second")));
  assert.equal(elements.get("save-draft").disabled, false);
});

function exportRequests(harness) {
  return harness.requests.filter(({url}) => url.split("?")[0] === "/api/export");
}
/* The download file is the element carrying a download attribute; body.appended keeps append-then-remove anchors visible. */
function exportDownload(harness) {
  return [...harness.created, ...harness.body.appended].find((node) => node instanceof Element && typeof node.download === "string");
}
async function clickControl(elements, id) {
  const node = elements.get(id);
  assert.ok(node, `页面应当存在 #${id} 元素`);
  assert.equal(typeof node.listeners.click, "function", `#${id} 应绑定 click 处理函数（index.html 缺少该控件或 app.js 未绑定）；当前实现未绑定`);
  await node.listeners.click();
}

test("export button downloads the latest reviews as subvideo-reviews.jsonl and reports success", async () => {
  const harness = await createHarness({candidates: [candidate("clip")]});

  await clickControl(harness.elements, "export-reviews");

  const latest = exportRequests(harness).find(({url}) => !url.includes("all_revisions=1"));
  assert.ok(latest, "点击导出应实际请求 /api/export 获取最新修订；仅给 window.location.href 赋值不算导出");
  const file = exportDownload(harness);
  assert.ok(file, "导出应创建带 download 属性的下载链接");
  assert.equal(file.download, "subvideo-reviews.jsonl");
  assert.ok(harness.body.appended.includes(file), "下载链接应先挂到 document.body 再触发点击");
  assert.ok(file.clicks > 0, "下载链接应被 click 触发，而不是只创建不点击");
  /* harness 的 remove() 现在真的解绑，这条才能区分「代码调用了 remove」与「锚点其实留在 body 里」。 */
  assert.ok(!harness.body.children.includes(file), "下载链接点击后应从 document.body 移除，不能残留孤儿节点");
  assert.equal(file.removed, 1, "下载链接应被 remove() 移除恰好一次");
  assert.match(harness.elements.get("app-message").textContent, /导出/);
  assert.notEqual(harness.elements.get("app-message").attributes.role, "alert");
  assert.ok(harness.objectUrls.created >= 1, "成功导出应创建 blob URL 供下载链接使用");
  /* 只要求成对释放，不锁死同步/异步时机：harness 的 setTimeout 内联执行，两种实现都满足 revoked >= created。 */
  assert.ok(harness.objectUrls.revoked >= harness.objectUrls.created,
    `成功导出后应撤销每个 blob URL，实际创建 ${harness.objectUrls.created} 次、撤销 ${harness.objectUrls.revoked} 次`);
});

test("all-revisions export requests all_revisions=1 and downloads subvideo-reviews-history.jsonl", async () => {
  const harness = await createHarness({candidates: [candidate("clip")]});

  await clickControl(harness.elements, "export-all-revisions");

  assert.ok(exportRequests(harness).some(({url}) => url.includes("all_revisions=1")),
    "查看全部修订的导出应请求 /api/export?all_revisions=1");
  const file = exportDownload(harness);
  assert.ok(file, "导出应创建带 download 属性的下载链接");
  assert.equal(file.download, "subvideo-reviews-history.jsonl");
});

test("export failure surfaces an alert message instead of a silent download", async () => {
  /* server.py 的 assert_manifest() 走 409 + {"error": ...}；这条文案是用户唯一能据此行动的线索。 */
  const serverError = "生成清单在服务启动后已变化；请先记录未保存输入并重启。";
  const harness = await createHarness({candidates: [candidate("clip")], exportFailure: {
    ok: false, status: 409, blob: async () => ({}), json: async () => ({error: serverError}),
  }});

  await clickControl(harness.elements, "export-reviews");

  const message = harness.elements.get("app-message");
  assert.equal(message.attributes.role, "alert", "导出失败必须用 role=alert 明确告知，不能静默");
  assert.ok(message.textContent.trim().length > 0, "导出失败的 app-message 不能为空");
  /* 仅匹配 /导出失败|409/ 不能通过：必须是服务端 JSON error 原文的片段，否则用户拿不到可行动的说明。 */
  assert.match(message.textContent, /生成清单在服务启动后已变化/,
    `导出失败时 app-message 应包含服务端 error 文案「${serverError}」的片段，实际为「${message.textContent}」——当前实现丢弃了 JSON error，只剩状态码文案`);
  assert.equal(exportDownload(harness), undefined, "导出失败时不应仍然下载文件");
});

test("plain-text 500 export failure falls back to the status-code message", async () => {
  /* 代理或网关可能返回 HTML 错误页，response.json() 会抛 SyntaxError；此时仍须给出可读的状态码文案。 */
  const harness = await createHarness({candidates: [candidate("clip")], exportFailure: {
    ok: false, status: 500, blob: async () => ({}),
    json: async () => { throw new SyntaxError("Unexpected token < in JSON at position 0"); },
  }});

  await clickControl(harness.elements, "export-reviews");

  const message = harness.elements.get("app-message");
  assert.equal(message.attributes.role, "alert", "非 JSON 的失败响应同样必须用 role=alert 告知，不能静默");
  /* 必须锁住具体的「导出失败 (500)」：app.js 若去掉解析 JSON 的内层 try/catch，文案会变成 SyntaxError 的 message 而不再包含状态码。 */
  assert.match(message.textContent, /导出失败 \(500\)/,
    `响应体不是 JSON 时应回退到状态码文案「导出失败 (500)」，实际为「${message.textContent}」`);
  assert.equal(exportDownload(harness), undefined, "导出失败时不应仍然创建下载链接");
  assert.equal(harness.objectUrls.created, 0, "导出失败时不应创建 blob URL");
});

test("export error detail prefers a string message when the error field is an object", async () => {
  /* 服务端可能返回 {"error": {"code": ...}, "message": "..."}；只取 value.error 会把对象当文案丢掉，用户看不到真正原因。 */
  const harness = await createHarness({candidates: [candidate("clip")], exportFailure: {
    ok: false, status: 400, blob: async () => ({}),
    json: async () => ({error: {code: "X"}, message: "清单身份不匹配，请重载后核对。"}),
  }});

  await clickControl(harness.elements, "export-reviews");

  const message = harness.elements.get("app-message");
  assert.equal(message.attributes.role, "alert", "导出失败必须用 role=alert 明确告知");
  assert.match(message.textContent, /清单身份不匹配/,
    `error 字段是对象时应退回字符串 message，实际文案为「${message.textContent}」——当前实现 value?.error || value?.message 短路后丢弃了 message`);
});

test("a second export click while an export is in flight does not start another request", async () => {
  /* 导出期间重复点击（包括改点另一个导出按钮）不应产生第二个请求，且完成后按钮必须恢复可用。 */
  let releaseExport;
  const exportPending = new Promise((resolve) => { releaseExport = resolve; });
  const harness = await createHarness({candidates: [candidate("clip")], exportPending});
  const reviewsButton = harness.elements.get("export-reviews");
  const historyButton = harness.elements.get("export-all-revisions");

  /* 不等待第一次点击完成就点第二次；这里直接调 listeners.click()，浏览器对 disabled 的抑制不会被模拟。 */
  const first = reviewsButton.listeners.click();
  const second = historyButton.listeners.click();

  assert.equal(exportRequests(harness).length, 1,
    `导出进行中再次点击不应发起第二个 /api/export 请求，实际 ${exportRequests(harness).length} 个`);

  releaseExport();
  await Promise.all([first, second]);

  /* 只要求「不处于禁用态」：禁用按钮与 in-flight 标记两种实现都满足，不断言 disabled 恰为 false 而非 undefined。 */
  assert.ok(!reviewsButton.disabled, "导出完成后 export-reviews 不应停留在禁用态");
  assert.ok(!historyButton.disabled, "导出完成后 export-all-revisions 不应停留在禁用态");
  const settled = exportRequests(harness).length;
  await clickControl(harness.elements, "export-reviews");
  assert.ok(exportRequests(harness).length > settled, "导出完成后再次点击应能发起新的导出请求");
});

test("download anchor click failure still cleans the DOM and revokes the blob URL", async () => {
  /* 沙箱或浏览器在 a.click() 抛错时，链接清理与 blob 释放不能被跳过，否则 DOM 累积孤儿节点、blob URL 泄漏。 */
  const harness = await createHarness({candidates: [candidate("clip")], failDownloadClick: true});

  await clickControl(harness.elements, "export-reviews");

  const message = harness.elements.get("app-message");
  assert.equal(message.attributes.role, "alert", "下载触发失败必须用 role=alert 告知，不能静默");
  const file = exportDownload(harness);
  assert.ok(file, "下载链接应已创建（body.appended 记录 append-then-remove，锚点移除后仍可观察）");
  assert.ok(harness.body.appended.includes(file), "下载链接应先挂到 document.body 再触发点击");
  assert.ok(!harness.body.children.includes(file),
    "下载锚点 click() 抛错后也必须从 document.body 移除，不能残留孤儿节点");
  assert.ok(harness.objectUrls.created >= 1, "成功取得 blob 后应创建 blob URL");
  assert.ok(harness.objectUrls.revoked >= harness.objectUrls.created,
    `click() 抛错时 blob URL 仍须释放，实际创建 ${harness.objectUrls.created} 次、撤销 ${harness.objectUrls.revoked} 次`);
});

test("every getElementById lookup during start and export clicks resolves an id declared in index.html", async () => {
  const harness = await createHarness({candidates: [candidate("clip")]});
  // Cover the export handlers too; an unbound handler is reported by the export cases above.
  for (const id of ["export-reviews", "export-all-revisions"]) {
    const listener = harness.elements.get(id).listeners.click;
    if (typeof listener === "function") await listener();
  }

  const html = fs.readFileSync(path.join(__dirname, "../static/index.html"), "utf8");
  const declared = new Set([...html.matchAll(/\sid="([^"]+)"/g)].map(([, id]) => id));
  // Only ids looked up via getElementById are compared; nodes built by createElement have no id attribute.
  const missing = [...harness.requestedIds].filter((id) => !declared.has(id)).sort();
  assert.deepEqual(missing, [], `app.js 通过 getElementById 请求了 index.html 中不存在的 id（死分支）：${missing.join("、")}`);
});
