const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

// Ensure calendar boundaries are tested in a non-UTC timezone.
process.env.TZ = "Europe/Stockholm";
const source = fs.readFileSync(
  path.join(__dirname, "../static/js/profile.js"), "utf8"
);

function harness(saveRequest) {
  const listeners = new Map();
  const classes = () => ({
    add() {},
    remove() {},
    toggle() {},
    contains() { return false; },
  });
  function element(id) {
    const events = new Map();
    return {
      id,
      hidden: true,
      disabled: false,
      value: "",
      textContent: "",
      classList: classes(),
      addEventListener(name, listener) { events.set(name, listener); },
      querySelector(selector) {
        if (selector === "[name='csrfmiddlewaretoken']") {
          return { value: "real-test-csrf-token" };
        }
        return null;
      },
      removeAttribute() {},
      replaceChildren() {},
      focus() {},
      select() {},
      async click() {
        const action = events.get("click");
        if (action) return action({ preventDefault() {} });
      },
    };
  }
  const ids = [
    "userProfileOverlay", "userProfileView", "userProfileEditForm",
    "userProfileEditClose", "userProfileEditBack", "userProfileBioInput",
    "userProfileBioCount", "userProfileEditError", "userProfileFieldEditor",
    "userProfileFieldInput", "userProfileFieldSave", "userProfileFieldError",
    "userProfileBirthdayChoice", "userProfileBirthdayInput",
    "userProfileStatus", "userProfileEditStatus",
  ];
  const elems = Object.fromEntries(ids.map(id => [id, element(id)]));
  const toasts = [];
  const document = {
    body: { classList: classes() },
    getElementById(id) { return elems[id] || null; },
    querySelectorAll() { return []; },
    querySelector() { return { value: "fallback-csrf" }; },
    addEventListener(name, listener) { listeners.set(name, listener); },
  };
  const context = vm.createContext({
    document,
    window: {
      location: { href: "https://sovietgram.su/" },
      history: { replaceState() {} },
      setTimeout() { return 1; },
      clearTimeout() {},
      setInterval() { return 1; },
      clearInterval() {},
    },
    FormData,
    URL,
    fetch: saveRequest,
    showToast(text) { toasts.push(text); },
  });
  vm.runInContext(source, context, { filename: "profile.js" });
  vm.runInContext(`openedProfile = {
    is_self: true, username: "ivan", first_name: "Иван", last_name: "",
    bio: "", birthday: "", birthday_display: "", personal_channel: null,
    edit_url: "/profile/", profile_url: "/u/ivan/", display_name: "Иван",
    avatar_url: "", initials: "ИВ", owned_channels: []
  }`, context);
  elems.userProfileOverlay.hidden = false;
  elems.userProfileEditForm.hidden = false;
  elems.userProfileView.hidden = true;
  return { elems, toasts, context, listeners };
}

test("birthday can be saved from the overlay with Django CSRF token", async () => {
  let requests = 0;
  const { context, elems } = harness(async (url, options) => {
    requests++;
    assert.equal(url, "/profile/");
    assert.equal(options.method, "POST");
    assert.equal(options.body.get("csrfmiddlewaretoken"), "real-test-csrf-token");
    assert.equal(options.body.get("birthday"), "2006-11-10");
    return {
      ok: true,
      async json() {
        return {
          ok: true, first_name: "Иван", username: "ivan", bio: "",
          birthday: "2006-11-10", birthday_display: "10.11.2006",
          display_name: "Иван", profile_url: "/u/ivan/",
        };
      },
    };
  });
  vm.runInContext('openProfileFieldEditor("birthday")', context);
  assert.equal(elems.userProfileFieldInput.type, "date");
  elems.userProfileFieldInput.value = "2006-11-10";
  await vm.runInContext("saveProfileFieldEditor()", context);
  assert.equal(requests, 1);
  assert.equal(elems.userProfileBirthdayInput.value, "2006-11-10");
  assert.equal(elems.userProfileBirthdayChoice.textContent, "10.11.2006");
  assert.equal(elems.userProfileFieldEditor.hidden, true);
});

