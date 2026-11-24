const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const read = name => fs.readFileSync(path.join(__dirname,"..",name),"utf8");

function element(tag) {
  return {
    tag,children:[],attributes:{},dataset:{},handlers:{},
    appendChild(child) {this.children.push(child);return child;},
    replaceChildren(...children) {this.children=children;},
    setAttribute(key,value) {this.attributes[key]=value;},
    getAttribute(key) {return this.attributes[key];},
    addEventListener(name,handler) {this.handlers[name]=handler;},
  };
}
function load() {
  const context=vm.createContext({
    window:{},
    document:{
      getElementById:()=>null,
      querySelectorAll:()=>[],
      createElement:element,
      createTextNode:text=>({tag:"#text",textContent:text}),
    },
  });
  for (const file of ["message-format.js","message-social.js","composer-tools.js"]) {
    vm.runInContext(read("static/js/"+file),context);
  }
  return context.window;
}
const plain=value=>JSON.parse(JSON.stringify(value));

test("each markup type is rendered as a safe DOM element",()=>{
  const {SovietgramSocial:social}=load();
  const root=element("p");
  social.renderText(root,"**bold** *italic* __underline__ ~~strike~~ ||secret|| \x60code\x60\n> quote\n\x60\x60\x60\nx < y\n\x60\x60\x60");
  assert.deepEqual(root.children.filter(node=>node.tag!=="#text").map(node=>node.tag),["strong","em","u","s","button","code","span","code"]);
  const spoiler=root.children.find(node=>node.tag==="button");
  assert.equal(spoiler.getAttribute("aria-expanded"),"false");
  spoiler.handlers.click();
  assert.equal(spoiler.getAttribute("aria-expanded"),"true");
  const code=root.children.at(-1);
  assert.equal(code.textContent,"x < y");
  assert.equal(code.className,"message-code-block");
});

test("literal HTML, URLs, escaped markers and incomplete markup remain safe",()=>{
  const {SovietgramFormat:format,SovietgramSocial:social}=load();
  const source="https://example.org/a__b__ @foo__bar__ #a__b__ \\*literal\\* **incomplete";
  assert.deepEqual(plain(format.parse(source)),[{kind:"text",text:"https://example.org/a__b__ @foo__bar__ #a__b__ *literal* **incomplete"}]);
  const root=element("p");
  social.renderText(root,"**<img src=x onerror=alert(1)>** **@alice** \x60#notatag\x60");
  assert.equal(root.children[0].children[0].textContent,"<img src=x onerror=alert(1)>");
  const mention=root.children.find(node=>node.tag==="strong"&&node.children[0].tag==="a").children[0];
  assert.equal(mention.href,"/u/alice/");
  assert.equal(root.children.at(-1).textContent,"#notatag");
});

test("style combinations and selection formatting toggle correctly",()=>{
  const {SovietgramFormat:format}=load();
  const first=plain(format.wrapSelection("hello world",6,11,"bold"));
  assert.deepEqual(first,{text:"hello **world**",start:8,end:13});
  assert.deepEqual(plain(format.wrapSelection(first.text,first.start,first.end,"bold")),{text:"hello world",start:6,end:11});
  const combined=plain(format.wrapSelection(first.text,first.start,first.end,"italic"));
  assert.equal(combined.text,"hello ***world***");
  assert.equal(format.parse(combined.text)[1].kind,"boldItalic");
  const empty=plain(format.wrapSelection("hello",5,5,"underline"));
  assert.deepEqual(empty,{text:"hello____",start:7,end:7});
});

test("quotes wrap selected complete lines and code preserves whitespace",()=>{
  const {SovietgramFormat:format}=load();
  const quote=plain(format.wrapSelection("one\ntwo\nthree",1,6,"quote"));
  assert.equal(quote.text,"> one\n> two\nthree");
  assert.equal(format.parse(quote.text)[0].kind,"quote");
  const block=plain(format.wrapSelection("  a\n b",0,6,"block"));
  assert.equal(format.parse(block.text)[0].text,"  a\n b");
});

test("emoji insertion keeps Unicode clusters and a bounded deduplicated history",()=>{
  const {SovietgramComposerTools:tools}=load();
  const emoji="❤️‍🔥";
  assert.deepEqual(plain(tools.insertEmoji("aXb",1,2,emoji)),{text:"a"+emoji+"b",start:1+emoji.length,end:1+emoji.length});
  const all=tools.groups.flatMap(group=>group.values);
  assert.ok(all.length>200);
  const history=tools.addRecent(["😀","😂","bad","😀"],"😀");
  assert.deepEqual(plain(history),["😀","😂"]);
  assert.equal(tools.addRecent(all.slice(0,50),all[55]).length,24);
});

test("composer tools are loaded before chat and the GIF input is enabled",()=>{
  const template=read("templates/messenger/index.html");
  assert.ok(template.indexOf("js/message-format.js")<template.indexOf("js/message-social.js"));
  assert.ok(template.indexOf("js/composer-tools.js")<template.indexOf("js/chat.js"));
  assert.match(template,/image\/webp,image\/gif,video\/mp4/);
  const picker=read("templates/messenger/_composer_tools.html");
  assert.match(picker,/data-compose-panel="format"/);
  assert.match(picker,/data-compose-panel="emoji"/);
  for (const file of ["chat.js","attachment-files.js"]) {
    assert.doesNotMatch(read("static/js/"+file),/GIF в Sovietgram пока отключены/);
  }
});
