const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const read = file => fs.readFileSync(path.join(__dirname, "..", file), "utf8");
function helpers() {
  const context = {window: {}, document: {getElementById: () => null}};
  vm.runInNewContext(read("static/js/read-ack.js"), context);
  return context.window.SovietgramReadAckHelpers;
}
const bounds = {left: 400, right: 1200, top: 50, bottom: 800};
function article(id, top, bottom, own = false, left = 450, right = 650) {
  return {
    dataset: {messageId: String(id), messageOwn: String(own)},
    getBoundingClientRect: () => ({left,right,top,bottom,width:right-left,height:bottom-top}),
  };
}
function plain(value) {return JSON.parse(JSON.stringify(value));}

test("a visible incoming message in a short chat is a read candidate", () => {
  const {visibleCandidate} = helpers();
  assert.equal(visibleCandidate([article(18, 700, 750)], bounds, 0), 18);
  assert.equal(visibleCandidate([article(18, 700, 750), article(19, 755, 795,true)], bounds, 0), 18);
  assert.equal(visibleCandidate([article(18, 700, 750)], bounds, 18), 18);
});

test("offscreen, outgoing, hidden and only partly visible bubbles are not read", () => {
  const {visibleCandidate} = helpers();
  const hidden = article(19, 300, 350); hidden.hidden = true;
  assert.equal(visibleCandidate([
    article(11,-200,20), article(12,780,900), article(13,100,150,true),
    article(14,100,150,false,-20,200), article(15,300,300), hidden,
  ], bounds, 10), 10);
  assert.equal(visibleCandidate([article(21,-100,1200)],bounds,0),21);
  assert.equal(visibleCandidate([article(21,100,120)],{...bounds,bottom:50},0),0);
});

test("focus, visibility, overlay and history guard prevent acknowledgement", async () => {
  const {createTracker} = helpers();
  let allowed = false, writes = 0, refreshes = 0;
  const tracker = createTracker({
    canRead: () => allowed, candidate: () => 9,
    send: async () => {writes++;return {ok:true,own_last_read_id:9};},
    refreshed: () => refreshes++,
  });
  await tracker.check();
  assert.equal(writes,0);
  allowed = true;
  await tracker.check();
  await tracker.check();
  assert.equal(writes,1);
  assert.equal(refreshes,1);
  assert.equal(tracker.cursor,9);
});

test("failed acknowledgement is retried and marker survives until success", async () => {
  const {createTracker} = helpers();
  const requests = [];
  let time = 0, refreshes = 0;
  const tracker = createTracker({
    initialCursor: 1, initialMarker: "original-marker",
    canRead: () => true, candidate: () => 5, now: () => time,
    send: async fields => {
      requests.push(plain(fields));
      if (requests.length === 1) throw Error("offline");
      return {ok:true,own_last_read_id:5,marked_unread:false};
    },
    refreshed: () => refreshes++,
  });
  await tracker.check();
  assert.equal(tracker.cursor,1);
  await tracker.check();
  assert.equal(requests.length,1);
  time += 1001;
  await tracker.check();
  assert.deepEqual(requests,[{message_id:5,opened_marker:"original-marker"},{message_id:5,opened_marker:"original-marker"}]);
  assert.equal(tracker.cursor,5);
  assert.equal(refreshes,1);
  await tracker.check();
  assert.equal(requests.length,2);
});

test("simultaneous timer and scroll cannot send duplicate read acknowledgements", async () => {
  const {createTracker} = helpers();
  let resolve, writes=0, newest=3;
  const tracker=createTracker({
    canRead:()=>true,candidate:()=>newest,
    send:fields=>{writes++;return new Promise(done=>{resolve=()=>done({ok:true,own_last_read_id:fields.message_id});});},
  });
  const first=tracker.check();
  await tracker.check();
  assert.equal(writes,1);
  newest=4;
  resolve();await first;
  const second=tracker.check();
  assert.equal(writes,2);
  resolve();await second;
  assert.equal(tracker.cursor,4);
  tracker.observeCursor(2);
  assert.equal(tracker.cursor,4);
});

test("manual marker-only opening does not clear a different newer server mark", async () => {
  const {createTracker} = helpers();
  const requests=[];
  const tracker=createTracker({
    initialCursor:9,initialMarker:"old-marker",canRead:()=>true,candidate:cursor=>cursor,
    send:async fields=>{requests.push(plain(fields));return {ok:true,own_last_read_id:9,marked_unread:true};},
  });
  await tracker.check();await tracker.check();
  assert.deepEqual(requests,[{message_id:0,opened_marker:"old-marker"}]);
});

test("actual browser wiring runs an independent heartbeat and refreshes sidebar after ACK",()=>{
  const source=read("static/js/read-ack.js");
  assert.match(source,/window\.setInterval\(\(\) => void tracker\.check\(\), 1000\)/);
  assert.match(source,/document\.hasFocus\(\)/);
  assert.match(source,/!document\.hidden/);
  assert.match(source,/readHistoryBusy !== "true"/);
  assert.match(source,/window\.SovietgramSidebar\?\.refresh\(\)/);
  assert.match(source,/account_id: account/);
  const chat=read("static/js/chat.js");
  assert.match(chat,/window\.SovietgramReadAck\?\.observeCursor\(payload\.own_last_read_id\)/);
  assert.match(chat,/dataset\.readHistoryBusy = "true"/);
  assert.match(read("static/js/search.js"),/new URL\(href, window\.location\.href\)/);
  const template=read("templates/messenger/index.html");
  assert.ok(template.indexOf("js/read-ack.js")<template.indexOf("js/chat.js"));
});
