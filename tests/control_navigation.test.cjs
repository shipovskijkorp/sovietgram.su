const {test}=require("node:test");
const assert=require("node:assert/strict");
const fs=require("node:fs");
const read=file=>fs.readFileSync(file,"utf8");
test("community management entry points belong to the management controller",()=>{
  const settings=read("static/js/community-settings.js");
  assert.match(settings,/\[data-open-community-settings\], #communityProfileSettingsOpen/);
  assert.match(settings,/panel.hidden = false;[\s\S]*?fetchJson\(profileRoot.dataset.settingsUrl/);
  assert.doesNotMatch(settings,/await window.openCommunityProfile\(/);
  assert.doesNotMatch(read("static/js/chat.js"),/querySelector\("\[data-open-community-settings\]"\)/);
  const html=read("templates/messenger/_community_profile_overlay.html");
  assert.match(html,/id="communitySettingsRetry"/);
  assert.match(html,/id="communityProfileRetry"/);
});
test("chat menu can start selection with zero messages selected",()=>{
  const controls=read("static/js/chat-controls.js");
  assert.match(controls,/const hadSelection = selectedArticles.size > 0/);
  assert.match(controls,/if \(hadSelection && !selectedArticles.size\) selectionMode = false/);
  assert.match(controls,/\[data-select-messages\][\s\S]*?setSelectionMode\(true\)/);
});
