const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const source = fs.readFileSync(path.join(__dirname, "../static/js/voice-messages.js"), "utf8");
const speedKey = "sovietgram.voicePlaybackSpeed";
const volumeKey = "sovietgram.voiceVolume";
const autoplayKey = "sovietgram.voiceAutoplayNext";

// Exercise the actual player script and its settings handlers, not a copy
// of the preferences parser. The small DOM stand-in needs no media device.
class Element {
  constructor(tag = "div") {
    this.tagName = tag.toUpperCase();
    this.children = [];
    this.dataset = {};
    this.attributes = {};
    this.style = {};
    this.listeners = {};
    this.classes = new Set();
    this.classList = {
      toggle: (name, enabled) => enabled ? this.classes.add(name) : this.classes.delete(name),
    };
  }
  matches(selector) {
    const match = /^\[data-([a-z-]+)\]$/.exec(selector);
    if (!match) return false;
    const key = match[1].replace(/-([a-z])/g, (_, letter) => letter.toUpperCase());
    return Object.hasOwn(this.dataset, key);
  }
  querySelectorAll(selector) {
    return this.children.flatMap(child => [
      ...(child.matches(selector) ? [child] : []),
      ...child.querySelectorAll(selector),
    ]);
  }
  querySelector(selector) { return this.querySelectorAll(selector)[0] || null; }
  append(...children) { this.children.push(...children); }
  appendChild(child) { this.append(child); return child; }
  replaceChildren(...children) { this.children = children; }
  setAttribute(name, value) { this.attributes[name] = value; }
  addEventListener(name, listener) { (this.listeners[name] ||= []).push(listener); }
  emit(name, data = {}) {
    for (const listener of this.listeners[name] || []) listener({
      target: this, stopPropagation() {}, ...data,
    });
  }
  getBoundingClientRect() { return { top: 300, right: 350, bottom: 320, width: 270, height: 190 }; }
}

function load(storage = new Map(), unavailable = false) {
  const body = new Element("body");
  const root = new Element();
  root.dataset.voicePlayer = "";
  root.dataset.durationMs = "6000";
  root.dataset.waveform = "10,20,30";
  const playerElement = (tag, key) => {
    const node = new Element(tag);
    node.dataset[key] = "";
    root.append(node);
    return node;
  };
  const audio = playerElement("audio", "voiceAudio");
  audio.currentTime = 0;
  audio.duration = 6;
  playerElement("button", "voicePlay");
  playerElement("div", "voiceWaveform");
  const speed = playerElement("button", "voiceSettings");
  body.append(root);
  const document = {
    body,
    querySelector: selector => body.querySelector(selector),
    querySelectorAll: selector => body.querySelectorAll(selector),
    getElementById: () => null,
    createElement: tag => new Element(tag),
    addEventListener() {},
  };
  const window = { addEventListener() {}, innerWidth: 900, innerHeight: 600 };
  const localStorage = {
    getItem(key) {
      if (unavailable) throw new Error("Storage disabled");
      return storage.get(key) ?? null;
    },
    setItem(key, value) {
      if (unavailable) throw new Error("Storage disabled");
      storage.set(key, value);
    },
  };
  vm.runInNewContext(source, {
    window, document, Element, localStorage,
    MutationObserver: class { observe() {} },
  });
  speed.emit("click");
  return {
    api: window.SovietgramVoice,
    audio, speed,
    speedRange: body.querySelector("[data-voice-speed-range]"),
    volumeRange: body.querySelector("[data-voice-volume-range]"),
    autoplay: body.querySelector("[data-voice-autoplay]"),
    presets: body.querySelectorAll("[data-voice-speed-preset]"),
  };
}

test("first visit uses 1x speed and 100% volume in the player and selector", () => {
  const storage = new Map();
  const { api, audio, speed, speedRange, volumeRange, autoplay, presets } = load(storage);
  assert.equal(api.speed, 1);
  assert.equal(api.volume, 1);
  assert.equal(audio.playbackRate, 1);
  assert.equal(audio.defaultPlaybackRate, 1);
  assert.equal(audio.volume, 1);
  assert.equal(speed.textContent, "1×");
  assert.equal(speedRange.value, "1");
  assert.equal(volumeRange.value, "1");
  assert.equal(volumeRange.attributes["aria-valuetext"], "100%");
  assert.equal(autoplay.checked, true);
  assert.equal(presets.find(node => node.dataset.voiceSpeedPreset === "1").classes.has("is-active"), true);
  assert.equal(storage.size, 0, "Opening settings must not overwrite storage");
});

test("changed settings apply immediately and survive a page reload", () => {
  const storage = new Map();
  const first = load(storage);
  first.speedRange.value = "1.7";
  first.speedRange.emit("input");
  first.volumeRange.value = "0.35";
  first.volumeRange.emit("input");
  first.autoplay.checked = false;
  first.autoplay.emit("change");
  assert.equal(first.audio.playbackRate, 1.7);
  assert.equal(first.audio.volume, 0.35);
  assert.equal(first.volumeRange.attributes["aria-valuetext"], "35%");
  assert.equal(storage.get(speedKey), "1.7");
  assert.equal(storage.get(volumeKey), "0.35");
  assert.equal(storage.get(autoplayKey), "false");
  const reloaded = load(storage);
  assert.equal(reloaded.api.speed, 1.7);
  assert.equal(reloaded.api.volume, 0.35);
  assert.equal(reloaded.api.autoplayNext, false);
  assert.equal(reloaded.speedRange.value, "1.7");
  assert.equal(reloaded.volumeRange.value, "0.35");
  assert.equal(reloaded.audio.playbackRate, 1.7);
  assert.equal(reloaded.audio.volume, 0.35);
});

test("explicitly selected minimum speed and mute remain valid", () => {
  const player = load(new Map([[speedKey, "0.5"], [volumeKey, "0"]]));
  assert.equal(player.api.speed, 0.5);
  assert.equal(player.api.volume, 0);
  assert.equal(player.audio.volume, 0);
});

test("invalid preferences and disabled storage use normal defaults", () => {
  for (const [speed, volume] of [["", ""], [" ", "garbage"], ["0", "-1"], ["Infinity", "2"]]) {
    const player = load(new Map([[speedKey, speed], [volumeKey, volume]]));
    assert.equal(player.api.speed, 1);
    assert.equal(player.api.volume, 1);
  }
  const player = load(new Map(), true);
  assert.equal(player.api.speed, 1);
  assert.equal(player.api.volume, 1);
  player.speedRange.value = "2";
  player.speedRange.emit("input");
  assert.equal(player.audio.playbackRate, 2);
});
