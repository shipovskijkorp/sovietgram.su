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
  let activePlayer = null;
  const selecting = root => Boolean(root.closest(".conversation.is-message-selection"));
  function hydrate(root) {
    if (!root || root.dataset.noteHydrated) return;
    const video=root.querySelector("video"), button=root.querySelector("[data-note-play]");
    const seek=root.querySelector("[data-note-seek]"), badge=root.querySelector("[data-note-time]");
    const arc=root.querySelector("[data-note-arc]"), thumb=root.querySelector("[data-note-thumb]");
    const ring=root.querySelector(".video-note-player__ring"), error=root.querySelector("[data-note-error]");
    const mute=root.querySelector("[data-note-mute]"), collapse=root.querySelector("[data-note-collapse]");
    if(!video||!button||!seek||!ring||!badge||!arc||!thumb||!mute||!collapse)return;
    root.dataset.noteHydrated="true";
    const article=()=>root.closest(".message");
    let marking=false, dragging=null, animation=0, playToken=0, wantsPlay=false;
    const expanded=()=>root.classList.contains("is-expanded");
    const duration=()=>Number.isFinite(video.duration)&&video.duration>0
      ?video.duration:Math.max(0,Number(root.dataset.durationMs||0)/1000);
    function update(){
      const total=duration(),elapsed=Number.isFinite(video.currentTime)?video.currentTime:0;
      const ratio=total?Math.min(1,Math.max(0,elapsed/total)):0;
      const progress=ratio*100,angle=ratio*2*Math.PI;
      arc.setAttribute("stroke-dasharray",progress+" "+(100-progress));
      thumb.setAttribute("cx",String(50+47.5*Math.sin(angle)));
      thumb.setAttribute("cy",String(50-47.5*Math.cos(angle)));
      seek.setAttribute("aria-valuenow",String(Math.round(progress)));
      seek.setAttribute("aria-valuetext",time(elapsed)+" / "+time(total));
      seek.setAttribute("aria-disabled",String(!total||video.readyState<1));
      badge.textContent=time(expanded()?Math.ceil(Math.max(0,total-elapsed)):Math.ceil(total));
    }
    function tick(){
      animation=0;
      update();
      if(!video.paused&&!video.ended&&root.isConnected)animation=requestAnimationFrame(tick);
    }
    function state(){
      const playing=!video.paused&&!video.ended;
      root.classList.toggle("is-playing",playing);
      button.setAttribute("aria-label",playing?"Приостановить видеокружок":"Воспроизвести видеокружок");
      button.setAttribute("aria-pressed",String(playing));
      if(!playing&&animation){cancelAnimationFrame(animation);animation=0;}
      if(playing&&!animation)animation=requestAnimationFrame(tick);
      update();
    }
    function setExpanded(value, reveal=false){
      if(expanded()===value)return;
      const before=stage?.getBoundingClientRect(),atBottom=stage&&stage.scrollHeight-stage.scrollTop-stage.clientHeight<45;
      const old=ring.getBoundingClientRect();
      root.classList.toggle("is-expanded",value);
      article()?.classList.toggle("has-expanded-video-note",value);
      seek.setAttribute("tabindex",value?"0":"-1");
      mute.hidden=collapse.hidden=!value;
      update();
      if(stage&&before&&root.isConnected){
        // Keep the viewport anchored; only reveal a note the user clicked.
        requestAnimationFrame(()=>{
          if(!root.isConnected)return;
          if(atBottom){stage.scrollTop=stage.scrollHeight;return;}
          if(!value||!reveal)return;
          const rect=ring.getBoundingClientRect(),viewport=stage.getBoundingClientRect();
          if(old.top>=before.top-4&&old.bottom<=before.bottom+4&&rect.bottom>viewport.bottom-12)
            stage.scrollTop+=rect.bottom-viewport.bottom+12;
        });
      }
    }
    function deactivate({reset=false}={}){
      ++playToken;wantsPlay=false;dragging=null;video.pause();
      if(reset){try{video.currentTime=0;}catch(_){}}
      if(activePlayer===controller)activePlayer=null;
      setExpanded(false);state();
    }
    const controller={root,video,deactivate};
    async function mark(){
      if(marking||root.dataset.listened==="true"||!root.dataset.markPlayedUrl)return;
      marking=true;
      try{
        const csrf=(form?.querySelector("[name=csrfmiddlewaretoken]")||
          $("settingsAjaxForm")?.querySelector("[name=csrfmiddlewaretoken]")||
          document.querySelector("[name=csrfmiddlewaretoken]"))?.value;
        const account=stage?.dataset.accountId||document.body.dataset.accountId;
        if(!csrf||!account)return;
        const response=await fetch(root.dataset.markPlayedUrl,{
          method:"POST",credentials:"same-origin",headers:{"X-Requested-With":"XMLHttpRequest"},
          body:new URLSearchParams({csrfmiddlewaretoken:csrf,account_id:account}),
        });
        if(response.ok&&(await response.json()).ok)setListened(root);
      }catch(_){}finally{marking=false;}
    }
    function updateMute(){
      mute.setAttribute("aria-pressed",String(video.muted));
      mute.setAttribute("aria-label",video.muted?"Включить звук":"Выключить звук");
      mute.title=video.muted?"Включить звук":"Выключить звук";
      root.classList.toggle("is-muted",video.muted);
    }
    async function play(){
      if(!root.isConnected||selecting(root))return;
      if(activePlayer&&activePlayer!==controller)activePlayer.deactivate();
      activePlayer=controller;
      setExpanded(true,true);
      if(video.ended){try{video.currentTime=0;}catch(_){}}
      if(error)error.hidden=true;
      const token=++playToken;wantsPlay=true;
      try{
        await video.play();
        if(token!==playToken)return;
        state();
      }catch(_){
        if(token!==playToken)return;
        wantsPlay=false;state();
        if(error){error.textContent="Не удалось воспроизвести видео. Нажмите ещё раз.";error.hidden=false;}
      }
    }
    button.addEventListener("click",()=>{
      if(selecting(root))return;
      if(wantsPlay||!video.paused){++playToken;wantsPlay=false;video.pause();state();}
      else void play();
    });
    collapse.addEventListener("click",()=>{if(!selecting(root)){deactivate();button.focus({preventScroll:true});}});
    mute.addEventListener("click",()=>{if(!selecting(root)){video.muted=!video.muted;updateMute();}});
    function seekTo(ratio){
      const total=duration();
      if(!total||video.readyState<1)return;
      try{video.currentTime=Math.max(0,Math.min(total-0.01,total*ratio));update();}catch(_){}
    }
    function seekAt(event){
      const rect=seek.getBoundingClientRect();
      const dx=event.clientX-(rect.left+rect.width/2),dy=event.clientY-(rect.top+rect.height/2);
      if(!rect.width||!rect.height)return;
      const angle=Math.atan2(dx,-dy);
      seekTo((angle+2*Math.PI)%(2*Math.PI)/(2*Math.PI));
    }
    seek.addEventListener("pointerdown",event=>{
      if(!expanded()||selecting(root)||event.button!==0||video.readyState<1)return;
      event.preventDefault();event.stopPropagation();
      seek.focus({preventScroll:true});
      dragging={id:event.pointerId,resume:!video.paused};
      if(dragging.resume){++playToken;wantsPlay=false;video.pause();}
      try{seek.setPointerCapture(event.pointerId);}catch(_){}
      seekAt(event);
    });
    seek.addEventListener("pointermove",event=>{
      if(dragging?.id!==event.pointerId)return;
      event.preventDefault();seekAt(event);
    });
    function endSeek(event,canceled=false){
      if(dragging?.id!==event.pointerId)return;
      const resume=dragging.resume;dragging=null;
      if(!canceled)seekAt(event);
      if(resume&&activePlayer===controller&&expanded())void play();
    }
    seek.addEventListener("pointerup",event=>endSeek(event));
    seek.addEventListener("pointercancel",event=>endSeek(event,true));
    seek.addEventListener("lostpointercapture",event=>endSeek(event,true));
    seek.addEventListener("keydown",event=>{
      if(!expanded()||selecting(root))return;
      const total=duration();if(!total)return;
      let target=video.currentTime||0;
      switch(event.key){
        case "ArrowLeft":case "ArrowDown":target-=5;break;
        case "ArrowRight":case "ArrowUp":target+=5;break;
        case "Home":target=0;break;case "End":target=total;break;
        default:return;
      }
      event.preventDefault();seekTo(target/total);
    });
    for(const name of ["loadedmetadata","loadeddata","durationchange","timeupdate","seeked"])
      video.addEventListener(name,update);
    video.addEventListener("playing",()=>{wantsPlay=false;state();void mark();});
    video.addEventListener("pause",()=>{wantsPlay=false;state();});
    video.addEventListener("ended",()=>deactivate({reset:true}));
    video.addEventListener("volumechange",updateMute);
    video.addEventListener("error",()=>{
      wantsPlay=false;state();
      if(error){error.textContent="Видео недоступно или формат не поддерживается.";error.hidden=false;}
    });
    updateMute();state();
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
  if(flow)new MutationObserver(records=>{
    for(const record of records)for(const node of record.addedNodes)if(node.nodeType===1)hydrateTree(node);
    if(activePlayer&&!activePlayer.root.isConnected)activePlayer.deactivate();
  }).observe(flow,{childList:true,subtree:true});
  // Pause another player, including the existing voice player, when a
  // received video note or other audio/video starts. Preview camera is silent.
  document.addEventListener("play",event=>{
    const player=event.target;
    if(!["AUDIO","VIDEO"].includes(player.tagName))return;
    if(player.id==="videoNotePreview" && player.srcObject)return;
    if(activePlayer&&activePlayer.video!==player)activePlayer.deactivate();
    for(const other of document.querySelectorAll("audio,video"))
      if(other!==player && !other.paused && !(other.id==="videoNotePreview"&&other.srcObject))other.pause();
  },true);
  const isOpen=()=>Boolean(dialog && !dialog.hidden);
  window.SovietgramVideoNotes={buildPlayer,setListened,isOpen};
  if(!dialog||!form||!stage)return;

  // A plain overlay avoids native dialog focus changes and pointer capture
  // loss in browsers while the composer button is still being held.
  document.body.appendChild(dialog);
  const preview=$("videoNotePreview"), clock=$("videoNoteClock"), status=$("videoNoteStatus");
  const start=$("videoNoteStart"), stop=$("videoNoteStop"), send=$("videoNoteSend");
  const camera=$("videoNoteCamera"), retake=$("videoNoteRetake"), close=$("videoNoteClose"), retry=$("videoNoteRetry");
  const silent=$("videoNoteSilent"), silentRow=$("videoNoteSilentRow");
  const gestureBar=$("videoNoteGesture"), gestureHint=$("videoNoteGestureHint"), elapsed=$("videoNoteElapsed");
  const MAX_MS=60000, MIN_MS=200, MAX_BYTES=25*1024*1024;
  const CAMERA_TIMEOUT=30000, STOP_TIMEOUT=5000, DECODE_TIMEOUT=10000;
  let state="idle", generation=0, facing="user", source=null, session=null, pending=null, objectUrl="";
  let holdMode=false, holdLocked=false, openingTimer=0, uploadController=null, restoreFocus=null, reviewCleanup=null;
  const stopTracks=stream=>stream?.getTracks?.().forEach(track=>track.stop());
  function ui(next,message="") {
    state=next; status.textContent=message;
    dialog.dataset.recordState=next;
    const holding=holdMode&&!holdLocked&&["opening","ready","recording"].includes(next);
    dialog.classList.toggle("is-holding",holding);
    dialog.classList.toggle("is-locked",holdLocked);
    gestureBar.hidden=!holding;
    // Keep an explicit escape hatch and normal controls visible during hold.
    start.hidden=next!=="ready";
    start.disabled=next!=="ready";
    camera.hidden=!["ready","error"].includes(next);
    camera.disabled=!["ready","error"].includes(next);
    retry.hidden=next!=="error";
    stop.hidden=next!=="recording";
    retake.hidden=!["checking","review"].includes(next);
    send.hidden=!["recording","checking","review","sending"].includes(next);
    send.disabled=next==="checking"||next==="sending"||(next==="review"&&!pending?.verified);
    retake.disabled=next==="sending";
    close.disabled=false;
    close.setAttribute("aria-label",next==="sending"?"Прервать ожидание отправки":"Отменить видеозапись");
    close.querySelector("span").textContent=next==="sending"?"Прервать":"Отмена";
    send.setAttribute("aria-label",next==="sending"?"Отправка…":"Отправить");
    send.querySelector("span").textContent=next==="sending"?"Отправка…":"Отправить";
    silentRow.hidden=next!=="review";
    silent.disabled=Boolean(pending?.data);
    clock.hidden=!["recording","stopping"].includes(next);
  }
  function clearPreview() {
    reviewCleanup?.();reviewCleanup=null;
    preview.pause();preview.autoplay=false;preview.controls=false;preview.muted=true;
    preview.srcObject=null;preview.removeAttribute("src");
    try{preview.load();}catch(_){}
    preview.classList.remove("is-mirrored");
    if(objectUrl){URL.revokeObjectURL(objectUrl);objectUrl="";}
  }
  function releaseRecording(current) {
    if(!current)return;
    clearInterval(current.timer);clearTimeout(current.deadline);clearTimeout(current.stopTimer);
  }
  function reset() {
    ++generation;clearTimeout(openingTimer);openingTimer=0;
    const current=session;session=null;
    releaseRecording(current);
    if(current&&current.recorder.state!=="inactive"){try{current.recorder.stop();}catch(_){}}
    stopTracks(source);source=null;pending=null;
    clearPreview();
    holdMode=false;holdLocked=false;
    dialog.style.removeProperty("--note-cancel-progress");
    dialog.style.removeProperty("--note-lock-progress");
    ui("idle");
  }
  function closeRecorder() {
    reset();dialog.hidden=true;
    window.SovietgramVoice?.syncComposerActions?.();
    if(restoreFocus?.isConnected)restoreFocus.focus({preventScroll:true});
    restoreFocus=null;
  }
  function fail(message) {
    reset();ui("error",message);
  }
  function manualMode(message) {
    holdMode=false;holdLocked=false;
    ui(state,message||status.textContent);
  }
  function cameraError(error) {
    switch(error?.name){
      case "NotAllowedError":case "SecurityError":
        return "Нет разрешения на камеру или микрофон. Разрешите доступ к сайту в браузере и нажмите «Повторить».";
      case "NotFoundError":case "DevicesNotFoundError":
        return "Камера или микрофон не найдены.";
      case "NotReadableError":case "TrackStartError":case "AbortError":
        return "Не удалось открыть камеру или микрофон. Проверьте, не заняты ли они другой программой, и повторите.";
      case "OverconstrainedError":
        return "Камера не поддерживает запрошенные параметры. Попробуйте другую камеру.";
      default:return error?.message||"Не удалось открыть камеру.";
    }
  }
  async function getCamera() {
    const audio={echoCancellation:true,noiseSuppression:true,autoGainControl:true};
    try {
      return await navigator.mediaDevices.getUserMedia({video:{
        facingMode:{ideal:facing},width:{ideal:480},height:{ideal:480},
        aspectRatio:{ideal:1},frameRate:{ideal:24,max:30},
      },audio});
    } catch(error) {
      // Some drivers and mobile browsers reject otherwise advisory constraints.
      if(!["OverconstrainedError","ConstraintNotSatisfiedError","TypeError"].includes(error?.name))throw error;
      return navigator.mediaDevices.getUserMedia({video:{facingMode:{ideal:facing}},audio:true});
    }
  }
  async function openCamera() {
    const token=++generation;
    clearTimeout(openingTimer);
    stopTracks(source);source=null;pending=null;clearPreview();
    ui("opening","Разрешите доступ к камере и микрофону. Можно отпустить кнопку.");
    openingTimer=setTimeout(()=>{
      if(token===generation&&state==="opening")fail("Камера не ответила. Проверьте разрешения и нажмите «Повторить».");
    },CAMERA_TIMEOUT);
    try {
      if(!window.isSecureContext||!navigator.mediaDevices?.getUserMedia||!window.MediaRecorder)
        throw new Error("Запись требует HTTPS, камеры и браузера с поддержкой MediaRecorder.");
      const stream=await getCamera();
      if(token!==generation||!isOpen()){stopTracks(stream);return;}
      if(document.hidden){stopTracks(stream);fail("Вернитесь на вкладку и нажмите «Повторить».");return;}
      if(!stream.getVideoTracks().some(track=>track.readyState==="live")||
         !stream.getAudioTracks().some(track=>track.readyState==="live")){
        stopTracks(stream);throw new Error("Для кружка нужны работающие камера и микрофон.");
      }
      clearTimeout(openingTimer);openingTimer=0;source=stream;
      preview.autoplay=true;preview.muted=true;preview.srcObject=source;
      preview.classList.toggle("is-mirrored",facing==="user");
      // Preview playback is not a prerequisite for native recording. A rejected
      // play() or delayed metadata event must not stall the entire UI.
      try {
        const playing=preview.play();
        playing?.catch(()=>{if(token===generation&&state==="ready")
          status.textContent="Предпросмотр не запустился. Нажмите «Записать» или смените камеру.";});
      } catch(_) {}
      for(const track of stream.getTracks())track.addEventListener("ended",()=>{
        if(token!==generation||source!==stream)return;
        if(state==="recording")finish(false);
        else if(state==="ready")fail("Камера или микрофон отключились. Нажмите «Повторить».");
      });
      ui("ready","Камера готова. Нажмите «Записать».");
      if(holdMode)begin();
    } catch(error) {
      if(token===generation)fail(cameraError(error));
    }
  }
  function recorderTypes() {
    // Prefer portable WebM/Opus on Chromium/Firefox; Safari can select MP4.
    const options=["video/webm;codecs=vp8,opus","video/webm",
      "video/webm;codecs=vp9,opus","video/mp4;codecs=avc1.42E01E,mp4a.40.2","video/mp4"];
    const supported=options.filter(type=>{
      try{return !MediaRecorder.isTypeSupported||MediaRecorder.isTypeSupported(type);}catch(_){return false;}
    });
    return [...supported,""];
  }
  function finish(sendImmediately=false) {
    const current=session;
    if(!current||state!=="recording")return;
    current.autoSend=sendImmediately===true;
    current.duration=Math.min(MAX_MS,Math.max(0,Math.round(performance.now()-current.started)));
    clearInterval(current.timer);clearTimeout(current.deadline);
    ui("stopping","Подготовка записи…");
    current.stopTimer=setTimeout(()=>{
      if(session===current)fail("Браузер не завершил запись. Попробуйте ещё раз.");
    },STOP_TIMEOUT);
    try {
      if(current.recorder.state!=="inactive")current.recorder.stop();
    } catch(_) {fail("Не удалось завершить запись. Попробуйте ещё раз.");}
  }
  async function containerType(blob) {
    const header=new Uint8Array(await blob.slice(0,16).arrayBuffer());
    if(header.length>=4&&header[0]===0x1a&&header[1]===0x45&&header[2]===0xdf&&header[3]===0xa3)return "video/webm";
    if(header.length>=12&&String.fromCharCode(...header.slice(4,8))==="ftyp")return "video/mp4";
    return "";
  }
  async function prepareReview(current) {
    if(session!==current)return;
    releaseRecording(current);
    // Browser may stop itself (device lost). Still calculate the elapsed time.
    const duration=current.duration||Math.min(MAX_MS,Math.max(0,Math.round(performance.now()-current.started)));
    session=null;stopTracks(source);source=null;clearPreview();
    holdMode=false;holdLocked=false;
    const token=generation;
    const raw=new Blob(current.chunks);
    if(duration<MIN_MS||!raw.size||raw.size>MAX_BYTES){
      fail(raw.size>MAX_BYTES?"Запись превышает 25 МиБ.":raw.size?"Запись слишком короткая.":"Камера не передала ни одного фрагмента записи.");
      return;
    }
    ui("checking","Проверка записанного видео…");
    let type;
    try{type=await containerType(raw);}catch(_){type="";}
    if(token!==generation||!isOpen())return;
    if(!type){fail("Полученный файл не является поддерживаемым WebM или MP4. Попробуйте снова.");return;}
    const blob=new Blob([raw],{type});
    const item={blob,duration,filename:"video-note-"+Date.now()+(type==="video/mp4"?".mp4":".webm"),data:null,verified:false};
    pending=item;objectUrl=URL.createObjectURL(blob);
    preview.preload="auto";preview.autoplay=false;preview.controls=true;preview.muted=false;silent.checked=false;
    // Validate that the browser can actually decode a video track, not just
    // that MediaRecorder returned a nonempty audio-only or invalid container.
    let timer=0, settled=false;
    const cleanup=()=>{
      clearTimeout(timer);
      for(const name of ["loadeddata","canplay","playing"])preview.removeEventListener(name,decoded);
      preview.removeEventListener("error",invalid);
      if(reviewCleanup===cleanup)reviewCleanup=null;
    };
    const decoded=()=>{
      if(token!==generation||pending!==item){cleanup();return;}
      if(preview.readyState<2||!preview.videoWidth||!preview.videoHeight)return;
      if(settled)return;settled=true;cleanup();
      item.verified=true;
      ui("review","Запись готова. Можно посмотреть или отправить.");
      if(current.autoSend)void upload();
    };
    const invalid=()=>{
      if(settled)return;settled=true;cleanup();
      if(token===generation&&pending===item)fail("Не удалось декодировать записанное видео. Запишите кружок заново.");
    };
    reviewCleanup=cleanup;
    for(const name of ["loadeddata","canplay","playing"])preview.addEventListener(name,decoded);
    preview.addEventListener("error",invalid);
    timer=setTimeout(()=>{
      if(token!==generation||pending!==item){cleanup();return;}
      // Mobile data-saving modes may defer preload until the user presses play.
      // Keep the recording and let the user trigger decoding, never auto-send
      // a video that has not been verified.
      current.autoSend=false;
      ui("review","Нажмите ▶ на предпросмотре, чтобы проверить видео, или перезапишите его.");
    },DECODE_TIMEOUT);
    preview.src=objectUrl;preview.load();decoded();
  }
  function begin() {
    if(state!=="ready"||!source)return;
    if(!source.getVideoTracks().some(track=>track.readyState==="live")){
      fail("Камера отключилась. Нажмите «Повторить».");return;
    }
    // Record the camera stream directly. Canvas capture + requestAnimationFrame
    // can produce black/empty frames on real GPUs and mobile browsers.
    // The circular player still crops the center of the original video.
    let lastError=null;
    for(const mime of recorderTypes()){
      for(const withBitrate of [true,false]){
        let recorder=null,current=null;
        try{
          const options={...(mime?{mimeType:mime}:{}),...(withBitrate?{videoBitsPerSecond:1400000,audioBitsPerSecond:64000}:{})};
          recorder=new MediaRecorder(source,options);
          current={recorder,chunks:[],bytes:0,started:performance.now(),duration:0,timer:0,deadline:0,stopTimer:0,autoSend:false};
          session=current;
          recorder.addEventListener("dataavailable",event=>{
            if(session!==current||!event.data?.size)return;
            current.chunks.push(event.data);current.bytes+=event.data.size;
            if(current.bytes>MAX_BYTES&&state==="recording")finish(false);
          });
          recorder.addEventListener("error",()=>{
            if(session===current)fail("Ошибка кодирования видео. Проверьте камеру и повторите.");
          });
          recorder.addEventListener("stop",()=>{void prepareReview(current);},{once:true});
          recorder.start(250);current.started=performance.now();
          elapsed.textContent="0:00";ui("recording",holdLocked?"Запись зафиксирована":"Идёт запись…");
          current.timer=setInterval(()=>{elapsed.textContent=time(Math.min(MAX_MS,performance.now()-current.started)/1000);},100);
          current.deadline=setTimeout(()=>finish(false),MAX_MS);
          return;
        }catch(error){
          lastError=error;session=null;
          releaseRecording(current);
          if(recorder&&recorder.state!=="inactive"){try{recorder.stop();}catch(_){}}
        }
      }
    }
    fail("Не удалось запустить видеокодек"+(lastError?.name?" ("+lastError.name+")":"")+". Попробуйте другой браузер или камеру.");
  }
  async function upload() {
    if(state!=="review"||!pending?.verified)return;
    const item=pending,token=generation;
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
    const controller=new AbortController();uploadController=controller;
    const deadline=setTimeout(()=>controller.abort(),90000);
    try {
      const response=await window.SovietgramSendRetry.fetchSend(form.action,{
        method:"POST",credentials:"same-origin",headers:{"X-Requested-With":"XMLHttpRequest"},
        body:item.data,signal:controller.signal,
      });
      const result=await response.json().catch(()=>({}));
      if(token!==generation||pending!==item)return;
      if(!response.ok||!result.ok||!result.message)
        throw new Error(result.error||Object.values(result.errors||{}).flat()[0]?.message||"Не удалось отправить запись.");
      if(($("replyToInput")?.value||"")===(item.data.get("reply_to")||"")&&
         (window.SovietgramChat?.currentQuote?.()||"")===(item.data.get("reply_quote")||""))
        window.SovietgramChat?.clearReplyState?.();
      if(!window.SovietgramChat?.acceptSentMessage?.(result.message))window.SovietgramChat?.syncNow?.();
      closeRecorder();notify("Видеокружок отправлен.");
    } catch(error) {
      if(token===generation&&pending===item)ui("review",
        (controller.signal.aborted?"Отправка прервана или сервер не ответил.":error.message||"Ошибка отправки.")+
        " Запись сохранена для повтора без дублирования.");
    } finally {clearTimeout(deadline);if(uploadController===controller)uploadController=null;}
  }
  function openRecorder(held=false) {
    if(isOpen())return false;
    if(window.SovietgramVoice?.isRecording?.()||($("voiceRecordingBar")&&!$("voiceRecordingBar").hidden)){
      notify("Сначала завершите голосовую запись.");return false;
    }
    restoreFocus=document.activeElement;
    holdMode=held;holdLocked=false;facing="user";
    gestureHint.textContent="‹ Сдвиньте влево для отмены";
    dialog.hidden=false;
    // Do not steal focus or pointer capture during a live hold.
    if(!held)close.focus({preventScroll:true});
    void openCamera();return true;
  }
  function stopOrCancel() {
    if(state==="sending"){
      // A server may already have committed the upload. Preserve its UUID
      // and the recording when the user interrupts the wait.
      uploadController?.abort();return;
    }
    if(pending&&!window.confirm("Удалить записанный кружок?"))return;
    closeRecorder();
  }
  Object.assign(window.SovietgramVideoNotes,{
    openPreview:()=>openRecorder(false),startHold:()=>openRecorder(true),
    moveHold:(cancelProgress,lockProgress)=>{
      if(!holdMode||holdLocked||!isOpen())return;
      dialog.style.setProperty("--note-cancel-progress",String(cancelProgress));
      dialog.style.setProperty("--note-lock-progress",String(lockProgress));
      gestureHint.textContent=cancelProgress>.5?"Отмена записи":lockProgress>.5?"Фиксация записи":"‹ Сдвиньте влево для отмены";
    },
    lockHold:()=>{
      if(!holdMode||!isOpen())return;
      holdLocked=true;ui(state,state==="opening"?"Подключение камеры… Запись зафиксирована.":"Запись зафиксирована");
    },
    cancelHold:()=>{if(holdMode&&isOpen()&&state!=="sending")closeRecorder();},
    // Browser permission prompts and touch pointer interruptions must not
    // discard the recorder. Finish into preview, never send on interruption.
    interruptHold:()=>{
      if(!holdMode||holdLocked||!isOpen())return;
      if(state==="recording")finish(false);
      else if(["opening","ready"].includes(state))manualMode("Подключите камеру, затем нажмите «Записать».");
    },
    releaseHold:()=>{
      if(!holdMode||holdLocked||!isOpen())return;
      if(state==="recording")finish(true);
      else if(["opening","ready"].includes(state))manualMode("Подключите камеру, затем нажмите «Записать».");
    },
  });
  document.addEventListener("click",event=>{
    if(!event.target.closest?.("[data-open-video-note]")||isOpen())return;
    event.preventDefault();window.SovietgramAttachmentMenu?.close();openRecorder(false);
  });
  start.addEventListener("click",()=>{holdMode=false;holdLocked=true;begin();});
  stop.addEventListener("click",()=>finish(false));
  close.addEventListener("click",stopOrCancel);
  retry.addEventListener("click",()=>{holdMode=false;holdLocked=false;void openCamera();});
  camera.addEventListener("click",()=>{
    if(!["ready","error"].includes(state))return;
    holdMode=false;holdLocked=false;facing=facing==="user"?"environment":"user";void openCamera();
  });
  retake.addEventListener("click",()=>{
    if(["review","checking"].includes(state)&&window.confirm("Удалить текущую запись и записать новую?")){
      holdMode=false;holdLocked=false;void openCamera();
    }
  });
  send.addEventListener("click",()=>{if(state==="recording")finish(true);else void upload();});
  document.addEventListener("keydown",event=>{
    if(!isOpen())return;
    if(event.key==="Escape"){event.preventDefault();stopOrCancel();}
    if(event.key==="Tab"){
      const focusable=[...dialog.querySelectorAll("button,input,video[controls]")].filter(node=>!node.disabled&&node.getClientRects().length);
      if(!focusable.length)return;
      const first=focusable[0],last=focusable[focusable.length-1];
      if(!dialog.contains(document.activeElement)||event.shiftKey&&document.activeElement===first||!event.shiftKey&&document.activeElement===last){
        event.preventDefault();(event.shiftKey?last:first).focus();
      }
    }
  },true);
  document.addEventListener("visibilitychange",()=>{
    if(!document.hidden||!isOpen())return;
    if(state==="recording")finish(false);
    else if(state==="opening"){
      // An OS permission prompt may momentarily hide the document.
      // Keep the permission request alive; late streams are checked above.
      manualMode("Ожидание разрешения камеры и микрофона…");
    }else if(state==="ready")fail("Камера отключена в фоновой вкладке. Нажмите «Повторить».");
  });
  window.addEventListener("pagehide",()=>{uploadController?.abort();if(isOpen())reset();dialog.hidden=true;});
})();
