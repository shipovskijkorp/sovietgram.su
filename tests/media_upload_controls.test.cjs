const {test}=require("node:test");
const assert=require("node:assert/strict");
const fs=require("node:fs");
const read=file=>fs.readFileSync(file,"utf8");
test("one uploader owns file selection, drop and paste",()=>{
  const chat=read("static/js/chat.js");
  const uploader=read("static/js/attachment-files.js");
  assert.doesNotMatch(chat,/function openMediaComposer|function uploadMediaRequest/);
  assert.match(uploader,/addEventListener\("drop"/);
  assert.match(uploader,/addEventListener\("paste"/);
  assert.match(uploader,/function openTransfer/);
  assert.match(uploader,/data.append\("account_id", accountId\)/);
});
test("retry plan keeps stable batch IDs and only sends unfinished uploads",()=>{
  const uploader=read("static/js/attachment-files.js");
  assert.match(uploader,/const plan = retryPlan \|\| buildPlan\(\)/);
  assert.match(uploader,/plan.batches\[plan.completed\]/);
  assert.match(uploader,/plan.completed\+\+/);
  assert.match(uploader,/activeUpload\?\.abort\(\)/);
  assert.match(uploader,/data.append\("compress_images", "1"\)/);
  assert.match(read("templates/messenger/index.html"),/id="mediaComposeCompress"/);
});

test("ordinary uploader receives the configured server limits",()=>{
  const template=read("templates/messenger/index.html");
  const uploader=read("static/js/attachment-files.js");
  assert.match(template,/data-max-file-mib="{{ upload_file_mib }}"/);
  assert.match(template,/data-max-total-mib="{{ upload_total_mib }}"/);
  assert.match(uploader,/form\.dataset\.maxFileMib/);
  assert.match(uploader,/form\.dataset\.maxTotalMib/);
  assert.match(uploader,/xhr\.status === 413/);
});

test("media retry plan is persisted before uploading and after every acknowledged batch",()=>{
  const js=read("static/js/attachment-files.js");
  const store=read("static/js/media-drafts.js");
  assert.match(js,/await persistCurrent\(\)/);
  assert.match(js,/plan\.completed\+\+;[\s\S]*?await persistCurrent\(\)/);
  assert.match(store,/current\?\.revision\|\|null/);
  assert.match(store,/store\.put\(\{key,revision,bytes,expiresAt:now\+TTL,data\}\)/);
  assert.match(js,/accountId\+"\x3a"\+conversation\.dataset\.chatId/);
});
