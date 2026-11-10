const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

process.env.TZ = "Europe/Stockholm";
const source = fs.readFileSync(path.join(__dirname, "../static/js/settings.js"), "utf8");

function element() {
  const children = [];
  return {
    children, hidden: false, dataset: {}, classList: {
      add() {}, remove() {}, toggle() {},
    },
    append(...items) { children.push(...items); },
    appendChild(item) { children.push(item); },
    replaceChildren(...items) { children.splice(0, children.length, ...items); },
    addEventListener() {}, querySelectorAll() { return []; },
    querySelector() { return null; }, setAttribute() {},
  };
}

function startSettings(initialSessions, currentSessions) {
  const root = element();
  root.hidden = true;
  root.dataset.settingsUrl = "/settings/";
  const list = element();
  const count = element();
  const timers = [];
  const elements = {
    telegramSettings: root,
    privacySessionsList: list,
    privacySessionCount: count,
    settingsSessionsData: { textContent: JSON.stringify(initialSessions) },
  };
  let requests = 0;
  const document = {
    hidden: false,
    body: { classList: element().classList, dataset: {} },
    documentElement: { dataset: {} },
    getElementById(id) { return elements[id] || null; },
    querySelector() { return null; }, querySelectorAll() { return []; },
    createElement() { return element(); }, addEventListener() {},
  };
  const context = vm.createContext({
    document,
    window: {
      location: {
        href: "https://sovietgram.su/?settings=sessions",
        origin: "https://sovietgram.su",
      },
      history: { pushState() {}, replaceState() {} },
      addEventListener() {},
      setInterval(callback) { timers.push(callback); return timers.length; },
      clearTimeout() {}, setTimeout() { return 1; },
    },
    localStorage: { setItem() {} },
    URL, Date, Intl,
    fetch: async (url, options) => {
      requests++;
      assert.equal(new URL(url).searchParams.get("action"), "privacy_state");
      assert.equal(options.cache, "no-store");
      assert.equal(options.headers["X-Requested-With"], "XMLHttpRequest");
      return { ok: true, async json() { return { ok: true, sessions: currentSessions() }; } };
    },
  });
  vm.runInContext(source, context, { filename: "settings.js" });
  return { root, list, count, timers, requests: () => requests };
}

const sample = {
  token: "a",
  current: true,
  user_agent: "Firefox",
  ip: "127.0.0.1",
  login_at: "2026-11-10T19:30:00+00:00",
  expires_at: "2026-11-11T19:30:00+00:00",
};

test("shows login instant in local timezone, distinct from session expiry", async () => {
  const view = startSettings([sample], () => [sample]);
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(view.list.children.length, 1);
  const details = view.list.children[0].children[1].children[1].textContent;
  assert.match(details, /Вход: 10\\.11\\.2026, 20:30/);
  assert.match(details, /Истекает: 11\\.11\\.2026, 20:30/);
  assert.equal(view.count.textContent, "1");
});

test("unknown login instant stays unknown for legacy sessions", async () => {
  const old = { ...sample, login_at: "", expires_at: "" };
  const view = startSettings([old], () => [old]);
  await new Promise(resolve => setImmediate(resolve));
  const details = view.list.children[0].children[1].children[1].textContent;
  assert.match(details, /Вход: нет данных/);
});

test("active sessions refresh without a page reload", async () => {
  let latest = [sample];
  const view = startSettings([sample], () => latest);
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(typeof view.timers[0], "function");

  latest = [sample, { ...sample, token: "b", current: false, user_agent: "Mobile" }];
  view.timers[0]();
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(view.list.children.length, 2);
  assert.equal(view.count.textContent, "2");
  assert.ok(view.requests() >= 2);
});
