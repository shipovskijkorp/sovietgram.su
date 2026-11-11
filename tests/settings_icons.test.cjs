const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const read = relative => fs.readFileSync(
  path.join(__dirname, "..", relative), "utf8",
);

test("settings overlay uses the shared native lock, settings, and archive icons", () => {
  const template = read("templates/accounts/_settings_overlay.html");
  assert.match(
    template,
    /tg-native-icon tg-native-icon--lock tg-settings-row__icon/,
  );
  assert.match(
    template,
    /tg-native-icon tg-native-icon--settings tg-settings-row__icon/,
  );
  assert.match(
    template,
    /tg-native-icon tg-native-icon--archive tg-settings-row__icon/,
  );
  assert.doesNotMatch(template, /tg-settings-section-icon--(?:lock|chat|archive)/);
});

test("shared native icons use luminance masks for opaque Telegram PNG assets", () => {
  const css = read("static/css/icon-scale.css");
  const nativeIcon = css.match(/\.tg-native-icon\s*\{[^}]+\}/);
  assert.ok(nativeIcon, "native icon base rule must exist");
  assert.match(nativeIcon[0], /mask-mode:\s*luminance/);
  assert.match(nativeIcon[0], /mask-size:\s*24px 24px/);
});


test("settings radio controls are centered in their grid column", () => {
  const css = read("static/css/settings.css");
  assert.match(
    css,
    /\.tg-settings-radio-row__control\s*\{\s*justify-self:\s*center;\s*\}/,
  );
});
