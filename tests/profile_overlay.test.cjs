const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

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
