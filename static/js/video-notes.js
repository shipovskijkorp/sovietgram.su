(() => {
  "use strict";
  const $ = id => document.getElementById(id);
  const template = $("videoNotePlayerTemplate");
  const form = $("messageForm");
  const stage = $("messageStage");
  const dialog = $("videoNoteDialog");
  const notify = message => {
    if (typeof window.showToast === "function") window.showToast(message);
    else if ($("toast")) $("toast").textContent = message;
  };
  const time = seconds => {
    const value = Math.max(0, Math.floor(Number(seconds) || 0));
    return Math.floor(value/60) + ":" + String(value%60).padStart(2,"0");
  };
  function setListened(root) {
    root.dataset.listened = "true";
    const dot = root.querySelector("[data-note-unread]");
    if (dot) dot.hidden = true;
  }
  function hydrate(root) {
    if (!root || root.dataset.noteHydrated) return;
    const video = root.querySelector("video"), button = root.querySelector("[data-note-play]");
    const seek = root.querySelector("[data-note-seek]"), badge = root.querySelector("[data-note-time]");
    const ring = root.querySelector(".video-note-player__ring"), error = root.querySelector("[data-note-error]");
    if (!video || !button || !seek || !ring || !badge) return;
    root.dataset.noteHydrated = "true";
    let marking = false;
    const duration = () => Number.isFinite(video.duration) && video.duration > 0
      ? video.duration : Math.max(0, Number(root.dataset.durationMs || 0)/1000);
    function update() {
      const total = duration();
      const elapsed = Number.isFinite(video.currentTime) ? video.currentTime : 0;
      const ratio = total ? Math.min(1,Math.max(0,elapsed/total)) : 0;
      ring.style.setProperty("--note-progress", (ratio*100)+"%");
      seek.value = String(Math.round(ratio*1000));
      seek.disabled = !total;
      badge.textContent = time(video.paused && elapsed === 0 ? total : elapsed) + (video.paused && elapsed === 0 ? "" : " / "+time(total));
    }
    function state() {
      const playing = !video.paused && !video.ended;
      root.classList.toggle("is-playing",playing);
      button.textContent = playing ? "Ⅱ" : "▶";
      button.setAttribute("aria-label", playing ? "Приостановить видеокружок" : "Воспроизвести видеокружок");
      update();
    }
    async function mark() {
      if (marking || root.dataset.listened === "true" || !root.dataset.markPlayedUrl) return;
      marking = true;
      try {
        const csrf = (form?.querySelector("[name=csrfmiddlewaretoken]") ||
          $("settingsAjaxForm")?.querySelector("[name=csrfmiddlewaretoken]"))?.value;
        if (!csrf) return;
        const response = await fetch(root.dataset.markPlayedUrl, {
          method:"POST", credentials:"same-origin", headers:{"X-Requested-With":"XMLHttpRequest"},
          body:new URLSearchParams({csrfmiddlewaretoken:csrf,account_id:stage?.dataset.accountId || ""}),
        });
        if (response.ok && (await response.json()).ok) setListened(root);
      } catch (_) {} finally { marking = false; }
    }
    async function toggle() {
      if (!video.paused) { video.pause(); return; }
      if (error) error.hidden = true;
      try { await video.play(); }
      catch (_) { if(error){error.textContent="Не удалось воспроизвести видео.";error.hidden=false;} }
    }
    button.addEventListener("click", toggle);
    video.addEventListener("click", toggle);
    for(const name of ["loadedmetadata","durationchange","timeupdate"]) video.addEventListener(name,update);
    video.addEventListener("playing",()=>{state();void mark();});
    video.addEventListener("pause",state);
    video.addEventListener("ended",state);
    video.addEventListener("error",()=>{if(error){error.textContent="Видео недоступно или формат не поддерживается.";error.hidden=false;}});
    seek.addEventListener("input",()=>{
      const total = duration();
      if(total && video.readyState > 0) { try{ video.currentTime=total*Number(seek.value)/1000; }catch(_){} }
    });
    state();
  }
  function buildPlayer(attachment) {
    const root = template.content.firstElementChild.cloneNode(true);
    root.dataset.noteId = String(attachment.id);
    root.dataset.durationMs = String(attachment.duration_ms || 0);
    root.dataset.markPlayedUrl = attachment.mark_played_url || "";
    root.dataset.listened = String(Boolean(attachment.listened));
    root.querySelector("[data-note-unread]").hidden = Boolean(attachment.listened);
    const video = root.querySelector("video");
    video.preload = document.body.dataset.mediaPreload === "false" ? "none" : "metadata";
    video.src = attachment.url;
    hydrate(root);
    return root;
  }
  function hydrateTree(root) {
    if(root.matches?.("[data-video-note-player]")) hydrate(root);
    root.querySelectorAll?.("[data-video-note-player]").forEach(hydrate);
  }
  hydrateTree(document);
  const flow = $("messageFlow");
  if(flow) new MutationObserver(records=>records.forEach(record=>record.addedNodes.forEach(node=>{
    if(node.nodeType===1)hydrateTree(node);
  }))).observe(flow,{childList:true,subtree:true});
  // Pause another player, including the existing voice player, when a
  // received video note or other audio/video starts. Preview camera is silent.
  document.addEventListener("play",event=>{
    const player=event.target;
    if(!["AUDIO","VIDEO"].includes(player.tagName))return;
    if(player.id==="videoNotePreview" && player.srcObject)return;
    for(const other of document.querySelectorAll("audio,video"))
      if(other!==player && !other.paused && !(other.id==="videoNotePreview"&&other.srcObject))other.pause();
  },true);
  window.SovietgramVideoNotes = {buildPlayer, setListened, isOpen:()=>Boolean(dialog?.open)};
  if(!dialog || !form || !stage)return;

  const preview=$("videoNotePreview"), clock=$("videoNoteClock"), status=$("videoNoteStatus");
  const start=$("videoNoteStart"), stop=$("videoNoteStop"), send=$("videoNoteSend");
  const camera=$("videoNoteCamera"), retake=$("videoNoteRetake"), close=$("videoNoteClose");
  const silent=$("videoNoteSilent"), silentRow=$("videoNoteSilentRow");
  const MAX_MS=60000, MIN_MS=200, MAX_BYTES=25*1024*1024;
  let state="idle", generation=0, facing="user", source=null, session=null, pending=null, objectUrl="";
  let holdMode=false, holdLocked=false;
  const gestureBar=$("videoNoteGesture"), gestureHint=$("videoNoteGestureHint"), actions=$("videoNoteActions");
  const elapsed=$("videoNoteElapsed");
  const stopTracks=stream=>stream?.getTracks?.().forEach(track=>track.stop());
  function ui(next,message="") {
    state=next; status.textContent=message;
    dialog.dataset.recordState=next;
    const holding=holdMode && !holdLocked && ["opening","ready","recording"].includes(next);
    dialog.classList.toggle("is-holding",holding);
    dialog.classList.toggle("is-locked",holdLocked);
    gestureBar.hidden=!holding;
    actions.hidden=holding;
    start.hidden=!["ready","opening","error"].includes(next);
    start.disabled=next!=="ready";
    camera.hidden=holding || !["ready","opening","error"].includes(next);
    camera.disabled=next==="opening";
    stop.hidden=next!=="recording";
    retake.hidden=!["review","sending"].includes(next);
    send.hidden=!["review","sending"].includes(next) && !(next==="recording" && !holding);
    send.disabled=retake.disabled=close.disabled=silent.disabled=next==="sending"||next==="stopping";
    send.setAttribute("aria-label",next==="sending"?"Отправка…":"Отправить");
    silentRow.hidden=!["review","sending"].includes(next);
    clock.hidden=!["recording","stopping"].includes(next);
  }
  function clearPreview() {
    preview.pause(); preview.srcObject=null; preview.removeAttribute("src"); preview.controls=false; preview.muted=true;
    preview.classList.remove("is-mirrored");
    if(objectUrl){URL.revokeObjectURL(objectUrl);objectUrl="";}
  }
  function releaseRecording(current) {
    if(!current)return;
    clearInterval(current.timer);
    clearTimeout(current.deadline);
    cancelAnimationFrame(current.frame);
    if(current.recordStream && current.recordStream!==source)stopTracks(current.recordStream);
  }
  function cancel() {
    generation++;
    holdMode=false;holdLocked=false;
    dialog.style.removeProperty("--note-cancel-progress");
    dialog.style.removeProperty("--note-lock-progress");
    const current=session; session=null;
    if(current && current.recorder.state!=="inactive") { try{current.recorder.stop();}catch(_){} }
    releaseRecording(current); stopTracks(source);source=null;pending=null;
    clearPreview();ui("idle");
  }
  function shut() { if(state==="sending")return;cancel();if(dialog.open)dialog.close(); }
  async function openCamera() {
    const token=++generation;
    stopTracks(source); source=null; pending=null; clearPreview();
    ui("opening","Разрешите доступ к камере и микрофону.");
    try {
      if(!window.isSecureContext || !navigator.mediaDevices?.getUserMedia || !window.MediaRecorder)
        throw new Error("Запись доступна только в браузере с поддержкой камеры и HTTPS.");
      const stream=await navigator.mediaDevices.getUserMedia({video:{
        facingMode:{ideal:facing},width:{ideal:480},height:{ideal:480},aspectRatio:{ideal:1},frameRate:{ideal:24,max:30},
      },audio:true});
      if(token!==generation||!dialog.open||document.hidden){stopTracks(stream);return;}
      if(!stream.getVideoTracks().length||!stream.getAudioTracks().length){stopTracks(stream);throw new Error("Нужны камера и микрофон.");}
      source=stream; preview.srcObject=source; preview.muted=true;
      preview.classList.toggle("is-mirrored",facing==="user");
      await preview.play();
      if(token!==generation||!dialog.open){stopTracks(stream);return;}
      for(const track of source.getTracks())track.addEventListener("ended",()=>{
        if(token!==generation||source!==stream)return;
        if(state==="recording")finish();
        else if(state==="ready"){stopTracks(source);source=null;clearPreview();ui("error","Камера отключилась. Смените камеру или откройте запись заново.");}
      });
      ui("ready","До 60 секунд. Перед отправкой можно посмотреть запись.");
      if(holdMode) begin();
    } catch(error) {
      if(token!==generation)return;
      stopTracks(source);source=null;clearPreview();
      ui("error",error?.name==="NotAllowedError"?"Доступ к камере или микрофону запрещён.":error?.name==="NotFoundError"?"Камера или микрофон не найдены.":error.message||"Не удалось открыть камеру.");
    }
  }
  function mimeType() {
    return ["video/mp4;codecs=avc1.42E01E,mp4a.40.2","video/mp4","video/webm;codecs=vp8,opus","video/webm;codecs=vp9,opus","video/webm"].find(type=>
      typeof MediaRecorder.isTypeSupported==="function"&&MediaRecorder.isTypeSupported(type)) || "";
  }
  function finish(sendImmediately=false) {
    const current=session;
    if(!current||state!=="recording")return;
    current.autoSend=sendImmediately===true;
    current.duration=Math.min(MAX_MS,Math.max(0,Math.round(performance.now()-current.started)));
    clearInterval(current.timer);clearTimeout(current.deadline);
    ui("stopping","Подготовка записи…");
    try{if(current.recorder.state!=="inactive")current.recorder.stop();}
    catch(_){cancel();ui("error","Не удалось завершить запись.");}
  }
  function begin() {
    if(state!=="ready"||!source)return;
    // Square center crop at a modest resolution. On browsers without canvas
    // capture the actual camera stream is kept and still displayed round.
    let recordStream=source, canvas=null, context=null;
    if(preview.videoWidth&&preview.videoHeight){
      const target=document.createElement("canvas");target.width=target.height=480;
      const ctx=target.getContext("2d",{alpha:false});
      if(ctx&&typeof target.captureStream==="function"){
        try{
          const captured=target.captureStream(24);
          if(captured.getVideoTracks().length){
            for(const audio of source.getAudioTracks())captured.addTrack(audio);
            recordStream=captured;canvas=target;context=ctx;
          }else stopTracks(captured);
        }catch(_){}
      }
    }
    const mime=mimeType();
    let recorder;
    try{
      const options={videoBitsPerSecond:1400000,audioBitsPerSecond:64000,...(mime?{mimeType:mime}:{})};
      try{recorder=new MediaRecorder(recordStream,options);}
      catch(_){recorder=new MediaRecorder(recordStream,mime?{mimeType:mime}:undefined);}
    }catch(_){
      if(recordStream!==source)stopTracks(recordStream);
      cancel();ui("error","Браузер не смог начать запись видео. Смените камеру или попробуйте другой браузер.");return;
    }
    const current={recorder,recordStream,chunks:[],bytes:0,started:performance.now(),duration:0,frame:0,timer:0,deadline:0};
    session=current;
    function draw(){
      if(session!==current||!context)return;
      if(preview.videoWidth&&preview.videoHeight){
        const edge=Math.min(preview.videoWidth,preview.videoHeight);
        context.drawImage(preview,(preview.videoWidth-edge)/2,(preview.videoHeight-edge)/2,edge,edge,0,0,480,480);
      }
      current.frame=requestAnimationFrame(draw);
    }
    if(canvas)draw();
    recorder.addEventListener("dataavailable",event=>{
      if(session!==current||!event.data?.size)return;
      current.chunks.push(event.data);current.bytes+=event.data.size;
      if(current.bytes>MAX_BYTES&&state==="recording")finish();
    });
    recorder.addEventListener("error",()=>{
      if(session!==current)return;
      cancel();ui("error","Ошибка записи. Попробуйте снова.");
    });
    recorder.addEventListener("stop",()=>{
      if(session!==current)return;
      releaseRecording(current);
      stopTracks(source);source=null;session=null;clearPreview();
      const type=(recorder.mimeType||current.chunks[0]?.type||mime).split(";",1)[0].toLowerCase();
      if(!["video/webm","video/mp4"].includes(type)){
        ui("error","Формат записанного видео не поддерживается.");return;
      }
      const blob=new Blob(current.chunks,{type});
      if(current.duration<MIN_MS||!blob.size||blob.size>MAX_BYTES){
        ui("error",blob.size>MAX_BYTES?"Запись больше 25 МБ.":"Запись слишком короткая.");return;
      }
      pending={blob,duration:current.duration,filename:"video-note-"+Date.now()+(type==="video/mp4"?".mp4":".webm"),data:null};
      objectUrl=URL.createObjectURL(blob);preview.src=objectUrl;preview.controls=true;preview.muted=false;
      silent.checked=false;
      ui("review","Просмотрите кружок или отправьте его.");
      if(current.autoSend) void upload();
    },{once:true});
    try{
      recorder.start(250);current.started=performance.now();
      elapsed.textContent="0:00";ui("recording",holdLocked?"Запись зафиксирована":"Идёт запись…");
      current.timer=setInterval(()=>{elapsed.textContent=time(Math.min(MAX_MS,performance.now()-current.started)/1000);},100);
      current.deadline=setTimeout(()=>finish(false),MAX_MS);
    }catch(_){cancel();ui("error","Не удалось начать запись.");}
  }
  async function upload() {
    if(state!=="review"||!pending)return;
    const item=pending;
    if(!item.data){
      const reply=$("replyToInput")?.value||"",quote=reply?window.SovietgramChat?.currentQuote?.()||"":"";
      const data=new FormData();
      const csrf=form.querySelector("[name=csrfmiddlewaretoken]")?.value;
      if(!csrf){ui("review","Не удалось получить CSRF-токен. Обновите страницу.");return;}
      data.append("csrfmiddlewaretoken",csrf);data.append("account_id",stage.dataset.accountId);
      data.append("attachment_mode","video_note");data.append("text","");
      data.append("video_note_duration_ms",String(item.duration));
      data.append("client_message_id",window.SovietgramSendRetry.uuid());
      data.append("silent",silent.checked?"1":"0");data.append("preserve_draft","1");
      if(reply)data.append("reply_to",reply);if(quote)data.append("reply_quote",quote);
      data.append("attachments",item.blob,item.filename);item.data=data;
    }
    preview.pause();ui("sending","Отправка видеокружка…");
    try {
      const response=await window.SovietgramSendRetry.fetchSend(form.action,{
        method:"POST",credentials:"same-origin",headers:{"X-Requested-With":"XMLHttpRequest"},body:item.data,
      });
      const result=await response.json().catch(()=>({}));
      if(!response.ok||!result.ok||!result.message)
        throw new Error(result.error||Object.values(result.errors||{}).flat()[0]?.message||"Не удалось отправить запись.");
      if(($("replyToInput")?.value||"")===(item.data.get("reply_to")||"")&&
         (window.SovietgramChat?.currentQuote?.()||"")===(item.data.get("reply_quote")||""))
        window.SovietgramChat?.clearReplyState?.();
      if(!window.SovietgramChat?.acceptSentMessage?.(result.message))
        window.SovietgramChat?.syncNow?.();
      cancel();dialog.close();notify("Видеокружок отправлен.");
    } catch(error) {
      ui("review",(error.message||"Ошибка отправки.")+" Запись сохранена для повтора.");
      // Retry the same immutable payload to avoid duplicate sends.
      silent.disabled=true;
    }
  }
  function openRecorder(held=false) {
    if(dialog.open)return false;
    if(window.SovietgramVoice?.isRecording?.() || ($("voiceRecordingBar") && !$("voiceRecordingBar").hidden)){
      notify("Сначала завершите голосовую запись.");return false;
    }
    holdMode=held;holdLocked=false;facing="user";
    gestureHint.textContent="‹ Сдвиньте влево для отмены";
    // A non-modal overlay during a held pointer preserves its capture on
    // the composer button. The overlay still intercepts unrelated clicks.
    if(held) dialog.show(); else dialog.showModal();
    void openCamera();return true;
  }
  Object.assign(window.SovietgramVideoNotes,{
    openPreview:()=>openRecorder(false),
    startHold:()=>openRecorder(true),
    moveHold:(cancelProgress,lockProgress)=>{
      if(!holdMode||holdLocked||!dialog.open)return;
      dialog.style.setProperty("--note-cancel-progress",String(cancelProgress));
      dialog.style.setProperty("--note-lock-progress",String(lockProgress));
      gestureHint.textContent=cancelProgress>.5?"Отмена записи":lockProgress>.5?"Фиксация записи":"‹ Сдвиньте влево для отмены";
    },
    lockHold:()=>{
      if(!holdMode||!dialog.open)return;
      holdLocked=true;ui(state,"Запись зафиксирована");
    },
    cancelHold:()=>{if(holdMode && dialog.open && state!=="sending")shut();},
    releaseHold:()=>{
      if(!holdMode||holdLocked||!dialog.open)return;
      if(state==="recording")finish(true);
      else if(["opening","ready"].includes(state)){
        shut();notify("Камера ещё не готова. Удерживайте кнопку до начала записи.");
      }
    },
  });
  document.addEventListener("click",event=>{
    if(!event.target.closest?.("[data-open-video-note]")||dialog.open)return;
    event.preventDefault();
    const menu=$("attachmentMenu");if(menu&&!menu.hidden)$("attachmentButton")?.click();
    openRecorder(false);
  });
  start.addEventListener("click",begin);stop.addEventListener("click",()=>finish(false));
  close.addEventListener("click",shut);
  camera.addEventListener("click",()=>{if(state!=="opening"){holdMode=false;holdLocked=false;facing=facing==="user"?"environment":"user";void openCamera();}});
  retake.addEventListener("click",()=>{if(state==="review"&&window.confirm("Удалить текущую запись и записать новую?")){holdMode=false;holdLocked=false;void openCamera();}});
  send.addEventListener("click",()=>{if(state==="recording")finish(true);else void upload();});
  dialog.addEventListener("cancel",event=>{event.preventDefault();if(state!=="sending")shut();});
  dialog.addEventListener("close",()=>{if(state!=="idle")cancel();window.SovietgramVoice?.syncComposerActions?.();});
  document.addEventListener("keydown",event=>{if(event.key==="Escape"&&dialog.open&&state!=="sending"){event.preventDefault();shut();}});
  document.addEventListener("visibilitychange",()=>{
    if(!document.hidden)return;
    if(state==="recording")finish();
    else if(state==="ready"||state==="opening"){
      generation++;stopTracks(source);source=null;clearPreview();
      ui("error","Камера отключена, поскольку вкладка скрыта. Смените камеру или откройте запись заново.");
    }
  });
  window.addEventListener("pagehide",cancel);
})();
