const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const source = fs.readFileSync(
  path.join(__dirname, "../static/js/settings.js"), "utf8"
);

class Node {
  constructor(options = {}) {
    this.dataset = options.dataset || {};
    this.type = options.type || "";
    this.name = options.name || "";
    this.value = options.value || "";
    this.checked = Boolean(options.checked);
    this.hidden = Boolean(options.hidden);
    this.disabled = false;
    this.textContent = "";
    this.children = [];
    this.handlers = new Map();
    this.classList = {
      add() {}, remove() {}, toggle() {}, contains() { return false; },
    };
  }
  addEventListener(name, fn) {
    const list = this.handlers.get(name) || [];
    list.push(fn);
    this.handlers.set(name, list);
  }
  async fire(name) {
    for (const fn of this.handlers.get(name) || []) {
      await fn({ target: this, preventDefault() {}, stopPropagation() {} });
    }
  }
  append(...nodes) { this.children.push(...nodes); }
  appendChild(node) { this.children.push(node); }
  replaceChildren(...nodes) { this.children.splice(0, this.children.length, ...nodes); }
  closest() { return new Node(); }
  querySelector() { return null; }
  querySelectorAll() { return []; }
  setAttribute() {}
}

const rule = (option = "everyone") => ({
  key: "last_seen",
  title: "Время последней активности",
  question: "Кто видит время последней активности?",
  option,
  option_label: { everyone: "Все", contacts: "Мои контакты", nobody: "Никто" }[option],
  always: [],
  never: [],
});

function start({ screen = "privacy-rule", state = {}, onPost = null } = {}) {
  const server = {
    rules: { last_seen: rule() },
    blocked: [],
    sessions: [],
    preferences: {
      theme: "light", enter_to_send: true,
      archive_in_main_menu: false, archive_unknown_chats: false,
      keep_archived_chats: false, delete_after_inactive_days: 365,
      default_auto_delete_seconds: 0,
    },
    ...state,
  };
  const elements = {
    settingsStatus: new Node({ hidden: true }),
    privacyRuleQuestion: new Node(),
    privacyAlwaysCount: new Node(),
    privacyNeverCount: new Node(),
    privacyInactiveValue: new Node(),
    privacyAutoDeleteValue: new Node(),
    settingsPrivacyData: { textContent: JSON.stringify(server.rules) },
    settingsBlockedData: { textContent: "[]" },
    settingsSessionsData: { textContent: "[]" },
  };

  const root = new Node({
    hidden: true, dataset: { settingsUrl: "/settings/", autoOpen: "" },
  });
  elements.telegramSettings = root;
  const labels = { last_seen: new Node() };
  const radio = {
    everyone: new Node({ type: "radio", name: "privacy-rule-option", value: "everyone" }),
    contacts: new Node({ type: "radio", name: "privacy-rule-option", value: "contacts" }),
    nobody: new Node({ type: "radio", name: "privacy-rule-option", value: "nobody" }),
  };
  const privacyRadios = Object.values(radio);
  const archive = new Node({
    type: "checkbox", dataset: { setting: "archive_in_main_menu" },
  });
  const themeLight = new Node({
    type: "radio", dataset: { setting: "theme", value: "light" },
    value: "light", checked: true,
  });
  const themeDark = new Node({
    type: "radio", dataset: { setting: "theme", value: "dark" },
    value: "dark",
  });
  const allSettings = [archive, themeLight, themeDark];
  const screens = ["main", "privacy", "privacy-rule", "privacy-exceptions", "archive"]
    .map(value => new Node({ dataset: { settingsScreen: value } }));

  root.querySelector = selector => {
    if (selector.startsWith("#settingsAjaxForm")) return { value: "fake-csrf" };
    const match = selector.match(/data-privacy-label="([^"]+)"/);
    if (match) return labels[match[1]] || null;
    return null;
  };
  root.querySelectorAll = selector => {
    if (selector === "[data-settings-screen]") return screens;
    if (selector === "[data-setting]") return allSettings;
    if (selector === 'input[name="privacy-rule-option"]') return privacyRadios;
    if (selector.includes("data-privacy-exception") && selector.includes("privacy-rule-option")) {
      return privacyRadios;
    }
    if (selector === "[data-theme-option]") return [];
    return [];
  };

  let reloadCount = 0;
  let postCount = 0;
  const location = {
    href: "https://sovietgram.su/?settings=" + screen + "&privacy=last_seen",
    origin: "https://sovietgram.su",
    reload() { reloadCount++; },
  };
  const document = {
    hidden: false,
    body: { classList: new Node().classList, dataset: { theme: "light" } },
    documentElement: { dataset: {} },
    getElementById(id) { return elements[id] || null; },
    querySelector() { return null; },
    querySelectorAll() { return []; },
    createElement() { return new Node(); },
    addEventListener() {},
  };
  const window = {
    location,
    history: { replaceState() {}, pushState() {} },
    addEventListener() {},
    setTimeout() { return 1; },
    clearTimeout() {},
    setInterval() { return 1; },
  };
  const fetch = async (url, options = {}) => {
    if (options.method === "POST") {
      postCount++;
      const body = options.body;
      assert.equal(body.get("csrfmiddlewaretoken"), "fake-csrf");
      if (onPost) return onPost(body, server);
      const setting = body.get("setting");
      if (setting) {
        const raw = body.get("value");
        const value = raw === "true" ? true : raw === "false" ? false : raw;
        server.preferences[setting] = value;
        return { ok: true, async json() { return { ok: true, value }; } };
      }
      return { ok: true, async json() { return { ok: true }; } };
    }
    assert.equal(new URL(url, window.location.origin).searchParams.get("action"), "privacy_state");
    return {
      ok: true,
      async json() { return { ok: true, ...structuredClone(server) }; },
    };
  };
  const context = vm.createContext({
    document, window, fetch, URL, FormData, Date, Intl, Set,
    CSS: { escape(text) { return text; } },
  });
  vm.runInContext(source, context, { filename: "settings.js" });
  const tick = () => new Promise(resolve => setImmediate(resolve));
  return {
    server, document, root, radio, archive, themeDark, labels,
    status: elements.settingsStatus,
    tick, reloadCount: () => reloadCount, postCount: () => postCount,
  };
}

