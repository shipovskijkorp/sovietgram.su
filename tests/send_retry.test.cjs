const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const { webcrypto } = require("node:crypto");
const { TextEncoder } = require("node:util");

function load(transport, storage = new Map()) {
  const context = {
    window: { crypto: webcrypto }, TextEncoder,
    fetch: transport,
    sessionStorage: {
      getItem: key => storage.get(key) ?? null,
      setItem: (key, value) => storage.set(key, value),
      removeItem: key => storage.delete(key),
    },
  };
  vm.runInNewContext(fs.readFileSync("static/js/send-retry.js", "utf8"), context);
  return context.window.SovietgramSendRetry;
}

test("batch retry uses the same UUID and a new operation gets a different UUID", () => {
  const helper = load(async () => {});
  const keys = helper.batch();
  const first = keys.key("part-1", ["caption", 10]);
  assert.match(first, /^[a-f0-9-]{36}$/);
  assert.equal(keys.key("part-1", ["caption", 10]), first);
  assert.notEqual(keys.key("part-2", ["caption", 10]), first);
  assert.notEqual(keys.key("part-1", ["edited", 10]), first);
  keys.clear();
  assert.notEqual(keys.key("part-1", ["caption", 10]), first);
});

test("uncertain network failure retries with the identical request body", async () => {
  const bodies = [];
  const helper = load(async (_url, options) => {
    bodies.push(options.body);
    if (bodies.length === 1) throw new TypeError("network lost");
    return { status: 200 };
  });
  const body = { client_message_id: helper.uuid(), text: "hello" };
  assert.equal((await helper.fetchSend("/send", { body })).status, 200);
  assert.equal(bodies.length, 2);
  assert.equal(bodies[0], bodies[1]);
});

test("text UUID survives reload until acknowledged without storing raw text", async () => {
  const storage = new Map();
  const firstHelper = load(async () => {}, storage);
  const first = await firstHelper.textKey("scope", ["private text", ""], firstHelper.batch());
  const secondHelper = load(async () => {}, storage);
  const second = await secondHelper.textKey("scope", ["private text", ""], secondHelper.batch());
  assert.equal(first, second);
  assert.equal(storage.get("scope").includes("private text"), false);
  secondHelper.clearText("scope", secondHelper.batch());
  assert.notEqual(await secondHelper.textKey("scope", ["private text", ""], secondHelper.batch()), first);
});
