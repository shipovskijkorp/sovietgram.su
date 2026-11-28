const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const path = require("node:path");

const read = file => fs.readFileSync(path.join(__dirname, "..", file), "utf8");

function loadReceipt() {
  const context = {
    window: {},
    document: {
      createElement(tag) {
        return {
          tag, className: "", dataset: {}, title: "", textContent: "",
          attributes: {},
          setAttribute(name, value) { this.attributes[name] = value; },
        };
      },
    },
  };
  vm.runInNewContext(read("static/js/message-status.js"), context);
  return context.window.SovietgramReadReceipt;
}

test("read receipts update in place with accessible labels and no text glyphs", () => {
  const receipt = loadReceipt();
  const node = receipt.create(false);
  assert.equal(node.className, "message-check");
  assert.equal(node.dataset.readState, "sent");
  assert.equal(node.attributes.role, "img");
  assert.equal(node.attributes["aria-label"], "Отправлено");
  assert.equal(node.textContent, "");
  assert.equal(receipt.set(node, true), node);
  assert.equal(node.dataset.readState, "read");
  assert.equal(node.title, "Прочитано");
  assert.equal(node.attributes["aria-label"], "Прочитано");
  assert.equal(node.textContent, "");
});

test("server markup and all live renderers share the vector receipt states", () => {
  const template = read("templates/messenger/index.html");
  const receipt = template.match(/<span class="message-check"[^>]*><\/span>/);
  assert.ok(receipt);
  assert.match(receipt[0], /data-read-state=".*?read.*?sent/);
  assert.match(read("templates/base.html"), /js\/message-status\.js/);
  for (const file of ["chat.js", "voice-messages.js", "messenger.js"]) {
    const source = read("static/js/" + file);
    assert.match(source, /SovietgramReadReceipt\.create\(message\.is_read\)/);
    assert.doesNotMatch(source, /check\.textContent\s*=\s*(?:message\.is_read|["']✓)/);
  }
  assert.match(read("static/js/chat.js"), /SovietgramReadReceipt\.set\(check, Number\(article\.dataset\.messageId\) <= value\)/);
  const css = read("static/css/messenger.css");
  assert.match(css, /message-sent\.svg/);
  assert.match(css, /message-read\.svg/);
  assert.match(css, /\.message-check\[data-read-state="read"\]/);
  for (const name of ["message-sent.svg", "message-read.svg"]) {
    const svg = read("static/icons/" + name);
    assert.match(svg, /viewBox="0 0 18 14"/);
    assert.match(svg, /<path /);
  }
});

test("a delayed sent update cannot undo a confirmed read receipt", () => {
  const receipt = loadReceipt();
  const node = receipt.create(true);
  receipt.set(node, false);
  assert.equal(node.dataset.readState, "read");
  assert.equal(node.attributes["aria-label"], "Прочитано");
});
