const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const path = require("node:path");
const read = file => fs.readFileSync(path.join(__dirname, "..", file), "utf8");

test("filters combine category and unread state with local text search", () => {
  // Exercise the actual filter functions with lightweight DOM stand-ins.
  const source = read("static/js/search.js");
  const start = source.indexOf("  function matchesChatFilter(row)");
  const end = source.indexOf("  filterControls.forEach(control => {", start);
  assert.ok(start >= 0 && end > start);
  const rows = [
    { dataset: { chatType: "private", chatUnread: "true", search: "alice" } },
    { dataset: { chatType: "group", chatUnread: "false", search: "group" } },
    { dataset: { chatType: "channel", chatUnread: "true", search: "news" } },
  ];
  const empty = {};
  const context = vm.createContext({
    sidebarInput: { value: "" },
    chatRows: () => rows,
    chatFilterEmpty: () => empty,
    filterControls: [],
    activeChatFilter: "unread",
  });
  vm.runInContext(source.slice(start, end) + "\napplyLocalChatFilter();", context);
  assert.deepEqual(rows.map(row => row.hidden), [false, true, false]);
  vm.runInContext('activeChatFilter = "group"; applyLocalChatFilter();', context);
  assert.deepEqual(rows.map(row => row.hidden), [true, false, true]);
  context.sidebarInput.value = "news";
  vm.runInContext('activeChatFilter = "all"; applyLocalChatFilter();', context);
  assert.deepEqual(rows.map(row => row.hidden), [true, true, false]);
});

test("sidebar refresh retains filters and context menu works on refreshed rows", () => {
  const source = read("static/js/search.js");
  assert.match(source, /chatList\.replaceChildren\(\.\.\.next\.childNodes\);[\s\S]{0,220}applyLocalChatFilter\(\);/);
  assert.match(source, /chatList\.addEventListener\("contextmenu"/);
  assert.match(source, /rowAction\.value = unread \? "mark_read" : "mark_unread"/);
  assert.match(source, /window\.confirm\("Отметить все чаты/);
  assert.match(read("static/js/read-ack.js"), /opened_marker: openedUnreadMarker/);
});
