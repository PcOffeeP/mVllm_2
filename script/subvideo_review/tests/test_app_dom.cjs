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
  }
  replaceChildren(...children) { this.children = children; }
  append(...children) { this.children.push(...children); }
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
  const ids = ["scope-filter", "fold-filter", "source-filter", "status-filter", "attention-filter", "audit-info", "candidate-search", "candidate-list", "pending-sources", "pending-list", "video-player", "clip-title", "clip-meta", "timeline-info", "source-reference", "view-source", "label-fields", "review-note", "decision-reason", "save-draft", "confirm-review", "return-review", "question-review", "previous-candidate", "next-candidate", "review-status", "app-message", "revision-history"];
  const elements = new Map(ids.map((id) => [id, new Element(id === "pending-sources" ? "details" : "div")]));
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
  const reviewFor = (id) => overrides.reviews?.[id] || {latest: null, history: [], isolated_history: []};
  const candidates = overrides.candidates || ["candidate_one", "candidate_two", "candidate_test"].map((id) => ({candidate_id: id, source_id: "synthetic_source", source_type: "real", scope: id === "candidate_test" ? "test" : "development", folds: {}, clip_sha256: "0".repeat(64), review_status: "unreviewed", window: {}, frame_mapping: {}, source_reference: {}, candidate_reference: {"断裂状态": "已断裂"}}));
  const context = {
    document: {
      getElementById: (id) => elements.get(id),
      querySelectorAll: () => selects,
      createElement: (tag) => new Element(tag),
      addEventListener: (event, callback) => { if (event === "DOMContentLoaded") ready = callback; },
    },
    window: {addEventListener() {}, confirm: () => allowDiscard},
    fetch: async (url, options = {}) => {
      requests.push({url, options});
      if (url.startsWith("/api/reviews?candidate_id=")) return {ok: true, json: async () => reviewFor(decodeURIComponent(url.split("=")[1]))};
      if (url === "/api/reviews") {
        if (overrides.saveResponse) return overrides.saveResponse;
        const body = JSON.parse(options.body);
        return {ok: true, json: async () => ({...body, review_id: "synthetic_revision"})};
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
