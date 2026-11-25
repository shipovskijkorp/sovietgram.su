/* Content-free notification polling, with browser-local sound preferences. */
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
  let enabled=true, audio=null, cursor=null, initial=null, busy=false;
  try { desktopEnabled = localStorage.getItem(desktopKey) === "true"; } catch (_) {}
  function desktopActive() { return hasDesktop && desktopEnabled && Notification.permission === "granted"; }
  function syncDesktop() {
    if (!desktop) return;
    desktop.hidden = !hasDesktop;
    desktop.setAttribute("aria-pressed", String(desktopActive()));
    const title = desktopActive() ? "Выключить системные уведомления" : "Включить системные уведомления";
    desktop.title = title; desktop.setAttribute("aria-label", title);
  }
  syncDesktop();
  desktop?.addEventListener("click", async () => {
    if (!hasDesktop) return;
    try {
      desktopEnabled = !desktopActive() && await Notification.requestPermission() === "granted";
      localStorage.setItem(desktopKey, String(desktopEnabled));
    } catch (_) { desktopEnabled = false; }
    syncDesktop();
    if (desktopActive()) void poll();
    else if (Notification.permission === "denied") window.showToast?.("Уведомления запрещены в настройках браузера.");
  });
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
        const ids = chats.get(item.chat_id) || [];
        ids.push(String(item.id)); chats.set(item.chat_id, ids);
      }
      for (const [chatId, ids] of chats) {
        try {
          const notice = new Notification("Sovietgram", {
            body: "Новое сообщение", tag: "sovietgram-"+button.dataset.accountId+"-"+chatId,
          });
          notice.onclick = async () => {
            notice.close(); window.focus();
            // Do not route an old notification into a different account.
            try {
              const response = await fetch("/presence/heartbeat/", {credentials:"same-origin",cache:"no-store"});
              const state = await response.json();
              window.location.assign(String(state.account_id) === button.dataset.accountId ? "/chat/"+chatId+"/" : "/");
            } catch (_) { window.location.assign("/"); }
          };
          ids.forEach(id => claimed.add(id));
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
  try { enabled=localStorage.getItem(key)!=="false"; } catch(_error) {}
  function sync() {
    button.setAttribute("aria-pressed",String(enabled));
    const label=enabled?"Выключить звуковые уведомления":"Включить звуковые уведомления";
    button.setAttribute("aria-label",label);button.title=label;
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
  async function poll() {
    focusState();
    if(busy || (!desktopActive() && (!enabled || document.hidden || !document.hasFocus())))return;
    busy=true;
    try {
      const url=new URL(button.dataset.notificationUrl,window.location.origin);
      url.searchParams.set("account_id",button.dataset.accountId);
      if(cursor)url.searchParams.set("since",cursor);
      const response=await fetch(url,{credentials:"same-origin",cache:"no-store"});
      const result=await response.json();
      if(!response.ok||!result.ok||String(result.account_id)!==button.dataset.accountId)return;
      const first=!initial;
      if(first)initial=result.server_time;
      cursor=nextCursor(result.server_time,initial);
      const fresh=newIds(result.ids||[],seen);
      if(!first && fresh.length) {
        play();
        const ids = new Set(fresh);
        await showDesktop((result.items || []).filter(item => ids.has(String(item.id))));
      }
    }catch(_error){}finally{busy=false;}
  }
  button.addEventListener("click",()=>{
    enabled=!enabled;sync();
    try{localStorage.setItem(key,String(enabled));}catch(_error){}
    if(enabled){void unlock();void poll();}
  });
  document.addEventListener("pointerdown",()=>void unlock(),{passive:true});
  document.addEventListener("keydown",()=>void unlock());
  window.addEventListener("storage",event=>{
    if(event.key===key){enabled=event.newValue!=="false";sync();}
    if(event.key===desktopKey){desktopEnabled=event.newValue==="true";syncDesktop();void poll();}
  });
  window.addEventListener("focus",()=>{focusState();syncDesktop();void poll();});
  window.addEventListener("blur",()=>{focusState(true);void poll();});
  window.addEventListener("pagehide",()=>focusState(true));
  document.addEventListener("visibilitychange",()=>{focusState();void poll();});
  window.setInterval(poll,5000);
  void poll();
})();
