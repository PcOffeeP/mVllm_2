/* Synthetic DOM contract test, using Node's built-in runner and no media/network.
 *
 * 契约范围（本轮前端改造，测试先行 = 红阶段）：
 *   A. 播放进度条：#clip-progress / #clip-time / #step-back / #step-forward；
 *   B. 左侧候选列表可折叠：#toggle-candidates + #main-content.is-collapsed + localStorage 记忆；
 *   C. 文案：确认按钮「确认完成，进入下一个」、确认后自动前进、#clip-meta 三折可读 + SHA256 折叠；
 *   D. 源标签就近对比：11 个 .source-hint[data-source-hint] 显示各自控件的源视频标注；
 *   E. static/index.html 的静态结构断言 + CSP 自检（无内联 handler / style / script / 远程资源）。
 *
 * 合成 DOM 只实现被断言的能力：Element 桩、11 个 select 桩、11 个 .source-hint 桩、
 * localStorage 桩（可抛错）、#video-player 的可写 currentTime/duration。不做选择器作用域建模。
 */
const assert = require("node:assert/strict");
const test = require("node:test");
const vm = require("node:vm");
const fs = require("node:fs");
const path = require("node:path");

/* 表单 11 项的固定顺序，与 app.js 的 names 常量、index.html 的 select 顺序一致。 */
const LABEL_NAMES = ["断裂状态", "断裂模式", "断裂位置", "异常情况.未夹紧", "异常情况.视频异常", "异常情况.爆炸性断裂", "断裂现象.伸长", "断裂现象.颈缩", "断裂现象.开裂", "断裂现象.界面分离", "断裂现象.断后脱夹"];
/* 控件 name → candidate.source_reference 里的键（D 段映射表；源标注与审核字段不是一一同名）。 */
const SOURCE_HINT_KEYS = {
  "断裂状态": "断裂状态",
  "断裂模式": "断裂模式",
  "断裂位置": "断裂位置",
  "异常情况.未夹紧": "异常_未夹紧",
  "异常情况.视频异常": "异常_视频异常",
  "异常情况.爆炸性断裂": "异常_爆炸性断裂",
  "断裂现象.伸长": "现象_伸长",
  "断裂现象.颈缩": "现象_颈缩",
  "断裂现象.开裂": "现象_开裂",
  "断裂现象.界面分离": "现象_界面分离",
  "断裂现象.断后脱夹": "现象_断后脱夹",
};
/* 11 个审核控件在 index.html 里的 id（E 段：一个不少）。 */
const SELECT_IDS = ["fracture-status", "fracture-mode", "fracture-location", "abnormal-unclamped", "abnormal-video", "abnormal-explosive", "phenomenon-elongation", "phenomenon-necking", "phenomenon-cracking", "phenomenon-interface-separation", "phenomenon-post-fracture-release"];

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
    /* 消息条滚动契约（F3）只观察「是否被调用」，参数形式原样记录、不做形状断言。 */
    this.scrollCalls = [];
    /* classList 桩：折叠契约要断言 #main-content 上的 is-collapsed 类，内部集合暴露出来便于直接读取。 */
    this.classes = new Set();
    const classes = this.classes;
    this.classList = {
      add: (...classNames) => { classNames.forEach((name) => classes.add(String(name))); },
      remove: (...classNames) => { classNames.forEach((name) => classes.delete(String(name))); },
      toggle: (name, force) => {
        const key = String(name);
        const shouldAdd = force === undefined ? !classes.has(key) : Boolean(force);
        if (shouldAdd) classes.add(key); else classes.delete(key);
        return shouldAdd;
      },
      contains: (name) => classes.has(String(name)),
    };
  }
  /* 真实 DOM 里 el.title = x 会写回 title 属性；桩把两者打通，测试既可读 attribute 也可读属性。 */
  get title() { return this.attributes.title === undefined ? "" : this.attributes.title; }
  set title(value) { this.attributes.title = String(value); }
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
  scrollIntoView(options) { this.scrollCalls.push(options); }
  setAttribute(key, value) { this.attributes[key] = value; }
  removeAttribute(key) { delete this.attributes[key]; }
  addEventListener(name, listener) { this.listeners[name] = listener; }
  querySelector() { return null; }
  /* 元素级 querySelectorAll 与 document 级共用同一套桩集合：测试不锁定「从哪儿查」的实现细节。 */
  querySelectorAll(selector) { return this.ownerQuerySelectorAll ? this.ownerQuerySelectorAll(selector) : []; }
  closest() { return this.frame || null; }
  pause() {}
  /* 浏览器在 load()/切换 src 后会把 currentTime 归零、duration 变回未知；桩照此语义重置，
     这样「切换候选重置进度」既可由 JS 显式重置、也可由浏览器语义满足，不逼实现二选一。 */
  load() { this.currentTime = 0; this.duration = NaN; }
  play() { return Promise.resolve(); }
}

/* 合成页面桩住的 id 清单（hoist 到模块作用域：「required / harness / index.html 三处 id 一致」静态守卫要复用它）。 */
const HARNESS_IDS = ["scope-filter", "fold-filter", "source-filter", "status-filter", "attention-filter", "audit-info", "candidate-search", "candidate-list", "pending-sources", "pending-list", "video-player", "clip-title", "clip-meta", "timeline-info", "source-reference", "view-source", "prefill-notice", "label-fields", "review-note", "decision-reason", "save-draft", "confirm-review", "return-review", "question-review", "previous-candidate", "next-candidate", "review-status", "app-message", "revision-history", "export-reviews", "export-all-revisions",
  /* 前端改造新增的控件（A/B/C/D 契约依赖） */
  "main-content", "toggle-candidates", "candidate-panel-body", "clip-progress", "clip-time", "step-back", "step-forward", "timeline-list", "source-extras-body", "clip-sha", "clip-sha-value",
  /* 第二轮新增：#candidate-count 的「当前筛选数 / 总数」回归 */
  "candidate-count"];

