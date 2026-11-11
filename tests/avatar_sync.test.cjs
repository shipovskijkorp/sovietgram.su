const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const source = fs.readFileSync(
  path.join(__dirname, "../static/js/avatar-sync.js"), "utf8"
);

class AvatarNode {
  constructor(tagName, className, dataset, text = "") {
    this.tagName = tagName.toUpperCase();
    this.className = className || "";
    this.dataset = { ...dataset };
    this.textContent = text;
    this.src = "";
    this.alt = "";
    this.loading = "";
    this.attributes = {};
  }
  getAttribute(name) {
    if (name === "src") return this.src || null;
    return this.attributes[name] ?? null;
  }
  replaceWith(next) {
    const index = nodes.indexOf(this);
    if (index >= 0) nodes[index] = next;
  }
}

const nodes = [];
const document = {
  createElement(tag) {
    return new AvatarNode(tag, "", {});
  },
  querySelectorAll(selector) {
    const kind = selector.includes("data-avatar-user-id")
      ? "avatarUserId" : "avatarChatId";
    return nodes.filter(node => node.dataset[kind] != null);
  },
};
const context = vm.createContext({ document, window: {} });
vm.runInContext(source, context, { filename: "avatar-sync.js" });
const sync = context.window.SovietgramAvatarSync;

test("user avatar URL updates all matching nodes and leaves other users alone", () => {
  nodes.splice(0, nodes.length,
    new AvatarNode("img", "conversation-header__avatar", { avatarUserId: "12" }),
    new AvatarNode("span", "chat-info-avatar chat-info-avatar--fallback", { avatarUserId: "12" }, "ИВ"),
    new AvatarNode("img", "chat-row__avatar", { avatarUserId: "99" }),
  );
  nodes[0].src = "/u/ivan/avatar/?v=old";
  const changed = sync.updateUser(12, "/u/ivan/avatar/?v=new", "ИВ");
  assert.equal(changed, 2);
  assert.equal(nodes[0].src, "/u/ivan/avatar/?v=new");
  assert.equal(nodes[1].tagName, "IMG");
  assert.equal(nodes[1].src, "/u/ivan/avatar/?v=new");
  assert.equal(nodes[1].className, "chat-info-avatar chat-info-avatar--fallback");
  assert.equal(nodes[1].dataset.avatarUserId, "12");
  assert.equal(nodes[2].src, "");
});

test("removing a photo replaces image with initials without reloading", () => {
  nodes.splice(0, nodes.length,
    new AvatarNode("img", "conversation-header__avatar", { avatarUserId: "12" }),
  );
  nodes[0].src = "/u/ivan/avatar/?v=old";
  assert.equal(sync.updateUser("12", "", "ИВ"), 1);
  assert.equal(nodes[0].tagName, "SPAN");
  assert.equal(nodes[0].textContent, "ИВ");
  assert.equal(nodes[0].className, "conversation-header__avatar");
  assert.equal(nodes[0].dataset.avatarUserId, "12");
});

test("group avatar updates are scoped to the requested community", () => {
  nodes.splice(0, nodes.length,
    new AvatarNode("span", "conversation-header__avatar conversation-header__avatar--fallback", { avatarChatId: "4" }, "Г"),
    new AvatarNode("img", "chat-info-avatar", { avatarChatId: "5" }),
  );
  assert.equal(sync.updateChat(4, "/media/chat_avatars/4/new.png", "Гр"), 1);
  assert.equal(nodes[0].tagName, "IMG");
  assert.equal(nodes[0].src, "/media/chat_avatars/4/new.png");
  assert.equal(nodes[1].src, "");
});

test("avatar fallback text updates when no image is available", () => {
  nodes.splice(0, nodes.length,
    new AvatarNode("span", "chat-row__avatar chat-row__avatar--fallback", { avatarChatId: "4" }, "Г"),
  );
  sync.updateChat(4, "", "К");
  assert.equal(nodes[0].tagName, "SPAN");
  assert.equal(nodes[0].textContent, "К");
});
