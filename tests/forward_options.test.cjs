const {test}=require("node:test");
const assert=require("node:assert/strict");
const fs=require("node:fs");
const read=path=>fs.readFileSync(path,"utf8");
test("forwarding has a single modern controller with stable per-target keys",()=>{
  const chat=read("static/js/chat.js"), controls=read("static/js/chat-controls.js");
  assert.doesNotMatch(chat,/legacyForwardKeys|const forwardTargets =/);
  assert.match(controls,/selectedTargets\.size < 10/);
  assert.match(controls,/forwardCompleted\.has\(key\)/);
  assert.match(controls,/forwardSendKeys\.key\(key, \[article\.dataset\.forwardUrl, hide, silent\]\)/);
  assert.match(controls,/hide_sender: hide \? "1" : "0"/);
});
test("hashtag search uses the paginated controller, not a second HTTP request",()=>{
  const controls=read("static/js/chat-controls.js");
  assert.doesNotMatch(controls,/function scheduleSearch\(/);
  assert.match(controls,/searchInput\.dispatchEvent\(new Event\("input"/);
  assert.match(read("static/js/chat.js"),/searchInput\?\.addEventListener\("input", restartChatSearch\)/);
});