async function createHarness(overrides = {}) {
  const ids = HARNESS_IDS;
  const tags = {
    "pending-sources": "details", "source-reference": "details", "clip-sha": "details",
    "export-reviews": "button", "export-all-revisions": "button", "confirm-review": "button",
    "toggle-candidates": "button", "step-back": "button", "step-forward": "button",
    "clip-progress": "input",
  };
  const elements = new Map(ids.map((id) => [id, new Element(tags[id] || "div")]));
  elements.get("scope-filter").value = overrides.scope || "development";
  /* 合成 DOM 不解析 index.html 的 hidden 属性，这里取「可见」作初值：浏览器里 hidden 会保留上一个候选
     留下的状态，所以 app.js 必须在每次选候选时显式设置提示的显隐，不能依赖 HTML 默认值。 */
  elements.get("prefill-notice").hidden = false;
  elements.get("fold-filter").value = "all";
  /* 折叠开关的初始态来自 index.html 的静态属性（aria-expanded="true"、文案「收起列表」）。
     桩按浏览器语义预置，避免测试要求 app.js 重复写死初始值；静态声明由 E 段单独断言。 */
  const toggle = elements.get("toggle-candidates");
  toggle.textContent = "收起列表";
  toggle.setAttribute("aria-expanded", "true");
  toggle.setAttribute("aria-controls", "candidate-panel-body");
  /* 进度条读数与滑块初值同样来自 index.html 的静态值。 */
  elements.get("clip-progress").value = "0";
  elements.get("clip-time").textContent = "0.00s / 0.00s";
  /* #candidate-count 的初值同样来自 index.html；JS 必须在每次 renderList() 后更新它。 */
  elements.get("candidate-count").textContent = "等待载入";
  /* #app-message 的每次写入都留痕：历史刷新失败这类「独立提示」可能与保存提示先后覆盖，
     只有看到整条提示流，才能既断言最终文案、又断言该提示确实出现过。 */
  const appMessage = elements.get("app-message");
  const messages = [];
  let appMessageText = "";
  Object.defineProperty(appMessage, "textContent", {
    configurable: true,
    get() { return appMessageText; },
    set(value) { appMessageText = String(value); messages.push(appMessageText); },
  });
  const videoFrame = new Element("div");
  const video = elements.get("video-player");
  video.frame = videoFrame;
  video.currentTime = 0;
  video.duration = NaN;
  /* play() 计数：自动播放契约要观察「是否尝试播放」；rejected 分支要验证提示且不崩。 */
  video.playCalls = 0;
  video.play = () => {
    video.playCalls += 1;
    return overrides.playRejects ? Promise.reject(new Error("NotAllowedError: 自动播放被拒绝")) : Promise.resolve();
  };
  const summary = new Element("summary");
  summary.textContent = "待处理来源及原因";
  const details = elements.get("pending-sources");
  const pendingList = elements.get("pending-list");
  details.append(summary, pendingList);
  /* #source-reference 改成 details 结构：summary 是开合入口，其余源标注信息进 #source-extras-body。
     app.js 只允许重写 source-extras-body 的内容，不得清掉 summary。 */
  const sourceSummary = new Element("summary");
  sourceSummary.textContent = "其余源标注信息（非五类标签）";
  const sourceReference = elements.get("source-reference");
  const sourceExtras = elements.get("source-extras-body");
  sourceReference.append(sourceSummary, sourceExtras);
  /* #timeline-info 只重写子容器 #timeline-list 的内容。 */
  const timelineInfo = elements.get("timeline-info");
  const timelineList = elements.get("timeline-list");
  timelineInfo.append(timelineList);
  const names = LABEL_NAMES;
  const selects = names.map((name) => Object.assign(new Element("select"), {name}));
  /* 11 个 .source-hint 桩：dataset.sourceHint 与控件 name 一一对应，初始文案与 index.html 一致。 */
  const hints = names.map((name) => {
    const hint = new Element("span");
    hint.dataset.sourceHint = name;
    hint.textContent = "源视频：未标注";
    hint.classList.add("source-hint");
    return hint;
  });
  let ready;
  let allowDiscard = false;
  const confirmTexts = [];
  const requests = [];
  const created = [];
  const requestedIds = new Set();
  const objectUrls = {created: 0, revoked: 0};
  /* localStorage 桩：折叠状态必须被记住，但断言不依赖具体 key 名（见 B 段的快照复用法）。 */
  const storageStore = {...(overrides.storedCollapse || {})};
  const storageGuard = () => { if (overrides.throwStorage) throw new Error("localStorage 被禁用"); };
  const localStorageStub = {
    getItem: (key) => { storageGuard(); const name = String(key); return Object.prototype.hasOwnProperty.call(storageStore, name) ? String(storageStore[name]) : null; },
    setItem: (key, value) => { storageGuard(); storageStore[String(key)] = String(value); },
    removeItem: (key) => { storageGuard(); delete storageStore[String(key)]; },
  };
  /* 选择器分派：源标签提示与 11 个 select 是两类桩，其余选择器沿用「返回 11 个 select」的既有行为。 */
  const querySelectorAll = (selector) => {
    const text = String(selector);
    if (text.includes("source-hint") || text.includes("data-source-hint")) return hints;
    return selects;
  };
  elements.forEach((node) => { node.ownerQuerySelectorAll = querySelectorAll; });
  /* Download anchors are appended to body before click; keep every append so append-then-remove stays observable. */
  const body = new Element("body");
  body.appended = [];
  body.append = (...children) => { children.forEach((child) => { if (child instanceof Element) child.parent = body; }); body.children.push(...children); body.appended.push(...children); };
  /* 可控时钟（F5）：「距保存多久」必须由测试决定，不能依赖真实时间。vm 沙箱自带 Date，
     宿主侧打桩对沙箱无效，所以显式注入一个可推进的 Date 实现；初始值固定，用例之间互不影响。 */
  const clock = {value: 1_700_000_000_000};
  class ClockDate extends Date {
    constructor(...args) { if (args.length === 0) super(clock.value); else super(...args); }
    static now() { return clock.value; }
  }
  const reviewFor = (id) => overrides.reviews?.[id] || {latest: null, history: [], isolated_history: []};
  /* 最近一次 POST 成功的候选：reviewsGetFailure="after-save" 只让它的历史刷新失败。 */
  let savedCandidateId = null;
  const candidates = overrides.candidates || ["candidate_one", "candidate_two", "candidate_test"].map((id) => ({candidate_id: id, source_id: "synthetic_source", source_type: "real", scope: id === "candidate_test" ? "test" : "development", folds: {}, clip_sha256: "0".repeat(64), review_status: "unreviewed", window: {}, frame_mapping: {}, source_reference: {}, candidate_reference: {"断裂状态": "已断裂"}}));
  const context = {
    document: {
      getElementById: (id) => { requestedIds.add(id); return elements.get(id); },
      querySelectorAll,
      /* failDownloadClick 只作用于下载锚点（a），用来验证 a.click() 抛错时的清理路径。 */
      createElement: (tag) => { const node = new Element(tag); if (overrides.failDownloadClick && String(tag).toLowerCase() === "a") node.failClick = true; created.push(node); return node; },
      addEventListener: (event, callback) => { if (event === "DOMContentLoaded") ready = callback; },
      body,
    },
    window: {addEventListener() {}, confirm: (text) => { confirmTexts.push(String(text)); return allowDiscard; }, location: {href: ""}, localStorage: localStorageStub},
    /* 裸 localStorage 与 window.localStorage 指向同一个桩：两种写法都必须能工作。 */
    localStorage: localStorageStub,
    /* Timers run inline: revoke timing (sync vs setTimeout) must not decide pass/fail, and a vm context has no timers of its own. */
    setTimeout: (callback, ...args) => { callback(...args); return 0; },
    clearTimeout: () => {},
    /* app.js 里的 Date.now() 走这个桩，见 clock。 */
    Date: ClockDate,
    URL: {
      createObjectURL: () => { objectUrls.created += 1; return `blob:synthetic/${objectUrls.created}`; },
      revokeObjectURL: () => { objectUrls.revoked += 1; },
    },
    fetch: async (url, options = {}) => {
      requests.push({url, options});
      if (url.startsWith("/api/reviews?candidate_id=")) {
        const candidateId = decodeURIComponent(url.split("=")[1]);
        /* reviewsGetFailure 支持两种写法：
           - "after-save"：只让「刚保存过的候选」的历史刷新失败（保存成功不得被历史刷新失败否决）；
           - {candidateId}：只让指定候选的历史读取失败（进入下一个候选时历史失败不得吞掉自动播放）。 */
        const failure = overrides.reviewsGetFailure;
        const fails = failure === "after-save"
          ? candidateId === savedCandidateId
          : Boolean(failure && typeof failure === "object" && failure.candidateId === candidateId);
        if (fails) return {ok: false, status: 500, json: async () => ({error: "历史读取失败"})};
        return {ok: true, json: async () => reviewFor(candidateId)};
      }
      if (url === "/api/reviews") {
        if (overrides.saveResponse) return overrides.saveResponse;
        const payload = JSON.parse(options.body);
        savedCandidateId = payload.candidate_id;
        return {ok: true, json: async () => ({...payload, review_id: "synthetic_revision"})};
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
  if (typeof ready !== "function") throw new Error("static/app.js 没有注册 DOMContentLoaded 启动钩子，合成页面无法启动");
  await ready();
  return {elements, selects, requests, videoFrame, summary, details, pendingList,
    created, requestedIds, objectUrls, body, confirmTexts, hints, video, messages,
    playCalls: () => video.playCalls,
    localStorage: localStorageStub, localStorageStore: storageStore,
    clock: {now: () => clock.value, set: (value) => { clock.value = value; }, advance: (milliseconds) => { clock.value += milliseconds; }},
    workspace: elements.get("main-content"), sourceSummary, sourceExtras, timelineList,
    allowDiscard: (value) => { allowDiscard = value; }};
}

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
/* 正文文本：跳过 <details> 子树。用来表达「原始 JSON 只能出现在折叠区，不得摊在正文」这条约束。 */
function bodyText(node) {
  if (typeof node === "string") return node;
  if (!(node instanceof Element)) return "";
  if (node.tagName === "DETAILS") return "";
  return [typeof node.textContent === "string" ? node.textContent : "", ...node.children.map(bodyText)].filter(Boolean).join(" ");
}
function timelineText(harness) {
  return bodyText(harness.elements.get("timeline-info"));
}
/* 深度优先遍历（含自身）：在 #timeline-info 子树内定位承载帧映射 JSON 的节点与它的 details 容器。 */
function walkTree(node, visit) {
  if (!(node instanceof Element)) return;
  visit(node);
  node.children.forEach((child) => walkTree(child, visit));
}
function ancestorsOf(node) {
  const chain = [];
  for (let current = node.parent; current; current = current.parent) chain.push(current);
  return chain;
}
/* 简易 CSS 规则切分：提取「选择器 { 声明 }」，并保留外层 @media 条件（rule.media）。
 * 旧版正则只留下内层选择器、丢掉了媒体条件，无法断言「某个断点内某个选择器某条声明」；
 * 这里改为按花括号扫描：@ 开头的 prelude 只压栈不产出规则，声明块整段取出（声明值里不会有花括号）。
 * 既有调用方只用 selector / body，语义与原实现一致：@media 内规则的 selector 仍是内层选择器。 */
function cssRules(css) {
  const source = String(css).replace(/\/\*[\s\S]*?\*\//g, " ");
  const rules = [];
  const stack = [];
  let prelude = "";
  for (let index = 0; index < source.length; index += 1) {
    const char = source[index];
    if (char === "{") {
      const head = prelude.trim();
      prelude = "";
      if (head.startsWith("@")) {
        stack.push({at: head, media: head.startsWith("@media") ? head.replace(/^@media\s+/, "") : null});
        continue;
      }
      const end = source.indexOf("}", index + 1);
      const body = end < 0 ? source.slice(index + 1) : source.slice(index + 1, end);
      rules.push({
        selector: head,
        body,
        media: stack.filter((entry) => entry.media).map((entry) => entry.media),
        atRules: stack.map((entry) => entry.at),
      });
      index = end < 0 ? source.length : end;
      continue;
    }
    if (char === "}") {
      stack.pop();
      prelude = "";
      continue;
    }
    prelude += char;
  }
  return rules;
}

/* 声明值/属性比较前统一压空白并转小写：min(58vh,620px) 与 min(58vh, 620px) 这类排版差异不得决定成败。 */
function squeeze(value) { return String(value).replace(/\s+/g, "").toLowerCase(); }
/* 声明块 → 属性表（后出现的同名声明覆盖先出现的，与层叠一致）。 */
function declarations(rule) {
  const map = new Map();
  String(rule.body).split(";").forEach((chunk) => {
    const colon = chunk.indexOf(":");
    if (colon < 0) return;
    const prop = chunk.slice(0, colon).trim().toLowerCase();
    if (!prop) return;
    map.set(prop, squeeze(chunk.slice(colon + 1)));
  });
  return map;
}
function selectorsOf(rule) {
  return String(rule.selector).split(",").map((text) => text.trim().replace(/\s+/g, " ")).filter(Boolean);
}
/* 选择器列表里是否含目标选择器（精确比较，不含后代/伪类变体）。 */
function ruleMatchesSelector(rule, selector) {
  const target = String(selector).replace(/\s+/g, " ").trim();
  return selectorsOf(rule).includes(target);
}
/* 非媒体查询下的声明合并表：同一选择器可分散在多条基础规则里，逐个收集后统一断言。 */
function baseDeclarations(rules, selector) {
  const merged = new Map();
  rules.filter((rule) => rule.media.length === 0 && ruleMatchesSelector(rule, selector)).forEach((rule) => {
    declarations(rule).forEach((value, prop) => merged.set(prop, {value, rule}));
  });
  return merged;
}
function assertBaseDeclaration(rules, selector, prop, expected) {
  const matching = rules.filter((rule) => rule.media.length === 0 && ruleMatchesSelector(rule, selector));
  const merged = baseDeclarations(rules, selector);
  const entry = merged.get(prop);
  /* 失败信息里回显原始声明文本（保留排版），便于直接定位到源文件里的规则。 */
  const seen = matching.map((rule) => `${rule.selector.trim()} { ${rule.body.trim()} }`).join(" | ");
  assert.ok(entry,
    `static/style.css 的基础规则「${selector}」应声明 ${prop}，实际基础规则为「${seen || "（无）"}」`);
  assert.equal(entry.value, squeeze(expected),
    `static/style.css 中「${selector}」的 ${prop} 应为「${expected}」，实际为「${entry.value}」（来自规则：${entry.rule.selector.trim()} { ${entry.rule.body.trim()} }）`);
  return entry.value;
}
/* 媒体查询内的声明断言：先确认断点存在，再确认块内该选择器声明了期望值。 */
function assertMediaDeclaration(rules, conditionPattern, selector, prop, expected) {
  const conditions = [...new Set(rules.flatMap((rule) => rule.media))];
  const scoped = rules.filter((rule) => rule.media.some((condition) => conditionPattern.test(condition)));
  assert.ok(scoped.length > 0,
    `static/style.css 应存在满足 ${conditionPattern} 的媒体查询规则，实际全部媒体条件为 ${JSON.stringify(conditions)}`);
  const values = scoped.filter((rule) => ruleMatchesSelector(rule, selector))
    .map((rule) => declarations(rule).get(prop))
    .filter((value) => value !== undefined);
  assert.ok(values.length > 0,
    `媒体查询 ${conditionPattern} 内应有声明 ${prop} 的「${selector}」规则，实际块内选择器为 ${JSON.stringify([...new Set(scoped.flatMap((rule) => selectorsOf(rule)))])}`);
  assert.ok(values.includes(squeeze(expected)),
    `媒体查询 ${conditionPattern} 内「${selector}」的 ${prop} 应为「${expected}」，实际为 ${JSON.stringify(values)}`);
}
/* 媒体条件里 min-width 的具体像素值：用于「某个值恰为 1200px」这类精确否定断言。
 * 条件里没有 min-width、或不是像素值（em/calc 等）时返回 null——不猜、不近似。 */
function minWidthPx(condition) {
  const match = /min-width:\s*(\d+)px/.exec(String(condition));
  return match ? Number(match[1]) : null;
}
/* 媒体查询内「某选择器 + 匹配属性名」的全部声明（跨同名规则收集，保留来源规则便于失败信息定位）。
 * 否定断言用它取出块内真实的写法，而不是「没找到就通过」。 */
function mediaDeclarations(rules, conditionPattern, selector, propPattern) {
  return rules
    .filter((rule) => rule.media.some((condition) => conditionPattern.test(condition)))
    .filter((rule) => ruleMatchesSelector(rule, selector))
    .flatMap((rule) => [...declarations(rule).entries()]
      .filter(([prop]) => propPattern.test(prop))
      .map(([prop, value]) => ({prop, value, rule})));
}
/* 否定断言：媒体查询内该选择器不得出现匹配的声明；失败信息回显违规规则全文（选择器 + 声明 + 媒体条件）。 */
function assertNoMediaDeclaration(rules, conditionPattern, selector, propPattern, note) {
  const offenders = mediaDeclarations(rules, conditionPattern, selector, propPattern)
    .map((entry) => `${entry.rule.selector.trim()} { ${entry.prop}: ${entry.value} } @media ${JSON.stringify(entry.rule.media)}`);
  assert.deepEqual(offenders, [],
    `${note}（媒体条件模式 ${conditionPattern}，选择器「${selector}」，属性 ${propPattern}）`);
}
/* 媒体块内的「最终生效值」：按 cssRules() 产出的源码顺序合并同名声明（后出现的规则覆盖先出现的，与层叠一致）。
 * 这是对 assertMediaDeclaration()「块内存在一条期望值即通过」的收紧：同一断点块里若后面再跟一条覆盖规则
 * （例如 `.filters { grid-template-columns: 1fr }`），合并后的末值就是被覆盖的值，断言必红。
 * 有意做成新增专用 helper 而不是改 assertMediaDeclaration()：上百条既有用例依赖后者「存在即通过」的语义。 */
function effectiveMediaDeclarations(rules, conditionPattern, selector, props) {
  const merged = new Map();
  rules
    .filter((rule) => rule.media.some((condition) => conditionPattern.test(condition)))
    .filter((rule) => ruleMatchesSelector(rule, selector))
    .forEach((rule) => {
      declarations(rule).forEach((value, prop) => {
        if (!props.includes(prop)) return;
        merged.set(prop, {value, rule});
      });
    });
  return merged;
}
function assertEffectiveMediaDeclaration(rules, conditionPattern, selector, prop, expected) {
  const merged = effectiveMediaDeclarations(rules, conditionPattern, selector, [prop]);
  const entry = merged.get(prop);
  assert.ok(entry,
    `媒体查询 ${conditionPattern} 内「${selector}」应最终生效 ${prop}，实际块内没有该声明（按源码顺序合并到的属性为 ${JSON.stringify([...merged.keys()])}）`);
  assert.equal(entry.value, squeeze(expected),
    `媒体查询 ${conditionPattern} 内「${selector}」的 ${prop} 最终生效值应为「${expected}」（按源码顺序合并块内全部同名声明，后者覆盖前者），实际为「${entry.value}」（末条来源规则：${entry.rule.selector.trim()} { ${entry.rule.body.trim()} }）`);
  return entry.value;
}
/* 标签与取值的先后关系断言：容忍分隔符与括号排版差异，但不允许取值缺失。 */
function assertValueNear(text, label, expected, note) {
  const index = text.indexOf(label);
  assert.ok(index >= 0, `${note}：时间线应包含标签「${label}」，实际文本为「${text}」`);
  const after = text.slice(index + label.length, index + label.length + 24);
  assert.ok(after.includes(expected), `${note}：「${label}」之后应给出「${expected}」，实际其后 24 个字符为「${after}」`);
}
function hintFor(harness, name) {
  const hint = harness.hints.find((node) => node.dataset.sourceHint === name);
  assert.ok(hint, `合成页面缺少 data-source-hint="${name}" 的 .source-hint 桩元素`);
  return hint.textContent;
}
/* 触发绑定过的监听器；未绑定时给出「控件缺失或未绑定」的断言失败，而不是 harness 的 TypeError。 */
async function fire(elements, id, event, ...args) {
  const node = elements.get(id);
  assert.ok(node, `合成页面应当存在 #${id} 元素`);
  const listener = node.listeners[event];
  assert.equal(typeof listener, "function", `#${id} 应绑定 ${event} 处理函数（index.html 缺少该控件或 app.js 未绑定），实际为 ${typeof listener}`);
  return await listener(...args);
}
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
function postRequests(requests) {
  return requests.filter(({url, options}) => url === "/api/reviews" && options.method === "POST");
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
  /* 迁移：源标注不再整块渲染进 #source-reference，而是就近显示在每个控件下方的 .source-hint。
     旧断言在整块文本里匹配 /无法判断（原值：无法确定）/，这里改为匹配「断裂状态」控件下方的 hint。
     待处理来源的源标注仍是旧词「无法确定」：只读展示时映射为统一术语并保留原值，存储不动。 */
  assert.equal(hintFor(harness, "断裂状态"), "源视频：无法判断（原值：无法确定）",
    `待处理来源源标注里的历史旧值应显示为「源视频：无法判断（原值：无法确定）」，实际为「${hintFor(harness, "断裂状态")}」`);
  assert.equal(hintFor(harness, "断裂模式"), "源视频：未标注",
    `该来源只标注了断裂状态，其余控件应显示「源视频：未标注」，断裂模式实际为「${hintFor(harness, "断裂模式")}」`);
  assert.ok(harness.hints.slice(2).every((node) => node.textContent === "源视频：未标注"),
    `未标注的其余 9 个控件应显示「源视频：未标注」，实际为 ${JSON.stringify(harness.hints.map((node) => node.textContent))}`);
  assert.equal(elements.get("source-reference").children[0], harness.sourceSummary,
    "renderReference() 不得清掉 #source-reference 的 <summary>（它是 details 的开合入口）");
  assert.equal(elements.get("review-status").textContent, "原视频只读查看");
  assert.equal(elements.get("confirm-review").disabled, true);
  assert.ok(selects.every((select) => select.disabled && select.value === ""));
  assert.equal(details.children[0], summary);
});

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
  const harness = await createHarness({candidates: [candidate("coverage", {
    candidate_reference: null, review_focus: null, window: {window_role: "coverage"},
  })]});
  const {elements, selects, requests} = harness;
  assert.ok(selects.every((node) => node.value === ""));
  /* 迁移：时间线改成结构化渲染后不再用「无指定重点」措辞；空 review_focus 的等价断言是
     「生成时建议关注」这一项取值为「未记录」。 */
  assertValueNear(timelineText(harness), "生成时建议关注", "未记录", "review_focus 为 null 时");
  /* 迁移：源标注从整块文本改为就近的 .source-hint，断言位置随之迁移。 */
  assert.equal(hintFor(harness, "断裂状态"), "源视频：发生断裂",
    `源标注应就近显示为「源视频：发生断裂」，实际为「${hintFor(harness, "断裂状态")}」`);
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
  const harness = await createHarness({candidates: [candidate("clip")], reviews: {
    clip: {latest, history: [latest], isolated_history: [old]},
  }});
  const {elements, selects} = harness;
  /* latest.labels 是历史修订里的旧词「无法确定」：表单上必须映射为统一术语「无法判断」。 */
  assert.equal(selects[0].value, "无法判断",
    `历史修订的旧值「无法确定」应映射为表单值「无法判断」，实际为「${selects[0].value}」`);
  assert.ok(selects.slice(1).every((node) => node.value === ""),
    `latest.labels 只给断裂状态，其余字段应保持空白，实际为 ${JSON.stringify(controlValues(selects))}`);
  assert.equal(elements.get("prefill-notice").hidden, true,
    "已有已保存修订时控件以 latest.labels 为准，预填提示必须隐藏");
  assert.equal(elements.get("review-note").value, "human note");
  /* 迁移：源标注在旧渲染里是整块文本（/源视频标注.*发生断裂/），现在改为就近的 .source-hint；
     候选标签初值不再单独渲染成块，它的等价断言是「预填进控件」（本文件多处 selects 断言覆盖）。 */
  assert.equal(hintFor(harness, "断裂状态"), "源视频：发生断裂",
    `源标注只作参考，应就近显示为「源视频：发生断裂」，实际为「${hintFor(harness, "断裂状态")}」`);
  assertValueNear(timelineText(harness), "生成时建议关注", "断裂位置", "review_focus 有内容时");
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
  const legacyHint = hintFor(legacy, "断裂状态");
  assert.equal(legacyHint, "源视频：无法判断（原值：无法确定）",
    `源标注里的旧值应显示为「源视频：无法判断（原值：无法确定）」，实际为「${legacyHint}」`);
  /* 源标注仍只作参考、不预填；候选标签初值则作为草稿初值进入表单，旧词先映射为统一术语
     （候选初值里的旧词「无法识别」→「无法判断」即由此断言覆盖）。 */
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
  const harness = await createHarness({candidates: [candidate("clip")], bootstrap: {
    audit_current: false, audit_status: "mismatch", audit_message: "核验记录与当前清单哈希不匹配；问题提示未映射。",
  }});
  const {elements} = harness;
  assert.equal(elements.get("attention-filter").disabled, true);
  assert.match(elements.get("audit-info").textContent, /哈希不匹配/);
  /* 迁移：时间线改为固定六项结构后「标签组合待复核」这一行总在，旧断言 /待复核/ 不再成立；
     等价语义改为「没有任何待复核内容被声称」——取值必须是「未记录」。 */
  assertValueNear(timelineText(harness), "标签组合待复核", "未记录", "技术核验不匹配且候选没有 audit_issues 时");
});

test("save conflict leaves human input available and never advances to another clip", async () => {
  const {elements, selects, requests} = await createHarness({
    candidates: [candidate("first", {candidate_reference: fullCandidateLabels()}), candidate("second")],
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

/* ---------------------------------------------------------------------------------------------
 * A. 播放进度条：拖动滑块定位、timeupdate 反向同步、帧号只在 output.media.fps 可用时出现、
 *    逐帧步进（无 fps 时 1/30 秒）、切换候选重置、播放结束引导「确认完成，进入下一个」。
 * ------------------------------------------------------------------------------------------- */

test("dragging the progress bar seeks the video to the matching time", async () => {
  const harness = await createHarness({candidates: [candidate("scrub")]});
  const {elements} = harness;
  const video = elements.get("video-player");
  video.duration = 2;

  elements.get("clip-progress").value = "500";
  await fire(elements, "clip-progress", "input");

  assert.ok(Math.abs(video.currentTime - 1) <= 0.001,
    `进度条 500/1000 应把 currentTime 定位到 1 秒（duration = 2 秒），实际为 ${video.currentTime}`);
});

test("timeupdate keeps the progress bar and the readout in sync when no fps is available", async () => {
  const harness = await createHarness({candidates: [candidate("sync")]});
  const {elements} = harness;
  const video = elements.get("video-player");
  video.duration = 2;
  await fire(elements, "video-player", "loadedmetadata");

  video.currentTime = 0.4;
  await fire(elements, "video-player", "timeupdate");

  assert.equal(elements.get("clip-progress").value, "200",
    `0.40 秒 / 2.00 秒 应反映为进度条 200，实际为「${elements.get("clip-progress").value}」`);
  assert.equal(elements.get("clip-time").textContent, "0.40s / 2.00s",
    `无帧率时读数应为「0.40s / 2.00s」，实际为「${elements.get("clip-time").textContent}」`);
});

test("the readout appends frame numbers only when the candidate exposes media fps", async () => {
  const harness = await createHarness({candidates: [candidate("framed", {output: {media: {fps: 30}}})]});
  const {elements} = harness;
  const video = elements.get("video-player");
  video.duration = 2;

  await fire(elements, "video-player", "loadedmetadata");
  assert.equal(elements.get("clip-time").textContent, "0.00s / 2.00s · 帧 0 / 60",
    `有 fps 时载入后读数应为「0.00s / 2.00s · 帧 0 / 60」，实际为「${elements.get("clip-time").textContent}」`);

  video.currentTime = 0.4;
  await fire(elements, "video-player", "timeupdate");
  assert.equal(elements.get("clip-time").textContent, "0.40s / 2.00s · 帧 12 / 60",
    `有 fps 时 0.40 秒应换算成帧 12 / 60，实际为「${elements.get("clip-time").textContent}」`);
});

test("the readout degrades without fps and the step buttons document the 1/30 second default", async () => {
  const harness = await createHarness({candidates: [candidate("no_fps")]});
  const {elements} = harness;
  const video = elements.get("video-player");
  video.duration = 2;

  await fire(elements, "video-player", "loadedmetadata");
  video.currentTime = 0.4;
  await fire(elements, "video-player", "timeupdate");
  elements.get("clip-progress").value = "800";
  await fire(elements, "clip-progress", "input");

  const readout = elements.get("clip-time").textContent;
  assert.ok(!readout.includes("帧"),
    `候选取不到 output.media.fps 时不得显示帧号（不得用别的字段推算），实际读数为「${readout}」`);
  for (const id of ["step-back", "step-forward"]) {
    const title = elements.get(id).title;
    assert.match(title, /1\/30/,
      `#${id} 的 title 应说明无 fps 时按 1/30 秒步进，实际为「${title}」`);
  }
});

test("step buttons move by one frame and never step below zero", async () => {
  const harness = await createHarness({candidates: [candidate("stepping")]});
  const {elements} = harness;
  const video = elements.get("video-player");
  video.duration = 2;
  await fire(elements, "video-player", "loadedmetadata");
  video.currentTime = 0.4;

  await fire(elements, "step-forward", "click");
  assert.ok(Math.abs(video.currentTime - (0.4 + 1 / 30)) < 1e-6,
    `无 fps 时前进一步应按 1/30 秒，期望 ${0.4 + 1 / 30}，实际 ${video.currentTime}`);

  /* 正反步进互为逆操作：+1/30 之后回退一次即回到 0.4。 */
  await fire(elements, "step-back", "click");
  assert.ok(Math.abs(video.currentTime - 0.4) < 1e-6,
    `后退一步应回到 0.4，实际 ${video.currentTime}`);

  await fire(elements, "step-back", "click");
  assert.ok(Math.abs(video.currentTime - (0.4 - 1 / 30)) < 1e-6,
    `再后退一步应为 ${0.4 - 1 / 30}，实际 ${video.currentTime}`);

  video.currentTime = 0.01;
  await fire(elements, "step-back", "click");
  assert.ok(video.currentTime >= 0,
    `步进不得把 currentTime 变成负数，实际 ${video.currentTime}`);
});

test("switching candidates resets the progress bar and the readout", async () => {
  const harness = await createHarness({candidates: [candidate("first"), candidate("second")]});
  const {elements} = harness;
  const video = elements.get("video-player");
  video.duration = 2;
  await fire(elements, "video-player", "loadedmetadata");
  video.currentTime = 0.4;
  await fire(elements, "video-player", "timeupdate");
  assert.equal(elements.get("clip-progress").value, "200",
    `前置条件：切换前进度条应已同步到 200，实际为「${elements.get("clip-progress").value}」`);
  assert.equal(elements.get("clip-time").textContent, "0.40s / 2.00s",
    `前置条件：切换前读数应为「0.40s / 2.00s」，实际为「${elements.get("clip-time").textContent}」`);

  await fire(elements, "next-candidate", "click");

  assert.equal(elements.get("clip-title").textContent, "second",
    `前置条件：应已切到第二个候选，实际为「${elements.get("clip-title").textContent}」`);
  assert.equal(elements.get("clip-progress").value, "0",
    `切换候选后进度条必须回到 0，实际为「${elements.get("clip-progress").value}」`);
  assert.equal(elements.get("clip-time").textContent, "0.00s / 0.00s",
    `切换候选后读数必须回到未载入状态「0.00s / 0.00s」，实际为「${elements.get("clip-time").textContent}」`);
});

test("playback end invites the human to confirm and advance while staying on the candidate", async () => {
  const harness = await createHarness({candidates: [
    candidate("first", {candidate_reference: fullCandidateLabels()}), candidate("second"),
  ]});
  const {elements} = harness;

  await fire(elements, "video-player", "ended");

  const text = elements.get("app-message").textContent;
  assert.match(text, /确认完成，进入下一个/,
    `播放结束的提示应引导「确认完成，进入下一个」，实际为「${text}」`);
  assert.equal(elements.get("clip-title").textContent, "first",
    `播放结束不得自动切换候选，实际为「${elements.get("clip-title").textContent}」`);
});

/* ---------------------------------------------------------------------------------------------
 * B. 左侧候选列表可折叠：aria-expanded 切换、#main-content.is-collapsed、业务状态不受影响、
 *    localStorage 记忆（断言不依赖 key 名）、localStorage 抛错不崩。
 * ------------------------------------------------------------------------------------------- */

test("the candidate list collapses and expands without touching the review form", async () => {
  const harness = await createHarness({candidates: [
    candidate("a", {candidate_reference: fullCandidateLabels()}), candidate("b"),
  ]});
  const {elements, workspace} = harness;
  const toggle = elements.get("toggle-candidates");
  const before = {
    title: elements.get("clip-title").textContent,
    values: controlValues(harness.selects),
    rows: elements.get("candidate-list").children.length,
  };

  assert.equal(toggle.attributes["aria-expanded"], "true",
    `#toggle-candidates 初始 aria-expanded 应为 "true"，实际为「${toggle.attributes["aria-expanded"]}」`);

  await fire(elements, "toggle-candidates", "click");
  assert.equal(toggle.attributes["aria-expanded"], "false",
    `点击折叠后 aria-expanded 应为 "false"，实际为「${toggle.attributes["aria-expanded"]}」`);
  assert.ok(workspace.classList.contains("is-collapsed"),
    "#main-content 折叠时应带 is-collapsed 类");
  assert.equal(toggle.textContent, "展开列表",
    `折叠后按钮文案应为「展开列表」，实际为「${toggle.textContent}」`);

  await fire(elements, "toggle-candidates", "click");
  assert.equal(toggle.attributes["aria-expanded"], "true",
    `再次点击展开后 aria-expanded 应回到 "true"，实际为「${toggle.attributes["aria-expanded"]}」`);
  assert.ok(!workspace.classList.contains("is-collapsed"),
    "#main-content 展开后不应再有 is-collapsed 类");
  assert.equal(toggle.textContent, "收起列表",
    `展开后按钮文案应为「收起列表」，实际为「${toggle.textContent}」`);

  assert.equal(elements.get("clip-title").textContent, before.title,
    `折叠/展开不得改变当前候选，切换前「${before.title}」、之后「${elements.get("clip-title").textContent}」`);
  assert.deepEqual(controlValues(harness.selects), before.values,
    "折叠/展开不得改动 11 个标签控件的值");
  assert.equal(elements.get("candidate-list").children.length, before.rows,
    `折叠/展开不得重建或清空候选列表，之前 ${before.rows} 条、之后 ${elements.get("candidate-list").children.length} 条`);
});

test("the collapsed state is remembered across page loads", async () => {
  /* 实现中立：不假定 key 名，把折叠态的整份 localStorage 快照搬进新页面，新页面必须直接是折叠态。 */
  const first = await createHarness({candidates: [candidate("a")]});
  await fire(first.elements, "toggle-candidates", "click");
  const snapshot = {...first.localStorageStore};
  assert.ok(Object.keys(snapshot).length > 0,
    "折叠态应写入 localStorage，实际存储为空（断言不依赖具体 key 名）");

  const second = await createHarness({candidates: [candidate("a")], storedCollapse: snapshot});
  assert.ok(second.workspace.classList.contains("is-collapsed"),
    `重开页面（快照 ${JSON.stringify(snapshot)}）后 #main-content 应保持 is-collapsed`);
  assert.equal(second.elements.get("toggle-candidates").attributes["aria-expanded"], "false",
    `折叠态下重开页面 aria-expanded 应为 "false"，实际为「${second.elements.get("toggle-candidates").attributes["aria-expanded"]}」`);
});

test("a throwing localStorage does not break start-up or the collapse toggle", async () => {
  let harness;
  await assert.doesNotReject(async () => {
    harness = await createHarness({candidates: [candidate("a")], throwStorage: true});
  }, "localStorage 的 getItem/setItem 抛错时页面启动不得抛错");

  const toggle = harness.elements.get("toggle-candidates");
  const initial = toggle.attributes["aria-expanded"];
  await fire(harness.elements, "toggle-candidates", "click");
  assert.notEqual(toggle.attributes["aria-expanded"], initial,
    `localStorage 抛错时折叠仍须切换 aria-expanded（初始「${initial}」，点击后「${toggle.attributes["aria-expanded"]}」）`);
});

/* ---------------------------------------------------------------------------------------------
 * C. 文案与确认流程：确认按钮新文案、校验未通过不发 POST、确认后自动进入下一个、
 *    最后一个候选停留并说明、保存冲突不跳转（见上方既有用例）、#clip-meta 三折可读 + SHA256 折叠。
 * ------------------------------------------------------------------------------------------- */

test("confirmation is refused until all eleven controls are filled", async () => {
  const harness = await createHarness({candidates: [candidate("partial", {candidate_reference: {"断裂状态": "已断裂"}})]});

  await fire(harness.elements, "confirm-review", "click");

  assert.equal(postRequests(harness.requests).length, 0,
    `11 项未填满时点击确认不得发出 POST，实际发出 ${postRequests(harness.requests).length} 次`);
  assert.match(harness.elements.get("app-message").textContent, /确认须完成全部 11 项/,
    `校验提示应匹配 /确认须完成全部 11 项/，实际为「${harness.elements.get("app-message").textContent}」`);
});

test("confirmation saves once and advances to the next visible candidate without a discard prompt", async () => {
  const harness = await createHarness({candidates: [
    candidate("first", {candidate_reference: fullCandidateLabels()}),
    candidate("second", {candidate_reference: fullCandidateLabels()}),
  ]});
  const {elements} = harness;

  await fire(elements, "confirm-review", "click");

  const posts = postRequests(harness.requests);
  assert.equal(posts.length, 1, `点击确认应恰好发出 1 次 POST，实际 ${posts.length} 次`);
  assert.equal(JSON.parse(posts[0].options.body).review_status, "confirmed",
    `确认保存的 review_status 应为 confirmed，实际为「${JSON.parse(posts[0].options.body).review_status}」`);
  assert.equal(elements.get("clip-title").textContent, "second",
    `确认后应自动进入下一个候选，实际停留在「${elements.get("clip-title").textContent}」`);
  assert.deepEqual(harness.confirmTexts, [],
    `确认后自动前进不得弹未保存确认，实际弹出 ${JSON.stringify(harness.confirmTexts)}`);
  assert.match(elements.get("app-message").textContent, /进入下一个/,
    `确认后的提示应说明已进入下一个，实际为「${elements.get("app-message").textContent}」`);
});

test("confirming the last visible candidate stays on it and says it is the last one", async () => {
  const harness = await createHarness({candidates: [candidate("only", {candidate_reference: fullCandidateLabels()})]});
  const {elements} = harness;

  await fire(elements, "confirm-review", "click");

  const posts = postRequests(harness.requests);
  assert.equal(posts.length, 1, `点击确认应恰好发出 1 次 POST，实际 ${posts.length} 次`);
  assert.equal(JSON.parse(posts[0].options.body).review_status, "confirmed",
    `确认保存的 review_status 应为 confirmed，实际为「${JSON.parse(posts[0].options.body).review_status}」`);
  assert.equal(elements.get("clip-title").textContent, "only",
    `筛选内只剩一个候选时确认后不得切换，实际为「${elements.get("clip-title").textContent}」`);
  assert.match(elements.get("app-message").textContent, /最后一个候选/,
    `确认后应说明这是最后一个候选，实际为「${elements.get("app-message").textContent}」`);
});

test("clip meta renders readable folds and moves the SHA256 into the collapsed details", async () => {
  const sha = "a".repeat(64);
  const harness = await createHarness({candidates: [candidate("meta", {clip_sha256: sha})]});
  const {elements} = harness;

  const meta = elements.get("clip-meta").textContent;
  assert.ok(!meta.includes('{"0":'),
    `#clip-meta 不得再原样输出三折 JSON（{"0":…），实际为「${meta}」`);
  assert.match(meta, /第0折=验证/,
    `#clip-meta 应给出可读的三折文案「第0折=验证」，实际为「${meta}」`);
  assert.match(meta, /第1折=训练/,
    `#clip-meta 应给出可读的三折文案「第1折=训练」，实际为「${meta}」`);
  assert.ok(!/[0-9a-f]{64}/.test(meta),
    `#clip-meta 不得包含 64 位 SHA256（已折叠到 #clip-sha），实际为「${meta}」`);
  assert.equal(elements.get("clip-sha-value").textContent, sha,
    `SHA256 应落到 #clip-sha-value，实际为「${elements.get("clip-sha-value").textContent}」`);
});

/* ---------------------------------------------------------------------------------------------
 * D. 源标签就近对比：11 个 .source-hint 按映射表取值、旧词只做显示层映射、
 *    源值绝不进入 select、标签键不进「其余源标注信息」区块、非标签键仍要渲染。
 * ------------------------------------------------------------------------------------------- */

test("each source hint shows the mapped source value below its own control", async () => {
  const reference = {};
  reference[SOURCE_HINT_KEYS["断裂状态"]] = "发生断裂";
  reference[SOURCE_HINT_KEYS["异常情况.未夹紧"]] = "是";
  reference[SOURCE_HINT_KEYS["断裂现象.颈缩"]] = "无法确定";
  const harness = await createHarness({candidates: [candidate("hinted", {source_reference: reference})]});

  const expected = Object.fromEntries(LABEL_NAMES.map((name) => [name, "源视频：未标注"]));
  expected["断裂状态"] = "源视频：发生断裂";
  expected["异常情况.未夹紧"] = "源视频：是";
  /* 旧词只在显示层映射：值统一为「无法判断」并保留原值。 */
  expected["断裂现象.颈缩"] = "源视频：无法判断（原值：无法确定）";

  for (const name of LABEL_NAMES) {
    assert.equal(hintFor(harness, name), expected[name],
      `data-source-hint="${name}"（源键 ${SOURCE_HINT_KEYS[name]}）的文案应为「${expected[name]}」，实际为「${hintFor(harness, name)}」`);
  }
});

test("source labels never leak into the eleven review controls", async () => {
  const harness = await createHarness({candidates: [candidate("isolation", {
    source_reference: {"断裂状态": "发生断裂"},
    candidate_reference: {"断裂状态": "已断裂"},
  })]});

  assert.equal(harness.selects[0].value, "已断裂",
    `断裂状态应来自候选标签初值「已断裂」，实际为「${harness.selects[0].value}」`);
  assert.ok(harness.selects.slice(1).every((node) => node.value === ""),
    `候选标签只给断裂状态，其余 10 项必须为空，实际为 ${JSON.stringify(controlValues(harness.selects))}`);
  assert.ok(harness.selects.every((node) => node.value !== "发生断裂"),
    `源标注值不得进入任何审核控件，实际为 ${JSON.stringify(controlValues(harness.selects))}`);
});

test("label keys stay out of the extra source block and the summary survives", async () => {
  const harness = await createHarness({candidates: [candidate("labels_only", {source_reference: {
    "断裂状态": "发生断裂", "现象_颈缩": "是",
  }})]});

  const extras = textOf(harness.elements.get("source-extras-body"));
  assert.ok(!extras.includes("发生断裂"),
    `11 个标签键的源值已就近显示在控件下方，不得重复进 #source-extras-body，实际为「${extras}」`);
  assert.equal(harness.elements.get("source-reference").children[0], harness.sourceSummary,
    "renderReference() 不得清掉 #source-reference 的 <summary>（清掉后 details 无法再开合）");
  assert.equal(harness.sourceSummary.textContent, "其余源标注信息（非五类标签）",
    `#source-reference 的 <summary> 文案应保持不变，实际为「${harness.sourceSummary.textContent}」`);
});

test("non-label source keys stay visible in the extra source block", async () => {
  const harness = await createHarness({candidates: [candidate("extras", {source_reference: {
    "id": "video_0001", "video_path": "data/videos/video_0001.mp4", "标注状态": "已标注·有断裂", "视频帧率": "30",
  }})]});

  const extras = textOf(harness.elements.get("source-extras-body"));
  for (const fragment of ["video_0001", "video_path", "data/videos/video_0001.mp4", "标注状态", "已标注·有断裂", "视频帧率"]) {
    assert.ok(extras.includes(fragment),
      `#source-extras-body 应渲染非标签源键/值「${fragment}」，实际为「${extras}」`);
  }
});

/* ---------------------------------------------------------------------------------------------
 * 时间线结构化渲染：#timeline-list 是唯一被重写的子容器，正文不得出现 frame_mapping 的原始 JSON。
 * ------------------------------------------------------------------------------------------- */

test("the timeline renders six labelled facts instead of a JSON blob", async () => {
  const harness = await createHarness({candidates: [candidate("timeline", {
    window: {window_role: "event", start_frame: 120, end_frame: 180, source_start_pts: 4, source_end_pts: 6, duration: 2},
    review_focus: ["断裂位置"],
    audit_issues: ["标签组合A"],
    frame_mapping: {anchors: [[0, 0], [1, 1]]},
  })]});
  const text = timelineText(harness);

  for (const label of ["窗口角色", "源帧区间", "源时间", "时长", "生成时建议关注", "标签组合待复核"]) {
    assert.ok(text.includes(label), `#timeline-info 应结构化渲染「${label}」这一项，实际文本为「${text}」`);
  }
  assert.ok(text.includes("120") && text.includes("180"),
    `源帧区间应给出 120 与 180，实际文本为「${text}」`);
  assertValueNear(text, "生成时建议关注", "断裂位置", "review_focus 有内容时");
  /* 断言的是「正文区域」（跳过 <details> 子树）不含原始 JSON：把 frame_mapping 放进折叠的 details 是允许的。 */
  assert.ok(!bodyText(harness.timelineList).includes('{"anchors"'),
    `时间线正文不得把 frame_mapping 的 JSON 原样输出，实际为「${bodyText(harness.timelineList)}」`);
});

test("missing timeline facts render as 未记录", async () => {
  const harness = await createHarness({candidates: [candidate("empty_window", {window: {}, review_focus: null, audit_issues: []})]});
  const text = timelineText(harness);

  assertValueNear(text, "窗口角色", "未记录", "window 为空对象时");
  assertValueNear(text, "源帧区间", "未记录", "window 为空对象时");
  assertValueNear(text, "源时间", "未记录", "window 为空对象时");
  assertValueNear(text, "时长", "未记录", "window 为空对象时");
  assertValueNear(text, "生成时建议关注", "未记录", "review_focus 为 null 时");
  assertValueNear(text, "标签组合待复核", "未记录", "audit_issues 为空时");
  assert.ok(!text.includes("无指定重点"),
    `新契约不再使用「无指定重点」措辞，应改为「未记录」，实际文本为「${text}」`);
});

/* ---------------------------------------------------------------------------------------------
 * E. 导出（既有语义原样保留）
 * ------------------------------------------------------------------------------------------- */

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

  /* 三处 id 清单必须一致：app.js 的 `required` 数组、测试 harness 的 ids、index.html 声明的 id。
     集合差非空意味着一处漏了：required 里的 id 不在页面/harness 里是死分支；harness 有而 required 没校验的 id，
     则页面真的缺控件时也发现不了（例如 #candidate-count 曾只在 harness 与 index.html 里）。
     index.html 允许有额外 id（标题等 JS 从不查找的锚点），因此只要求 required/harness 两集合互等且都被页面声明。 */
  const appCode = fs.readFileSync(path.join(__dirname, "../static/app.js"), "utf8");
  const requiredBlock = /const required = \[([\s\S]*?)\]/.exec(appCode);
  assert.ok(requiredBlock, "static/app.js 应保留 `const required = [...]` 的必要控件清单");
  const requiredIds = new Set([...requiredBlock[1].matchAll(/"([^"]+)"/g)].map(([, id]) => id));
  const harnessIds = new Set(HARNESS_IDS);
  const minus = (left, right) => [...left].filter((id) => !right.has(id)).sort();

  assert.deepEqual(minus(harnessIds, requiredIds), [],
    `测试 harness 已桩住但这些 id 不在 app.js 的 required 清单里（页面真缺控件时启动不会报错）：${minus(harnessIds, requiredIds).join("、")}`);
  assert.deepEqual(minus(requiredIds, harnessIds), [],
    `app.js 的 required 清单里这些 id 在测试 harness 中没有桩元素：${minus(requiredIds, harnessIds).join("、")}`);
  assert.deepEqual(minus(requiredIds, declared), [],
    `app.js 的 required 清单里这些 id 在 index.html 中没有声明：${minus(requiredIds, declared).join("、")}`);
  assert.deepEqual(minus(harnessIds, declared), [],
    `测试 harness 桩住的这些 id 在 index.html 中没有声明：${minus(harnessIds, declared).join("、")}`);
});

/* ---------------------------------------------------------------------------------------------
 * static/index.html 静态契约（E 段）与 CSP 自检。
 * ------------------------------------------------------------------------------------------- */

const htmlText = fs.readFileSync(path.join(__dirname, "../static/index.html"), "utf8");

/* 取包含某标记的那个标签片段，便于断言属性。 */
function tagContaining(marker) {
  const index = htmlText.indexOf(marker);
  assert.ok(index >= 0, `static/index.html 应包含「${marker}」，实际未找到`);
  const start = htmlText.lastIndexOf("<", index);
  const end = htmlText.indexOf(">", index);
  return {index, start, end, tag: htmlText.slice(start, end + 1)};
}
/* 取某个开始标记到结束标记之间的文本：去掉标签并压缩空白，用来做文案断言。 */
function innerTextOf(openMarker, closeMarker) {
  const index = htmlText.indexOf(openMarker);
  assert.ok(index >= 0, `static/index.html 应包含「${openMarker}」，实际未找到`);
  const contentStart = htmlText.indexOf(">", index) + 1;
  const contentEnd = htmlText.indexOf(closeMarker, contentStart);
  assert.ok(contentEnd > contentStart, `static/index.html 中「${openMarker}」之后应出现「${closeMarker}」`);
  return htmlText.slice(contentStart, contentEnd).replace(/<[^>]*>/g, " ").replace(/\s+/g, " ").trim();
}
function firstIndex(pattern, note) {
  const index = typeof pattern === "string" ? htmlText.indexOf(pattern) : htmlText.search(pattern);
  assert.ok(index >= 0, `static/index.html 应包含${note}，实际未找到`);
  return index;
}

test("index.html places every source hint right after its own select", async () => {
  for (const name of LABEL_NAMES) {
    const marker = `data-source-hint="${name}"`;
    const occurrences = htmlText.split(marker).length - 1;
    assert.equal(occurrences, 1, `static/index.html 应恰好出现一次 ${marker}，实际 ${occurrences} 次`);
    const hintIndex = htmlText.indexOf(marker);
    const selectIndex = firstIndex(`name="${name}"`, ` name="${name}" 的 <select>`);
    assert.ok(hintIndex > selectIndex,
      `${marker} 必须出现在 name="${name}" 的 <select> 之后（就近显示在每个标签控件下方），实际索引 ${hintIndex} <= ${selectIndex}`);
    const tag = htmlText.slice(htmlText.lastIndexOf("<", hintIndex), htmlText.indexOf(">", hintIndex) + 1);
    assert.match(tag, /class="source-hint"/,
      `${marker} 所在的标签应带 class="source-hint"，实际为「${tag}」`);
  }
});

test("index.html turns the source reference into a details with a summary for the remaining source data", async () => {
  assert.ok(!/<aside[^>]*\bid="source-reference"/.test(htmlText),
    "static/index.html 不应再用 <aside id=\"source-reference\">，应改为 <details>");
  const reference = tagContaining('id="source-reference"');
  assert.match(reference.tag, /^<details/,
    `#source-reference 应是 <details ...>，实际为「${reference.tag}」`);
  const summaryStart = htmlText.indexOf("<summary", reference.index);
  const summaryEnd = htmlText.indexOf("</summary>", summaryStart);
  assert.ok(summaryStart > reference.index && summaryEnd > summaryStart,
    "#source-reference 内应有 <summary>，它是 details 的开合入口");
  const summaryText = htmlText.slice(htmlText.indexOf(">", summaryStart) + 1, summaryEnd)
    .replace(/<[^>]*>/g, " ").replace(/\s+/g, " ").trim();
  assert.ok(summaryText.includes("其余源标注信息（非五类标签）"),
    `#source-reference 的 <summary> 应说明这是其余源标注信息（非五类标签），实际为「${summaryText}」`);
});

test("index.html keeps the source preview button inside the media column", async () => {
  const mediaColumn = firstIndex(/<div[^>]*class="[^"]*\bmedia-column\b/, " .media-column 区块");
  const viewSource = firstIndex('id="view-source"', " #view-source 按钮");
  const labelSection = firstIndex(/<section[^>]*class="[^"]*\blabel-section\b/, " .label-section 区块");
  assert.ok(mediaColumn < viewSource && viewSource < labelSection,
    `#view-source 应位于 .media-column 内（.media-column 索引 ${mediaColumn} < #view-source 索引 ${viewSource} < .label-section 索引 ${labelSection}）`);
});

test("index.html keeps all eleven labelled controls inside the label section after the media block", async () => {
  const mediaAndReference = firstIndex(/<section[^>]*class="[^"]*\bmedia-and-reference\b/, " .media-and-reference 区块");
  const labelFields = firstIndex('id="label-fields"', " #label-fields 容器");
  const notesSection = firstIndex(/<section[^>]*class="[^"]*\bnotes-section\b/, " .notes-section 区块");
  assert.ok(mediaAndReference < labelFields && labelFields < notesSection,
    `#label-fields 应位于 .media-and-reference 之后、.notes-section 之前（索引 ${mediaAndReference} / ${labelFields} / ${notesSection}）`);
  for (const name of LABEL_NAMES) {
    assert.ok(htmlText.includes(`name="${name}"`), `static/index.html 应保留 name="${name}" 的审核控件`);
  }
  for (const id of SELECT_IDS) {
    assert.ok(htmlText.includes(`id="${id}"`), `static/index.html 应保留 id="${id}" 的审核控件`);
  }
});

