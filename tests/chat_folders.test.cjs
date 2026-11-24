const {test}=require("node:test");
const assert=require("node:assert/strict");
const fs=require("node:fs");
const path=require("node:path");
const vm=require("node:vm");
const read=p=>fs.readFileSync(path.join(__dirname,"..",p),"utf8");
function helpers(){
  const context={window:{},document:{getElementById:()=>null}};
  vm.runInNewContext(read("static/js/chat-folders.js"),context);
  return context.window.SovietgramFolderHelpers;
}
const plain=value=>JSON.parse(JSON.stringify(value));
test("explicit exceptions override automatic categories and excluded conditions",()=>{
  const {matches}=helpers();
  const folder={categories:["groups"],included:[1],excluded:[2],exclude_muted:true,exclude_archived:true,exclude_read:true};
  assert.equal(matches(folder,{id:1,category:"contacts",muted:true,archived:true,unread:false}),true);
  assert.equal(matches(folder,{id:2,category:"groups",unread:true}),false);
  assert.equal(matches(folder,{id:3,category:"groups",unread:true}),true);
  assert.equal(matches(folder,{id:3,category:"groups",unread:false}),false);
  assert.equal(matches(folder,{id:3,category:"groups",unread:true,muted:true}),false);
});
test("membership modes are mutually exclusive and bounded",()=>{
  const {changeMode,modeOf}=helpers();
  assert.deepEqual(plain(changeMode([1,2],[3],1,"exclude")),{included:[2],excluded:[3,1]});
  assert.deepEqual(plain(changeMode([1,2],[3],1,"auto")),{included:[2],excluded:[3]});
  assert.equal(modeOf({included:[1],excluded:[]},1),"include");
  assert.throws(()=>changeMode(Array.from({length:200},(_,i)=>i+1),[],201,"include"));
});
test("folder management, sidebar refresh, archive settings and folder-scoped actions are wired",()=>{
  const source=read("static/js/chat-folders.js");
  assert.match(source,/account_id:dialog.dataset.accountId/);
  assert.match(source,/revision:folder.revision/);
  assert.match(source,/void window.SovietgramSidebar\?\.refresh\(\)/);
  assert.match(read("static/js/archive.js"),/folder_id:customFolder/);
  assert.match(read("static/js/search.js"),/tabs.replaceChildren\(\.\.\.nextTabs.childNodes\)/);
  assert.match(read("templates/messenger/_chat_list.html"),/\?folder={{ active_folder.pk }}/);
  assert.match(read("templates/accounts/_settings_overlay.html"),/data-setting="keep_folder_chats_archived"/);
  assert.match(read("templates/messenger/index.html"),/js\/chat-folders.js/);
});
