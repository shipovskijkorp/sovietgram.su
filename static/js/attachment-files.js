(() => {
  const conversation = document.querySelector(".conversation--chat");
  const form = document.getElementById("messageForm");
  if (!conversation || !form) return;

  const inputs = {
    media: document.getElementById("mediaAttachmentsInput"),
    file: document.getElementById("fileAttachmentsInput"),
    audio: document.getElementById("audioAttachmentsInput"),
  };
  const modeInput = document.getElementById("attachmentModeInput");
  const backdrop = document.getElementById("mediaComposeBackdrop");
  const closeButton = document.getElementById("mediaComposeClose");
  const addButton = document.getElementById("mediaComposeAdd");
  const titleNode = document.getElementById("mediaComposeTitle");
  const summaryNode = document.getElementById("mediaComposeSummary");
  const previewNode = document.getElementById("mediaComposePreview");
  const captionNode = document.getElementById("mediaComposeCaption");
  const hintNode = document.getElementById("mediaComposeHint");
  const sendButton = document.getElementById("mediaComposeSend");
  const groupRow = document.getElementById("mediaComposeGroupRow");
  const groupToggle = document.getElementById("mediaComposeGroup");
  const silentToggle = document.getElementById("mediaComposeSilent");
  const compressToggle = document.getElementById("mediaComposeCompress");
  const compressRow = document.getElementById("mediaComposeCompressRow");
  const spoilerRow = document.getElementById("mediaComposeSpoilerRow");
  const spoilerToggle = document.getElementById("mediaComposeSpoiler");
  const scheduleToggle = document.getElementById("mediaComposeSchedule"), scheduleDate = document.getElementById("mediaComposeDate");
  const scheduleDateRow = document.getElementById("mediaComposeDateRow");
  const scheduleEndpoint = document.getElementById("messageStage")?.dataset.scheduledUrl;
  const abortButton = document.getElementById("mediaComposeAbort");
  const dropOverlay = document.getElementById("chatDropOverlay");
  const accountId = document.getElementById("messageStage")?.dataset.accountId || document.body.dataset.accountId || "";
  const progressNode = document.getElementById("mediaUploadProgress");
  const progressBar = document.getElementById("mediaUploadProgressBar");
  const messageInput = document.getElementById("messageInput");
  const replyInput = document.getElementById("replyToInput");
  const composerReply = document.getElementById("composerReply");
  const csrfToken = form.querySelector("[name='csrfmiddlewaretoken']")?.value || "";

  const MAX_ATTACHMENTS = 10;
  const FILE_MIB = Number(form.dataset.maxFileMib) || 25;
  const TOTAL_MIB = Number(form.dataset.maxTotalMib) || 100;
  const MAX_FILE_SIZE = FILE_MIB * 1024 * 1024;
  const MAX_TOTAL_SIZE = TOTAL_MIB * 1024 * 1024;
  const MEDIA_EXTENSIONS = new Set(["png","jpg","jpeg","webp","gif","mp4","webm","mov","m4v"]);
  const AUDIO_EXTENSIONS = new Set(["mp3","m4a","aac","ogg","oga","wav","flac","opus"]);

  let selectedFiles = [];
  let selectedMode = "media";
  let appendNextPick = false;
  let objectUrls = [];
  let busy = false, activeUpload = null, cancelled = false, dragDepth = 0;
  let retryPlan = null;
  let editingPhoto = false;
  const sendKeys = window.SovietgramSendRetry.batch();
  const draftRow = document.getElementById("mediaDraftRow"), draftSummary = document.getElementById("mediaDraftSummary");
  const draftStatus = document.getElementById("mediaDraftStatus"), draftResume = document.getElementById("mediaDraftResume");
  const draftDiscard = document.getElementById("mediaDraftDiscard"), draftReplyRow = document.getElementById("mediaDraftReply");
  const draftReplyText = document.getElementById("mediaDraftReplyText"), draftRemoveReply = document.getElementById("mediaDraftRemoveReply");
  let draftReply = "", draftQuote = "", draftOriginalText = "";
  let store = null, revision = null, writeQueue = Promise.resolve(), saveTimer = null;
  let storageProblem = "", conflict = false, volatile = false, corrupt = false, discarding = false;
  let pendingWrites = 0, planWasPersisted = false;

  function notify(text) {
    if (typeof window.showToast === "function") window.showToast(text);
    else if (typeof showToast === "function") showToast(text);
  }

  function updateDraftUI(){
    const exists=selectedFiles.length>0||corrupt;
    if(draftRow)draftRow.hidden=!exists||!backdrop?.hidden;
    if(draftSummary)draftSummary.textContent=corrupt?"Повреждённый локальный черновик":
      retryPlan?"Незавершённая отправка · "+retryPlan.completed+" / "+retryPlan.batches.length:
      "Черновик · "+pluralFiles(selectedFiles.length)+(storageProblem?" · только в этой вкладке":"");
    if(draftResume){
      draftResume.disabled=busy||discarding||corrupt;
      draftResume.textContent=retryPlan?"Продолжить":"Открыть";
    }
    if(draftDiscard)draftDiscard.disabled=busy||discarding||conflict;
    if(draftReplyRow)draftReplyRow.hidden=!draftReply;
    if(draftReplyText)draftReplyText.textContent="Ответ на сообщение № "+draftReply+(draftQuote?" · с цитатой":"");
    if(draftRemoveReply)draftRemoveReply.disabled=busy||Boolean(retryPlan);
    if(draftStatus)draftStatus.textContent=storageProblem||(
      revision&&!pendingWrites&&!saveTimer?"Сохранено в этом браузере на 7 дней.":"Сохранение локального черновика…");
  }
  function snapshot(){
    return {version:1,files:[...selectedFiles],mode:selectedMode,caption:captionNode?.value||"",
      group:groupToggle?.checked!==false,silent:Boolean(silentToggle?.checked),
      compress:Boolean(compressToggle?.checked),spoiler:Boolean(spoilerToggle?.checked),
      reply:draftReply,quote:draftQuote,originalDraft:draftOriginalText,
      schedule:Boolean(scheduleToggle?.checked),scheduleDate:scheduleDate?.value||"",
      plan:retryPlan?{...retryPlan,batches:retryPlan.batches.map(b=>({...b,files:[...b.files]}))}:null};
  }
  function persistenceError(error){
    storageProblem=error?.message||"Не удалось сохранить черновик.";
    if(error?.conflict)conflict=true;
    updateDraftUI();
  }
  function persistCurrent(){
    clearTimeout(saveTimer);saveTimer=null;
    if(!selectedFiles.length||corrupt||discarding)return Promise.resolve(false);
    const data=snapshot();
    pendingWrites++;updateDraftUI();
    const operation=writeQueue.then(async()=>{
      if(conflict||volatile||!store)return false;
      try{
        revision=await store.write(revision,data);
        if(data.plan)planWasPersisted=true;
        storageProblem="";return true;
      }catch(e){persistenceError(e);return false;}
    }).finally(()=>{pendingWrites--;updateDraftUI();});
    writeQueue=operation.catch(()=>false);
    return operation;
  }
  function schedulePersist(){
    if(!selectedFiles.length||retryPlan||corrupt)return;
    clearTimeout(saveTimer);
    saveTimer=setTimeout(()=>void persistCurrent(),150);
    updateDraftUI();
  }
  async function clearStored(){
    clearTimeout(saveTimer);saveTimer=null;
    await writeQueue;
    if(conflict)return false;
    if(!store)return revision===null;
    try{revision=await store.remove(revision);storageProblem="";return true;}
    catch(e){persistenceError(e);return false;}
  }
  function resetComposer(){
    retryPlan=null;selectedFiles=[];appendNextPick=false;corrupt=false;planWasPersisted=false;
    draftReply=draftQuote=draftOriginalText="";
    releaseUrls();sendKeys.clear();
    if(backdrop)backdrop.hidden=true;
    if(captionNode)captionNode.value="";
    setProgress(false,0);updateDraftUI();
  }
  function restore(data){
    selectedFiles=data.files;selectedMode=data.mode;retryPlan=data.plan||null;planWasPersisted=Boolean(retryPlan);
    draftReply=data.reply;draftQuote=data.quote;draftOriginalText=data.originalDraft;
    if(modeInput)modeInput.value=selectedMode;
    if(captionNode)captionNode.value=data.caption;
    if(groupToggle)groupToggle.checked=data.group!==false;
    if(silentToggle)silentToggle.checked=Boolean(data.silent);
    if(compressToggle)compressToggle.checked=Boolean(data.compress);
    if(spoilerToggle)spoilerToggle.checked=Boolean(data.spoiler);
    if(scheduleToggle)scheduleToggle.checked=Boolean(data.schedule||retryPlan?.scheduledFor);
    if(scheduleDate)scheduleDate.value=data.scheduleDate||"";
    syncSchedule();
    updateDraftUI();
  }
  const initDraft=(async()=>{
    try{
      store=await window.SovietgramMediaDrafts.create(accountId+":"+conversation.dataset.chatId);
      const record=await store.load();
      if(record){
        revision=record.revision;
        if(!window.SovietgramMediaDrafts.valid(record.data)){
          corrupt=true;storageProblem="Не удалось прочитать черновик. Его можно удалить.";return;
        }
        restore(record.data);
      }
    }catch(e){store=null;persistenceError(e);}
    finally{if(draftRow)draftRow.dataset.ready="true";updateDraftUI();}
  })();
  function resumeDraft(){
    if(!selectedFiles.length||busy||discarding||corrupt)return;
    renderSelection();resizeCaption();setProgress(false,0);
    if(retryPlan&&sendButton)sendButton.textContent="Продолжить отправку";
    if(backdrop)backdrop.hidden=false;
    updateDraftUI();
    if(!retryPlan)captionNode?.focus();
  }
  async function discardDraft(confirmFirst=true){
    if(busy||editingPhoto||discarding)return;
    if(confirmFirst&&!window.confirm(retryPlan?
      "Удалить незавершённую отправку? Уже принятые сервером файлы останутся в переписке.":
      "Удалить черновик вложений с этого устройства?"))return;
    discarding=true;updateDraftUI();
    try{
      if(!await clearStored()){notify(storageProblem||"Не удалось удалить черновик.");return;}
      resetComposer();
      volatile=false;
    }finally{discarding=false;updateDraftUI();}
  }
  draftResume?.addEventListener("click",resumeDraft);
  draftDiscard?.addEventListener("click",()=>void discardDraft());
  draftRemoveReply?.addEventListener("click",()=>{
    if(busy||retryPlan)return;
    draftReply=draftQuote="";updateDraftUI();void persistCurrent();
  });
  for(const toggle of [groupToggle,silentToggle,compressToggle,spoilerToggle])
    toggle?.addEventListener("change",()=>void persistCurrent());
  function syncSchedule(){
    if(!scheduleToggle||!scheduleDate)return;
    const enabled=scheduleToggle.checked;
    scheduleDateRow.hidden=!enabled;
    scheduleDate.disabled=!enabled||busy||Boolean(retryPlan);
    const api=window.SovietgramSchedule;
    if(enabled&&api&&!retryPlan){
      scheduleDate.min=api.localDateValue(Date.now()+60000);
      scheduleDate.max=api.localDateValue(Date.now()+365*86400000-60000);
      if(!scheduleDate.value)scheduleDate.value=api.localDateValue(Date.now()+300000);
    }
    if(!busy&&!retryPlan&&sendButton)sendButton.textContent=enabled?"Запланировать":"Отправить";
  }
  scheduleToggle?.addEventListener("change",()=>{syncSchedule();void persistCurrent();});
  scheduleDate?.addEventListener("input",schedulePersist);
  scheduleDate?.addEventListener("change",()=>void persistCurrent());
  captionNode?.addEventListener("input",schedulePersist);
  document.addEventListener("visibilitychange",()=>{
    if(document.hidden&&saveTimer&&!retryPlan)void persistCurrent();
  });
  window.addEventListener("pagehide",()=>{
    if(saveTimer&&!retryPlan&&!corrupt)void persistCurrent();
  });
  function extension(file) {
    const name = (file?.name || "").toLowerCase();
    const index = name.lastIndexOf(".");
    return index >= 0 ? name.slice(index + 1) : "";
  }

  function isMedia(file) {
    const ext = extension(file);
    const type = (file.type || "").toLowerCase();
    return MEDIA_EXTENSIONS.has(ext) && (
      type.startsWith("image/")
      || type.startsWith("video/")
      || (!type && MEDIA_EXTENSIONS.has(ext))
    );
  }

  function isAudio(file) {
    const ext = extension(file);
    const type = (file.type || "").toLowerCase();
    return AUDIO_EXTENSIONS.has(ext) && (type.startsWith("audio/") || !type);
  }

  function formatBytes(bytes) {
    if (!bytes) return "0 Б";
    if (bytes < 1024) return bytes + " Б";
    if (bytes < 1024 * 1024) return Math.round(bytes / 1024) + " КБ";
    return (bytes / (1024 * 1024)).toFixed(1) + " МБ";
  }

  function pluralFiles(count) {
    if (count % 10 === 1 && count % 100 !== 11) return count + " файл";
    if ([2,3,4].includes(count % 10) && ![12,13,14].includes(count % 100)) return count + " файла";
    return count + " файлов";
  }

  function validate(files, mode) {
    if (!files.length) return "Файлы не выбраны.";
    if (files.length > MAX_ATTACHMENTS) return "Можно отправить не больше 10 файлов за раз.";

    let total = 0;
    for (const file of files) {
      if (mode === "media" && !isMedia(file)) {
        return "Для «Фото или видео» выберите PNG, JPEG, WebP, GIF, MP4, WebM, MOV или M4V.";
      }
      if (mode === "audio" && !isAudio(file)) {
        return "Для «Музыка» выберите MP3, M4A, AAC, OGG, WAV, FLAC или OPUS.";
      }
      if (file.size > MAX_FILE_SIZE) return file.name + ": файл больше " + FILE_MIB + " МБ.";
      total += file.size;
    }
    if (total > MAX_TOTAL_SIZE) return "Общий размер файлов больше " + TOTAL_MIB + " МБ.";
    return "";
  }

  function releaseUrls() {
    objectUrls.forEach((url) => URL.revokeObjectURL(url));
    objectUrls = [];
  }

  function setProgress(active, percent = 0) {
    busy = active;
    if (sendButton) {
      sendButton.disabled = active;
      sendButton.textContent = active ? "Отправка…" : "Отправить";
    }
    if (addButton) addButton.disabled = active;
    if (closeButton) closeButton.disabled = active;
    if (silentToggle) silentToggle.disabled = active || Boolean(retryPlan);
    if (compressToggle) compressToggle.disabled = active || Boolean(retryPlan);
    if (spoilerToggle) spoilerToggle.disabled = active || Boolean(retryPlan);
    if (scheduleToggle) scheduleToggle.disabled = active || Boolean(retryPlan);
    syncSchedule();
    if (groupToggle) groupToggle.disabled = active || Boolean(retryPlan);
    if (captionNode) captionNode.readOnly = active || Boolean(retryPlan);
    if (addButton) addButton.disabled = active || Boolean(retryPlan);
    if (abortButton) abortButton.hidden = !active;
    for (const button of previewNode?.querySelectorAll(".media-preview-remove, .media-preview-edit") || []) button.disabled = active || Boolean(retryPlan);
    if (progressNode) progressNode.hidden = !active;
    if (progressBar) progressBar.style.width = Math.max(0, Math.min(100, percent)) + "%";
  }

  function closeComposer() {
    if (busy || editingPhoto || discarding) return;
    if (backdrop) backdrop.hidden = true;
    releaseUrls();
    appendNextPick = false;
    updateDraftUI();
    if (saveTimer) void persistCurrent();
  }

  function removeFile(index) {
    if (busy || retryPlan || editingPhoto) return;
    if (selectedFiles.length === 1) { void discardDraft(false); return; }
    selectedFiles.splice(index, 1);
    renderSelection();
    updateDraftUI();void persistCurrent();
  }

  async function editPhoto(index) {
    if (busy || retryPlan || editingPhoto || !window.SovietgramPhotoEditor?.edit) return;
    const original = selectedFiles[index];
    if (!original) return;
    editingPhoto = true;
    try {
      const result = await window.SovietgramPhotoEditor.edit(original);
      if (!result || selectedFiles[index] !== original) return;
      const next = [...selectedFiles]; next[index] = result;
      const issue = validate(next, selectedMode);
      if (issue) { notify(issue); return; }
      selectedFiles = next;
      sendKeys.clear();
      renderSelection();
      updateDraftUI();void persistCurrent();
    } catch (e) { notify(e.message || "Не удалось открыть редактор."); }
    finally { editingPhoto = false; }
  }

  function renderSelection() {
    if (!previewNode) return;
    releaseUrls();
    previewNode.replaceChildren();

    const total = selectedFiles.reduce((sum, file) => sum + file.size, 0);
    if (summaryNode) summaryNode.textContent = pluralFiles(selectedFiles.length) + " · " + formatBytes(total);

    if (titleNode) {
      if (selectedMode === "media") {
        titleNode.textContent = selectedFiles.length > 1
          ? "Отправить медиа"
          : ((selectedFiles[0]?.type || "").startsWith("video/") ? "Отправить видео" : "Отправить фото");
      } else if (selectedMode === "audio") {
        titleNode.textContent = selectedFiles.length > 1 ? "Отправить музыку" : "Отправить трек";
      } else {
        titleNode.textContent = selectedFiles.length > 1 ? "Отправить файлы" : "Отправить файл";
      }
    }

    if (hintNode) {
      hintNode.textContent = selectedMode === "media"
        ? "Фото, GIF и видео будут показаны прямо в переписке."
        : selectedMode === "audio"
          ? "Музыка будет отправлена со встроенным проигрывателем."
          : "Документы будут отправлены без обработки.";
    }

    if (groupRow) groupRow.hidden = selectedMode !== "media" || selectedFiles.length < 2;
    if (spoilerRow) spoilerRow.hidden = selectedMode !== "media";
    if (compressRow) compressRow.hidden = selectedMode !== "media" || !selectedFiles.some(file => ["jpg","jpeg","png","webp"].includes(extension(file)));

    if (selectedMode === "media") {
      const grid = document.createElement("div");
      grid.className = "media-preview-grid";
      grid.dataset.count = String(selectedFiles.length);

      selectedFiles.forEach((file, index) => {
        const card = document.createElement("div");
        card.className = "media-preview-card";
        const url = URL.createObjectURL(file);
        objectUrls.push(url);

        if ((file.type || "").startsWith("video/") || ["mp4","webm","mov","m4v"].includes(extension(file))) {
          const video = document.createElement("video");
          video.src = url;
          video.muted = true;
          video.playsInline = true;
          video.preload = "metadata";
          card.appendChild(video);

          const badge = document.createElement("span");
          badge.className = "media-preview-video-badge";
          badge.textContent = "▶ Видео";
          card.appendChild(badge);
        } else {
          const image = document.createElement("img");
          image.src = url;
          image.alt = file.name;
          card.appendChild(image);
        }

        if (window.SovietgramPhotoEditor?.canEdit(file)) {
          const edit = document.createElement("button");
          edit.type = "button"; edit.className = "media-preview-edit";
          edit.textContent = "✎"; edit.title = "Редактировать фото";
          edit.setAttribute("aria-label", "Редактировать фото");
          edit.disabled = busy || Boolean(retryPlan);
          edit.addEventListener("click", () => void editPhoto(index));
          card.appendChild(edit);
        }
        const remove = document.createElement("button");
        remove.type = "button";
        remove.className = "media-preview-remove";
        remove.setAttribute("aria-label", "Убрать файл");
        remove.textContent = "×";
        remove.addEventListener("click", () => removeFile(index));
        card.appendChild(remove);
        grid.appendChild(card);
      });

      previewNode.appendChild(grid);
      return;
    }

    const list = document.createElement("div");
    list.className = "media-preview-files";
    selectedFiles.forEach((file, index) => {
      const row = document.createElement("div");
      row.className = "media-preview-file";

      const icon = document.createElement("span");
      icon.className = "media-preview-file__icon";
      icon.textContent = selectedMode === "audio" ? "♪" : "⌑";

      const copy = document.createElement("span");
      copy.className = "media-preview-file__text";
      const name = document.createElement("strong");
      name.textContent = file.name;
      const meta = document.createElement("small");
      meta.textContent = formatBytes(file.size);
      copy.append(name, meta);

      const remove = document.createElement("button");
      remove.type = "button";
      remove.className = "media-preview-remove";
      remove.setAttribute("aria-label", "Убрать файл");
      remove.textContent = "×";
      remove.addEventListener("click", () => removeFile(index));

      row.append(icon, copy, remove);
      list.appendChild(row);
    });
    previewNode.appendChild(list);
  }

  async function openComposer(files, mode, preserveCaption = false) {
    await initDraft;
    if (busy || retryPlan || editingPhoto || discarding || corrupt || conflict) {
      notify("Сначала завершите или отмените текущую отправку файлов.");
      return;
    }
    if (conversation.dataset.canSendMedia === "false") {
      notify("Администраторы запретили отправлять медиа и файлы.");
      return;
    }

    const error = validate(files, mode);
    if (error) {
      notify(error);
      return;
    }

    if (selectedFiles.length && !preserveCaption && !window.confirm("Заменить существующий черновик вложений?")) return;
    const previousCaption = captionNode?.value || "";
    if (!preserveCaption) {
      draftReply=replyInput?.value||"";
      draftQuote=draftReply?window.SovietgramChat?.currentQuote?.()||"":"";
      draftOriginalText=messageInput?.value||"";
    }
    selectedFiles = files;
    selectedMode = mode;
    if (modeInput) modeInput.value = mode;
    if (groupToggle && !preserveCaption) groupToggle.checked = true;
    if (silentToggle && !preserveCaption) silentToggle.checked = false;
    if (compressToggle && !preserveCaption) compressToggle.checked = false;
    if (spoilerToggle && !preserveCaption) spoilerToggle.checked = false;
    if (!preserveCaption && scheduleToggle) {scheduleToggle.checked=false;scheduleDate.value="";}
    syncSchedule();
    if (captionNode) {
      captionNode.value = preserveCaption
        ? previousCaption
        : (messageInput?.value || "");
    }
    renderSelection();
    resizeCaption();
    if (progressNode) progressNode.hidden = true;
    if (progressBar) progressBar.style.width = "0%";
    if (backdrop) backdrop.hidden = false;
    updateDraftUI();void persistCurrent();
    window.setTimeout(() => captionNode?.focus(), 0);
    return true;
  }

  function pick(mode, append = false) {
    if (busy || editingPhoto || discarding || conflict || corrupt) return;
    if (selectedFiles.length && backdrop?.hidden) { resumeDraft(); return; }
    if (retryPlan) return;
    const input = inputs[mode];
    if (!input) {
      notify("Поле выбора файлов не найдено.");
      return;
    }

    appendNextPick = append;
    window.SovietgramAttachmentMenu?.close();

    try {
      if (typeof input.showPicker === "function") {
        input.showPicker();
      } else {
        input.click();
      }
    } catch (_error) {
      input.click();
    }
  }

  function onPicked(input, mode) {
    const files = [...(input.files || [])];
    input.value = "";
    if (!files.length) {
      appendNextPick = false;
      return;
    }

    const next = appendNextPick && selectedFiles.length && selectedMode === mode
      ? [...selectedFiles, ...files]
      : files;
    const preserveCaption = appendNextPick && backdrop && !backdrop.hidden;
    appendNextPick = false;
    openComposer(next, mode, preserveCaption);
  }

  function upload(files, text, mode, replyTo, onProgress, clientId, silent = false, attempt = 0, compress = false, quote = "", spoiler = false, scheduledFor = "") {
    return new Promise((resolve, reject) => {
      const data = new FormData();
      data.append("csrfmiddlewaretoken", csrfToken);
      data.append("text", text);
      data.append("attachment_mode", mode);
      data.append("client_message_id", clientId);
      data.append("account_id", accountId);
      data.append("preserve_draft", "1");
      if (compress) data.append("compress_images", "1");
      if (spoiler) data.append("media_spoiler", "1");
      if (scheduledFor) data.append("scheduled_for", scheduledFor);
      if (silent) data.append("silent", "1");
      if (replyTo) data.append("reply_to", replyTo);
      if (replyTo && quote) data.append("reply_quote", quote);
      files.forEach((file) => data.append("attachments", file, file.name));

      if (cancelled) { reject(new Error("Загрузка отменена.")); return; }
      const xhr = new XMLHttpRequest();
      activeUpload = xhr;
      xhr.open("POST", scheduledFor ? scheduleEndpoint : form.action);
      const uploadBytes = files.reduce((sum, file) => sum + file.size, 0);
      xhr.timeout = Math.max(180000, Math.ceil(uploadBytes / (128 * 1024)) * 1000 + 60000);
      xhr.setRequestHeader("X-Requested-With", "XMLHttpRequest");
      xhr.responseType = "json";

      xhr.upload.addEventListener("progress", (event) => {
        if (event.lengthComputable) onProgress(event.loaded, event.total);
      });

      xhr.addEventListener("load", () => {
        const payload = xhr.response || {};
        if (xhr.status >= 200 && xhr.status < 300 && payload.ok) {
          if (scheduledFor && (!payload.item || payload.item.status === "canceled")) {reject(new Error("Эта отложенная отправка уже отменена."));return;}
          resolve(payload);
          return;
        }
        if (!attempt && [502, 503, 504].includes(xhr.status)) {
          upload(files, text, mode, replyTo, onProgress, clientId, silent, 1, compress, quote, spoiler, scheduledFor).then(resolve, reject);
          return;
        }
        if (xhr.status === 413) {
          reject(new Error("Размер вложений превышает лимит веб-сервера."));
          return;
        }
        const firstError = Object.values(payload.errors || {}).flat()?.[0]?.message;
        reject(new Error(payload.error || firstError || "Не удалось отправить файлы."));
      });
      xhr.addEventListener("error", () => {
        if (!attempt) upload(files, text, mode, replyTo, onProgress, clientId, silent, 1, compress, quote, spoiler, scheduledFor).then(resolve, reject);
        else reject(new Error("Не удалось загрузить файлы. Повторите отправку."));
      });
      xhr.addEventListener("timeout", () => {
        if (!attempt && !cancelled) upload(files, text, mode, replyTo, onProgress, clientId, silent, 1, compress, quote, spoiler, scheduledFor).then(resolve, reject);
        else reject(new Error("Сервер не ответил вовремя. Можно повторить загрузку."));
      });
      xhr.addEventListener("abort", () => reject(new Error("Загрузка отменена. Сервер мог уже принять файл.")));
      xhr.addEventListener("loadend", () => { if (activeUpload === xhr) activeUpload = null; });
      xhr.send(data);
    });
  }

  function renderSent(message) {
    try {
      if (typeof window.renderSovietgramChatMessage === "function") window.renderSovietgramChatMessage(message);
      else void window.SovietgramChat?.syncNow?.();
    } catch (error) {
      // An acknowledged upload must not become a failed send because of DOM rendering.
      console.warn("Attachment sent; rendering failed", error);
      try { void window.SovietgramChat?.syncNow?.(); } catch (_) {}
    }
  }

  function buildPlan() {
    const files = [...selectedFiles];
    const caption = captionNode?.value || "";
    const replyTo = draftReply;
    const quote = draftQuote;
    const silent = Boolean(silentToggle?.checked);
    const compress = selectedMode === "media" && Boolean(compressToggle?.checked);
    const spoiler = selectedMode === "media" && Boolean(spoilerToggle?.checked);
    const scheduledFor = scheduleToggle?.checked ? window.SovietgramSchedule.toScheduledISO(scheduleDate.value) : "";
    if(scheduledFor&&!scheduleEndpoint)throw Error("Планирование недоступно.");
    const separate = selectedMode === "media" && files.length > 1 && groupToggle && !groupToggle.checked;
    const signature = [files.map(window.SovietgramSendRetry.fileIdentity), caption, selectedMode, replyTo, silent, compress, Boolean(separate)];
    if (quote) signature.push(quote);
    if (spoiler) signature.push("spoiler");
    if (scheduledFor) signature.push(["schedule",scheduledFor]);
    const batches = separate ? files.map((file, index) => ({
      files: [file], caption: index === files.length - 1 ? caption : "", reply: index === 0 ? replyTo : "",
      quote: index === 0 ? quote : "", id: sendKeys.key(index, signature),
    })) : [{files, caption, reply:replyTo, quote, id:sendKeys.key("album", signature)}];
    return {batches, mode:selectedMode, silent, compress, spoiler, scheduledFor, completed:0,
            originalDraft:draftOriginalText, originalReply:replyTo, originalQuote:quote};
  }

  async function sendSelected() {
    if (conflict) { notify(storageProblem); return; }
    if (!selectedFiles.length || busy || editingPhoto || discarding || corrupt) return;
    const error = validate(selectedFiles, selectedMode);
    if (error) { notify(error); return; }
    if(!retryPlan&&scheduleToggle?.checked){
      try{window.SovietgramSchedule.toScheduledISO(scheduleDate.value);if(!scheduleEndpoint)throw Error("Планирование недоступно.");}
      catch(e){notify(e.message);return;}
    }
    const plan = retryPlan || buildPlan();
    retryPlan = plan;
    cancelled = false;
    setProgress(true, 0);
    const bytes = batch => batch.files.reduce((sum, file) => sum + file.size, 0);
    const totalBytes = Math.max(1, plan.batches.reduce((sum, batch) => sum + bytes(batch), 0));
    let sentBytes = plan.batches.slice(0, plan.completed).reduce((sum, batch) => sum + bytes(batch), 0);
    try {
      // The exact files, options and UUIDs must be committed before the
      // first request; an old tab cannot replace another tab's retry plan.
      if (!volatile && !await persistCurrent()) {
        if (conflict) throw Error(storageProblem);
        if (planWasPersisted || plan.completed)
          throw Error("Сначала восстановите доступ к локальной очереди. Сохранённая отправка не будет удалена.");
        if (!window.confirm((storageProblem||"Локальное хранилище недоступно.")+
          " Отправить без восстановления после перезагрузки?")) {
          // Keep the plan intact, including UUIDs.
          throw Error("Отправка отложена.");
        }
        if (!await clearStored()) throw Error(storageProblem||"Не удалось очистить старую запись.");
        volatile=true;storageProblem="Без сохранения: не закрывайте вкладку.";updateDraftUI();
      }
      while (plan.completed < plan.batches.length) {
        if (cancelled) throw new Error("Загрузка отменена.");
        const batch = plan.batches[plan.completed];
        const payload = await upload(
          batch.files, batch.caption, plan.mode, batch.reply,
          (loaded, total) => setProgress(true, (sentBytes + bytes(batch) * (total ? loaded / total : 0)) / totalBytes * 100),
          batch.id, plan.silent, 0, plan.compress, batch.quote, plan.spoiler, plan.scheduledFor || "",
        );
        plan.completed++;
        sentBytes += bytes(batch);
        if (plan.scheduledFor) {
          if(payload.item.status==="sent")void window.SovietgramChat?.syncNow?.();
        } else renderSent(payload.message);
        if (!volatile && !await persistCurrent())
          throw Error("Сервер принял файл, но не удалось сохранить прогресс. Повтор безопасен с тем же идентификатором.");
      }
      if (!volatile && !await clearStored()) throw Error("Файлы отправлены, но не удалось очистить локальную очередь.");
      if (messageInput && messageInput.value === plan.originalDraft) {
        messageInput.value = "";
        messageInput.dispatchEvent(new Event("input", { bubbles: true }));
      }
      if (replyInput && replyInput.value === plan.originalReply &&
          (window.SovietgramChat?.currentQuote?.() || "") === plan.originalQuote) {
        window.SovietgramChat?.clearReplyState?.();
      }
      resetComposer();
      volatile=false;
      setProgress(false, 100);
      void window.SovietgramSidebar?.refresh?.();
      window.SovietgramChat?.focusComposer?.();
      if(plan.scheduledFor)notify("Вложения запланированы.");
    } catch (uploadError) {
      setProgress(false, 0);
      if (sendButton) sendButton.textContent = "Повторить отправку";
      updateDraftUI();
      notify(uploadError.message + " Отправлено: " + plan.completed + " из " + plan.batches.length + ". Повтор продолжит оставшиеся.");
    }
  }

  abortButton?.addEventListener("click", () => {
    if (!busy) return;
    cancelled = true;
    activeUpload?.abort();
  });

  function resizeCaption() {
    if (!captionNode) return;
    captionNode.style.height = "auto";
    captionNode.style.height = Math.min(captionNode.scrollHeight,120) + "px";
  }
  captionNode?.addEventListener("input", resizeCaption);

  function fromTransfer(transfer) {
    return [...(transfer?.files || [])].filter(file => file.size > 0);
  }
  function openTransfer(files) {
    if (!files.length) return;
    if (busy || retryPlan || editingPhoto || discarding || conflict || corrupt) { notify("Сначала завершите текущую отправку или редактирование."); return; }
    const mode = files.every(isMedia) ? "media" : files.every(isAudio) ? "audio" : "file";
    const append = backdrop && !backdrop.hidden && selectedMode === mode;
    openComposer(append ? [...selectedFiles, ...files] : files, mode, append);
  }
  const fileDrag = event => [...(event.dataTransfer?.types || [])].includes("Files");
  if (dropOverlay) {
    document.addEventListener("dragenter", event => {
      if (!fileDrag(event) || busy || retryPlan) return;
      dragDepth++; dropOverlay.hidden = false;
    });
    document.addEventListener("dragover", event => {
      if (!fileDrag(event)) return;
      event.preventDefault();
      if (event.dataTransfer) event.dataTransfer.dropEffect = busy || retryPlan ? "none" : "copy";
    });
    document.addEventListener("dragleave", () => {
      dragDepth = Math.max(0,dragDepth-1);
      if (!dragDepth) dropOverlay.hidden = true;
    });
    document.addEventListener("drop", event => {
      const files = fromTransfer(event.dataTransfer);
      if (!files.length) return;
      event.preventDefault(); dragDepth = 0; dropOverlay.hidden = true;
      openTransfer(files);
    });
  }
  messageInput?.addEventListener("paste", event => {
    const files = fromTransfer(event.clipboardData);
    if (!files.length) return;
    event.preventDefault(); openTransfer(files);
  });

  // Own attachment file actions before the legacy chat handlers can consume
  // the same event. This isolates file picking from the large chat.js module.
  document.addEventListener("click", (event) => {
    const modeButton = event.target.closest?.("[data-attachment-mode]");
    if (modeButton) {
      event.preventDefault();
      event.stopImmediatePropagation();
      pick(modeButton.dataset.attachmentMode || "media", false);
      return;
    }

    if (event.target.closest?.("#mediaComposeAdd")) {
      event.preventDefault();
      event.stopImmediatePropagation();
      pick(selectedMode, true);
      return;
    }

    if (event.target.closest?.("#mediaComposeSend")) {
      event.preventDefault();
      event.stopImmediatePropagation();
      sendSelected();
      return;
    }

    if (event.target.closest?.("#mediaComposeClose")) {
      event.preventDefault();
      event.stopImmediatePropagation();
      closeComposer();
      return;
    }

    if (event.target === backdrop) {
      event.preventDefault();
      event.stopImmediatePropagation();
      closeComposer();
    }
  }, true);

  document.addEventListener("change", (event) => {
    const entries = Object.entries(inputs);
    const match = entries.find(([, input]) => input === event.target);
    if (!match) return;
    event.stopImmediatePropagation();
    onPicked(match[1], match[0]);
  }, true);

  document.addEventListener("keydown", event=>{
    if(event.key==="Escape"&&backdrop&&!backdrop.hidden&&!document.getElementById("photoEditor")?.open&&!editingPhoto){
      event.preventDefault();event.stopImmediatePropagation();closeComposer();
    }
  },true);
  captionNode?.addEventListener("keydown", (event) => {
    if (event.key !== "Enter" || event.shiftKey) return;
    if (!(event.ctrlKey || event.metaKey || document.body.dataset.enterToSend !== "false")) return;
    event.preventDefault();
    event.stopImmediatePropagation();
    sendSelected();
  }, true);

  window.SovietgramAttachmentFiles = {
    pick,
    close: closeComposer,
    visible: () => Boolean(backdrop && !backdrop.hidden),
    send: sendSelected,
    openGif: file => openComposer([file], "media"),
  };
})();