test("index.html exposes a 0-1000 range slider as the clip progress bar", async () => {
  const progress = tagContaining('id="clip-progress"');
  assert.match(progress.tag, /type="range"/, `#clip-progress 应是 type="range" 的滑块，实际为「${progress.tag}」`);
  assert.match(progress.tag, /min="0"/, `#clip-progress 应有 min="0"，实际为「${progress.tag}」`);
  assert.match(progress.tag, /max="1000"/, `#clip-progress 应有 max="1000"，实际为「${progress.tag}」`);
  assert.match(progress.tag, /step="1"/, `#clip-progress 应有 step="1"，实际为「${progress.tag}」`);
});

test("index.html wraps the queue controls in the collapsible panel body", async () => {
  const panelBodyStart = firstIndex(/<div[^>]*\bid="candidate-panel-body"/, " <div id=\"candidate-panel-body\"> 容器");
  const panelBodyEnd = htmlText.indexOf("</aside>", panelBodyStart);
  assert.ok(panelBodyEnd > panelBodyStart,
    `#candidate-panel-body 之后应出现候选面板的 </aside>，实际索引 ${panelBodyEnd}`);
  const region = htmlText.slice(panelBodyStart, panelBodyEnd);
  assert.match(region, /class="[^"]*\bfilters\b/,
    `#candidate-panel-body 内应包含 .filters 筛选区，实际区块开头为「${region.slice(0, 160)}…」`);
  for (const marker of ['id="candidate-list"', 'id="pending-sources"']) {
    assert.ok(region.includes(marker), `#candidate-panel-body 内应包含 ${marker}，实际区块不含它`);
    assert.ok(htmlText.indexOf(marker) > panelBodyStart, `${marker} 应出现在 #candidate-panel-body 之后`);
  }
});

