const test=require("node:test");
const assert=require("node:assert/strict");
const {messages,createDeck}=require("../static/js/easter-star.js");

function memory(){
  const values=new Map();
  return {getItem:key=>values.get(key)??null,setItem:(key,value)=>values.set(key,value)};
}
test("every one of the 45 replies appears once per cycle, never twice consecutively",()=>{
  assert.equal(messages.length,45);
  assert.equal(new Set(messages).size,45);
  const next=createDeck({random:()=>0});
  let previous=null;
  for(let cycle=0;cycle<3;cycle++){
    const seen=new Set();
    for(let i=0;i<messages.length;i++){
      const reply=next();
      assert.notEqual(reply,previous);
      assert.ok(!seen.has(reply));
      seen.add(reply);
      previous=reply;
    }
    assert.equal(seen.size,messages.length);
  }
});
test("cycle survives reload and navigation; sequential clicks in another tab use the same deck",()=>{
  const storage=memory(),key="account-1";
  const first=createDeck({storage,key,random:()=>0});
  const seen=new Set(Array.from({length:17},()=>first()));
  const second=createDeck({storage,key,random:()=>0});
  for(let i=17;i<45;i++){
    const reply=(i%2===0?first:second)();
    assert.ok(!seen.has(reply));
    seen.add(reply);
  }
  assert.equal(seen.size,45);
  const other=createDeck({storage,key:"account-2",random:()=>0});
  assert.equal(other(),messages[0]);
});
test("storage failures or corrupt state fall back safely",()=>{
  const storage=memory(),key="corrupt";
  storage.setItem(key,"not valid JSON");
  const next=createDeck({storage,key,random:()=>0});
  assert.equal(next(),messages[0]);
  assert.equal(next(),messages[1]);
  const blocked=createDeck({catalog:["a","b"],random:()=>0,storage:{
    getItem(){throw Error("blocked");},setItem(){throw Error("blocked");}
  }});
  assert.deepEqual([blocked(),blocked(),blocked(),blocked()],["a","b","a","b"]);
});
