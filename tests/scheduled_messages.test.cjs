const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const read = name => fs.readFileSync(path.join(__dirname,"..",name),"utf8");

function load(file) {
  const context = { window: {}, document: { getElementById: () => null } };
  vm.runInNewContext(read("static/js/"+file),context);
  return context.window;
}
test("schedule local datetime round trips to the server's UTC timestamp", () => {
  const api=load("scheduled-messages.js").SovietgramSchedule;
  const future=new Date("2028-02-29T16:40:00.000Z");
  const local=api.localDateValue(future);
  assert.equal(api.toScheduledISO(local,future.getTime()-60000),future.toISOString());
  assert.throws(()=>api.toScheduledISO(local,future.getTime()));
  assert.throws(()=>api.toScheduledISO("not a date",future.getTime()));
  assert.throws(()=>api.toScheduledISO(local,future.getTime()-366*86400000));
});

test("notification overlap does not replay the same messages", () => {
  const api=load("sound-notifications.js").SovietgramNotificationSound;
  const seen=new Set();
  assert.deepEqual(Array.from(api.newIds([1,2,2],seen)),["1","2"]);
  assert.deepEqual(Array.from(api.newIds([2,3],seen)),["3"]);
  assert.equal(api.nextCursor("2026-11-24T20:00:02Z","2026-11-24T20:00:00Z"),"2026-11-24T20:00:00.000Z");
  assert.equal(api.nextCursor("2026-11-24T20:00:10Z","2026-11-24T20:00:00Z"),"2026-11-24T20:00:05.000Z");
});

test("text and media retries include silent mode and outbox uses a private endpoint", () => {
  const chat=read("static/js/chat.js");
  assert.match(chat,/if \(silent\) data.set\("silent", "1"\)/);
  assert.match(chat,/silent \? \[sentText, sentReply, "silent"\]/);
  const media=read("static/js/attachment-files.js");
  assert.match(media,/data.append\("silent", "1"\)/);
  assert.match(media,/clientId, silent, 1/);
  assert.match(read("static/js/scheduled-messages.js"),/fields.client_message_id=await window.SovietgramSendRetry.textKey/);
  assert.match(read("templates/messenger/index.html"),/data-scheduled-url/);
  assert.match(read("templates/messenger/_scheduled_messages.html"),/id="scheduledDate"/);
});
