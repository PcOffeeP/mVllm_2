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
  addEventListener(name, listener) { this.listeners[name] = listener; }
  querySelector() { return null; }
  closest() { return this.frame || null; }
  pause() {}
  load() {}
  play() { return Promise.resolve(); }
}

test("pending title survives, playback end keeps current candidate, explicit next plays, source preview is read only", async () => {
  const ids = ["source-filter", "status-filter", "candidate-search", "candidate-list", "pending-sources", "pending-list", "video-player", "clip-title", "clip-meta", "timeline-info", "source-reference", "label-fields", "review-note", "decision-reason", "save-draft", "confirm-review", "return-review", "question-review", "previous-candidate", "next-candidate", "review-status", "app-message", "revision-history"];
  const elements = new Map(ids.map((id) => [id, new Element(id === "pending-sources" ? "details" : "div")]));
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
  const requests = [];
  const candidates = ["candidate_one", "candidate_two"].map((id) => ({candidate_id: id, source_id: "synthetic_source", source_type: "real", clip_sha256: "0".repeat(64), review_status: "unreviewed", window: {}, frame_mapping: {}, source_reference: {}}));
  const context = {
    document: {
      getElementById: (id) => elements.get(id),
      querySelectorAll: () => selects,
      createElement: (tag) => new Element(tag),
      addEventListener: (event, callback) => { if (event === "DOMContentLoaded") ready = callback; },
    },
    window: {addEventListener() {}},
    fetch: async (url) => {
      requests.push(url);
      if (url.startsWith("/api/reviews?candidate_id=")) return {ok: true, json: async () => ({latest: null, history: [], isolated_history: []})};
      assert.equal(url, "/api/bootstrap");
      return {ok: true, json: async () => ({candidates, pending_sources: [
        {source_id: "synthetic_pending", status: "pending", reason: "synthetic_reason", source_preview_available: true, source_reference: {"断裂状态": "无法确定"}},
      ]})};
    },
  };
  const code = fs.readFileSync(path.join(__dirname, "../static/app.js"), "utf8");
  vm.runInNewContext(code, context);
  await ready();
  assert.equal(elements.get("clip-title").textContent, "candidate_one");
  assert.equal(videoFrame.dataset.state, "loading");
  elements.get("video-player").listeners.loadeddata();
  assert.equal(videoFrame.dataset.state, "loaded");
  elements.get("video-player").listeners.ended();
  assert.equal(elements.get("clip-title").textContent, "candidate_one");
  assert.ok(!requests.some((url) => url.includes("candidate_two")));
  assert.match(elements.get("app-message").textContent, /请填写并确认/);
  await elements.get("next-candidate").listeners.click();
  assert.equal(elements.get("clip-title").textContent, "candidate_two");
  assert.equal(videoFrame.dataset.state, "loading");
  elements.get("video-player").listeners.loadeddata();
  assert.equal(videoFrame.dataset.state, "loaded");
  assert.ok(requests.some((url) => url.includes("candidate_two")));
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
