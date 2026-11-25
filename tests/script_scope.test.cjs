const {test}=require("node:test");
const assert=require("node:assert/strict");
const fs=require("node:fs");
const vm=require("node:vm");
test("classic page scripts do not redeclare global lexical identifiers",()=>{
  // Compiling the actual scripts in document order catches lexical conflicts
  // that node --check on each individual script cannot see.
  const paths=["app.js","profile.js","chat.js","media-gallery.js"];
  const source=paths.map(p=>fs.readFileSync("static/js/"+p,"utf8")).join("\n;\n");
  assert.doesNotThrow(()=>new vm.Script(source));
});
test("hidden elements stay hidden when components use explicit display rules",()=>{
  assert.match(fs.readFileSync("static/css/styles.css","utf8"),/\[hidden\][^{]*\{\s*display:\s*none\s*!important/);
});
