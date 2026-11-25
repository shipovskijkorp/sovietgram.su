const {test}=require("node:test");
const assert=require("node:assert/strict");
const fs=require("node:fs");
const vm=require("node:vm");
const {webcrypto}=require("node:crypto");
const context={window:{crypto:webcrypto}};
vm.runInNewContext(fs.readFileSync("static/js/send-retry.js","utf8"),context);
const {createOutbox}=context.window.SovietgramSendRetry;
function storageFor(map=new Map()) {
  return {getItem:key=>map.get(key)??null,setItem:(key,value)=>map.set(key,value),removeItem:key=>map.delete(key)};
}
test("queued message survives reload and preserves UUID on uncertain delivery",async()=>{
  const storage=storageFor();let time=1000;const sent=[];
  let box=createOutbox({storage,key:"account1.chat1",now:()=>time,send:async item=>{
    sent.push(item);throw Error("lost response");
  }});
  assert.equal(box.enqueue("hello","4",true),true);
  const id=box.snapshot()[0].id;
  assert.equal(await box.flush(),false);
  assert.equal(box.snapshot()[0].state,"waiting");
  assert.equal(box.snapshot()[0].id,id);
  assert.equal(await box.flush(),false);
  assert.equal(sent.length,1);
  time+=5000;
  box=createOutbox({storage,key:"account1.chat1",now:()=>time,send:async item=>{sent.push(item);return {ok:true};}});
  assert.equal(await box.flush(),true);
  assert.equal(sent[1].id,id);assert.equal(sent[1].reply,"4");assert.equal(sent[1].silent,true);
  assert.equal(box.snapshot().length,0);
  assert.equal(storage.getItem("account1.chat1"),null);
});
test("permanent error blocks FIFO until retry or discard",async()=>{
  let rejected=true;const sent=[];
  const box=createOutbox({storage:storageFor(),key:"q",send:async item=>{
    sent.push(item.text);return rejected?{error:"Forbidden"}:{ok:true};
  }});
  box.enqueue("first");box.enqueue("second");
  assert.equal(await box.flush(),false);assert.equal(box.snapshot()[0].state,"failed");
  assert.equal(await box.flush(),false);assert.deepEqual(sent,["first"]);
  rejected=false;
  box.retryItem(box.snapshot()[0].id);
  assert.equal(await box.flush(),true);assert.equal(await box.flush(),true);
  assert.deepEqual(sent,["first","first","second"]);
});
test("retry delay, storage isolation, queue bound and cancellation",async()=>{
  const storage=storageFor();let t=1000;
  const box=createOutbox({storage,key:"a",now:()=>t,send:async()=>({retry:true,delay:60000})});
  for(let i=0;i<20;i++)assert.equal(box.enqueue("message "+i),true);
  assert.equal(box.enqueue("overflow"),false);
  await box.flush();assert.equal(box.snapshot()[0].nextAttempt,61000);
  assert.equal(createOutbox({storage,key:"b",send:async()=>({ok:true})}).snapshot().length,0);
  box.discard(box.snapshot()[0].id);assert.equal(box.snapshot().length,19);
});
test("concurrent flush does not send same queued item twice",async()=>{
  let resolve;let calls=0;
  const box=createOutbox({storage:storageFor(),key:"q",send:()=>{calls++;return new Promise(r=>{resolve=r;});}});
  box.enqueue("message");
  const first=box.flush();
  assert.equal(await box.flush(),false);
  assert.equal(box.discard(box.snapshot()[0].id),false);
  resolve({ok:true});assert.equal(await first,true);assert.equal(calls,1);
});
