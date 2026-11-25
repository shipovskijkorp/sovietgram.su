const {test}=require("node:test");
const assert=require("node:assert/strict");
const fs=require("node:fs");
const path=require("node:path");
const read=file=>fs.readFileSync(path.join(__dirname,"..",file),"utf8");
const vm=require("node:vm");
const {webcrypto}=require("node:crypto");
const {TextEncoder}=require("node:util");

function stickerClient(transport, storage = new Map()) {
  const context = {
    window:{crypto:webcrypto}, document:{getElementById:()=>null},
    fetch:transport, FormData, TextEncoder,
    sessionStorage:{
      getItem:key=>storage.get(key)??null,
      setItem:(key,value)=>storage.set(key,value),
      removeItem:key=>storage.delete(key),
    },
  };
  vm.runInNewContext(read("static/js/send-retry.js"),context);
  vm.runInNewContext(read("static/js/stickers.js"),context);
  return context.window.SovietgramStickerSend.createStickerSender({
    retry:context.window.SovietgramSendRetry, csrf:"csrf", url:"/chat/17/send/",
    accountId:"4",chatId:"17",
  });
}
function response(status, payload, redirected = false) {
  return {status,ok:status>=200&&status<300,redirected,json:async()=>payload};
}
test("sticker transport works without chat.js and preserves the text draft",async()=>{
  const calls=[];
  const send=stickerClient(async (url, options)=>{
    calls.push({url,options});
    return response(200,{ok:true,message:{id:81,attachments:[{kind:"sticker"}]}});
  });
  assert.equal((await send(5,"12",true)).id,81);
  const {url,options}=calls[0];
  assert.equal(url,"/chat/17/send/");
  assert.equal(options.body.get("account_id"),"4");
  assert.equal(options.body.get("sticker_id"),"5");
  assert.equal(options.body.get("attachment_mode"),"media");
  assert.equal(options.body.get("reply_to"),"12");
  assert.equal(options.body.get("silent"),"1");
  assert.match(options.body.get("client_message_id"),/^[a-f0-9-]{36}$/);
  assert.equal(options.body.has("text"),false);
  assert.equal(options.body.has("attachments"),false);
  assert.equal(options.credentials,"same-origin");
  assert.equal(options.headers["X-Requested-With"],"XMLHttpRequest");
  const js=read("static/js/stickers.js");
  assert.doesNotMatch(js,/SovietgramChat\?\.sendSticker|messageInput\.value\s*=|clearDraftState\(/);
  assert.match(js,/save_message/);
  assert.match(js,/renderSovietgramChatMessage\(message\)/);
});
test("sticker retry reuses the UUID after lost responses, even after reload",async()=>{
  const ids=[],storage=new Map();
  let fail=true;
  const transport=async(_,options)=>{
    ids.push(options.body.get("client_message_id"));
    if(fail)throw new TypeError("network");
    return response(200,{ok:true,message:{id:9}});
  };
  await assert.rejects(stickerClient(transport,storage)(3),/Нет ответа сервера/);
  fail=false;
  assert.equal((await stickerClient(transport,storage)(3)).id,9);
  assert.equal(ids.length,3);
  assert.equal(new Set(ids).size,1);
  await stickerClient(transport,storage)(3);
  assert.notEqual(ids[3],ids[0]);
});
test("sticker errors expose actual server reason instead of a generic boolean",async()=>{
  await assert.rejects(stickerClient(async()=>response(403,{error:"Медиа запрещены"}))(3),/Медиа запрещены/);
  await assert.rejects(stickerClient(async()=>response(400,{errors:{reply_to:[{message:"Ответ недоступен"}]}}))(3),/Ответ недоступен/);
  await assert.rejects(stickerClient(async()=>response(500,{}))(3),/Ошибка сервера \(500\)/);
  await assert.rejects(stickerClient(async()=>response(200,{},true))(3),/Сессия истекла/);
});
test("link previews render remote metadata as text and do not load remote images",()=>{
  const js=read("static/js/link-previews.js");
  assert.match(js,/data-load-link-preview/);
  assert.match(js,/title.textContent=preview.title/);
  assert.match(js,/desc.textContent=preview.description/);
  assert.doesNotMatch(js,/innerHTML|new Image\(|\.src\s*=/);
  assert.match(js,/message_id:article.dataset.messageId/);
  const template=read("templates/messenger/index.html");
  assert.match(template,/data-link-preview-url/);
  assert.match(template,/attachment.kind == 'sticker'/);
  assert.match(template,/js\/stickers.js/);
  assert.match(template,/js\/link-previews.js/);
});
