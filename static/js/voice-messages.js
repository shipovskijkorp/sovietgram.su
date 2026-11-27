(() => {
  const conversation = document.querySelector(".conversation--chat");
  const form = document.getElementById("messageForm");
  const messageInput = document.getElementById("messageInput");
  const composerActionButton = document.getElementById("sendButton");
  const recordButton = composerActionButton;
  const recordBar = document.getElementById("voiceRecordingBar");
  const recordDelete = document.getElementById("voiceRecordDelete");
  const recordSend = document.getElementById("voiceRecordSend");
  const recordSchedule = document.getElementById("voiceRecordSchedule");
  const recordTimer = document.getElementById("voiceRecordTimer");
  const recordWaveform = document.getElementById("voiceRecordWaveform");
  const recordHint = document.getElementById("voiceRecordHint");
  const recordLock = document.getElementById("voiceRecordLock");
  const replyInput = document.getElementById("replyToInput");
  const composerReply = document.getElementById("composerReply");
  const csrfToken = form?.querySelector("[name='csrfmiddlewaretoken']")?.value || "";

  const SPEED_KEY = "sovietgram.voicePlaybackSpeed";
  const VOLUME_KEY = "sovietgram.voiceVolume";
  const AUTOPLAY_KEY = "sovietgram.voiceAutoplayNext";
  const MAX_RECORDING_MS = 100 * 60 * 1000;
  const MIN_RECORDING_MS = 200;
  const MAX_VOICE_BYTES = 25 * 1024 * 1024;
  const WAVEFORM_SAMPLES = 64;
  const CANCEL_DISTANCE = 92;
  const LOCK_DISTANCE = 78;

  let activePlayer = null;
  let progressFrame = 0;
  let recordSession = null;
  let pendingPointer = null;
  let settingsPopup = null;
  let settingsAnchor = null;

  function notify(text) {
    if (typeof window.showToast === "function") window.showToast(text);
    else if (typeof showToast === "function") showToast(text);
  }

  function readNumber(key, fallback, min, max) {
    try {
      const stored = localStorage.getItem(key);
      // Number(null) and Number("") are 0, not a missing preference.
      // A real, explicitly saved zero volume is still a valid choice.
      if (stored === null || stored.trim() === "") return fallback;
      const raw = Number(stored);
      if (Number.isFinite(raw) && raw >= min && raw <= max) return raw;
    } catch (_error) {
      // Storage is optional.
    }
    return fallback;
  }

  function readBool(key, fallback) {
    try {
      const raw = localStorage.getItem(key);
      if (raw === "true") return true;
      if (raw === "false") return false;
    } catch (_error) {
      // Storage is optional.
    }
    return fallback;
  }

  function store(key, value) {
    try {
      localStorage.setItem(key, String(value));
    } catch (_error) {
      // Storage is optional.
    }
  }

  let voiceSpeed = readNumber(SPEED_KEY, 1, 0.5, 2.5);
  let voiceVolume = readNumber(VOLUME_KEY, 1, 0, 1);
  let autoplayNext = readBool(AUTOPLAY_KEY, true);

  function formatTime(seconds, tenths = false) {
    const safe = Math.max(0, Number(seconds) || 0);
    const minutes = Math.floor(safe / 60);
    const remainder = safe - minutes * 60;
    if (tenths) {
      return `${minutes}:${Math.floor(remainder).toString().padStart(2, "0")}.${Math.floor((remainder % 1) * 10)}`;
    }
    return `${minutes}:${Math.floor(remainder).toString().padStart(2, "0")}`;
  }

  function speedLabel(speed) {
    const rounded = Math.round(speed * 10) / 10;
    return `${Number.isInteger(rounded) ? rounded.toFixed(0) : rounded.toFixed(1)}×`;
  }

  function parseWaveform(raw) {
    return String(raw || "")
      .split(",")
      .map((value) => Number(value))
      .filter((value) => Number.isFinite(value))
      .slice(0, 96)
      .map((value) => Math.max(0, Math.min(100, value)));
  }

  function fallbackWaveform() {
    return Array.from({ length: 46 }, (_, index) => {
      const wave = Math.sin(index * 1.77) * 0.32 + Math.sin(index * 0.47) * 0.18;
      return Math.round(38 + wave * 55 + (index % 5) * 4);
    }).map((value) => Math.max(12, Math.min(78, value)));
  }

  function renderWaveform(root, values) {
    const container = root.querySelector("[data-voice-waveform]");
    if (!container) return;
    const source = values.length ? values : fallbackWaveform();
    container.replaceChildren();
    source.forEach((value, index) => {
      const bar = document.createElement("i");
      bar.style.height = `${3 + Math.round((Math.max(0, value) / 100) * 14)}px`;
      bar.dataset.voiceBar = String(index);
      container.appendChild(bar);
    });
  }

  function updatePlayerProgress(root) {
    const audio = root.querySelector("[data-voice-audio]");
    const waveform = root.querySelector("[data-voice-waveform]");
    if (!audio || !waveform) return;

    const fallbackDuration = (Number(root.dataset.durationMs) || 0) / 1000;
    const duration = Number.isFinite(audio.duration) && audio.duration > 0
      ? audio.duration
      : fallbackDuration;
    const current = Math.max(0, Number(audio.currentTime) || 0);
    const progress = duration > 0 ? Math.max(0, Math.min(1, current / duration)) : 0;

    const currentNode = root.querySelector("[data-voice-current]");
    const durationNode = root.querySelector("[data-voice-duration]");
    if (currentNode) currentNode.textContent = formatTime(current);
    if (durationNode) durationNode.textContent = formatTime(duration);

    const bars = [...waveform.querySelectorAll("[data-voice-bar]")];
    const activeCount = Math.round(progress * bars.length);
    bars.forEach((bar, index) => bar.classList.toggle("is-active", index < activeCount));
    waveform.setAttribute("aria-valuenow", String(Math.round(progress * 100)));
  }

  function stopProgressLoop() {
    if (progressFrame) cancelAnimationFrame(progressFrame);
    progressFrame = 0;
  }

  function startProgressLoop(root) {
    stopProgressLoop();
    const tick = () => {
      const audio = root.querySelector("[data-voice-audio]");
      if (!audio || audio.paused || audio.ended) {
        progressFrame = 0;
        updatePlayerProgress(root);
        return;
      }
      updatePlayerProgress(root);
      progressFrame = requestAnimationFrame(tick);
    };
    progressFrame = requestAnimationFrame(tick);
  }

  function setPlayState(root, playing) {
    root.classList.toggle("is-playing", playing);
    const button = root.querySelector("[data-voice-play]");
    if (button) {
      button.setAttribute(
        "aria-label",
        playing ? "Приостановить голосовое сообщение" : "Воспроизвести голосовое сообщение",
      );
    }
  }

  function applyPlaybackSettings(root) {
    const audio = root.querySelector("[data-voice-audio]");
    if (!audio) return;
    audio.playbackRate = voiceSpeed;
    audio.defaultPlaybackRate = voiceSpeed;
    audio.volume = voiceVolume;
    if ("preservesPitch" in audio) audio.preservesPitch = true;
    if ("webkitPreservesPitch" in audio) audio.webkitPreservesPitch = true;
    const speed = root.querySelector("[data-voice-settings]");
    if (speed) speed.textContent = speedLabel(voiceSpeed);
  }

  function applyAllPlaybackSettings() {
    document.querySelectorAll("[data-voice-player]").forEach(applyPlaybackSettings);
  }

  async function markListened(root) {
    if (
      root.dataset.listened === "true"
      || root.dataset.own === "true"
      || !root.dataset.markPlayedUrl
    ) return;

    root.dataset.listened = "true";
    const unread = root.querySelector("[data-voice-unread]");
    if (unread) unread.hidden = true;

    const data = new FormData();
    data.append("csrfmiddlewaretoken", csrfToken);
    try {
      const response = await fetch(root.dataset.markPlayedUrl, {
        method: "POST",
        credentials: "same-origin",
        headers: { "X-Requested-With": "XMLHttpRequest" },
        body: data,
      });
      if (!response.ok) throw new Error("mark failed");
    } catch (_error) {
      // Playback must never fail only because the read marker could not sync.
      root.dataset.listened = "false";
    }
  }

  function nextVoiceRoot(root) {
    const all = [...document.querySelectorAll("[data-voice-player]")];
    const index = all.indexOf(root);
    return index >= 0 ? all[index + 1] || null : null;
  }

  async function playRoot(root) {
    const audio = root.querySelector("[data-voice-audio]");
    if (!audio) return;

    if (activePlayer && activePlayer !== root) {
      const previous = activePlayer.querySelector("[data-voice-audio]");
      previous?.pause();
    }

    applyPlaybackSettings(root);
    document.querySelectorAll("audio, video").forEach((media) => {
      if (media !== audio && !media.paused) media.pause();
    });
    try {
      await audio.play();
    } catch (_error) {
      notify("Не удалось воспроизвести голосовое сообщение.");
    }
  }

  function seekRoot(root, ratio) {
    const audio = root.querySelector("[data-voice-audio]");
    if (!audio) return;
    const fallbackDuration = (Number(root.dataset.durationMs) || 0) / 1000;
    const duration = Number.isFinite(audio.duration) && audio.duration > 0
      ? audio.duration
      : fallbackDuration;
    if (!duration) return;
    audio.currentTime = Math.max(0, Math.min(duration, duration * ratio));
    updatePlayerProgress(root);
  }

  function hydratePlayer(root) {
    if (!root || root.dataset.voiceReady === "true") return;
    root.dataset.voiceReady = "true";

    const audio = root.querySelector("[data-voice-audio]");
    const play = root.querySelector("[data-voice-play]");
    const waveform = root.querySelector("[data-voice-waveform]");
    const speed = root.querySelector("[data-voice-settings]");
    if (!audio || !play || !waveform) return;

    if (!audio.src && root.dataset.src) audio.src = root.dataset.src;
    renderWaveform(root, parseWaveform(root.dataset.waveform));
    applyPlaybackSettings(root);
    updatePlayerProgress(root);

    audio.addEventListener("loadedmetadata", () => updatePlayerProgress(root));
    audio.addEventListener("durationchange", () => updatePlayerProgress(root));
    audio.addEventListener("timeupdate", () => updatePlayerProgress(root));
    audio.addEventListener("play", () => {
      activePlayer = root;
      setPlayState(root, true);
      markListened(root);
      startProgressLoop(root);
      if ("mediaSession" in navigator) {
        try {
          navigator.mediaSession.metadata = new MediaMetadata({
            title: "Голосовое сообщение",
            artist: "Sovietgram",
          });
          navigator.mediaSession.setActionHandler("play", () => playRoot(root));
          navigator.mediaSession.setActionHandler("pause", () => audio.pause());
          navigator.mediaSession.setActionHandler("seekbackward", (details) => {
            audio.currentTime = Math.max(0, audio.currentTime - (details.seekOffset || 10));
          });
          navigator.mediaSession.setActionHandler("seekforward", (details) => {
            const duration = Number.isFinite(audio.duration) ? audio.duration : audio.currentTime + 10;
            audio.currentTime = Math.min(duration, audio.currentTime + (details.seekOffset || 10));
          });
          navigator.mediaSession.setActionHandler("seekto", (details) => {
            if (Number.isFinite(details.seekTime)) audio.currentTime = details.seekTime;
          });
        } catch (_error) {
          // Optional browser integration.
        }
      }
    });
    audio.addEventListener("pause", () => {
      setPlayState(root, false);
      updatePlayerProgress(root);
      if (activePlayer === root && !audio.ended) stopProgressLoop();
    });
    audio.addEventListener("ended", () => {
      setPlayState(root, false);
      updatePlayerProgress(root);
      if (activePlayer === root) {
        activePlayer = null;
        stopProgressLoop();
      }
      if (autoplayNext) {
        const next = nextVoiceRoot(root);
        if (next) playRoot(next);
      }
    });
    audio.addEventListener("error", () => {
      setPlayState(root, false);
      notify("Голосовое сообщение недоступно для воспроизведения.");
    });

    play.addEventListener("click", () => {
      if (audio.paused || audio.ended) playRoot(root);
      else audio.pause();
    });

    waveform.addEventListener("click", (event) => {
      const rect = waveform.getBoundingClientRect();
      if (!rect.width) return;
      seekRoot(root, (event.clientX - rect.left) / rect.width);
    });
    waveform.addEventListener("keydown", (event) => {
      const fallbackDuration = (Number(root.dataset.durationMs) || 0) / 1000;
      const duration = Number.isFinite(audio.duration) && audio.duration > 0
        ? audio.duration
        : fallbackDuration;
      if (!duration) return;
      if (event.key === "ArrowLeft" || event.key === "ArrowRight") {
        event.preventDefault();
        const delta = event.key === "ArrowRight" ? 5 : -5;
        audio.currentTime = Math.max(0, Math.min(duration, audio.currentTime + delta));
        updatePlayerProgress(root);
      } else if (event.key === "Home") {
        event.preventDefault();
        audio.currentTime = 0;
        updatePlayerProgress(root);
      } else if (event.key === "End") {
        event.preventDefault();
        audio.currentTime = Math.max(0, duration - 0.01);
        updatePlayerProgress(root);
      }
    });

    speed?.addEventListener("click", (event) => {
      event.stopPropagation();
      openSettings(speed);
    });
  }

  function hydrateTree(node = document) {
    if (node instanceof Element && node.matches("[data-voice-player]")) hydratePlayer(node);
    node.querySelectorAll?.("[data-voice-player]").forEach(hydratePlayer);
  }

  function buildVoicePlayerFallback(attachment, isOwn) {
    const root = document.createElement("div");
    root.className = "voice-message";
    root.dataset.voicePlayer = "";
    root.dataset.src = attachment.url || "";
    root.dataset.markPlayedUrl = attachment.mark_played_url || "";
    root.dataset.durationMs = String(Number(attachment.duration_ms) || 0);
    root.dataset.waveform = Array.isArray(attachment.waveform)
      ? attachment.waveform.join(",")
      : "";
    root.dataset.own = isOwn ? "true" : "false";
    root.dataset.listened = attachment.listened ? "true" : "false";

    const play = document.createElement("button");
    play.type = "button";
    play.className = "voice-message__play";
    play.dataset.voicePlay = "";
    play.setAttribute("aria-label", "Воспроизвести голосовое сообщение");
    const glyph = document.createElement("span");
    glyph.className = "voice-message__play-glyph";
    glyph.setAttribute("aria-hidden", "true");
    play.appendChild(glyph);

    const body = document.createElement("div");
    body.className = "voice-message__body";
    const waveform = document.createElement("div");
    waveform.className = "voice-message__waveform";
    waveform.dataset.voiceWaveform = "";
    waveform.tabIndex = 0;
    waveform.setAttribute("role", "slider");
    waveform.setAttribute("aria-label", "Позиция воспроизведения");
    waveform.setAttribute("aria-valuemin", "0");
    waveform.setAttribute("aria-valuemax", "100");
    waveform.setAttribute("aria-valuenow", "0");

    const meta = document.createElement("div");
    meta.className = "voice-message__time";
    const current = document.createElement("span");
    current.dataset.voiceCurrent = "";
    current.textContent = "0:00";
    const duration = document.createElement("span");
    duration.className = "voice-message__duration";
    duration.dataset.voiceDuration = "";
    duration.textContent = "0:00";
    const unread = document.createElement("span");
    unread.className = "voice-message__unread";
    unread.dataset.voiceUnread = "";
    unread.setAttribute("aria-label", "Не прослушано");
    unread.hidden = Boolean(attachment.listened || isOwn);
    meta.append(current, duration, unread);
    body.append(waveform, meta);

    const speed = document.createElement("button");
    speed.type = "button";
    speed.className = "voice-message__speed";
    speed.dataset.voiceSettings = "";
    speed.setAttribute("aria-label", "Настройки воспроизведения");
    speed.textContent = speedLabel(voiceSpeed);

    const audio = document.createElement("audio");
    audio.dataset.voiceAudio = "";
    audio.preload = document.body.dataset.mediaPreload === "false" ? "none" : "metadata";
    audio.src = attachment.url || "";

    root.append(play, body, speed, audio);
    return root;
  }

  function insertVoiceMessageFallback(message) {
    const flow = document.getElementById("messageFlow");
    if (!flow || !message?.id) return false;

    const selector = `[data-message-id="${message.id}"]`;
    const existing = document.querySelector(selector);
    if (existing) {
      hydrateTree(existing);
      return true;
    }

    const attachment = (message.attachments || []).find((item) => item.kind === "voice");
    if (!attachment) return false;

    const article = document.createElement("article");
    article.id = `message-${message.id}`;
    article.className = `message ${message.is_own ? "message--outgoing" : "message--incoming"}`;
    article.dataset.messageId = String(message.id);
    article.dataset.messageOwn = String(Boolean(message.is_own));
    article.dataset.messageText = message.text || "";
    article.dataset.messageKind = message.special?.type || "";
    article.dataset.messageSender = message.sender_name || "";
    article.dataset.messagePinned = String(Boolean(message.is_pinned));
    article.dataset.editUrl = message.urls?.edit || "";
    article.dataset.deleteUrl = message.urls?.delete || "";
    article.dataset.forwardUrl = message.urls?.forward || "";
    article.dataset.pinUrl = message.urls?.pin || "";
    article.dataset.reactionUrl = message.urls?.reaction || "";

    const media = document.createElement("div");
    media.className = "message-media";
    media.dataset.count = "1";
    media.appendChild(buildVoicePlayerFallback(attachment, Boolean(message.is_own)));
    article.appendChild(media);

    const footer = document.createElement("footer");
    const time = document.createElement("time");
    time.textContent = message.time || "";
    footer.appendChild(time);
    if (message.is_own) {
      footer.appendChild(window.SovietgramReadReceipt.create(message.is_read));
    }
    article.appendChild(footer);
    window.SovietgramSocial?.renderReactions(article, message);

    const actions = document.createElement("button");
    actions.className = "message-action-trigger";
    actions.type = "button";
    actions.setAttribute("aria-label", "Действия с сообщением");
    actions.textContent = "⋮";
    article.appendChild(actions);

    flow.appendChild(article);
    hydrateTree(article);
    requestAnimationFrame(() => {
      const stage = document.getElementById("messageStage");
      if (stage) stage.scrollTop = stage.scrollHeight;
    });
    return true;
  }

  function publishSentVoice(message) {
    if (!message) return false;

    try {
      document.dispatchEvent(new CustomEvent("sovietgram:message-sent", {
        detail: { message },
      }));
    } catch (_error) {
      // A direct fallback below still renders the message.
    }

    let article = document.querySelector(`[data-message-id="${message.id}"]`);
    if (!article && typeof window.renderSovietgramChatMessage === "function") {
      try {
        window.renderSovietgramChatMessage(message);
      } catch (_error) {
        // The dedicated fallback does not depend on chat.js completing.
      }
      article = document.querySelector(`[data-message-id="${message.id}"]`);
    }

    // In a historical window chat.js asynchronously loads the latest page.
    // Never append a distant new voice message across that gap.
    if (!article && window.SovietgramChat) return true;
    if (!article) return insertVoiceMessageFallback(message);
    hydrateTree(article);
    return true;
  }

  const observer = new MutationObserver((records) => {
    records.forEach((record) => {
      record.addedNodes.forEach((node) => {
        if (node.nodeType === Node.ELEMENT_NODE) hydrateTree(node);
      });
    });
  });
  observer.observe(document.body, { childList: true, subtree: true });
  hydrateTree();

  // Telegram has one active audio stream. Starting music/video pauses voice,
  // and starting another voice already pauses the previous one in playRoot().
  document.addEventListener("play", (event) => {
    const media = event.target;
    if (!(media instanceof HTMLMediaElement) || media.matches("[data-voice-audio]")) return;
    const activeAudio = activePlayer?.querySelector("[data-voice-audio]");
    if (activeAudio && !activeAudio.paused) activeAudio.pause();
  }, true);

  function createSettingsPopup() {
    const popup = document.createElement("section");
    popup.className = "voice-player-settings";
    popup.hidden = true;

    const heading = document.createElement("div");
    heading.className = "voice-player-settings__heading";
    const title = document.createElement("strong");
    title.textContent = "Скорость";
    const value = document.createElement("b");
    value.dataset.voiceSpeedValue = "";
    heading.append(title, value);

    const speedRange = document.createElement("input");
    speedRange.type = "range";
    speedRange.min = "0.5";
    speedRange.max = "2.5";
    speedRange.step = "0.1";
    speedRange.className = "voice-player-settings__range";
    speedRange.dataset.voiceSpeedRange = "";

    const presets = document.createElement("div");
    presets.className = "voice-player-settings__presets";
    [0.5, 1, 1.2, 1.5, 1.7, 2].forEach((point) => {
      const button = document.createElement("button");
      button.type = "button";
      button.dataset.voiceSpeedPreset = String(point);
      button.textContent = speedLabel(point);
      presets.appendChild(button);
    });

    const volumeLabel = document.createElement("label");
    volumeLabel.className = "voice-player-settings__setting";
    const volumeCopy = document.createElement("span");
    volumeCopy.textContent = "Громкость";
    const volumeRange = document.createElement("input");
    volumeRange.type = "range";
    volumeRange.min = "0";
    volumeRange.max = "1";
    volumeRange.step = "0.05";
    volumeRange.dataset.voiceVolumeRange = "";
    volumeLabel.append(volumeCopy, volumeRange);

    const autoplayLabel = document.createElement("label");
    autoplayLabel.className = "voice-player-settings__toggle";
    const autoplayCopy = document.createElement("span");
    autoplayCopy.innerHTML = "<strong>Следующее голосовое</strong><small>Автоматически продолжать воспроизведение</small>";
    const autoplayInput = document.createElement("input");
    autoplayInput.type = "checkbox";
    autoplayInput.dataset.voiceAutoplay = "";
    const switchTrack = document.createElement("i");
    autoplayLabel.append(autoplayCopy, autoplayInput, switchTrack);

    popup.append(heading, speedRange, presets, volumeLabel, autoplayLabel);
    document.body.appendChild(popup);

    function updateControls() {
      value.textContent = speedLabel(voiceSpeed);
      speedRange.value = String(voiceSpeed);
      volumeRange.value = String(voiceVolume);
      volumeRange.setAttribute("aria-valuetext", Math.round(voiceVolume * 100) + "%");
      speedRange.setAttribute("aria-label", "Скорость воспроизведения");
      speedRange.setAttribute("aria-valuetext", speedLabel(voiceSpeed));
      autoplayInput.checked = autoplayNext;
      presets.querySelectorAll("[data-voice-speed-preset]").forEach((button) => {
        button.classList.toggle(
          "is-active",
          Math.abs(Number(button.dataset.voiceSpeedPreset) - voiceSpeed) < 0.01,
        );
      });
    }

    function setSpeed(next) {
      voiceSpeed = Math.max(0.5, Math.min(2.5, Math.round(Number(next) * 10) / 10));
      store(SPEED_KEY, voiceSpeed);
      applyAllPlaybackSettings();
      updateControls();
    }

    speedRange.addEventListener("input", () => setSpeed(speedRange.value));
    presets.addEventListener("click", (event) => {
      const button = event.target.closest("[data-voice-speed-preset]");
      if (button) setSpeed(button.dataset.voiceSpeedPreset);
    });
    volumeRange.addEventListener("input", () => {
      voiceVolume = Math.max(0, Math.min(1, Number(volumeRange.value)));
      store(VOLUME_KEY, voiceVolume);
      applyAllPlaybackSettings();
      updateControls();
    });
    autoplayInput.addEventListener("change", () => {
      autoplayNext = autoplayInput.checked;
      store(AUTOPLAY_KEY, autoplayNext);
    });

    popup.updateControls = updateControls;
    return popup;
  }

  function closeSettings() {
    if (!settingsPopup) return;
    settingsPopup.hidden = true;
    settingsAnchor = null;
  }

  function openSettings(anchor) {
    if (!settingsPopup) settingsPopup = createSettingsPopup();
    if (!settingsPopup.hidden && settingsAnchor === anchor) {
      closeSettings();
      return;
    }

    settingsAnchor = anchor;
    settingsPopup.updateControls?.();
    settingsPopup.hidden = false;
    const rect = anchor.getBoundingClientRect();
    const box = settingsPopup.getBoundingClientRect();
    let left = rect.right - box.width;
    let top = rect.top - box.height - 8;
    left = Math.max(8, Math.min(left, window.innerWidth - box.width - 8));
    if (top < 8) top = Math.min(window.innerHeight - box.height - 8, rect.bottom + 8);
    settingsPopup.style.left = `${left}px`;
    settingsPopup.style.top = `${Math.max(8, top)}px`;
  }

  document.addEventListener("click", (event) => {
    if (
      settingsPopup
      && !settingsPopup.hidden
      && !settingsPopup.contains(event.target)
      && !event.target.closest?.("[data-voice-settings]")
    ) closeSettings();
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && settingsPopup && !settingsPopup.hidden) closeSettings();
  });

  const modeKey = "sovietgram.recordMode.v1." + (document.body?.dataset.accountId || "default");
  let preferredMode = "voice", gesture = null;
  try { if (localStorage.getItem(modeKey) === "video_note") preferredMode = "video_note"; } catch (_) {}

  function isVoiceMode() {
    return composerActionButton?.dataset.composerAction === "voice";
  }
  function canVoice() {
    return composerActionButton?.dataset.canRecordVoice === "true" && conversation?.dataset.canRecordVoice !== "false";
  }
  function canVideo() {
    return composerActionButton?.dataset.canRecordVideoNote === "true";
  }
  function syncComposerActions() {
    if (!form || !composerActionButton || recordSession || gesture || window.SovietgramVideoNotes?.isOpen()) return;
    const hasText = Boolean(messageInput?.value.trim());
    let mode = "send";
    if (!hasText) {
      if (preferredMode === "video_note" && canVideo()) mode = "video_note";
      else if (canVoice()) mode = "voice";
      else if (canVideo()) mode = "video_note";
    }
    const recording = mode !== "send";
    composerActionButton.dataset.composerAction = mode;
    // Keep the shared idle recorder styling (including responsive palettes).
    composerActionButton.classList.toggle("is-voice-mode", recording);
    composerActionButton.classList.toggle("is-video-note-mode", mode === "video_note");
    composerActionButton.type = recording ? "button" : "submit";
    composerActionButton.setAttribute("aria-label", mode === "voice" ? "Записать голосовое сообщение" :
      mode === "video_note" ? "Записать видеокружок" : "Отправить");
    composerActionButton.title = recording ? (canVoice() && canVideo() ?
      "Нажмите для смены режима, удерживайте для записи" : "Удерживайте для записи") : "Отправить";
  }
  function tapRecorder() {
    if (recordSession || pendingVoiceData || window.SovietgramVideoNotes?.isOpen()) return;
    if (canVoice() && canVideo()) {
      preferredMode = isVoiceMode() ? "video_note" : "voice";
      try { localStorage.setItem(modeKey, preferredMode); } catch (_) {}
      syncComposerActions();
      notify(preferredMode === "video_note" ? "Видеокружок · удерживайте для записи" : "Голосовое · удерживайте для записи");
    } else if (canVideo()) window.SovietgramVideoNotes?.openPreview();
    else notify("Удерживайте кнопку для записи голосового сообщения.");
  }

  messageInput?.addEventListener("input", syncComposerActions);
  syncComposerActions();

  function selectRecorderMime() {
    if (!window.MediaRecorder) return "";
    const candidates = [
      "audio/webm;codecs=opus",
      "audio/ogg;codecs=opus",
      "audio/webm",
      "audio/ogg",
      "audio/mp4",
    ];
    return candidates.find((type) => (
      !MediaRecorder.isTypeSupported || MediaRecorder.isTypeSupported(type)
    )) || "";
  }

  function recordingExtension(mime) {
    const base = String(mime || "").split(";", 1)[0].toLowerCase();
    if (base.includes("ogg") || base.includes("opus")) return "ogg";
    if (base.includes("mp4")) return "m4a";
    return "webm";
  }

  function stopTracks(session) {
    session.stream?.getTracks?.().forEach((track) => track.stop());
    if (session.audioContext && session.audioContext.state !== "closed") {
      session.audioContext.close().catch(() => {});
    }
  }

  function resampleWaveform(samples, target = WAVEFORM_SAMPLES) {
    if (!samples.length) return Array.from({ length: target }, () => 18);
    const result = [];
    for (let index = 0; index < target; index += 1) {
      const start = Math.floor((index / target) * samples.length);
      const end = Math.max(start + 1, Math.floor(((index + 1) / target) * samples.length));
      let peak = 0;
      for (let cursor = start; cursor < Math.min(samples.length, end); cursor += 1) {
        peak = Math.max(peak, samples[cursor] || 0);
      }
      result.push(Math.max(4, Math.min(100, Math.round(peak * 100))));
    }
    return result;
  }

  function drawRecordingWaveform(session) {
    if (!recordWaveform || recordSession !== session) return;
    const context = recordWaveform.getContext("2d");
    if (!context) return;

    const rect = recordWaveform.getBoundingClientRect();
    const ratio = window.devicePixelRatio || 1;
    const width = Math.max(1, Math.round(rect.width * ratio));
    const height = Math.max(1, Math.round(rect.height * ratio));
    if (recordWaveform.width !== width || recordWaveform.height !== height) {
      recordWaveform.width = width;
      recordWaveform.height = height;
    }

    let level = 0.08;
    if (session.analyser && session.audioData) {
      session.analyser.getByteTimeDomainData(session.audioData);
      let sum = 0;
      for (const value of session.audioData) {
        const normalized = (value - 128) / 128;
        sum += normalized * normalized;
      }
      level = Math.min(1, Math.sqrt(sum / session.audioData.length) * 3.7);
    }

    const now = performance.now();
    if (now - session.lastWaveSampleAt >= 70) {
      session.samples.push(level);
      session.lastWaveSampleAt = now;
    }

    context.clearRect(0, 0, width, height);
    const bars = 46;
    const visible = session.samples.slice(-bars);
    const gap = 2 * ratio;
    const barWidth = Math.max(1 * ratio, (width - gap * (bars - 1)) / bars);
    context.fillStyle = getComputedStyle(recordWaveform).color || "#cc0000";
    for (let index = 0; index < bars; index += 1) {
      const sample = visible[index - (bars - visible.length)] || 0.08;
      const barHeight = Math.max(3 * ratio, Math.min(height, sample * height));
      const x = index * (barWidth + gap);
      const y = (height - barHeight) / 2;
      context.fillRect(x, y, barWidth, barHeight);
    }

    session.animationFrame = requestAnimationFrame(() => drawRecordingWaveform(session));
  }

  function setRecordingUi(session) {
    if (!form || !recordBar) return;
    form.classList.add("is-voice-recording");
    recordBar.hidden = false;
    recordBar.classList.toggle("is-locked", Boolean(session?.locked));
    recordBar.classList.toggle("is-sending", Boolean(session?.sending));
    if (recordHint) {
      recordHint.textContent = session?.sending
        ? "Отправка…"
        : session?.locked
          ? "Запись зафиксирована"
          : "Сдвиньте влево для отмены";
    }
    if (recordLock) recordLock.hidden = Boolean(session?.locked || session?.sending);
    if (recordSchedule) recordSchedule.hidden = !session?.locked || Boolean(session?.sending);
  }

  function clearRecordingUi() {
    form?.classList.remove("is-voice-recording");
    if (recordBar) {
      recordBar.hidden = true;
      recordBar.classList.remove("is-locked", "is-sending", "is-cancelling");
      recordBar.style.setProperty("--voice-cancel-progress", "0");
      recordBar.style.setProperty("--voice-lock-progress", "0");
    }
    if (recordTimer) recordTimer.textContent = "0:00.0";
    if (recordLock) recordLock.hidden = false;
    if (recordSchedule) recordSchedule.hidden = true;
    syncComposerActions();
  }

  const voiceRetryRow = document.getElementById("voiceRetryRow");
  const voiceRetrySend = document.getElementById("voiceRetrySend");
  const voiceRetryDiscard = document.getElementById("voiceRetryDiscard");
  let pendingVoiceData = null;
  let voiceRetryBusy = false, voiceAttempted = false;
  const voiceRetrySchedule = document.getElementById("voiceRetrySchedule");
  const voiceRetryStatus = document.getElementById("voiceRetryStatus");
  const scheduleStage = document.getElementById("messageStage");

  function prepareVoice(blob, mime, durationMs, waveform) {
    if (!form) throw new Error("Форма отправки недоступна.");
    if (blob.size > MAX_VOICE_BYTES) {
      throw new Error("Запись получилась больше 25 МБ. Отправьте её более короткими частями.");
    }

    const data = new FormData();
    data.append("csrfmiddlewaretoken", csrfToken);
    data.append("text", "");
    data.append("attachment_mode", "voice");
    data.append("account_id", scheduleStage?.dataset.accountId || "");
    data.append("client_message_id", window.SovietgramSendRetry.uuid());
    data.append("voice_duration_ms", String(Math.max(MIN_RECORDING_MS, Math.round(durationMs))));
    data.append("voice_waveform", JSON.stringify(waveform));
    const replyTo = replyInput?.value || "";
    if (replyTo) data.append("reply_to", replyTo);
    const quote = replyTo ? window.SovietgramChat?.currentQuote?.() || "" : "";
    if (quote) data.append("reply_quote", quote);
    data.append(
      "attachments",
      blob,
      `voice-${Date.now()}.${recordingExtension(mime)}`,
    );

    return data;
  }

  async function uploadVoice(data) {
    const endpoint = data.has("scheduled_for") ? scheduleStage.dataset.scheduledUrl : form.action;
    const response = await window.SovietgramSendRetry.fetchSend(endpoint, {
      method: "POST",
      credentials: "same-origin",
      headers: { "X-Requested-With": "XMLHttpRequest" },
      body: data,
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok || !payload.ok) {
      const first = Object.values(payload.errors || {}).flat()?.[0]?.message;
      throw new Error(payload.error || first || "Не удалось отправить голосовое сообщение.");
    }
    if(data.has("scheduled_for") && (!payload.item || payload.item.status === "canceled"))
      throw Error("Эта отложенная отправка уже отменена.");
    return payload;
  }

  function updateVoiceRetryUi() {
    if (voiceRetryRow) voiceRetryRow.hidden = !pendingVoiceData;
    if (voiceRetrySend) {
      voiceRetrySend.disabled = voiceRetryBusy;
      voiceRetrySend.textContent=voiceAttempted?"Повторить": "Отправить";
    }
    if(voiceRetrySchedule){voiceRetrySchedule.hidden=voiceAttempted||!pendingVoiceData||!scheduleStage?.dataset.scheduledUrl;voiceRetrySchedule.disabled=voiceRetryBusy;}
    if(voiceRetryStatus)voiceRetryStatus.textContent=voiceAttempted?"Отправка голосового не подтверждена сервером.":"Запись готова к отправке." ;
    if (voiceRetryDiscard) voiceRetryDiscard.disabled = voiceRetryBusy;
  }

  async function sendPendingVoice() {
    if (!pendingVoiceData || voiceRetryBusy) return;
    const data = pendingVoiceData;
    voiceRetryBusy = true;voiceAttempted=true;
    updateVoiceRetryUi();
    try {
      const result = await uploadVoice(data);
      pendingVoiceData = null;
      if (replyInput && replyInput.value === (data.get("reply_to") || "") &&
          (window.SovietgramChat?.currentQuote?.() || "") === (data.get("reply_quote") || "")) {
        window.SovietgramChat?.clearReplyState?.();
      }
      if(data.has("scheduled_for")){
        notify("Голосовое сообщение запланировано.");
        if(result.item.status==="sent")void window.SovietgramChat?.syncNow?.();
      }else{
        const inserted = publishSentVoice(result.message);
        if (!inserted) window.setTimeout(() => window.SovietgramChat?.syncNow?.(), 50);
      }
    } catch (error) {
      notify(error.message || "Не удалось отправить голосовое сообщение. Запись сохранена для повтора.");
    } finally {
      voiceRetryBusy = false;
      updateVoiceRetryUi();
    }
  }

  async function schedulePendingVoice(){
    if(!pendingVoiceData||voiceRetryBusy||voiceAttempted)return;
    const data=pendingVoiceData;
    voiceRetryBusy=true;updateVoiceRetryUi();
    let when=null;
    try{when=await window.SovietgramSchedule?.pickRecordingTime?.();}
    finally{voiceRetryBusy=false;updateVoiceRetryUi();}
    if(!when||pendingVoiceData!==data)return;
    data.set("scheduled_for",when);
    await sendPendingVoice();
  }
  voiceRetrySchedule?.addEventListener("click",()=>void schedulePendingVoice());
  voiceRetrySend?.addEventListener("click", sendPendingVoice);
  voiceRetryDiscard?.addEventListener("click", () => {
    if (voiceRetryBusy) return;
    pendingVoiceData = null;
    updateVoiceRetryUi();
  });

  async function finalizeRecording(session) {
    window.clearInterval(session.timerInterval);
    if (session.animationFrame) cancelAnimationFrame(session.animationFrame);
    stopTracks(session);

    const durationMs = Math.max(0, performance.now() - session.startedAt);
    const action = session.stopAction || "cancel";
    const mime = session.recorder.mimeType || session.mime || session.chunks[0]?.type || "audio/webm";
    const blob = new Blob(session.chunks, { type: mime });
    const waveform = resampleWaveform(session.samples);

    if (recordSession === session) recordSession = null;

    if (action !== "send" && action !== "schedule") {
      clearRecordingUi();
      window.SovietgramChat?.focusComposer?.();
      return;
    }

    if (durationMs < MIN_RECORDING_MS || blob.size === 0) {
      clearRecordingUi();
      notify("Голосовое сообщение слишком короткое.");
      window.SovietgramChat?.focusComposer?.();
      return;
    }

    session.sending = true;
    recordSession = session;
    setRecordingUi(session);
    try {
      pendingVoiceData = prepareVoice(blob, mime, durationMs, waveform);
      voiceAttempted=false;updateVoiceRetryUi();
      if(action==="schedule")await schedulePendingVoice();else await sendPendingVoice();
    } catch (error) {
      notify(error.message || "Не удалось отправить голосовое сообщение.");
    } finally {
      if (recordSession === session) recordSession = null;
      clearRecordingUi();
      window.SovietgramChat?.focusComposer?.();
    }
  }

  function requestStop(session, action) {
    if (!session || session.stopping) return;
    session.stopping = true;
    session.stopAction = action;
    if (session.recorder.state === "inactive") {
      finalizeRecording(session);
      return;
    }
    try {
      session.recorder.stop();
    } catch (_error) {
      finalizeRecording(session);
    }
  }

  function updateRecordingTimer(session) {
    if (recordSession !== session) return;
    const elapsed = Math.max(0, performance.now() - session.startedAt);
    if (recordTimer) recordTimer.textContent = formatTime(elapsed / 1000, true);
    if (elapsed >= MAX_RECORDING_MS) requestStop(session, "send");
  }

  async function startRecording(pointerEvent) {
    if (window.SovietgramVideoNotes?.isOpen()) return;
    if (
      !form
      || !recordButton
      || !isVoiceMode()
      || recordSession
      || pendingVoiceData
      || messageInput?.value.trim()
    ) return;
    if (!navigator.mediaDevices?.getUserMedia || !window.MediaRecorder) {
      notify("Этот браузер не поддерживает запись голосовых сообщений.");
      return;
    }

    const token = Symbol("voice-record");
    pendingPointer = {
      token,
      pointerId: pointerEvent.pointerId,
      startX: pointerEvent.clientX,
      startY: pointerEvent.clientY,
      released: false,
      locked: false,
    };

    recordButton.classList.add("is-arming");
    let stream = null;
    try {
      stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
          channelCount: 1,
        },
      });

      if (!pendingPointer || pendingPointer.token !== token || pendingPointer.released || window.SovietgramVideoNotes?.isOpen()) {
        stream.getTracks().forEach((track) => track.stop());
        return;
      }

      const mime = selectRecorderMime();
      let recorder;
      try {
        recorder = mime
          ? new MediaRecorder(stream, { mimeType: mime, audioBitsPerSecond: 32000 })
          : new MediaRecorder(stream, { audioBitsPerSecond: 32000 });
      } catch (_error) {
        recorder = mime ? new MediaRecorder(stream, { mimeType: mime }) : new MediaRecorder(stream);
      }

      const session = {
        stream,
        recorder,
        mime,
        chunks: [],
        samples: [],
        startedAt: performance.now(),
        lastWaveSampleAt: 0,
        pointerId: pendingPointer.pointerId,
        startX: pendingPointer.startX,
        startY: pendingPointer.startY,
        locked: pendingPointer.locked,
        stopping: false,
        sending: false,
        stopAction: "",
        timerInterval: 0,
        animationFrame: 0,
        analyser: null,
        audioData: null,
        audioContext: null,
      };

      try {
        const AudioContext = window.AudioContext || window.webkitAudioContext;
        if (AudioContext) {
          session.audioContext = new AudioContext();
          const source = session.audioContext.createMediaStreamSource(stream);
          session.analyser = session.audioContext.createAnalyser();
          session.analyser.fftSize = 512;
          session.analyser.smoothingTimeConstant = 0.68;
          session.audioData = new Uint8Array(session.analyser.fftSize);
          source.connect(session.analyser);
        }
      } catch (_error) {
        // Recording still works without live level visualization.
      }

      recorder.addEventListener("dataavailable", (event) => {
        if (event.data?.size) session.chunks.push(event.data);
      });
      recorder.addEventListener("stop", () => finalizeRecording(session), { once: true });
      recorder.addEventListener("error", () => {
        if (recordSession === session) {
          notify("Ошибка записи микрофона.");
          requestStop(session, "cancel");
        }
      });

      recordSession = session;
      pendingPointer = null;
      recorder.start(250);
      session.timerInterval = window.setInterval(() => updateRecordingTimer(session), 100);
      setRecordingUi(session);
      drawRecordingWaveform(session);
    } catch (error) {
      stream?.getTracks().forEach(track => track.stop());
      if (recordSession?.stream === stream) { stopTracks(recordSession); recordSession = null; clearRecordingUi(); }
      const name = error?.name || "";
      if (name === "NotAllowedError" || name === "SecurityError") {
        notify("Разрешите Sovietgram доступ к микрофону в настройках браузера.");
      } else if (name === "NotFoundError") {
        notify("Микрофон не найден.");
      } else {
        notify("Не удалось начать запись голосового сообщения.");
      }
    } finally {
      recordButton.classList.remove("is-arming");
      if (pendingPointer?.token === token) pendingPointer = null;
    }
  }

  // One gesture controller owns the composer microphone/camera button.
  // A short tap changes mode; no media permission is requested until hold.
  recordButton?.addEventListener("pointerdown", event => {
    const mode = recordButton.dataset.composerAction;
    if (mode === "send" || gesture || recordSession || pendingPointer || pendingVoiceData ||
        window.SovietgramVideoNotes?.isOpen() || !event.isPrimary ||
        (event.pointerType === "mouse" && event.button !== 0)) return;
    event.preventDefault();
    const g = {mode, pointerId:event.pointerId, clientX:event.clientX, clientY:event.clientY,
      started:false, locked:false, canceled:false, timer:0};
    gesture = g;
    try { recordButton.setPointerCapture(event.pointerId); } catch (_) {}
    g.timer = window.setTimeout(() => {
      if (gesture !== g || g.canceled) return;
      g.started = true;
      if (g.mode === "video_note") {
        if (!window.SovietgramVideoNotes?.startHold()) g.canceled = true;
      } else void startRecording(g);
    }, 240);
  });

  recordButton?.addEventListener("click", event => {
    if (recordButton.dataset.composerAction === "send" && !gesture) return;
    event.preventDefault();
    // Keyboard or assistive activation can select a mode without a pointer.
    // The attachment menu remains a keyboard-friendly video preview path.
    if (event.detail === 0 && !gesture) tapRecorder();
  });
  recordButton?.addEventListener("contextmenu", event => {
    if (recordButton.dataset.composerAction !== "send") event.preventDefault();
  });

  function stopGesture(event, canceled = false) {
    const g = gesture;
    if (!g || g.pointerId !== event.pointerId) return;
    gesture = null; window.clearTimeout(g.timer);
    if (!g.started && !g.canceled && !canceled) { tapRecorder(); return; }
    if (g.started && g.mode === "video_note") {
      if (g.canceled) window.SovietgramVideoNotes?.cancelHold();
      else if (canceled) window.SovietgramVideoNotes?.interruptHold();
      else if (!g.locked) window.SovietgramVideoNotes?.releaseHold();
    } else if (g.started) {
      if (pendingPointer?.pointerId === g.pointerId && !g.locked) pendingPointer.released = true;
      const session = recordSession;
      if (session?.pointerId === g.pointerId && !session.locked && !session.stopping)
        requestStop(session, canceled || g.canceled ? "cancel" : "send");
    }
    syncComposerActions();
  }
  document.addEventListener("pointermove", event => {
    const g = gesture;
    if (!g || g.pointerId !== event.pointerId || g.locked || g.canceled) return;
    const dx = event.clientX - g.clientX, dy = event.clientY - g.clientY;
    if (!g.started) {
      if (Math.abs(dx) > 24 || Math.abs(dy) > 24) { g.canceled = true; window.clearTimeout(g.timer); }
      return;
    }
    const cancelProgress = Math.max(0, Math.min(1, -dx / CANCEL_DISTANCE));
    const lockProgress = Math.max(0, Math.min(1, -dy / LOCK_DISTANCE));
    if (g.mode === "video_note") window.SovietgramVideoNotes?.moveHold(cancelProgress, lockProgress);
    else {
      recordBar?.style.setProperty("--voice-cancel-progress", String(cancelProgress));
      recordBar?.style.setProperty("--voice-lock-progress", String(lockProgress));
    }
    if (dx <= -CANCEL_DISTANCE && -dx >= -dy) {
      g.canceled = true;
      if (g.mode === "video_note") window.SovietgramVideoNotes?.cancelHold();
      else {
        if (pendingPointer?.pointerId === g.pointerId) pendingPointer.released = true;
        if (recordSession?.pointerId === g.pointerId) requestStop(recordSession,"cancel");
      }
    } else if (dy <= -LOCK_DISTANCE) {
      g.locked = true;
      if (g.mode === "video_note") window.SovietgramVideoNotes?.lockHold();
      else {
        if (pendingPointer?.pointerId === g.pointerId) pendingPointer.locked = true;
        if (recordSession?.pointerId === g.pointerId) { recordSession.locked = true; setRecordingUi(recordSession); }
      }
    }
  }, true);
  document.addEventListener("pointerup", event => stopGesture(event), true);
  document.addEventListener("pointercancel", event => stopGesture(event,true), true);
  recordButton?.addEventListener("lostpointercapture", event => {
    // Normal pointerup already cleared gesture. An unexpected capture loss
    // (browser permission UI, touch interruption) must never leave it stuck.
    if (gesture?.pointerId === event.pointerId) stopGesture(event,true);
  });

  recordDelete?.addEventListener("click", () => {
    if (recordSession && !recordSession.sending) requestStop(recordSession, "cancel");
  });
  recordSchedule?.addEventListener("click",()=>{
    if(recordSession?.locked&&!recordSession.sending)requestStop(recordSession,"schedule");
  });
  recordSend?.addEventListener("click", () => {
    if (recordSession && !recordSession.sending) requestStop(recordSession, "send");
  });

  document.addEventListener("visibilitychange", () => {
    if (document.hidden && gesture) stopGesture({pointerId:gesture.pointerId},true);
  });
  window.addEventListener("beforeunload", () => {
    if (recordSession && !recordSession.stopping) requestStop(recordSession, "cancel");
  });

  window.SovietgramVoice = {
    hydrate: hydrateTree,
    syncComposerActions,
    isRecording: () => Boolean(recordSession || (pendingPointer && !pendingPointer.released) ||
      (gesture?.started && gesture.mode === "voice" && !gesture.canceled)),
    get speed() { return voiceSpeed; },
    get volume() { return voiceVolume; },
    get autoplayNext() { return autoplayNext; },
  };
})();
