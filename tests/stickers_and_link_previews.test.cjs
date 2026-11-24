const {test}=require("node:test");
const assert=require("node:assert/strict");
const fs=require("node:fs");
const path=require("node:path");
const read=file=>fs.readFileSync(path.join(__dirname,"..",file),"utf8");
test("sticker sends use account-scoped idempotent keys and preserve the text draft",()=>{
  const js=read("static/js/chat.js");
  const send=js.slice(js.indexOf("async sendSticker("),js.indexOf("clearScheduledDraft("));
  assert.match(send,/data.set\("sticker_id"/);
  assert.match(send,/data.set\("account_id"/);
  assert.match(send,/stickerSendKeys/);
  assert.match(send,/renderMessage\(payload.message\)/);
  assert.doesNotMatch(send,/messageInput.value = ""|clearDraftState\(/);
  assert.match(read("static/js/stickers.js"),/save_message/);
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
