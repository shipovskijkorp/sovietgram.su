const {test}=require("node:test");
const assert=require("node:assert/strict");
const fs=require("node:fs");
const path=require("node:path");
const read=p=>fs.readFileSync(path.join(__dirname,"..",p),"utf8");
test("favorites and recent lists use explicit scoped actions",()=>{
  const js=read("static/js/stickers.js");
  assert.match(js,/result.favorites/);
  assert.match(js,/result.recent/);
  assert.match(js,/mutate\("favorite",\{sticker_id:item.id,favorite:item.favorite\?"0":"1"\}/);
  assert.match(js,/mutate\("forget_recent"/);
  assert.match(js,/mutate\("clear_recent"\)/);
  assert.match(read("templates/messenger/_sticker_controls.html"),/id="stickerClearRecent"/);
});
test("moderated invitation UI includes approval flag and stale request protection",()=>{
  const js=read("static/js/community-settings.js");
  assert.match(js,/requires_approval: data.get\("requires_approval"\)/);
  assert.match(js,/settings.urls.join_request_action/);
  assert.match(js,/revision:item.revision/);
  assert.match(read("templates/messenger/_community_profile_overlay.html"),/name="requires_approval"/);
  assert.match(read("templates/messenger/join_requests.html"),/name="revision" value="{{ row.created_at.isoformat }}"/);
  assert.match(read("templates/messenger/join_invite.html"),/invite.requires_approval/);
});
