const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const read = file => fs.readFileSync(path.join(__dirname,"..",file),"utf8");

function helpers() {
  const context={window:{},document:{getElementById:()=>null}};
  vm.runInNewContext(read("static/js/archive.js"),context);
  return context.window.SovietgramArchiveHelpers;
}

test("selection is bounded and toggles without mutating the previous selection",()=>{
  const {nextSelection}=helpers();
  const prior=new Set(["1"]);
  assert.deepEqual(Array.from(nextSelection(prior,"2",2)),["1","2"]);
  assert.deepEqual(Array.from(prior),["1"]);
  assert.deepEqual(Array.from(nextSelection(new Set(["1","2"]),"3",2)),["1","2"]);
  assert.deepEqual(Array.from(nextSelection(new Set(["1","2"]),"1",2)),["2"]);
});

test("hidden archive can be temporarily revealed only in the appropriate sidebar filter",()=>{
  const {archiveVisible}=helpers();
  assert.equal(archiveVisible(true,false,false,"all",3),false);
  assert.equal(archiveVisible(true,true,false,"all",3),true);
  assert.equal(archiveVisible(false,false,false,"unread",0),false);
  assert.equal(archiveVisible(false,false,false,"unread",2),true);
  assert.equal(archiveVisible(false,true,true,"all",2),false);
  assert.equal(archiveVisible(false,true,false,"channel",2),false);
});

test("live archive controls are wired to explicit actions and preserve account and folder scope",()=>{
  const source=read("static/js/archive.js");
  assert.match(source,/account_id:account,action/);
  assert.match(source,/folder:archived\?"archive":"main"/);
  assert.match(source,/chat_ids:JSON.stringify\(numbers\)/);
  assert.match(source,/post\("archive_read_all"\)/);
  assert.match(source,/post\("archive_visibility"/);
  assert.match(source,/touchstart/);
  assert.match(source,/touchend/);
  assert.match(source,/move_up/);
  assert.match(read("static/js/search.js"),/next.dataset.accountId !== chatList.dataset.accountId/);
  assert.match(read("static/js/search.js"),/SovietgramArchive\?\.onRefresh\(\)/);
  const template=read("templates/messenger/index.html");
  assert.match(template,/id="archiveDrawerEntry"/);
  assert.match(template,/id="archiveSelectionBar"/);
  assert.match(template,/id="archiveFolderMenuButton"/);
  assert.match(template,/data-global-search-url="[^"]+\?archived=1/);
  assert.match(read("templates/messenger/_chat_list.html"),/data-archive-loud-unread/);
});
