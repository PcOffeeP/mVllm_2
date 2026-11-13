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
  }
  replaceChildren(...children) { this.children = children; }
  append(...children) { this.children.push(...children); }
  removeChild(child) { const index = this.children.indexOf(child); if (index >= 0) this.children.splice(index, 1); return child; }
  remove() {}
  click() { this.clicks += 1; }
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
  const ids = ["scope-filter", "fold-filter", "source-filter", "status-filter", "attention-filter", "audit-info", "candidate-search", "candidate-list", "pending-sources", "pending-list", "video-player", "clip-title", "clip-meta", "timeline-info", "source-reference", "view-source", "label-fields", "review-note", "decision-reason", "save-draft", "confirm-review", "return-review", "question-review", "previous-candidate", "next-candidate", "review-status", "app-message", "revision-history", "export-reviews", "export-all-revisions"];
  const tags = {"pending-sources": "details", "export-reviews": "button", "export-all-revisions": "button"};
  const elements = new Map(ids.map((id) => [id, new Element(tags[id] || "div")]));
  elements.get("scope-filter").value = overrides.scope || "development";
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
  const requests = [];
  const created = [];
  const requestedIds = new Set();
  const objectUrls = {created: 0, revoked: 0};
  /* Download anchors are appended to body before click; keep every append so append-then-remove stays observable. */
  const body = new Element("body");
  body.appended = [];
  body.append = (...children) => { body.children.push(...children); body.appended.push(...children); };
  const reviewFor = (id) => overrides.reviews?.[id] || {latest: null, history: [], isolated_history: []};
  const candidates = overrides.candidates || ["candidate_one", "candidate_two", "candidate_test"].map((id) => ({candidate_id: id, source_id: "synthetic_source", source_type: "real", scope: id === "candidate_test" ? "test" : "development", folds: {}, clip_sha256: "0".repeat(64), review_status: "unreviewed", window: {}, frame_mapping: {}, source_reference: {}, candidate_reference: {"断裂状态": "已断裂"}}));
  const context = {
    document: {
      getElementById: (id) => { requestedIds.add(id); return elements.get(id); },
      querySelectorAll: () => selects,
      createElement: (tag) => { const node = new Element(tag); created.push(node); return node; },
      addEventListener: (event, callback) => { if (event === "DOMContentLoaded") ready = callback; },
      body,
    },
    window: {addEventListener() {}, confirm: () => allowDiscard, location: {href: ""}},
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
    created, requestedIds, objectUrls, body,
    allowDiscard: (value) => { allowDiscard = value; }};
}

test("pending title survives, playback end keeps current candidate, explicit next plays, source preview is read only", async () => {
  const harness = await createHarness();
  const {elements, selects, requests, videoFrame, summary, details, pendingList} = harness;
  assert.equal(elements.get("clip-title").textContent, "candidate_one");
  assert.ok(selects.every((select) => select.value === ""));
  selects[0].value = "无法确定";
  selects[0].listeners.change();
  elements.get("scope-filter").value = "test";
  await elements.get("scope-filter").listeners.change();
  assert.equal(elements.get("scope-filter").value, "development");
  assert.equal(elements.get("clip-title").textContent, "candidate_one");
  assert.equal(selects[0].value, "无法确定");
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
  assert.ok(selects.every((select) => select.value === ""));
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

test("source and automatic labels are visible references while only current human revision fills controls", async () => {
  const latest = {review_id: "current-human", review_status: "draft", labels: {"断裂状态": "无法确定"}, note: "human note"};
  const old = {review_id: "isolated-human", review_status: "confirmed", labels: {"断裂状态": "未断裂"}};
  const {elements, selects} = await createHarness({candidates: [candidate("clip")], reviews: {
    clip: {latest, history: [latest], isolated_history: [old]},
  }});
  assert.equal(selects[0].value, "无法确定");
  assert.ok(selects.slice(1).every((node) => node.value === ""));
  assert.equal(elements.get("review-note").value, "human note");
  const reference = textOf(elements.get("source-reference"));
  assert.match(reference, /源视频标注.*发生断裂/);
  assert.match(reference, /候选标签初值.*已断裂/);
  assert.match(elements.get("timeline-info").textContent, /生成时建议关注.*断裂位置/);
  assert.match(textOf(elements.get("revision-history")), /已隔离旧身份/);
  const isolated = await createHarness({candidates: [candidate("clip")], reviews: {
    clip: {latest: null, history: [], isolated_history: [old]},
  }});
  assert.ok(isolated.selects.every((node) => node.value === ""));
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
  selects[0].value = "无法确定";
  selects[0].listeners.change();
  await elements.get("save-draft").listeners.click();
  assert.equal(elements.get("clip-title").textContent, "first");
  assert.equal(selects[0].value, "无法确定");
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