test("index.html carries the exact copy for the new confirm-and-advance workflow", async () => {
  assert.equal(innerTextOf('id="confirm-review"', "</button>"), "确认完成，进入下一个",
    `#confirm-review 的按钮文案应为「确认完成，进入下一个」，实际为「${innerTextOf('id="confirm-review"', "</button>")}」`);
  assert.equal(innerTextOf('id="prefill-notice"', "</p>"), "已按生成标签预填为草稿；每项下方注明源视频标注，仅供参考。空白表示未判断。",
    `#prefill-notice 的文案不符，实际为「${innerTextOf('id="prefill-notice"', "</p>")}」`);
  assert.equal(innerTextOf('class="fields-intro"', "</p>"), "每项下方注明源视频对应标注（仅供参考，不会写入审核值）。确认需填满 11 项。",
    `.fields-intro 的文案不符，实际为「${innerTextOf('class="fields-intro"', "</p>")}」`);
  const headerNote = innerTextOf('class="header-note"', "</div>");
  assert.match(headerNote, /每个标签下方注明源视频标注/,
    `.header-note 应说明每个标签下方注明源视频标注，实际为「${headerNote}」`);
  assert.match(headerNote, /预填只是草稿，确认后自动进入下一个/,
    `.header-note 应说明预填只是草稿、确认后自动进入下一个，实际为「${headerNote}」`);
});

test("index.html declares the collapse toggle and the collapsed SHA details", async () => {
  const toggle = tagContaining('id="toggle-candidates"');
  assert.match(toggle.tag, /aria-expanded="true"/,
    `#toggle-candidates 初始应有 aria-expanded="true"，实际为「${toggle.tag}」`);
  assert.match(toggle.tag, /aria-controls="candidate-panel-body"/,
    `#toggle-candidates 应用 aria-controls 指向 #candidate-panel-body，实际为「${toggle.tag}」`);
  assert.equal(innerTextOf('id="toggle-candidates"', "</button>"), "收起列表",
    `#toggle-candidates 初始文案应为「收起列表」，实际为「${innerTextOf('id="toggle-candidates"', "</button>")}」`);

  const sha = tagContaining('id="clip-sha"');
  assert.match(sha.tag, /^<details/,
    `#clip-sha 应是 <details ...>（SHA256 折叠在内部），实际为「${sha.tag}」`);
  assert.ok(!/\sopen(\s|=|>|\/)/.test(sha.tag),
    `#clip-sha 默认应收起（不得带 open 属性），实际为「${sha.tag}」`);
});

