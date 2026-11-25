const {test}=require("node:test");
const assert=require("node:assert/strict");
const fs=require("node:fs");
const path=require("node:path");
const read=p=>fs.readFileSync(path.join(__dirname,"..",p),"utf8");
test("community moderation editor posts scoped explicit rights and duration",()=>{
  const js=read("static/js/community-settings.js");
  assert.match(js,/settings.urls.moderation/);
  assert.match(js,/account_id:document.getElementById\("messageStage"\)\?\.dataset.accountId/);
  assert.match(js,/permissions:JSON.stringify\(permissions\)/);
  assert.match(js,/member.can_edit_admin_rights/);
  assert.match(js,/member.can_restrict/);
  assert.match(js,/member.can_ban/);
  assert.match(js,/applyModeration\("lift",row.user_id\)/);
  assert.match(read("templates/messenger/_community_profile_overlay.html"),/id="communityModerationDialog"/);
});
test("message moderation controls respect server-derived privileges",()=>{
  assert.match(read("static/js/chat-controls.js"),/conversation.dataset.canModerateMessages === "true"/);
  assert.match(read("templates/messenger/index.html"),/data-can-moderate-messages=/);
  assert.match(read("templates/messenger/index.html"),/{% if can_pin_messages %}/);
  assert.match(read("static/js/community-profile.js"),/!profile.can_edit_info/);
});
