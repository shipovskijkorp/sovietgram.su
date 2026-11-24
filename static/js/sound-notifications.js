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
  let enabled=true, audio=null, cursor=null, initial=null, busy=false;
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
    if(busy || !enabled || document.hidden || !document.hasFocus())return;
    busy=true;
    try {
      const url=new URL(button.dataset.notificationUrl,window.location.origin);
      if(cursor)url.searchParams.set("since",cursor);
      const response=await fetch(url,{credentials:"same-origin",cache:"no-store"});
      const result=await response.json();
      if(!response.ok||!result.ok||String(result.account_id)!==button.dataset.accountId)return;
      const first=!initial;
      if(first)initial=result.server_time;
      cursor=nextCursor(result.server_time,initial);
      const fresh=newIds(result.ids||[],seen);
      if(!first && fresh.length)play();
    }catch(_error){}finally{busy=false;}
  }
  button.addEventListener("click",()=>{
    enabled=!enabled;sync();
    try{localStorage.setItem(key,String(enabled));}catch(_error){}
    if(enabled){cursor=initial=null;seen.clear();void unlock();void poll();}
  });
  document.addEventListener("pointerdown",()=>void unlock(),{passive:true});
  document.addEventListener("keydown",()=>void unlock());
  window.addEventListener("storage",event=>{
    if(event.key===key){enabled=event.newValue!=="false";sync();}
  });
  window.addEventListener("focus",()=>void poll());
  document.addEventListener("visibilitychange",()=>{if(!document.hidden)void poll();});
  window.setInterval(poll,5000);
  void poll();
})();