test("failed privacy rule save restores server-confirmed radio selection", async () => {
  const view = start({
    onPost: async () => ({
      ok: false, async json() { return { ok: false, error: "Не удалось сохранить" }; },
    }),
  });
  await view.tick();
  assert.equal(view.radio.everyone.checked, true);

  view.radio.everyone.checked = false;
  view.radio.contacts.checked = true;
  await view.radio.contacts.fire("change");

  assert.equal(view.postCount(), 1);
  assert.equal(view.radio.everyone.checked, true);
  assert.equal(view.radio.contacts.checked, false);
  assert.equal(view.server.rules.last_seen.option, "everyone");
  assert.match(view.status.textContent, /Не удалось сохранить/);
});

test("rapid privacy changes never submit competing requests", async () => {
  let finish;
  const view = start({
    onPost: async (body, server) => {
      await new Promise(resolve => { finish = resolve; });
      const updated = rule(body.get("option"));
      server.rules.last_seen = updated;
      return { ok: true, async json() { return { ok: true, rule: updated }; } };
    },
  });
  await view.tick();
  view.radio.contacts.checked = true;
  const first = view.radio.contacts.fire("change");
  await view.tick();
  view.radio.nobody.checked = true;
  await view.radio.nobody.fire("change");

  assert.equal(view.postCount(), 1);
  finish();
  await first;
  assert.equal(view.server.rules.last_seen.option, "contacts");
  assert.equal(view.radio.contacts.checked, true);
  assert.equal(view.radio.nobody.checked, false);
});

test("opening settings refreshes preferences from the server", async () => {
  const view = start({
    screen: "archive",
    state: { preferences: {
      theme: "dark", enter_to_send: false, archive_in_main_menu: true,
      archive_unknown_chats: false, keep_archived_chats: false,
      delete_after_inactive_days: 365, default_auto_delete_seconds: 0,
    } },
  });
  await view.tick();

  assert.equal(view.archive.checked, true);
  assert.equal(view.themeDark.checked, true);
  assert.equal(view.document.body.dataset.theme, "dark");
});

test("archive placement is applied immediately with a single reload", async () => {
  const view = start({ screen: "archive" });
  await view.tick();
  view.archive.checked = true;
  await view.archive.fire("change");
  // The real change listener intentionally starts the save asynchronously.
  await view.tick();
  assert.equal(view.postCount(), 1);
  assert.equal(view.server.preferences.archive_in_main_menu, true);
  assert.equal(view.reloadCount(), 1);
});
