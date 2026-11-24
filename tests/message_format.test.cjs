const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const read = name => fs.readFileSync(path.join(__dirname,"..",name),"utf8");

function element(tag) {
  return {
    tag,children:[],attributes:{},dataset:{},handlers:{},innerHTML:"",
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

test("server-rendered Markdown is used instead of the raw source",()=>{
  const {SovietgramSocial:social}=load();
  const root=element("div");
  const source="# Heading\n\n**text**";
  const safe="<h1>Heading</h1>\n<p><strong>text</strong></p>";
  social.renderText(root,source,safe);
  assert.equal(root.innerHTML,safe);
  assert.equal(root.dataset.markdownRendered,"true");
  assert.equal(root.dataset.socialText,source);
  social.renderText(root,source,safe);
  assert.equal(root.innerHTML,safe);
  social.renderText(root,"## Updated","<h2>Updated</h2>");
  assert.equal(root.innerHTML,"<h2>Updated</h2>");
});

test("plain text fallback never interprets raw HTML as markup",()=>{
  const {SovietgramSocial:social}=load();
  const root=element("div");
  social.renderText(root,"<img src=x onerror=alert(1)> @alice");
  assert.equal(root.innerHTML,"");
  assert.equal(root.children[0].textContent,"<img src=x onerror=alert(1)> ");
  assert.equal(root.children[1].href,"/u/alice/");
});

test("bold and italic selection toggles preserve the other style",()=>{
  const {SovietgramFormat:format}=load();
  const first=plain(format.wrapSelection("hello world",6,11,"bold"));
  assert.deepEqual(first,{text:"hello **world**",start:8,end:13});
  assert.deepEqual(plain(format.wrapSelection(first.text,first.start,first.end,"bold")),{text:"hello world",start:6,end:11});
  const combined=plain(format.wrapSelection(first.text,first.start,first.end,"italic"));
  assert.equal(combined.text,"hello ***world***");
  assert.deepEqual(plain(format.wrapSelection(combined.text,combined.start,combined.end,"italic")),first);
  const empty=plain(format.wrapSelection("hello",5,5,"underline"));
  assert.deepEqual(empty,{text:"hello++++",start:7,end:7});
});

test("block insertion adds standard Markdown syntax",()=>{
  const {SovietgramFormat:format}=load();
  const quote=plain(format.wrapSelection("one\ntwo\nthree",1,6,"quote"));
  assert.equal(quote.text,"> one\n> two\nthree");
  assert.equal(format.wrapSelection("one\ntwo",0,7,"list").text,"- one\n- two");
  assert.equal(format.wrapSelection("one\ntwo",0,7,"ordered").text,"1. one\n2. two");
  assert.equal(format.wrapSelection("one",0,3,"task").text,"- [ ] one");
  assert.equal(format.wrapSelection("title",0,5,"heading").text,"## title");
  assert.match(format.wrapSelection("",0,0,"table").text,/\| --- \| --- \|/);
  assert.equal(format.wrapSelection("link",0,4,"link").text,"[link](https://example.com)");
});

test("emoji insertion keeps Unicode clusters and a bounded deduplicated history",()=>{
  const {SovietgramComposerTools:tools}=load();
  const emoji="❤️‍🔥";
  assert.deepEqual(plain(tools.insertEmoji("aXb",1,2,emoji)),{text:"a"+emoji+"b",start:1+emoji.length,end:1+emoji.length});
  const all=tools.groups.flatMap(group=>group.values);
  assert.ok(all.length>200);
  assert.deepEqual(plain(tools.addRecent(["😀","😂","bad","😀"],"😀")),["😀","😂"]);
  assert.equal(tools.addRecent(all.slice(0,50),all[55]).length,24);
});

test("initial, dynamic, edited and preview messages use the same server HTML",()=>{
  const template=read("templates/messenger/index.html");
  assert.match(template,/message.markdown_html_ui\|safe/);
  assert.match(template,/data-markdown-rendered="true"/);
  assert.match(template,/data-markdown-preview-url/);
  assert.match(read("static/js/chat.js"),/linkifyInto\(paragraph, message.text, message.markdown_html\)/);
  assert.match(read("static/js/chat-controls.js"),/renderText\(paragraph, message.text, message.markdown_html\)/);
  assert.match(read("static/js/composer-tools.js"),/renderText\(body,text,result.markdown_html\)/);
  assert.match(read("static/js/message-social.js"),/image.referrerPolicy = "no-referrer"/);
  assert.match(template,/image\/webp,image\/gif,video\/mp4/);
});
