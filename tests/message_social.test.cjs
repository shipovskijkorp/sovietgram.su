const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const read = file => fs.readFileSync(path.join(__dirname, "..", file), "utf8");

function element(tag = "div") {
  return {
    tag, children: [], dataset: {}, attributes: {},
    appendChild(child) { this.children.push(child); return child; },
    append(...children) { this.children.push(...children); },
    replaceChildren(...children) { this.children = children; },
    insertBefore(child, anchor) {
      const index = this.children.indexOf(anchor);
      this.children.splice(index < 0 ? this.children.length : index, 0, child);
    },
    querySelector(selector) {
      if (selector === "footer") return this.children.find(child => child.tag === "footer") || null;
      if (selector === "[data-message-reactions]") return this.children.find(child => child.dataset?.messageReactions !== undefined) || null;
      return null;
    },
    setAttribute(name, value) { this.attributes[name] = value; },
  };
}

function load() {
  const context = {
    window: {},
    document: {
      getElementById: () => null,
      createElement: tag => element(tag),
      createTextNode: text => ({ tag: "#text", textContent: text }),
    },
  };
  vm.runInNewContext(read("static/js/message-social.js"), context);
  return context.window.SovietgramSocial;
}

test("social tokens are detected without turning email addresses or URL fragments into mentions or tags", () => {
  const social = load();
  const text = "Привет, @alice. #Новости! test@site.ru https://site.ru/#tag @bob_1";
  const tokens = Array.from(social.tokenize(text), token => [token.kind, token.value]);
  assert.deepEqual(tokens.filter(([kind]) => kind === "mention"), [["mention", "@alice"], ["mention", "@bob_1"]]);
  assert.deepEqual(tokens.filter(([kind]) => kind === "hashtag"), [["hashtag", "#Новости"]]);
  assert.deepEqual(tokens.filter(([kind]) => kind === "url"), [["url", "test@site.ru"], ["url", "https://site.ru/#tag"]]);
  assert.equal(tokens.map(([, value]) => value).join(""), text);
});

test("renderer creates safe text nodes and encoded profile links", () => {
  const social = load();
  const root = element("p");
  social.renderText(root, "<img onerror=alert(1)> @alice #тема\nhttps://example.com");
  assert.equal(root.children[0].tag, "#text");
  assert.equal(root.children[0].textContent, "<img onerror=alert(1)> ");
  assert.equal(root.children.find(child => child.dataset?.userProfile !== undefined).href, "/u/alice/");
  assert.equal(root.children.find(child => child.dataset?.messageHashtag).dataset.messageHashtag, "#тема");
  assert.equal(root.children.at(-1).rel, "noopener noreferrer");
});

test("mention autocomplete replaces token at caret without swallowing adjacent text", () => {
  const social = load();
  const original = "Привет @ali и остальные";
  const token = social.mentionToken(original, "Привет @al".length);
  assert.equal(token.query, "al");
  const replaced = social.insertMention(original, token, "alice");
  assert.equal(replaced.text, "Привет @alice и остальные");
  assert.equal(replaced.caret, "Привет @alice".length);
  assert.equal(social.mentionToken("email@site", 10), null);
  assert.equal(social.mentionToken("https://x/@abc", 14), null);
});

test("reaction renderer discards stale revisions without replacing message media", () => {
  const social = load();
  const root = element("article");
  const media = element("audio");
  root.append(media, element("footer"));
  social.renderReactions(root, { reaction_version: 2, reactions: [
    { emoji: "👍", count: 2, selected: true },
  ] });
  const list = root.querySelector("[data-message-reactions]");
  assert.equal(list.children[0].attributes["aria-pressed"], "true");
  assert.equal(list.children[0].children[1].textContent, "2");
  assert.equal(root.children[0], media);
  social.renderReactions(root, { reaction_version: 1, reactions: [] });
  assert.equal(list.children.length, 1);
  social.renderReactions(root, { reaction_version: 3, reactions: [] });
  assert.equal(list.hidden, true);
  assert.equal(root.children[0], media);
});
