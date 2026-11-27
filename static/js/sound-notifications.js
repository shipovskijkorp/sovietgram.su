/* Content-free notification polling with account preferences and device-local desktop permission. */
(() => {
  function newIds(ids, seen) {
    const fresh = [];
    for (const id of ids) {
      const value = String(id);
      if (seen.has(value)) continue;
      fresh.push(value); seen.add(value);
    }
    while (seen.size > 500) seen.delete(seen.values().next().value);
    return fresh;
  }
  function nextCursor(serverTime, initialTime) {
    return new Date(Math.max(new Date(initialTime).getTime(),new Date(serverTime).getTime()-5000)).toISOString();
  }
  window.SovietgramNotificationSound = { newIds,nextCursor };
  const button = document.getElementById("notificationSoundToggle");
  if (!button?.dataset.notificationUrl) return;
  const key = "sovietgram.notification-sound."+button.dataset.accountId;
  const desktop = document.getElementById("notificationDesktopToggle");
  const desktopKey = "sovietgram.notification-desktop."+button.dataset.accountId;
  const claimKey = "sovietgram.notification-claims."+button.dataset.accountId;
  const focusedKey = "sovietgram.notification-focus."+button.dataset.accountId;
  const tabId = window.crypto?.randomUUID?.() || String(Math.random());
  const hasDesktop = typeof window.Notification === "function" && window.isSecureContext;
  let desktopEnabled = false;
  let enabled=true, audio=null, cursor=null, cursorId=0, initial=null, busy=false;
  const preferenceKey = "sovietgram.notification-preferences."+button.dataset.accountId;
  const preferenceControls = [...document.querySelectorAll("[data-notification-preference]")];
  const preferenceStatus = document.getElementById("notificationPreferencesStatus");
  const originalTitle = document.title;
  const defaults = {sound:true, message:true, mention:true, reply:true, badge:true};
  const normalize = value => Object.fromEntries(Object.keys(defaults).map(key => [key,value?.[key] !== false]));
  let initialPreferences = {};
  try { initialPreferences = JSON.parse(document.getElementById("notificationAccountPreferences")?.textContent || "{}") || {}; } catch (_) {}
  let serverPreferences = normalize(initialPreferences);
  let preferences = {...serverPreferences};
  let unreadCount = 0, desktopBusy = false;
  const pending = new Map();
  let saving = false, initializing = false, refreshing = false, generation = 0, saveError = "";
  const preferencesUrl = button.dataset.preferencesUrl;
  const accountId = button.dataset.accountId;
  enabled = preferences.sound;
  function applyPreferences() {
    preferences = {...serverPreferences, ...Object.fromEntries(pending)};
    enabled = preferences.sound;
    sync();
  }
  async function requestPreferences(data = null) {
    const url = new URL(preferencesUrl, window.location.origin);
    const options = {credentials:"same-origin",cache:"no-store"};
    if (data) {
      options.method = "POST";
      options.body = new URLSearchParams({...data, account_id: accountId});
      const csrf = document.querySelector("#settingsAjaxForm [name='csrfmiddlewaretoken']")?.value;
      if (!csrf) throw new Error("CSRF");
      options.headers = {"X-CSRFToken":csrf};
      options.keepalive = true;
    } else url.searchParams.set("account_id",accountId);
    const response = await fetch(url, options);
    const result = await response.json();
    if (!response.ok || !result.ok || String(result.account_id) !== accountId) throw new Error("Preferences");
    return normalize(result.preferences);
  }
  async function refreshPreferences() {
    if (!preferencesUrl || refreshing || saving || initializing || pending.size) return;
    refreshing = true;
    const version = generation;
    try {
      const value = await requestPreferences();
      if (version !== generation || saving || initializing || pending.size) return;
      serverPreferences = value; applyPreferences();
      void poll();
    } catch (_) {}
    finally { refreshing = false; }
  }
  async function flushPreferences() {
    if (saving || initializing || !preferencesUrl || !pending.size) return;
    saving = true; syncPreferences();
    try {
      while (pending.size) {
        const [name,value] = pending.entries().next().value;
        try {
          serverPreferences = await requestPreferences({key:name,value:value?"1":"0"});
        } catch (_) {
          saveError = "Не удалось сохранить настройки. Проверьте соединение и повторите.";
        }
        if (pending.get(name) === value) pending.delete(name);
        applyPreferences();
      }
    } finally { saving = false; syncPreferences(); void poll(); }
  }
  function changePreference(name,value) {
    if (!preferencesUrl || !Object.hasOwn(defaults,name)) return;
    generation++; saveError = "";
    pending.set(name,Boolean(value)); applyPreferences();
    void flushPreferences();
  }
  async function importLegacyPreferences() {
    if (!preferencesUrl || Object.keys(initialPreferences).length) return;
    let legacy;
    try {
      const raw = localStorage.getItem(preferenceKey);
      const sound = localStorage.getItem(key);
      if (raw === null && sound === null) return;
      legacy = normalize({...JSON.parse(raw || "{}"),sound:sound !== "false"});
    } catch (_) { return; }
    initializing = true; generation++;
    serverPreferences = legacy; applyPreferences();
    try {
      const data = {initialize:"1"};
      for (const name of Object.keys(defaults)) data[name] = legacy[name]?"1":"0";
      serverPreferences = await requestPreferences(data);
      try { localStorage.removeItem(key); localStorage.removeItem(preferenceKey); } catch (_) {}
    } catch (_) {
      serverPreferences = normalize(initialPreferences);
      saveError = "Не удалось перенести прежние настройки. Обновите страницу после восстановления связи.";
    }
    finally { initializing = false; applyPreferences(); void flushPreferences(); }
  }
  function updateBadge() {
    document.title = preferences.badge && unreadCount > 0 ? "(" + (unreadCount > 999 ? "999+" : unreadCount) + ") " + originalTitle : originalTitle;
  }
  function syncPreferences() {
    for (const control of preferenceControls) {
      const name = control.dataset.notificationPreference;
      control.checked = name === "sound" ? enabled : name === "desktop" ? desktopActive() : preferences[name] !== false;
      if (name === "desktop") control.disabled = !hasDesktop || desktopBusy;
    }
    if (preferenceStatus) preferenceStatus.textContent = saveError || (saving || initializing
      ? "Сохранение настроек…"
      : !hasDesktop
        ? "Настройки синхронизируются. Системные уведомления недоступны в этом браузере."
        : Notification.permission === "denied"
          ? "Настройки синхронизируются. Системные уведомления запрещены в браузере."
          : "Настройки синхронизируются между устройствами. Разрешение системных уведомлений задаётся отдельно в каждом браузере.");
    updateBadge();
  }
  try { desktopEnabled = localStorage.getItem(desktopKey) === "true"; } catch (_) {}
  function desktopActive() { return hasDesktop && desktopEnabled && Notification.permission === "granted"; }
  function syncDesktop() {
    if (!desktop) return;
    desktop.hidden = !hasDesktop;
    desktop.setAttribute("aria-pressed", String(desktopActive()));
    const title = desktopActive() ? "Выключить системные уведомления" : "Включить системные уведомления";
    desktop.title = title; desktop.setAttribute("aria-label", title);
    syncPreferences();
  }
  syncDesktop();
  async function setDesktop(desired) {
    if (!hasDesktop || desktopBusy) return;
    desktopBusy = true;
    syncPreferences();
    try {
      desktopEnabled = Boolean(desired) && (Notification.permission === "granted" || await Notification.requestPermission() === "granted");
      try { localStorage.setItem(desktopKey, String(desktopEnabled)); } catch (_) {}
    } catch (_) { desktopEnabled = false; }
    finally { desktopBusy = false; syncDesktop(); }
    if (desktopActive()) void poll();
    else if (desired && Notification.permission === "denied") window.showToast?.("Уведомления запрещены в настройках браузера.");
  }
  desktop?.addEventListener("click", () => { void setDesktop(!desktopActive()); });
  function focusState(forceBlur = false) {
    try {
      if (!forceBlur && !document.hidden && document.hasFocus()) {
        localStorage.setItem(focusedKey, JSON.stringify({id: tabId, at: Date.now()}));
      } else {
        const previous = JSON.parse(localStorage.getItem(focusedKey) || "null");
        if (previous?.id === tabId) localStorage.removeItem(focusedKey);
      }
    } catch (_) {}
  }
  function anotherTabFocused() {
    try {
      const focus = JSON.parse(localStorage.getItem(focusedKey) || "null");
      return focus && focus.id !== tabId && Date.now()-focus.at < 10000;
    } catch (_) { return false; }
  }
  async function showDesktop(items) {
    if (!desktopActive() || (!document.hidden && document.hasFocus()) || anotherTabFocused()) return;
    const claim = () => {
      if (!desktopActive() || (!document.hidden && document.hasFocus()) || anotherTabFocused()) return;
      let old = [];
      try { old = JSON.parse(localStorage.getItem(claimKey) || "[]"); } catch (_) {}
      const claimed = new Set(Array.isArray(old) ? old : []);
      const chats = new Map();
      for (const item of items) {
        if (claimed.has(String(item.id)) || !Number.isSafeInteger(item.chat_id) || item.chat_id <= 0) continue;
        const messages = chats.get(item.chat_id) || [];
        messages.push(item); chats.set(item.chat_id, messages);
      }
      for (const [chatId, messages] of chats) {
        try {
          const latest = messages.at(-1);
          const kind = messages.some(item => item.kind === "reply") ? "reply"
            : messages.some(item => item.kind === "mention") ? "mention" : "message";
          const body = kind === "reply" ? "Вам ответили" : kind === "mention" ? "Вас упомянули" :
            messages.length > 1 ? "Новые сообщения: " + messages.length : "Новое сообщение";
          const notice = new Notification("Sovietgram", {
            body, tag: "sovietgram-"+button.dataset.accountId+"-"+chatId,
          });
          notice.onclick = async () => {
            notice.close(); window.focus();
            // Do not route an old notification into a different account.
            try {
              const response = await fetch("/presence/heartbeat/", {credentials:"same-origin",cache:"no-store"});
              const state = await response.json();
              const messageId = Number.isSafeInteger(latest.id) && latest.id > 0 ? latest.id : 0;
              const target = "/chat/" + chatId + "/" + (messageId ? "?message=" + messageId + "#message-" + messageId : "");
              window.location.assign(String(state.account_id) === button.dataset.accountId ? target : "/");
            } catch (_) { window.location.assign("/"); }
          };
          messages.forEach(item => claimed.add(String(item.id)));
        } catch (_) {
          // Some mobile browsers require a service worker for notifications.
          desktopEnabled = false; syncDesktop();
          try { localStorage.setItem(desktopKey, "false"); } catch (_) {}
          window.showToast?.("Системные уведомления не поддерживаются этим браузером.");
          break;
        }
      }
      try { localStorage.setItem(claimKey, JSON.stringify([...claimed].slice(-500))); } catch (_) {}
    };
    if (navigator.locks?.request) {
      try { await navigator.locks.request(claimKey, claim); } catch (_) {}
    } else claim();
  }
  const seen=new Set();
  function sync() {
    button.setAttribute("aria-pressed",String(enabled));
    const label=enabled?"Выключить звуковые уведомления":"Включить звуковые уведомления";
    button.setAttribute("aria-label",label);button.title=label;
    syncPreferences();
  }
  sync();
  async function unlock() {
    if (!enabled) return;
    try {
      const Context=window.AudioContext || window.webkitAudioContext;
      if (!Context) return;
      if (!audio) audio=new Context();
      if (audio.state==="suspended") await audio.resume();
    } catch(_error) {}
  }
  function play() {
    if (!enabled || !audio || audio.state!=="running" || document.hidden || !document.hasFocus()) return;
    const time=audio.currentTime;
    for (const [frequency,offset] of [[660,0],[880,.09]]) {
      const oscillator=audio.createOscillator(), gain=audio.createGain();
      oscillator.type="sine"; oscillator.frequency.value=frequency;
      gain.gain.setValueAtTime(.0001,time+offset);
      gain.gain.exponentialRampToValueAtTime(.055,time+offset+.015);
      gain.gain.exponentialRampToValueAtTime(.0001,time+offset+.18);
      oscillator.connect(gain);gain.connect(audio.destination);
      oscillator.start(time+offset);oscillator.stop(time+offset+.19);
    }
  }
  function allowed(item) { return preferences[item.kind || "message"] !== false; }
  async function poll() {
    focusState();
    const alerts = desktopActive() || (enabled && !document.hidden && document.hasFocus());
    if(busy || (!alerts && !preferences.badge))return;
    busy=true;
    let more = false;
    try {
      const url=new URL(button.dataset.notificationUrl,window.location.origin);
      url.searchParams.set("account_id",button.dataset.accountId);
      if(preferences.badge)url.searchParams.set("include_unread","1");
      if(cursor){url.searchParams.set("since",cursor);url.searchParams.set("after_id",String(cursorId));}
      const response=await fetch(url,{credentials:"same-origin",cache:"no-store"});
      const result=await response.json();
      if(!response.ok||!result.ok||String(result.account_id)!==button.dataset.accountId)return;
      const first=!initial;
      if(first)initial=result.server_time;
      cursor=result.next_since || nextCursor(result.server_time,initial);
      cursorId=Number(result.next_after_id)||0;
      more=Boolean(result.has_more);
      if(Number.isSafeInteger(result.unread_count)){unreadCount=result.unread_count;updateBadge();}
      const fresh=new Set(newIds(result.ids||[],seen));
      if(!first && fresh.size) {
        const items=(result.items||[]).filter(item=>fresh.has(String(item.id)) && allowed(item));
        if(items.length){play();await showDesktop(items);}
      }
    }catch(_error){}finally{
      busy=false;
      if(more)window.setTimeout(poll,150);
    }
  }
  function setSound(value) {
    changePreference("sound",value);
    if(enabled){void unlock();void poll();}
  }
  button.addEventListener("click",()=>setSound(!enabled));
  for(const control of preferenceControls)control.addEventListener("change",()=>{
    const name=control.dataset.notificationPreference;
    if(name==="sound"){setSound(control.checked);return;}
    if(name==="desktop"){void setDesktop(control.checked);return;}
    if(!Object.hasOwn(defaults,name))return;
    changePreference(name,control.checked);
  });
  document.addEventListener("pointerdown",()=>void unlock(),{passive:true});
  document.addEventListener("keydown",()=>void unlock());
  window.addEventListener("storage",event=>{
    if(event.key===desktopKey){desktopEnabled=event.newValue==="true";syncDesktop();void poll();}
  });
  window.addEventListener("focus",()=>{focusState();syncDesktop();void refreshPreferences();void poll();});
  window.addEventListener("blur",()=>{focusState(true);void poll();});
  window.addEventListener("pagehide",()=>focusState(true));
  document.addEventListener("visibilitychange",()=>{focusState();void poll();});
  window.setInterval(poll,5000);
  window.setInterval(refreshPreferences,15000);
  void importLegacyPreferences();
  void poll();
})();