test("static assets stay inside the CSP: no inline handlers, inline styles, inline scripts or remote resources", () => {
  const files = {
    "static/index.html": htmlText,
    "static/app.js": fs.readFileSync(path.join(__dirname, "../static/app.js"), "utf8"),
    "static/style.css": fs.readFileSync(path.join(__dirname, "../static/style.css"), "utf8"),
  };
  for (const [name, content] of Object.entries(files)) {
    const handler = content.match(/\son[a-z]+\s*=/);
    assert.equal(handler, null,
      `${name} 含有内联事件处理器属性「${handler ? handler[0].trim() : ""}」，会被 CSP script-src 'self' 拒绝`);
    assert.ok(!content.includes('style="'),
      `${name} 含有内联 style="…" 属性，会被 CSP style-src 'self' 拒绝`);
    /* 内联 <style> 块同样被 style-src 'self' 拒绝；样式只能来自 /style.css。 */
    const styleBlock = content.match(/<style[\s>]/);
    assert.equal(styleBlock, null,
      `${name} 含有内联 <style> 样式块（命中「${styleBlock ? styleBlock[0] : ""}」），会被 CSP style-src 'self' 拒绝`);
    const remote = content.match(/https?:\/\//);
    assert.equal(remote, null,
      `${name} 含有「${remote ? remote[0] : ""}」形式的资源引用，会被 CSP default-src 'self' 拒绝；本地资源请用 / 开头的路径`);
  }
  /* 正向校验：<script> 只能带 src 的本地脚本，既排除内联内容，也避免断言因「没有 script 标签」而空跑。 */
  const scriptTags = [...files["static/index.html"].matchAll(/<script[^>]*>/g)].map((match) => match[0]);
  assert.ok(scriptTags.length > 0, "static/index.html 应至少有带 src 的本地脚本标签（/app.js）");
  const withoutSrc = scriptTags.filter((tag) => !/\bsrc=/.test(tag));
  assert.deepEqual(withoutSrc, [],
    `static/index.html 的每个 <script> 都必须带 src（不得内联），实际不符的标签：${withoutSrc.join("、")}`);
  const inlineScripts = [...files["static/index.html"].matchAll(/<script(?![^>]*\bsrc=)[^>]*>/g)].map((match) => match[0]);
  assert.deepEqual(inlineScripts, [],
    `static/index.html 含有不带 src 的内联 <script>（${inlineScripts.join("、")}），会被 CSP script-src 'self' 拒绝`);
});

/* ---------------------------------------------------------------------------------------------
 * 第二轮（审查发现）：以下 8 组断言每个都对应一个待修缺陷或测试缺口，先红后绿。
 * ------------------------------------------------------------------------------------------- */

/* 缺陷 1：确认后前进的位置与「是否最后一个」必须按「保存前」的 filtered() 顺序确定。
   现状缺陷：save() 先把候选改成 confirmed，再算 filtered() 时当前候选已不满足
   status-filter=unreviewed，indexOf 得 -1，于是既不前进又误报「最后一个候选」。 */
test("confirming under the status filter advances in the pre-save filtered order", async () => {
  const harness = await createHarness({candidates: [
    candidate("first", {candidate_reference: fullCandidateLabels()}),
    candidate("second", {candidate_reference: fullCandidateLabels()}),
  ]});
  const {elements} = harness;
  elements.get("status-filter").value = "unreviewed";
  await fire(elements, "status-filter", "change");
  assert.deepEqual(visibleIds(elements), ["first", "second"],
    "前置条件：按未审核筛选后应剩两个候选，实际为 " + JSON.stringify(visibleIds(elements)));

  await fire(elements, "confirm-review", "click");

  const posts = postRequests(harness.requests);
  assert.equal(posts.length, 1, `点击确认应恰好发出 1 次 POST，实际 ${posts.length} 次`);
  assert.equal(JSON.parse(posts[0].options.body).review_status, "confirmed",
    `确认保存的 review_status 应为 confirmed，实际为「${JSON.parse(posts[0].options.body).review_status}」`);
  assert.equal(elements.get("clip-title").textContent, "second",
    `保存后的前进目标应按保存前的筛选顺序取下一个候选，「second」；实际停留在「${elements.get("clip-title").textContent}」`
    + `（提示：${elements.get("app-message").textContent}）`);
});

test("the only unreviewed candidate under the status filter is reported as the last one", async () => {
  const harness = await createHarness({candidates: [candidate("only", {candidate_reference: fullCandidateLabels()})]});
  const {elements} = harness;
  elements.get("status-filter").value = "unreviewed";
  await fire(elements, "status-filter", "change");
  assert.deepEqual(visibleIds(elements), ["only"],
    "前置条件：按未审核筛选后应只剩一个候选，实际为 " + JSON.stringify(visibleIds(elements)));

  await fire(elements, "confirm-review", "click");

  const posts = postRequests(harness.requests);
  assert.equal(posts.length, 1, `点击确认应恰好发出 1 次 POST，实际 ${posts.length} 次`);
  assert.equal(JSON.parse(posts[0].options.body).review_status, "confirmed",
    `确认保存的 review_status 应为 confirmed，实际为「${JSON.parse(posts[0].options.body).review_status}」`);
  assert.equal(elements.get("clip-title").textContent, "only",
    `筛选内只有一个候选时不得切换，实际为「${elements.get("clip-title").textContent}」`);
  assert.match(elements.get("app-message").textContent, /最后一个候选/,
    `确认后应说明这是筛选内最后一个候选，实际为「${elements.get("app-message").textContent}」`);
});

/* 缺陷 2：frame_mapping 原始信息被整体丢弃。新契约：六项结构化正文照旧，另用一个默认收起的
   <details> 展示帧映射原始 JSON（textContent，不用 innerHTML），summary 说明这是帧映射。 */
test("frame mapping survives inside a collapsed details and stays out of the timeline body", async () => {
  const mapping = {anchors: [[973, 0], [974, 1]], output_start_frame: 0, source_start_frame: 973};
  const harness = await createHarness({candidates: [candidate("mapped", {frame_mapping: mapping})]});
  const timeline = harness.elements.get("timeline-info");

  const carriers = [];
  walkTree(timeline, (node) => {
    if (typeof node.textContent === "string" && node.textContent.includes('"anchors"')) carriers.push(node);
  });
  assert.ok(carriers.length > 0,
    `#timeline-info 子树内应保留帧映射原始 JSON（含 "anchors"），实际整棵子树都没有；正文文本为「${timelineText(harness)}」`);

  const carrier = carriers[0];
  const container = carrier.tagName === "DETAILS" ? carrier : ancestorsOf(carrier).find((node) => node.tagName === "DETAILS");
  assert.ok(container,
    `帧映射 JSON 应放在默认收起的 <details> 里，实际承载节点是 <${carrier.tagName.toLowerCase()}>，祖先链为 ${[carrier, ...ancestorsOf(carrier)].map((node) => node.tagName.toLowerCase()).join(" ← ")}`);
  assert.equal(container.attributes.open, undefined,
    `帧映射 details 应默认收起（不得带 open 属性），实际 attributes=${JSON.stringify(container.attributes)}`);
  const summaries = [];
  walkTree(container, (node) => { if (node.tagName === "SUMMARY") summaries.push(node.textContent); });
  assert.ok(summaries.some((text) => text.includes("帧映射")),
    `帧映射 details 的 <summary> 应说明这是帧映射，实际 summary 文案为 ${JSON.stringify(summaries)}`);
  assert.ok(carrier.textContent.includes("source_start_frame") && carrier.textContent.includes("973"),
    `帧映射 details 应保留原始内容（含 source_start_frame 与 973），实际为「${carrier.textContent}」`);

  /* 同时：正文（跳过 <details> 子树）不得摊开原始 JSON。 */
  const body = bodyText(timeline);
  assert.ok(!body.includes("anchors"),
    `帧映射 JSON 不得出现在时间线正文（只能进折叠区），实际正文为「${body}」`);
});

test("an empty frame mapping never fabricates frame mapping content", async () => {
  const harness = await createHarness({candidates: [candidate("no_mapping", {frame_mapping: {}})]});
  const body = timelineText(harness);
  for (const label of ["窗口角色", "源帧区间", "源时间", "时长", "生成时建议关注", "标签组合待复核"]) {
    assert.ok(body.includes(label), `frame_mapping 为空时六项正文仍要在，实际缺「${label}」，正文为「${body}」`);
  }
  /* 实现中立：要么根本没有帧映射 details，要么它的文本给出「未记录」，不得凭空造内容。 */
  const mappingDetails = [];
  walkTree(harness.elements.get("timeline-info"), (node) => {
    if (node.tagName !== "DETAILS") return;
    const summaries = [];
    walkTree(node, (child) => { if (child.tagName === "SUMMARY") summaries.push(child.textContent); });
    if (summaries.some((text) => text.includes("帧映射"))) mappingDetails.push(node);
  });
  assert.ok(mappingDetails.length <= 1, `帧映射 details 不应重复渲染，实际 ${mappingDetails.length} 个`);
  if (mappingDetails.length === 1) {
    const text = textOf(mappingDetails[0]);
    assert.ok(text.includes("未记录"),
      `frame_mapping 为空时帧映射 details 应显示「未记录」，实际为「${text}」`);
  }
});

/* 缺陷 3：POST 已成功、历史刷新 GET 失败时不得否决保存成功与自动前进，
   且历史刷新失败要留下独立提示。 */
test("a failed history refresh after a successful save still advances to the next candidate", async () => {
  const harness = await createHarness({
    candidates: [
      candidate("first", {candidate_reference: fullCandidateLabels()}),
      candidate("second", {candidate_reference: fullCandidateLabels()}),
    ],
    reviewsGetFailure: "after-save",
  });
  const {elements} = harness;

  await fire(elements, "confirm-review", "click");

  const posts = postRequests(harness.requests);
  assert.equal(posts.length, 1, `POST 已成功，点击确认应恰好发出 1 次 POST，实际 ${posts.length} 次`);
  assert.equal(JSON.parse(posts[0].options.body).review_status, "confirmed",
    `确认保存的 review_status 应为 confirmed，实际为「${JSON.parse(posts[0].options.body).review_status}」`);
  assert.equal(elements.get("clip-title").textContent, "second",
    `历史刷新失败不得阻止前进：期望进入「second」，实际停留在「${elements.get("clip-title").textContent}」`
    + `（最终提示：${elements.get("app-message").textContent}）`);
  const finalMessage = elements.get("app-message").textContent;
  assert.match(finalMessage, /已保存|修订/,
    `保存已成功，最终提示应包含「已保存」或「修订」，实际为「${finalMessage}」`);
  assert.doesNotMatch(finalMessage, /保存失败/,
    `保存已成功，最终提示不得说「保存失败」，实际为「${finalMessage}」`);
  assert.ok(harness.messages.some((text) => /历史|重载|刷新/.test(text)),
    `历史刷新失败应留下独立提示（历史未刷新/可重载/刷新失败），实际整条提示流为 ${JSON.stringify(harness.messages)}`);
});

/* 第三轮：进入下一个候选后，该候选的历史读取失败不得连带吞掉自动播放，也不得把错误提示静默覆盖。
   现状缺陷：selectCandidate() 把「拉历史」与「尝试 play()」放在同一个 try 里，GET 抛错直接进 catch，
   play() 不执行；随后确认处理器再用「已保存已确认；已进入下一个候选。」把错误提示盖掉。 */
test("a failed history read on the entered candidate still attempts playback and keeps both messages", async () => {
  const harness = await createHarness({
    candidates: [
      candidate("first", {candidate_reference: fullCandidateLabels()}),
      candidate("second", {candidate_reference: fullCandidateLabels()}),
    ],
    /* 第一个候选的 POST 与它自己的历史刷新都成功；只让被进入的 second 的历史读取失败。 */
    reviewsGetFailure: {candidateId: "second"},
  });
  const {elements} = harness;

  await fire(elements, "confirm-review", "click");

  const posts = postRequests(harness.requests);
  assert.equal(posts.length, 1, `点击确认应恰好发出 1 次 POST，实际 ${posts.length} 次`);
  assert.equal(JSON.parse(posts[0].options.body).review_status, "confirmed",
    `确认保存的 review_status 应为 confirmed，实际为「${JSON.parse(posts[0].options.body).review_status}」`);
  assert.equal(elements.get("clip-title").textContent, "second",
    `保存后应进入下一个候选「second」，实际停留在「${elements.get("clip-title").textContent}」`);
  assert.ok(harness.requests.some(({url}) => url === "/api/reviews?candidate_id=second"),
    "前置取证：应实际发起过 second 的历史读取请求（否则本用例没用上失败桩）");

  assert.equal(harness.playCalls(), 1,
    `下一候选历史读取失败后仍应尝试播放 1 次，实际 ${harness.playCalls()} 次`);

  const feedback = elements.get("app-message").textContent;
  assert.match(feedback, /已保存|进入下一个/,
    `最终提示应体现「已保存/已进入下一个候选」，实际为「${feedback}」`);
  assert.match(feedback, /历史|未能刷新|重载/,
    `下一候选历史读取失败时，最终提示必须同时体现错误（历史/未能刷新/重载），不得静默覆盖，实际为「${feedback}」`);
  assert.doesNotMatch(feedback, /保存失败/,
    `保存本身已成功，最终提示不得出现「保存失败」，实际为「${feedback}」`);
});

/* 缺陷 4：逐帧步进未处理 currentTime 为 NaN / duration 为 0 的边界。 */
test("stepping never leaves currentTime as NaN", async () => {
  const harness = await createHarness({candidates: [candidate("nan_time")]});
  const video = harness.video;
  video.duration = 2;

  video.currentTime = NaN;
  await fire(harness.elements, "step-forward", "click");
  assert.ok(Number.isFinite(video.currentTime),
    `currentTime 为 NaN 时前进一步不得保持 NaN/Infinity，实际为 ${video.currentTime}`);
  assert.ok(video.currentTime >= 0 && video.currentTime <= 2,
    `前进一步的结果应落在 [0, 2] 内，实际为 ${video.currentTime}`);

  video.currentTime = NaN;
  await fire(harness.elements, "step-back", "click");
  assert.ok(Number.isFinite(video.currentTime),
    `currentTime 为 NaN 时后退一步不得保持 NaN/Infinity，实际为 ${video.currentTime}`);
  assert.ok(video.currentTime >= 0 && video.currentTime <= 2,
    `后退一步的结果应落在 [0, 2] 内，实际为 ${video.currentTime}`);
});

test("stepping with zero duration keeps a finite current time at zero", async () => {
  const harness = await createHarness({candidates: [candidate("zero_duration")]});
  const video = harness.video;
  video.duration = 0;
  video.currentTime = 0;

  await fire(harness.elements, "step-forward", "click");
  assert.equal(video.currentTime, 0,
    `duration 为 0 时前进一步应停在 0，实际为 ${video.currentTime}`);
  assert.ok(Number.isFinite(video.currentTime), `duration 为 0 时 currentTime 必须是有限值，实际为 ${video.currentTime}`);

  await fire(harness.elements, "step-back", "click");
  assert.equal(video.currentTime, 0,
    `duration 为 0 时后退一步应停在 0（不得为负），实际为 ${video.currentTime}`);
  assert.ok(Number.isFinite(video.currentTime), `duration 为 0 时 currentTime 必须是有限值，实际为 ${video.currentTime}`);
});

/* 缺陷 5：自动播放原先未被断言。 */
test("explicit next attempts playback once", async () => {
  const harness = await createHarness({candidates: [candidate("first"), candidate("second")]});
  assert.equal(harness.playCalls(), 0, "前置条件：启动时不自动播放，play() 不应被调用");

  await fire(harness.elements, "next-candidate", "click");

  assert.equal(harness.elements.get("clip-title").textContent, "second", "前置条件：应已切到第二个候选");
  assert.equal(harness.playCalls(), 1, `点下一候选应尝试播放恰好 1 次，实际 ${harness.playCalls()} 次`);
});

test("confirming and auto-advancing attempts playback once", async () => {
  const harness = await createHarness({candidates: [
    candidate("first", {candidate_reference: fullCandidateLabels()}),
    candidate("second", {candidate_reference: fullCandidateLabels()}),
  ]});

  await fire(harness.elements, "confirm-review", "click");

  assert.equal(harness.elements.get("clip-title").textContent, "second", "前置条件：确认后应自动进入下一个候选");
  assert.equal(harness.playCalls(), 1, `确认后自动前进应尝试播放恰好 1 次，实际 ${harness.playCalls()} 次`);
});

test("a rejected play() surfaces a hint instead of crashing", async () => {
  const harness = await createHarness({candidates: [candidate("first"), candidate("second")], playRejects: true});

  await fire(harness.elements, "next-candidate", "click");

  assert.equal(harness.playCalls(), 1, `自动播放被拒绝时仍应先尝试播放 1 次，实际 ${harness.playCalls()} 次`);
  assert.match(harness.elements.get("app-message").textContent, /自动播放|点击播放/,
    `play() 被拒绝时应提示用户手动播放，实际为「${harness.elements.get("app-message").textContent}」`);
});

/* 缺陷 7：折叠后必须保留面板标题区（不得把标题 display:none）。 */
test("collapsing the candidate panel keeps a visible heading", async () => {
  const css = fs.readFileSync(path.join(__dirname, "../static/style.css"), "utf8");
  assert.ok(htmlText.includes('id="candidate-heading"'),
    "static/index.html 应保留 #candidate-heading（折叠后仍需要可见的标题区）");

  const rules = cssRules(css);
  const collapsed = rules.filter((rule) => rule.selector.includes("is-collapsed"));
  assert.ok(collapsed.length > 0,
    "static/style.css 应有作用于 .is-collapsed 的折叠规则，实际没有（折叠效果无法落地）");

  /* 标题可见：折叠态规则不得把标题区（.panel-heading / .panel-heading > div / #candidate-heading）display:none。 */
  const hidesHeading = collapsed.filter((rule) => /(#candidate-heading|\.panel-heading)\b/.test(rule.selector) && /display\s*:\s*none/.test(rule.body));
  assert.deepEqual(hidesHeading.map((rule) => `${rule.selector.trim()} { ${rule.body.trim()} }`), [],
    "折叠态规则不得把面板标题区 display:none；标题必须在折叠后仍可见（可用竖排/紧凑样式压缩）");

  /* 折叠效果真实存在：折叠态下候选正文（#candidate-panel-body / .candidate-list / .filters）必须不可见。 */
  const hidesBody = rules.some((rule) =>
    /(#candidate-panel-body|\.candidate-list|\.filters)\b/.test(rule.selector)
    && (rule.selector.includes("is-collapsed") || rule.selector.includes("[hidden]"))
    && /display\s*:\s*none/.test(rule.body));
  assert.ok(hidesBody,
    "折叠态必须真的隐藏候选正文（#candidate-panel-body[hidden] 或 .is-collapsed 下的 .candidate-list 为 display:none），实际未找到对应规则");
});

/* 缺陷 8：#candidate-count 必须恢复「当前筛选数 / 总数」。 */
test("index.html declares the candidate count badge", async () => {
  assert.ok(htmlText.includes('id="candidate-count"'),
    "static/index.html 应恢复 #candidate-count（显示「当前筛选数 / 总数」），实际未找到");
});

test("the candidate count shows the filtered total after filtering", async () => {
  const harness = await createHarness({candidates: [
    candidate("a"), candidate("b", {review_status: "confirmed"}), candidate("c"),
  ]});
  const count = harness.elements.get("candidate-count");
  assert.ok(count, "合成页面应提供 #candidate-count 元素");
  assert.match(count.textContent, /^\d+ \/ \d+$/,
    `启动后 #candidate-count 应显示「当前筛选数 / 总数」，实际为「${count.textContent}」`);
  assert.equal(count.textContent, "3 / 3",
    `默认筛选下三个候选都在，计数应为「3 / 3」，实际为「${count.textContent}」`);

  harness.elements.get("status-filter").value = "unreviewed";
  await fire(harness.elements, "status-filter", "change");

  assert.equal(count.textContent, "2 / 3",
    `筛选未审核后计数应为「2 / 3」，实际为「${count.textContent}」（可见候选：${JSON.stringify(visibleIds(harness.elements))}）`);
});

/* ---------------------------------------------------------------------------------------------
 * 第四轮（真机浏览器复验 F1–F5）：每个用例对应一个真机上暴露的 UI 缺陷，先红后绿。
 *   F1 .media-column 的 sticky 生效条件与视频区高度（显式 height，不再用宽高比推导；video 绝对定位铺满）；
 *   F2 断点与列宽（27rem 参考列 / 1200px 堆叠 / auto-fit 标签网格）；
 *   F3 #app-message 的位置、错误标记、滚动提示与错误配色；
 *   F4 候选列表高度上限与折叠态窄条（列宽 / 竖排 / aria-label）；
 *   F5 保存成功提示不被 ended 覆盖（可控时钟）。
 * 断言一律用 cssRules() 解析真实 static/style.css，不做裸字符串整行匹配。
 * ------------------------------------------------------------------------------------------- */

const styleText = fs.readFileSync(path.join(__dirname, "../static/style.css"), "utf8");

/* F3-1：消息条必须紧贴在审核工具条下方、画面与参考区上方——真机上它原本落在页面最底部，
   错误提示在滚动容器外看不见。 */
test("index.html puts the app message immediately after the review footer and above the media block", () => {
  const footer = firstIndex(/<footer[^>]*class="[^"]*\breview-footer\b/, " .review-footer 区块");
  const footerClose = htmlText.indexOf("</footer>", footer);
  assert.ok(footerClose > footer,
    `static/index.html 的 .review-footer 之后应有 </footer>，实际索引 ${footerClose}`);
  const message = tagContaining('id="app-message"');
  const media = firstIndex(/<section[^>]*class="[^"]*\bmedia-and-reference\b/, " .media-and-reference 区块");

  assert.ok(message.start > footerClose,
    `#app-message 应位于 .review-footer 之后（</footer> 索引 ${footerClose}，#app-message 起始索引 ${message.start}）`);
  assert.ok(message.start < media,
    `#app-message 应位于 .media-and-reference 之前（#app-message 索引 ${message.start}，.media-and-reference 索引 ${media}）`);

  const between = htmlText.slice(footerClose + "</footer>".length, message.start)
    .replace(/<!--[\s\S]*?-->/g, "").trim();
  assert.equal(between, "",
    `#app-message 的紧邻前一个兄弟应是 .review-footer；两者之间不得插入其它元素，实际中间内容为「${between.slice(0, 160)}」`);
});

/* F3-2：错误分支必须带上 data-kind="error"，错误样式（F3-4 的 CSS 规则）靠它选中。 */
test("a refused confirmation marks the app message as an error", async () => {
  const harness = await createHarness({candidates: [candidate("partial", {candidate_reference: {"断裂状态": "已断裂"}})]});

  await fire(harness.elements, "confirm-review", "click");

  const message = harness.elements.get("app-message");
  assert.match(message.textContent, /11/,
    `前置条件：确认校验失败的提示应说明须完成 11 项，实际为「${message.textContent}」`);
  assert.equal(message.dataset.kind, "error",
    `11 项未填满时 #app-message 的 data-kind 应为 "error"，实际为「${message.dataset.kind}」`);
  assert.equal(message.attributes.role, "alert",
    `错误提示应使用 role="alert"，实际为「${message.attributes.role}」`);
});

/* F3-3：错误提示要把消息条滚进可视区；断言的是「错误时被调用」，不锁死参数形式。 */
test("an error message scrolls the app message into view", async () => {
  const harness = await createHarness({candidates: [candidate("partial", {candidate_reference: {"断裂状态": "已断裂"}})]});
  const message = harness.elements.get("app-message");
  const before = message.scrollCalls.length;

  await fire(harness.elements, "confirm-review", "click");

  assert.match(message.textContent, /11/,
    `前置条件：确认校验失败的提示应说明须完成 11 项，实际为「${message.textContent}」`);
  assert.ok(message.scrollCalls.length > before,
    `错误提示应调用 #app-message.scrollIntoView 把消息条带进可视区，实际调用次数 ${before} → ${message.scrollCalls.length}`);
});

/* F3-3 守卫（有意写成弱断言）：普通 info 提示只要不抛错、文案确实写入即可。
   不要求、也不禁止 info 分支调用 scrollIntoView——那是非必需行为，锁死会让实现被迫二选一。 */
test("an informational message renders without requiring any scrolling", async () => {
  const harness = await createHarness({candidates: [candidate("info_only")]});
  const message = harness.elements.get("app-message");

  await assert.doesNotReject(async () => { await fire(harness.elements, "save-draft", "click"); },
    "普通（info）提示不得因滚动逻辑抛错");

  assert.match(message.textContent, /已保存/,
    `保存草稿后的普通提示应写入 #app-message，实际为「${message.textContent}」`);
  assert.notEqual(message.dataset.kind, "error",
    `普通提示的 data-kind 不应是 "error"，实际为「${message.dataset.kind}」`);
});

/* F3-4：错误样式必须真实存在于 style.css：用 cssRules() 解析出的规则体断言，不匹配整行字符串。 */
test("style.css styles the error app message with the danger palette", () => {
  const rules = cssRules(styleText);
  const errorRules = rules.filter((rule) => selectorsOf(rule).some((selector) =>
    /\.app-message\b/.test(selector) && /\[data-kind\s*=\s*["']?error["']?\]/.test(selector)));
  assert.ok(errorRules.length > 0,
    `static/style.css 应有 .app-message[data-kind="error"] 规则，实际 #app-message 相关选择器为 ${JSON.stringify(rules.filter((rule) => rule.selector.includes("app-message")).map((rule) => rule.selector.trim()))}`);

  const baseErrorRules = errorRules.filter((rule) => rule.media.length === 0);
  const scoped = baseErrorRules.length ? baseErrorRules : errorRules;
  const body = scoped.map((rule) => squeeze(rule.body)).join(";");
  assert.ok(/var\(--danger\)/.test(body),
    `.app-message[data-kind="error"] 应使用 --danger 前景/边框色，实际声明为「${body}」`);
  assert.ok(body.includes("#fdeaea"),
    `.app-message[data-kind="error"] 应用 #fdeaea 背景，实际声明为「${body}」`);
});

/* F5-1：保存成功后 3 秒内的播放结束提示不得把保存成功文案盖掉。时间维度用注入的可控时钟。 */
test("a saved message survives a playback end within three seconds", async () => {
  const harness = await createHarness({candidates: [candidate("just_saved")]});
  harness.clock.set(1_700_000_000_000);

  await fire(harness.elements, "save-draft", "click");
  const saved = harness.elements.get("app-message").textContent;
  assert.match(saved, /已保存/,
    `前置条件：保存草稿后提示应说明已保存，实际为「${saved}」`);

  harness.clock.advance(1000);
  await fire(harness.elements, "video-player", "ended");

  const after = harness.elements.get("app-message").textContent;
  assert.match(after, /已保存/,
    `保存成功 1000ms 后播放结束，提示应仍是保存成功文案，实际为「${after}」`);
  assert.doesNotMatch(after, /播放结束/,
    `保存成功 1000ms 后播放结束不得用「片段播放结束」覆盖保存提示，实际为「${after}」`);
});

/* F5-2：时间窗边界——距保存 ≥3000ms 后播放结束，恢复既有播放结束文案（不得永久吞掉这个提示）。 */
test("a playback end at least three seconds after saving restores the playback end copy", async () => {
  const harness = await createHarness({candidates: [candidate("saved_long_ago")]});
  harness.clock.set(1_700_000_000_000);

  await fire(harness.elements, "save-draft", "click");
  const saved = harness.elements.get("app-message").textContent;
  assert.match(saved, /已保存/,
    `前置条件：保存草稿后提示应说明已保存，实际为「${saved}」`);

  harness.clock.advance(3000);
  await fire(harness.elements, "video-player", "ended");

  const after = harness.elements.get("app-message").textContent;
  assert.match(after, /播放结束/,
    `距保存 3000ms（≥3000ms 的边界）后播放结束，提示应回到既有播放结束文案，实际为「${after}」`);
});

/* F5-3：从未保存时播放结束仍须给出既有提示——新逻辑不得把它静默吞掉。 */
test("a playback end without saving still explains the end of the clip", async () => {
  const harness = await createHarness({candidates: [candidate("never_saved")]});
  harness.clock.set(1_700_000_000_000);

  await fire(harness.elements, "video-player", "ended");

  const text = harness.elements.get("app-message").textContent;
  assert.match(text, /播放结束/,
    `未保存就播放结束时应给出既有播放结束提示，实际为「${text}」`);
  assert.match(text, /确认完成，进入下一个/,
    `播放结束提示应继续引导「确认完成，进入下一个」，实际为「${text}」`);
});

/* F4-1：候选列表自身高度上限 56vh 并内部滚动，否则整页跟着候选数变长。 */
test("style.css caps the candidate list at 56vh with its own scrolling", () => {
  const rules = cssRules(styleText);
  assertBaseDeclaration(rules, ".candidate-list", "max-height", "56vh");
  assertBaseDeclaration(rules, ".candidate-list", "overflow", "auto");
});

/* F4-2：≤780px 断点里仍保留 17rem 的短列表（移动端不被 56vh 撑爆）。 */
test("the 780px breakpoint keeps the candidate list short", () => {
  const rules = cssRules(styleText);
  assertMediaDeclaration(rules, /max-width:\s*780px/, ".candidate-list", "max-height", "17rem");
});

/* F4-3：折叠态窄条列宽 3.5rem（与竖排按钮的实际宽度匹配）。 */
test("the collapsed workspace narrows the rail to 3.5rem", () => {
  const rules = cssRules(styleText);
  assertBaseDeclaration(rules, ".workspace.is-collapsed", "grid-template-columns", "3.5rem minmax(0, 1fr)");
});

/* F4-4：折叠态下 #toggle-candidates 竖排。允许两种落地方式：直接指向 #toggle-candidates，
   或通过 .is-collapsed 下的 .button / .panel-heading 覆盖（该按钮带 .button 类）。 */
test("the collapsed toggle button is written vertically", () => {
  const rules = cssRules(styleText);
  const toggle = tagContaining('id="toggle-candidates"');
  assert.match(toggle.tag, /class="[^"]*\bbutton\b/,
    `前置条件：#toggle-candidates 应带 .button 类（折叠态竖排规则可能按类命中），实际为「${toggle.tag}」`);

  const vertical = rules.filter((rule) => squeeze(declarations(rule).get("writing-mode") || "") === "vertical-rl");
  const covering = vertical.filter((rule) => selectorsOf(rule).some((selector) =>
    selector.includes("toggle-candidates")
    || (selector.includes("is-collapsed") && /\.(button|panel-heading)\b/.test(selector))));
  assert.ok(covering.length > 0,
    `折叠态下 #toggle-candidates 应有 writing-mode: vertical-rl 生效（可直接指向 #toggle-candidates，也可经 .is-collapsed 下的 .button/.panel-heading），实际带 writing-mode: vertical-rl 的选择器为 ${JSON.stringify(vertical.map((rule) => rule.selector.trim()))}`);
});

/* F4-5：折叠按钮的静态 aria-label 必须存在（真机上收起后只剩一条窄条，无可读文本说明）。 */
test("index.html declares an aria-label on the collapse toggle", () => {
  const toggle = tagContaining('id="toggle-candidates"');
  const match = /\saria-label="([^"]*)"/.exec(toggle.tag);
  assert.ok(match, `#toggle-candidates 应有 aria-label（说明展开/收起候选列表），实际标签为「${toggle.tag}」`);
  assert.ok(match[1].trim().length > 0, `#toggle-candidates 的 aria-label 不得为空，实际为「${match[1]}」`);
  assert.match(match[1], /展开|收起/,
    `#toggle-candidates 的 aria-label 应说明展开/收起动作，实际为「${match[1]}」`);
});

/* F4-6：aria-label 随折叠状态在「展开候选列表」/「收起候选列表」之间切换（文案本身由 textContent 负责）。 */
test("the collapse toggle flips its aria-label between expand and collapse", async () => {
  const harness = await createHarness({candidates: [candidate("a")]});
  const toggle = harness.elements.get("toggle-candidates");

  await fire(harness.elements, "toggle-candidates", "click");
  const collapsed = toggle.attributes["aria-label"];
  assert.ok(typeof collapsed === "string" && collapsed.trim().length > 0,
    `折叠后 #toggle-candidates 应写入 aria-label，实际为「${collapsed}」`);
  assert.match(collapsed, /展开/,
    `折叠后 aria-label 应提示「展开候选列表」，实际为「${collapsed}」`);

  await fire(harness.elements, "toggle-candidates", "click");
  const expanded = toggle.attributes["aria-label"];
  assert.ok(typeof expanded === "string" && expanded.trim().length > 0,
    `展开后 #toggle-candidates 应写入 aria-label，实际为「${expanded}」`);
  assert.match(expanded, /收起/,
    `展开后 aria-label 应提示「收起候选列表」，实际为「${expanded}」`);
  assert.notEqual(expanded, collapsed,
    `展开/折叠两个状态的 aria-label 必须不同（否则屏幕阅读器听不出状态），实际都是「${expanded}」`);
});

/* F1-1：sticky 的两个必要条件（position + align-self）在基础规则里都存在。 */
test("style.css makes the media column sticky against its own box", () => {
  const rules = cssRules(styleText);
  assertBaseDeclaration(rules, ".media-column", "position", "sticky");
  assertBaseDeclaration(rules, ".media-column", "align-self", "start");
});

/* F1-2：sticky 祖先链不得是滚动容器：.media-and-reference / .review-panel / .workspace 一旦
   overflow 为 hidden/auto/scroll/clip，sticky 就会失效；.review-panel 若显式声明只能是 visible。 */
test("no ancestor of the media column turns into a scrolling container", () => {
  const rules = cssRules(styleText);
  const offenders = [];
  for (const selector of [".media-and-reference", ".review-panel", ".workspace"]) {
    rules.filter((rule) => ruleMatchesSelector(rule, selector)).forEach((rule) => {
      declarations(rule).forEach((value, prop) => {
        if (!/^overflow(-[xy])?$/.test(prop)) return;
        if (/^(hidden|auto|scroll|clip)$/.test(value)) offenders.push(`${rule.selector.trim()} { ${prop}: ${value} }`);
      });
    });
  }
  assert.deepEqual(offenders, [],
    `sticky 祖先链不得是滚动容器（overflow: hidden/auto/scroll/clip 会让 .media-column 的 sticky 失效），实际为 ${JSON.stringify(offenders)}`);

  const declared = rules.filter((rule) => ruleMatchesSelector(rule, ".review-panel"))
    .flatMap((rule) => (declarations(rule).get("overflow") === undefined ? [] : [declarations(rule).get("overflow")]));
  for (const value of new Set(declared)) {
    assert.equal(value, "visible",
      `.review-panel 的 overflow 只能是 visible 或未声明（滚动容器会让 sticky 失效），实际为「${value}」`);
  }
});

/* F1-3（契约变更）：画面高度改由显式 height 决定，不得再用 aspect-ratio 推导。
   为什么不能保留 `aspect-ratio: 16 / 9` + `overflow: hidden`：宽高比推导出的容器高度不是「确定的包含块高度」，
   里面 `.video-frame video` 的 height: 100% 取不到确定值，<video> 会按自身长宽比撑高（真机实测竖版
   videoWidth=222 / videoHeight=296 时撑到 711px，框只有 301px），超出的部分被 overflow: hidden 裁掉——
   竖版画面只剩上部约 42%，中下段全部丢失。所以本轮是契约变更而不是放宽：旧的 max-height 上限
   被显式 height 取代，同时 aspect-ratio 必须消失（只要有它，裁切就会重新出现）。
   数值锁死（不做「含 vh / 含 min(」这类宽松匹配）：min(50vh, 540px) 的来历是——
   900px 高的常规视口 → 50vh = 450px 框高，0.75 的竖版视频在 450px 高下宽约 337px（≥ 验收下限 330px）；
   540px 是上限，保证「框 + 进度条 + 时间读数」在首屏内不被推下去；min-height: 260px 是极小视口的兜底。 */
test("the video frame sets an explicit height instead of deriving it from an aspect ratio", () => {
  const rules = cssRules(styleText);
  const base = baseDeclarations(rules, ".video-frame");
  const dump = () => [...base.entries()].map(([prop, entry]) => `${prop}: ${entry.value}`).join("; ") || "（无）";

  /* 否定一：aspect-ratio 不得再出现在 .video-frame 的基础规则里。 */
  assert.equal(base.has("aspect-ratio"), false,
    `static/style.css 中「.video-frame」的基础规则不得再声明 aspect-ratio：宽高比推导出的高度不是确定的包含块高度，容器内的 height: 100% 取不到确定值，竖版视频会按自身比例撑高后被 overflow: hidden 裁掉；实际声明块为「${dump()}」`);

  /* 正向：显式 height 逐字锁死为 min(50vh, 540px)——宽泛的 /vh/ + /min\(/ 会让
     height: min(10vh, 100px) 这类退化写法也通过。 */
  const height = base.get("height");
  assert.ok(height,
    `static/style.css 中「.video-frame」的基础规则应声明显式 height: min(50vh, 540px)（900px 视口 → 450px 框高，0.75 竖版在此高度下宽约 337px ≥ 330px 验收下限；540px 上限保证「框 + 进度条 + 时间读数」留在首屏内），实际声明块为「${dump()}」`);
  assert.equal(height.value, squeeze("min(50vh, 540px)"),
    `「.video-frame」的 height 必须逐字为「min(50vh, 540px)」（900px 视口 → 450px 框高、0.75 竖版宽约 337px ≥ 330px 验收下限；540px 上限保证框 + 进度条 + 时间读数在首屏内），实际为「${height.value}」（来自规则：${height.rule.selector.trim()} { ${height.rule.body.trim()} }）`);

  /* 正向：极小视口兜底 min-height: 260px 也是逐字锁死的契约值。 */
  const minHeight = base.get("min-height");
  assert.ok(minHeight,
    `static/style.css 中「.video-frame」的基础规则应声明 min-height: 260px（极小视口下 min(50vh, 540px) 只有 50vh，260px 是保底兜底），实际声明块为「${dump()}」`);
  assert.equal(minHeight.value, squeeze("260px"),
    `「.video-frame」的 min-height 必须逐字为「260px」（极小视口下 min(50vh, 540px) 只剩 50vh 且没有下限，260px 是保底兜底），实际为「${minHeight.value}」（来自规则：${minHeight.rule.selector.trim()} { ${minHeight.rule.body.trim()} }）`);

  /* 否定二：旧的高度上限 max-height 必须去掉——显式 height 已取代它，留着会与 min-height 兜底打架。 */
  assert.equal(base.has("max-height"), false,
    `static/style.css 中「.video-frame」的基础规则不得再声明 max-height：高度上限已由显式 height 取代，再留一条 max-height（旧值 min(58vh, 620px)）会让高度重新变成「由内容/上限推导」而非确定值；实际声明块为「${dump()}」`);

  /* 保留项：定位上下文、网格化子层与裁切都还在（画面是否被裁改由 video 的 object-fit 负责）。 */
  assertBaseDeclaration(rules, ".video-frame", "position", "relative");
  assertBaseDeclaration(rules, ".video-frame", "display", "grid");
  assertBaseDeclaration(rules, ".video-frame", "overflow", "hidden");
});

/* F1-4：视频层绝对定位铺满容器（position: absolute + 贴满四边 + width/height: 100%）。
   容器有了显式 height，video 的 height: 100% 才拿得到确定的包含块高度；再配合 position: absolute，
   video 不再参与容器的自动高度计算，竖版画面只能在框内按 contain 缩放而不会把框撑高。
   否证：object-fit 不得退回 cover——cover 会按比例放大铺满并裁掉竖版画面的上下两端。 */
test("F1-4 the video layer absolutely fills the frame and keeps object-fit contain", () => {
  const rules = cssRules(styleText);
  const video = baseDeclarations(rules, ".video-frame video");
  const dump = () => [...video.entries()].map(([prop, entry]) => `${prop}: ${entry.value}`).join("; ") || "（无）";
  const valueOf = (prop) => (video.has(prop) ? video.get(prop).value : undefined);

  assert.equal(valueOf("position"), "absolute",
    `static/style.css 的基础规则「.video-frame video」应声明 position: absolute（否则 video 参与容器高度计算，竖版会撑高并被裁切），实际为「${valueOf("position")}」（声明块：${dump()}）`);
  /* 贴满四边有两种合法写法：inset: 0，或 top/right/bottom/left 四条都为 0（0px 同样接受）。 */
  const isZero = (prop) => {
    const value = valueOf(prop);
    return value !== undefined && /^0+$/.test(value.replace(/0px/g, "0"));
  };
  const insetOk = isZero("inset") || ["top", "right", "bottom", "left"].every(isZero);
  assert.ok(insetOk,
    `「.video-frame video」应贴满容器：写 inset: 0，或把 top/right/bottom/left 四条全部写成 0；实际声明块为「${dump()}」`);
  assert.equal(valueOf("width"), "100%",
    `「.video-frame video」的 width 应为 100%，实际为「${valueOf("width")}」（声明块：${dump()}）`);
  assert.equal(valueOf("height"), "100%",
    `「.video-frame video」的 height 应为 100%（容器已有显式 height，100% 才能拿到确定值），实际为「${valueOf("height")}」（声明块：${dump()}）`);
  assert.equal(valueOf("object-fit"), "contain",
    `「.video-frame video」的 object-fit 应为 contain（完整显示整幅画面），实际为「${valueOf("object-fit")}」（声明块：${dump()}）`);

  /* 否定：任何给 .video-frame video 的规则（含媒体块）都不得出现 object-fit: cover。 */
  const covers = rules
    .filter((rule) => ruleMatchesSelector(rule, ".video-frame video"))
    .flatMap((rule) => (declarations(rule).get("object-fit") === "cover" ? [`${rule.selector.trim()} { object-fit: cover } @media ${JSON.stringify(rule.media)}`] : []));
  assert.deepEqual(covers, [],
    `「.video-frame video」不得出现 object-fit: cover：cover 会按比例放大并裁掉竖版画面（真机实测竖版 222×296 只有上部约 42% 可见），实际违规规则为 ${JSON.stringify(covers)}`);
});

/* F1-5（契约再变更）：任何断点都不得覆盖 .video-frame 的高度契约。
   显式 height: min(50vh, 540px) 与极小视口兜底 min-height: 260px 只能来自基础规则。
   旧版用例只禁 height / max-height、并把断点内的 `min-height: 0` 当成「允许的覆盖」，那是错的：
   窄屏断点恰恰就是极小视口场景，把 min-height 归零后 min(50vh, 540px) 在矮视口退化成 50vh
   （400px 高的视口只剩 200px），260px 兜底在最需要它的场景失效。
   这两个断点里的 `min-height: 0` 原本的理由是「把 16:9 推导出的矮框从 300px 下限里放出来」，
   aspect-ratio 已移除，理由消失，因此本轮把它们纳入违规。
   证据形态：选择器用「含 .video-frame 复合体」的正则判定，不只是精确选择器 `.video-frame`——
   `.workspace .video-frame { min-height: 0 }` 这类后代选择器在浏览器里同样真实生效，必须一并违规；
   属性范围同时含 aspect-ratio（注释说比例推导必须彻底消失，就不能从断点里重新流回来）。 */
test("F1-5 no breakpoint overrides the video frame height contract", () => {
  const rules = cssRules(styleText);
  const allConditions = JSON.stringify([...new Set(rules.flatMap((rule) => rule.media))]);

  /* 非空通过防护：@media (max-width: 780px) 块必须真实存在，且确实含其它布局规则
     （该块有大量布局声明）。否则「块不存在 → 没有违规 → 通过」会让这条全量否证变成空断言。 */
  const narrow = rules.filter((rule) => rule.media.some((condition) => /max-width:\s*780px/.test(condition)));
  assert.ok(narrow.length > 0,
    `static/style.css 应存在 @media (max-width: 780px) 断点块，实际全部媒体条件为 ${allConditions}`);
  const narrowSelectors = [...new Set(narrow.flatMap((rule) => selectorsOf(rule)))].filter((selector) => selector !== ".video-frame");
  for (const expected of [".workspace", ".candidate-panel", ".media-and-reference"]) {
    assert.ok(narrowSelectors.includes(expected),
      `@media (max-width: 780px) 块内应确有其它布局规则（期望至少含「${expected}」），否则本用例的否证会空通过；实际块内除 .video-frame 外的选择器为 ${JSON.stringify(narrowSelectors)}`);
  }

  /* 全量否证（含選擇器形态）：媒体条件不限（rule.media.length > 0 即任意 @media 块），
     选择器用「含 .video-frame 复合体」的正则判定而不是 ruleMatchesSelector() 的精确比较——
     精确比较会放过 `.workspace .video-frame { min-height: 0 }` 这类真实生效的后代选择器覆盖。
     属性除 height / max-height / min-height 外还纳入 aspect-ratio：
     本用例注释声称宽高比推导必须彻底消失，那它就不能从断点里重新流进来。 */
  const OVERRIDE_PROPS = /^(height|max-height|min-height|aspect-ratio)$/;
  const touchesVideoFrame = (selector) => /(^|[\s>+~])\.video-frame(?![\w-])/.test(String(selector).replace(/\s+/g, " "));
  const offenders = [];
  rules.filter((rule) => rule.media.length > 0).forEach((rule) => {
    if (!selectorsOf(rule).some(touchesVideoFrame)) return;
    declarations(rule).forEach((value, prop) => {
      if (!OVERRIDE_PROPS.test(prop)) return;
      offenders.push(`${rule.selector.trim()} { ${prop}: ${value} } @media ${JSON.stringify(rule.media)}`);
    });
  });
  assert.deepEqual(offenders, [],
    `任何 @media 块内都不得给 .video-frame（含 .workspace .video-frame 这类后代形态）声明 height / max-height / min-height / aspect-ratio：显式 height: min(50vh, 540px) 与兜底 min-height: 260px 只能来自基础规则；窄屏断点一旦把 min-height 归零，min(50vh, 540px) 就会在矮视口退化成 50vh（400px 高的视口只剩 200px），260px 兜底在最需要它的场景失效；aspect-ratio 只要从断点里重新流回，宽高比推导的裁切就会重新出现；height: auto / max-height: 0 之类的覆盖则会让视频框直接塌陷；实际违规规则为 ${JSON.stringify(offenders)}`);
});

/* F1-6：占位层层级。video 成为绝对定位并带 z-index 后，.video-placeholder（position: absolute; inset: 0）
   若 z-index 仍是 auto，会被不透明的 video 背景（#13222b）整个盖住，loading / error 态的占位文案不可见。
   契约：placeholder 的 z-index 必须严格大于 video 的 z-index（当前约定 video=1、placeholder=2）。 */
test("F1-6 the placeholder layer stacks above the absolutely positioned video", () => {
  const rules = cssRules(styleText);
  assertBaseDeclaration(rules, ".video-placeholder", "position", "absolute");
  assertBaseDeclaration(rules, ".video-placeholder", "inset", "0");

  const video = baseDeclarations(rules, ".video-frame video");
  const placeholder = baseDeclarations(rules, ".video-placeholder");
  const dumpOf = (map) => [...map.entries()].map(([prop, entry]) => `${prop}: ${entry.value}`).join("; ") || "（无）";
  const videoEntry = video.get("z-index");
  assert.ok(videoEntry,
    `「.video-frame video」应声明 z-index（绝对定位后要与占位层比较层级），实际声明块为「${dumpOf(video)}」`);
  const placeholderEntry = placeholder.get("z-index");
  assert.ok(placeholderEntry,
    `「.video-placeholder」应声明 z-index 且严格大于「.video-frame video」的 z-index（否则被不透明的 video 背景盖住，loading/error 占位文案不可见）；实际「.video-placeholder」声明块为「${dumpOf(placeholder)}」`);
  const videoZ = Number.parseInt(videoEntry.value, 10);
  const placeholderZ = Number.parseInt(placeholderEntry.value, 10);
  assert.ok(Number.isFinite(videoZ) && Number.isFinite(placeholderZ),
    `z-index 应为整数字面量，实际「.video-frame video」为「${videoEntry.value}」、「.video-placeholder」为「${placeholderEntry.value}」`);
  assert.ok(placeholderZ > videoZ,
    `「.video-placeholder」的 z-index 必须严格大于「.video-frame video」的 z-index（当前约定 video=1、placeholder=2），实际 video=${videoZ}、placeholder=${placeholderZ}`);
});

/* F1-7：占位层的状态显隐。占位层存在的意义是承载 empty / loading / error 三态的提示文案，
   只有视频真正载入（data-state="loaded"）时才允许隐藏；反过来说，只有该 loaded 态规则允许隐藏占位层，
   其它任何落在 .video-placeholder 自身上的 display: none / visibility: hidden|collapse
   都会让「尚未载入视频」「媒体无法播放」这类文案消失。
   注意断言形态：loaded 态要求「每一条匹配规则的 display 都是 none」（不只看是否存在一条），
   否则后面再跟一条同选择器的 display: grid 就能把隐藏覆盖掉而用例仍绿。 */
test("F1-7 only the loaded state hides the video placeholder", () => {
  const rules = cssRules(styleText);
  /* 选择器比对放宽引号：data-state="loaded" / 'loaded' / 无引号都算同一个 loaded 态。 */
  const LOADED = /^\.video-frame\[data-state=(?:"loaded"|'loaded'|loaded)\]\s+\.video-placeholder$/;
  const loadedRules = rules.filter((rule) => selectorsOf(rule).some((selector) => LOADED.test(selector)));
  assert.ok(loadedRules.length > 0,
    `缺少 loaded 隐藏规则：static/style.css 应有「.video-frame[data-state="loaded"] .video-placeholder」规则（视频载入后隐藏占位层），实际含 .video-placeholder 的选择器为 ${JSON.stringify([...new Set(rules.flatMap((rule) => selectorsOf(rule)).filter((selector) => selector.includes("video-placeholder")))])}`);

  /* 逐条断言：所有匹配 loaded 态的规则，只要声明了 display，就必须是 none；且至少要有一条。
     这样「原规则 display: none 后面再追加同选择器 display: grid」这种末值覆盖才会被抓到。 */
  const loadedDisplays = [];
  const loadedViolations = [];
  loadedRules.forEach((rule) => {
    const display = declarations(rule).get("display");
    if (display === undefined) return;
    loadedDisplays.push(display);
    if (display !== "none") loadedViolations.push(`${rule.selector.trim()} { display: ${display} } @media ${JSON.stringify(rule.media)}`);
  });
  assert.ok(loadedDisplays.length > 0,
    `「.video-frame[data-state="loaded"] .video-placeholder」应声明 display: none（载入后占位文案必须让位给画面），实际匹配该选择器的规则里没有任何 display 声明：${JSON.stringify(loadedRules.map((rule) => rule.selector.trim()))}`);
  assert.deepEqual(loadedViolations, [],
    `「.video-frame[data-state="loaded"] .video-placeholder」的每一条声明 display 的规则都必须是 none：只要后面再跟一条同选择器的 display: grid / block，末值就覆盖掉隐藏，loaded 态占位层会重新盖住画面；实际违规规则为 ${JSON.stringify(loadedViolations)}（全部 display 声明为 ${JSON.stringify(loadedDisplays)}）`);

  /* 否证：除 loaded 态外，任何选择器落在 .video-placeholder 自身的规则都不得隐藏它——
     display: none 与 visibility: hidden|collapse 两种写法都要禁（只禁 display 会放过 visibility: hidden）。 */
  const offenders = [];
  rules.forEach((rule) => {
    const decls = declarations(rule);
    selectorsOf(rule).forEach((selector) => {
      /* 只看「主体就是占位层本身」的选择器（如 .video-placeholder、.foo .video-placeholder）；
         `.video-placeholder strong` 这类子元素选择器不在本条否证范围内。 */
      if (!/(^|\s)\.video-placeholder$/.test(selector)) return;
      if (LOADED.test(selector)) return;
      const display = decls.get("display");
      if (display === "none") offenders.push(`${selector} { display: none } @media ${JSON.stringify(rule.media)}`);
      const visibility = decls.get("visibility");
      if (visibility === "hidden" || visibility === "collapse") offenders.push(`${selector} { visibility: ${visibility} } @media ${JSON.stringify(rule.media)}`);
    });
  });
  assert.deepEqual(offenders, [],
    `只有 .video-frame[data-state="loaded"] .video-placeholder 允许隐藏占位层；其它落在 .video-placeholder 自身的 display: none 或 visibility: hidden|collapse 会让 empty / loading / error 态的提示文案（「尚未载入视频」「媒体无法播放」）消失，而这些态正是占位层存在的意义；实际违规规则为 ${JSON.stringify(offenders)}`);
});

/* F2-1：右列为固定 400px–27rem，窄下来不挤成一条线，宽屏也不无限变宽。 */
test("the media block reserves a 27rem minimum for the reference column", () => {
  const rules = cssRules(styleText);
  assertBaseDeclaration(rules, ".media-and-reference", "grid-template-columns", "minmax(0, 1fr) minmax(400px, 27rem)");
});

/* F2-2：1200px 断点起单列堆叠且取消 sticky（旧断点是 1050px，右侧参考列在那之前就被挤坏）。 */
test("the media block stacks and stops sticking under the 1200px breakpoint", () => {
  const rules = cssRules(styleText);
  assertMediaDeclaration(rules, /max-width:\s*1200px/, ".media-and-reference", "grid-template-columns", "1fr");
  assertMediaDeclaration(rules, /max-width:\s*1200px/, ".media-column", "position", "static");
});

/* F2-3：两处标签网格改为 auto-fit 自适应列（旧 repeat(3,…) 在中等宽度下把控件压到读不出值）。 */
test("both label grids use auto-fit columns of at least 9.5rem", () => {
  const rules = cssRules(styleText);
  const expected = "repeat(auto-fit, minmax(9.5rem, 1fr))";
  assertBaseDeclaration(rules, ".label-grid-single", "grid-template-columns", expected);
  assertBaseDeclaration(rules, ".label-grid-multi", "grid-template-columns", expected);
});

/* F2-4：≤560px 仍要退回单列（auto-fit 在极窄屏会落到 9.5rem 挤两列）。 */
test("the 560px breakpoint collapses both label grids to one column", () => {
  const rules = cssRules(styleText);
  assertMediaDeclaration(rules, /max-width:\s*560px/, ".label-grid-single", "grid-template-columns", "1fr");
  assertMediaDeclaration(rules, /max-width:\s*560px/, ".label-grid-multi", "grid-template-columns", "1fr");
});

/* ---------------------------------------------------------------------------------------------
 * 第五轮（纯布局修正 G1 / G2）：实现（static/style.css）已落地并被本节用例锁定。
 *   G1 宽屏双列（≥1200px）时视频列全程钉住、标签列自己滚动；1200px 以下堆叠模式不得给标签列限高；
 *   G2 ≥781px 候选面板 flex 定高、只有候选列表滚动（双层滚动退化为单层）；
 *      折叠窄条不被拉成整屏空框；≤780px 还原静态块。
 * 断言一律锁定具体声明值，不做「存在即通过」的空断言；解析复用 cssRules() 等既有 helper。
 * ------------------------------------------------------------------------------------------- */

/* G1-1：≥1201px 双列时两行对齐到顶部——否则标签列比视频列矮时会被拉伸居中，
   sticky 视频列相对行盒的位置跟着漂移，看起来就像「视频被钉住后越滚越偏」。
   H3：断点从 1200px 上移到 1201px，避免与 @media (max-width: 1200px) 的单列堆叠在恰好 1200px 时双重命中。 */
test("G1-1 the 1201px breakpoint top-aligns the media row", () => {
  const rules = cssRules(styleText);
  assertMediaDeclaration(rules, /min-width:\s*1201px/, ".media-and-reference", "align-items", "start");
});

/* G1-2：≥1201px 时标签列自己有滚动盒（限高 + 内部滚动 + 滚动不外溢 + 右侧留白）。
   padding 必须落在 `.media-and-reference .label-section` 上：既有同名规则 padding: 0 的优先级更高，
   写在裸 `.label-section` 上会被吃掉。
   H3：断点 1200px → 1201px（1200px 与 max-width:1200px 重叠）。 */
test("G1-2 the 1201px breakpoint gives the label column its own scroll box", () => {
  const rules = cssRules(styleText);
  const scope = /min-width:\s*1201px/;
  const selector = ".media-and-reference .label-section";
  assertMediaDeclaration(rules, scope, selector, "max-height", "calc(100vh - 6.5rem)");
  assertMediaDeclaration(rules, scope, selector, "overflow-y", "auto");
  assertMediaDeclaration(rules, scope, selector, "overscroll-behavior", "contain");
  assertMediaDeclaration(rules, scope, selector, "padding", "0 .5rem 0 0");
});

/* G1-3：sticky 的三个必要条件在基础规则里齐备（position + top + align-self）；
   本轮新增的是 top: 4.5rem——与 .review-footer 的 sticky 高度对齐，否则视频被页头/工具条压住一截。 */
test("G1-3 the media column is pinned 4.5rem below the viewport top", () => {
  const rules = cssRules(styleText);
  assertBaseDeclaration(rules, ".media-column", "position", "sticky");
  assertBaseDeclaration(rules, ".media-column", "top", "4.5rem");
  assertBaseDeclaration(rules, ".media-column", "align-self", "start");
});

/* G1-4：堆叠模式（1201px 以下，含基础规则与 max-width 断点）不得给标签列限高或内部滚动，
   否则窄屏下单列堆叠时右侧标签区会变成一条缝，用户滚不到底下的输入项。
   H3：豁免断点唯一化为 min-width: 1201px（恰为 1200px 的块与 max-width:1200px 重叠，不再豁免）。 */
test("G1-4 no breakpoint below 1201px caps or scrolls the label column", () => {
  const rules = cssRules(styleText);
  const targetsLabelColumn = (rule) => selectorsOf(rule).some((selector) => /(^|\s)\.label-section$/.test(selector));
  const offenders = [];
  rules.filter(targetsLabelColumn).forEach((rule) => {
    declarations(rule).forEach((value, prop) => {
      if (!/^(max-height|overflow|overflow-y)$/.test(prop)) return;
      const onlyWideScreen = rule.media.length > 0
        && rule.media.every((condition) => /min-width:\s*1201px/.test(condition));
      if (onlyWideScreen) return;
      offenders.push(`${rule.selector.trim()} { ${prop}: ${value} } @media ${JSON.stringify(rule.media)}`);
    });
  });
  assert.deepEqual(offenders, [],
    `只有 @media (min-width: 1201px) 内才允许给 .label-section / .media-and-reference .label-section 限高或内部滚动（堆叠模式必须整页滚动），实际违规规则为 ${JSON.stringify(offenders)}`);
});

/* G2-1：≥781px 时候选面板由内容撑高改为「视口高减上下各 1rem」的定高 flex 列，
   自身不再滚动（overflow: hidden），滚动下沉给列表——双层滚动退化为单层。 */
test("G2-1 the candidate panel is flex-pinned to the viewport height from 781px up", () => {
  const rules = cssRules(styleText);
  const scope = /min-width:\s*781px/;
  assertMediaDeclaration(rules, scope, ".candidate-panel", "height", "calc(100vh - 2rem)");
  assertMediaDeclaration(rules, scope, ".candidate-panel", "max-height", "calc(100vh - 2rem)");
  assertMediaDeclaration(rules, scope, ".candidate-panel", "display", "flex");
  assertMediaDeclaration(rules, scope, ".candidate-panel", "flex-direction", "column");
  assertMediaDeclaration(rules, scope, ".candidate-panel", "overflow", "hidden");
});

/* G2-2：#candidate-panel-body 是面板的 flex 主体——占满剩余高度、纵向排列、可被压缩到 0。 */
test("G2-2 the candidate panel body fills the panel as a shrinkable flex column", () => {
  const rules = cssRules(styleText);
  const scope = /min-width:\s*781px/;
  const selector = "#candidate-panel-body";
  assertMediaDeclaration(rules, scope, selector, "display", "flex");
  assertMediaDeclaration(rules, scope, selector, "flex-direction", "column");
  assertMediaDeclaration(rules, scope, selector, "flex", "1 1 auto");
  assertMediaDeclaration(rules, scope, selector, "min-height", "0");
});

/* G2-3（H1）：筛选区不参与伸缩，但**不再有自己的高度上限与滚动盒**——高度由内容决定，
   纵向滚动统一交给 #candidate-list，否则筛选区与列表会叠出两层滚动条。
   否证一：≥781px 块内 `.filters` 不得声明 max-height / overflow / overflow-y（含 max-height: none 这类伪装）；
   否证二：基础规则（无 @media）里的 `.filters` 同样不得声明三者中任何一个，筛选区不得自带任何滚动盒或高度上限。 */
test("G2-3 the filters block has no height cap and no inner scrolling", () => {
  const rules = cssRules(styleText);
  const scope = /min-width:\s*781px/;
  assertMediaDeclaration(rules, scope, ".filters", "flex", "0 0 auto");
  assertNoMediaDeclaration(rules, scope, ".filters", /^(max-height|overflow|overflow-y)$/,
    "筛选区不得再有自己的滚动盒，高度必须由内容决定：@media (min-width: 781px) 内的 .filters 不得声明 max-height / overflow / overflow-y");
  /* 基础规则同样要否定（三个属性一起）：只查 max-height 会漏掉 `overflow: auto` 这类自建滚动盒。 */
  const base = baseDeclarations(rules, ".filters");
  const baseOffenders = ["max-height", "overflow", "overflow-y"]
    .filter((prop) => base.has(prop))
    .map((prop) => `${base.get(prop).rule.selector.trim()} { ${prop}: ${base.get(prop).value} } @media ${JSON.stringify(base.get(prop).rule.media)}`);
  assert.deepEqual(baseOffenders, [],
    `筛选区不得自带任何滚动盒或高度上限，包括基础规则：static/style.css 中无 @media 的「.filters」不得声明 max-height / overflow / overflow-y，否则筛选区会与 #candidate-list 叠成两层滚动；实际违规声明为 ${JSON.stringify(baseOffenders)}`);
});

/* G2-4：#pending-sources（details）固定在面板底部，不参与伸缩，展开也只由自身内容决定。 */
test("G2-4 the pending sources block stays fixed at the panel bottom", () => {
  const rules = cssRules(styleText);
  assertMediaDeclaration(rules, /min-width:\s*781px/, "#pending-sources", "flex", "0 0 auto");
});

/* G2-5：flex 面板内列表必须解除既有 56vh 上限（max-height: none）才能吃满剩余高度，
   同时把基础 min-height: 15rem 归零，否则小窗口下列表压不下、面板再次溢出。 */
test("G2-5 the candidate list drops its base height cap inside the flex panel", () => {
  const rules = cssRules(styleText);
  const scope = /min-width:\s*781px/;
  assertMediaDeclaration(rules, scope, "#candidate-list", "min-height", "0");
  assertMediaDeclaration(rules, scope, "#candidate-list", "max-height", "none");
});

/* G2-6：折叠窄条里按钮宽度撑满 3.5rem 窄条（原本只有 31px，鼠标热区太小、竖排文字还溢出）。 */
test("G2-6 the collapsed rail button spans the full rail width", () => {
  const rules = cssRules(styleText);
  assertMediaDeclaration(rules, /min-width:\s*781px/, ".workspace.is-collapsed .panel-heading .button", "width", "100%");
});

/* G2-7：折叠窄条不能被定高规则拉成整屏空框——折叠态面板高度回落到内容高度。 */
test("G2-7 the collapsed rail is not stretched to a full viewport height", () => {
  const rules = cssRules(styleText);
  assertMediaDeclaration(rules, /min-width:\s*781px/, ".workspace.is-collapsed .candidate-panel", "height", "auto");
});

/* G2-8：定高改造不得丢掉原有的 sticky 锚定（面板仍贴在视口顶部 1rem、按自身高度对齐）。 */
test("G2-8 the candidate panel keeps its sticky anchoring below the 781px breakpoint", () => {
  const rules = cssRules(styleText);
  assertBaseDeclaration(rules, ".candidate-panel", "position", "sticky");
  assertBaseDeclaration(rules, ".candidate-panel", "top", "1rem");
  assertBaseDeclaration(rules, ".candidate-panel", "align-self", "start");
});

/* G2-9（语义）：候选列表在 flex 面板内是独立滚动容器——既要能伸缩（flex: 1 1 auto），
   也要真的允许纵向滚动（overflow-y: auto）；缺任一条就只是「看起来改了」，实际滚不动。 */
test("G2-9 the candidate list is an independent scroll container inside the flex panel", () => {
  const rules = cssRules(styleText);
  const scope = /min-width:\s*781px/;
  assertMediaDeclaration(rules, scope, "#candidate-list", "overflow-y", "auto");
  assertMediaDeclaration(rules, scope, "#candidate-list", "flex", "1 1 auto");
});

/* G2-10（语义）：flex 滚动链成立——#candidate-panel-body 必须同时给 min-height: 0 与 flex: 1 1 auto，
   否则它的高度由内容决定，列表的 overflow 永远不会触发；同时面板自身 overflow: hidden，
   链条才是单层滚动而不是内外两层一起滚。 */
test("G2-10 the flex scroll chain from panel to list is complete", () => {
  const rules = cssRules(styleText);
  const scope = /min-width:\s*781px/;
  assertMediaDeclaration(rules, scope, "#candidate-panel-body", "min-height", "0");
  assertMediaDeclaration(rules, scope, "#candidate-panel-body", "flex", "1 1 auto");
  assertMediaDeclaration(rules, scope, ".candidate-panel", "overflow", "hidden");
});

/* G2-11：≤780px 断点还原成静态块——不钉视口高度、不隐藏溢出，候选列表仍是 17rem 的短列表。 */
test("G2-11 the 780px breakpoint unpins the candidate panel from the viewport height", () => {
  const rules = cssRules(styleText);
  const scope = /max-width:\s*780px/;
  assertMediaDeclaration(rules, scope, ".candidate-panel", "position", "static");
  assertMediaDeclaration(rules, scope, ".candidate-panel", "max-height", "none");
  assertMediaDeclaration(rules, scope, ".candidate-panel", "height", "auto");
  assertMediaDeclaration(rules, scope, ".candidate-panel", "overflow", "visible");
});

/* ---------------------------------------------------------------------------------------------
 * 第六轮（CSS 微调 H1 / H2 / H3）：实现（static/style.css）已落地并被本节用例锁定。
 *   H1 筛选区取消自己的高度上限与内部滚动（见上面改写后的 G2-3）；
 *   H2 ≥781px 筛选区改成两列网格（label 与控件成对），≤780px 保持单列；
 *   H3 标签列限高/内滚的媒体断点 1200px → 1201px（见上面改写的 G1-1 / G1-2 / G1-4）。
 * 断言逐字锁定 `max-content minmax(0, 1fr) max-content minmax(0, 1fr)` 这一套轨宽，
 * 并配否定断言（不得出现多轨回归 / 不得出现恰为 1200px 的豁免块）。
 * ------------------------------------------------------------------------------------------- */

/* H2-1：≥781px 筛选区是两列网格容器，轨宽锁定为「label 列 / 控件列」各一对。
   四条轨分别是 label、控件、label、控件；用 max-content 贴合标签宽度、minmax(0, 1fr) 让控件列吃满。 */
test("H2-1 the 781px breakpoint turns the filters block into the locked four-track grid", () => {
  const rules = cssRules(styleText);
  const scope = /min-width:\s*781px/;
  assertMediaDeclaration(rules, scope, ".filters", "display", "grid");
  assertMediaDeclaration(rules, scope, ".filters", "grid-template-columns",
    "max-content minmax(0, 1fr) max-content minmax(0, 1fr)");
});

/* H2-2：网格的间距与行内对齐——.35rem 行距、.6rem 列距（label 与控件成对靠紧、两列之间留白），
   行内垂直居中，否则标签与 2.35rem 高的输入控件在行内错开半行。 */
test("H2-2 the filters grid keeps the locked gap and vertical centering", () => {
  const rules = cssRules(styleText);
  const scope = /min-width:\s*781px/;
  assertMediaDeclaration(rules, scope, ".filters", "gap", ".35rem .6rem");
  assertMediaDeclaration(rules, scope, ".filters", "align-items", "center");
});

/* H2-3：跨列关系——#audit-info（审核状态提示）整行独占，四个筛选项都能整行放下；
   #candidate-search 从第 2 条轨跨到末尾，保证它前面的 label 仍在第 1 条轨，label 与控件不错位。
   全量否证：跨列声明只能出现在 781px 块里——基础规则或其它断点块（780px / 1200px / 1201px）
   一旦给这两个选择器声明 grid-column，两列网格的对应关系就错位。 */
test("H2-3 audit info spans the whole grid row and the search field spans the control columns", () => {
  const rules = cssRules(styleText);
  const scope = /min-width:\s*781px/;
  assertMediaDeclaration(rules, scope, "#audit-info", "grid-column", "1 / -1");
  assertMediaDeclaration(rules, scope, "#candidate-search", "grid-column", "2 / -1");

  /* 遍历全文所有给这两个选择器声明 grid-column 的规则：每一条都必须落在 min-width: 781px 的媒体块内。 */
  const spanSelectors = ["#audit-info", "#candidate-search"];
  const offenders = [];
  rules.forEach((rule) => {
    if (!spanSelectors.some((selector) => ruleMatchesSelector(rule, selector))) return;
    const gridColumn = declarations(rule).get("grid-column");
    if (gridColumn === undefined) return;
    const onlyWideScope = rule.media.length > 0
      && rule.media.every((condition) => /min-width:\s*781px/.test(condition));
    if (onlyWideScope) return;
    offenders.push(`${rule.selector.trim()} { grid-column: ${gridColumn} } @media ${JSON.stringify(rule.media)}`);
  });
  assert.deepEqual(offenders, [],
    `跨列声明（#audit-info / #candidate-search 的 grid-column）只能出现在 @media (min-width: 781px) 块内；出现在基础规则或其它断点块里会让 label 与控件错位，实际违规规则为 ${JSON.stringify(offenders)}`);
});

/* H2-5（层叠）：781px 块内 `.filters` 的四个声明必须「最终生效」为锁定值，而不只是「块内存在一条这样的声明」。
   按 cssRules() 的源码顺序合并块内全部精确匹配 .filters 的同名声明（后者覆盖前者，与层叠一致）后取末值：
   若后面再跟一条 `.filters { grid-template-columns: 1fr }` 之类覆盖，末值就不是锁定值，本用例必红。 */
test("H2-5 the filters declarations inside the 781px block resolve to the locked values", () => {
  const rules = cssRules(styleText);
  const scope = /min-width:\s*781px/;

  assertEffectiveMediaDeclaration(rules, scope, ".filters", "grid-template-columns",
    "max-content minmax(0, 1fr) max-content minmax(0, 1fr)");
  assertEffectiveMediaDeclaration(rules, scope, ".filters", "gap", ".35rem .6rem");
  assertEffectiveMediaDeclaration(rules, scope, ".filters", "display", "grid");
  assertEffectiveMediaDeclaration(rules, scope, ".filters", "align-items", "center");
});

/* H2-4：≤780px 窄屏保持单列——筛选区回落成 1fr 单轨；否证：该断点块内 `.filters` 的
   grid-template-columns 只允许 `1fr`（不得残留 max-content / minmax() 这类多轨写法）。 */
test("H2-4 the 780px breakpoint keeps the filters block in a single column", () => {
  const rules = cssRules(styleText);
  const scope = /max-width:\s*780px/;
  assertMediaDeclaration(rules, scope, ".filters", "grid-template-columns", "1fr");
  const tracks = mediaDeclarations(rules, scope, ".filters", /^grid-template-columns$/).map((entry) => entry.value);
  const offenders = tracks.filter((value) => value !== "1fr");
  assert.deepEqual(offenders, [],
    `窄屏（@media (max-width: 780px)）筛选区必须是单列 grid-template-columns: 1fr，不得出现多轨/两列写法，实际为 ${JSON.stringify(offenders)}（块内全部声明：${JSON.stringify(tracks)}）`);
});

/* H3-1：1201px 是标签列限高/内滚的唯一豁免断点。
   否证：任何「min-width 恰为 1200px」的媒体块都不得给 .label-section 限高或内部滚动——
   1200px 会与 @media (max-width: 1200px) 的单列堆叠同时命中，此时标签列被限高就会变成一条缝。 */
test("H3-1 no exactly-1200px breakpoint caps or scrolls the label column", () => {
  const rules = cssRules(styleText);
  const targetsLabelColumn = (rule) => selectorsOf(rule).some((selector) => /(^|\s)\.label-section$/.test(selector));
  const offenders = [];
  rules.filter(targetsLabelColumn).forEach((rule) => {
    if (!rule.media.some((condition) => minWidthPx(condition) === 1200)) return;
    declarations(rule).forEach((value, prop) => {
      if (!/^(max-height|overflow|overflow-y)$/.test(prop)) return;
      offenders.push(`${rule.selector.trim()} { ${prop}: ${value} } @media ${JSON.stringify(rule.media)}`);
    });
  });
  assert.deepEqual(offenders, [],
    `1200px 会与 @media (max-width: 1200px) 的单列堆叠同时命中，标签列的限高/内滚必须写在 @media (min-width: 1201px) 内；实际在 min-width 恰为 1200px 的媒体块里发现 ${JSON.stringify(offenders)}`);
});