test("close button works even when bio save fails (no trapping modal)", async () => {
  const { context, elems, toasts } = harness(async () => ({
    ok: false,
    async json() { throw new SyntaxError("HTML error page"); },
  }));
  elems.userProfileBioInput.value = "Новый текст";
  await elems.userProfileEditClose.click();
  // The actual click handler intentionally starts an async close without
  // blocking DOM dispatch; let its save/error microtasks settle.
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(elems.userProfileOverlay.hidden, true);
  assert.ok(toasts.some(text => text.includes("не сохранены")));
});

test("back arrow works even when bio save fails", async () => {
  const { elems, toasts } = harness(async () => ({
    ok: false,
    async json() { return { ok: false, errors: { bio: [{ message: "Ошибка." }] } }; },
  }));
  elems.userProfileBioInput.value = "Новый текст";
  await elems.userProfileEditBack.click();
  assert.equal(elems.userProfileEditForm.hidden, true);
  assert.equal(elems.userProfileView.hidden, false);
  assert.ok(toasts.some(text => text.includes("не сохранены")));
});

test("bio blur and close reuse one pending POST instead of racing", async () => {
  let finish;
  let count = 0;
  const { context, elems } = harness(async (_url, options) => {
    count++;
    await new Promise(resolve => { finish = resolve; });
    return {
      ok: true,
      async json() {
        return {
          ok: true, username: "ivan", first_name: "Иван",
          display_name: "Иван", bio: options.body.get("bio"),
          birthday: "", profile_url: "/u/ivan/",
        };
      },
    };
  });
  elems.userProfileBioInput.value = "Сохранить один раз";
  const onBlur = vm.runInContext("flushBioSave()", context);
  const closing = vm.runInContext("closeUserProfile()", context);
  assert.equal(count, 1);
  finish();
  await Promise.all([onBlur, closing]);
  assert.equal(count, 1);
  assert.equal(elems.userProfileOverlay.hidden, true);
});

test("profile last seen uses browser timezone across UTC midnight", () => {
  const { context } = harness(async () => { throw new Error("no fetch"); });
  const result = vm.runInContext(`
    formatProfileLastSeen({
      status: "старый серверный статус",
      last_seen_exact: true,
      last_seen_at: "2026-11-09T23:30:00+00:00",
      is_online: false,
    }, new Date("2026-11-10T12:00:00+01:00"))
  `, context);
  assert.equal(result, "был(а) сегодня в 00:30");
});

test("private presence never renders hidden exact time", () => {
  const { context } = harness(async () => { throw new Error("no fetch"); });
  const result = vm.runInContext(`
    formatProfileLastSeen({
      status: "был(а) недавно",
      last_seen_exact: false,
      last_seen_at: "2026-11-09T23:30:00+00:00",
      is_online: true,
    }, new Date("2026-11-10T12:00:00+01:00"))
  `, context);
  assert.equal(result, "был(а) недавно");
});

test("profile online state updates without a full page reload", async () => {
  const { context, elems } = harness(async (url, options) => {
    assert.equal(url, "/u/ivan/");
    assert.equal(options.cache, "no-store");
    return {
      ok: true,
      async json() {
        return {
          ok: true, status: "в сети", is_online: true,
          last_seen_exact: true,
          last_seen_at: "2026-11-10T19:35:00+00:00",
          is_contact: false,
        };
      },
    };
  });
  vm.runInContext(`
    renderUserProfile({
      profile_url: "/u/ivan/", is_self: false, username: "ivan",
      status: "был(а) давно", last_seen_exact: false,
      last_seen_at: "", is_online: false,
    });
  `, context);
  assert.equal(elems.userProfileStatus.textContent, "был(а) давно");
  await vm.runInContext("refreshProfilePresence()", context);
  assert.equal(elems.userProfileStatus.textContent, "в сети");
  assert.equal(elems.userProfileEditStatus.textContent, "в сети");
});
