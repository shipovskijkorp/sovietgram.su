/* A private, server-backed scheduled outbox; no client-side delivery timers. */
(() => {
  function localDateValue(value) {
    const date = new Date(value);
    if (!Number.isFinite(date.getTime())) return "";
    const pad = n => String(n).padStart(2, "0");
    return date.getFullYear()+"-"+pad(date.getMonth()+1)+"-"+pad(date.getDate())+"T"+pad(date.getHours())+":"+pad(date.getMinutes());
  }
  function toScheduledISO(value, now = Date.now()) {
    const date = new Date(value);
    if (!value || !Number.isFinite(date.getTime()) || localDateValue(date) !== value)
      throw new Error("Укажите корректное местное время.");
    if (date.getTime() <= now) throw new Error("Выберите время в будущем.");
    if (date.getTime() > now + 365*86400000) throw new Error("Отправку можно запланировать не более чем на год.");
    return date.toISOString();
  }
  window.SovietgramSchedule = { localDateValue, toScheduledISO };
  const stage = document.getElementById("messageStage");
  const dialog = document.getElementById("scheduledDialog");
  if (!stage?.dataset.scheduledUrl || !dialog) return;
  const url = stage.dataset.scheduledUrl;
  const account = stage.dataset.accountId;
  const csrf = document.querySelector("[name='csrfmiddlewaretoken']")?.value || "";
  const $ = id => document.getElementById(id);
  const editor = $("scheduledEditor"), listPane = $("scheduledListPane"), list = $("scheduledList");
  const text = $("scheduledText"), date = $("scheduledDate"), silent = $("scheduledSilent");
  const specialFields = $("scheduledSpecialFields"), textRow = $("scheduledTextRow");
  let collectSpecial = null;
  const removeReply = $("scheduledRemoveReply"), replyRow = $("scheduledReplyRow");
  const errorNode = $("scheduledError"), title = $("scheduledTitle");
  const close = $("scheduledClose"), save = $("scheduledSave"), back = $("scheduledBack");
  const menu = $("sendOptionsMenu"), toggle = $("sendOptionsToggle"), send = $("sendButton");
  const input = $("messageInput"), reply = $("replyToInput");
  const scheduleButton = $("scheduleCurrentMessage"), silentButton = $("sendWithoutSound");
  const recordingDialog=$("scheduleRecordingDialog"),recordingForm=$("scheduleRecordingForm");
  const recordingDate=$("scheduleRecordingDate"),recordingError=$("scheduleRecordingError");
  let recordingResolve=null,recordingResult=null;
  window.SovietgramSchedule.pickRecordingTime=()=>{
    if(!recordingDialog||recordingDialog.open)return Promise.resolve(null);
    recordingDate.min=localDateValue(Date.now()+60000);
    recordingDate.max=localDateValue(Date.now()+365*86400000-60000);
    recordingDate.value=localDateValue(Date.now()+300000);
    recordingError.hidden=true;recordingResult=null;
    return new Promise(resolve=>{recordingResolve=resolve;recordingDialog.showModal();recordingDate.focus();});
  };
  recordingForm?.addEventListener("submit",event=>{
    event.preventDefault();
    try{recordingResult=toScheduledISO(recordingDate.value);recordingDialog.close();}
    catch(e){recordingError.textContent=e.message;recordingError.hidden=false;}
  });
  $("scheduleRecordingCancel")?.addEventListener("click",()=>recordingDialog.close());
  recordingDialog?.addEventListener("keydown",event=>event.stopPropagation());
  recordingDialog?.addEventListener("close",()=>{
    recordingResolve?.(recordingResult);recordingResolve=null;recordingResult=null;
  });
  const keys = window.SovietgramSendRetry.batch();
  const keyScope = "sovietgram.pending-schedule."+account+"."+url;
  let editing = null, original = null, stickerDraft = null, busy = false, listVersion = 0;

  function toast(value) { window.showToast?.(value); }
  function error(value = "") { errorNode.textContent = value; errorNode.hidden = !value; }
  function hideMenu() { menu.hidden = true; toggle?.setAttribute("aria-expanded","false"); }
  function showMenu(anchor) {
    if (!anchor || !input || input.readOnly || send?.disabled || $("voiceRecordingBar")?.hidden === false) return;
    const hasText = Boolean(input.value.trim());
    silentButton.disabled = scheduleButton.disabled = !hasText;
    menu.hidden = false;
    toggle?.setAttribute("aria-expanded","true");
    const rect = anchor.getBoundingClientRect();
    const viewport = window.visualViewport;
    const vw = viewport?.width || window.innerWidth, vh = viewport?.height || window.innerHeight;
    const x = viewport?.offsetLeft || 0, y = viewport?.offsetTop || 0;
    menu.style.maxHeight = Math.max(0, vh - 12)+"px";
    menu.style.overflowY = "auto";
    const box = menu.getBoundingClientRect();
    menu.style.left = Math.max(x+6,Math.min(rect.right-box.width,x+vw-box.width-6))+"px";
    menu.style.top = Math.max(y+6,Math.min(rect.top-box.height-8,y+vh-box.height-6))+"px";
  }
  toggle?.addEventListener("pointerdown", event => event.preventDefault());
  toggle?.addEventListener("click", () => menu.hidden ? showMenu(toggle) : hideMenu());
  send?.addEventListener("contextmenu", event => {
    if (send.dataset.composerAction === "voice") return;
    event.preventDefault(); event.stopPropagation(); showMenu(send);
  });
  document.addEventListener("pointerdown", event => {
    if (!menu.hidden && !menu.contains(event.target) && !toggle?.contains(event.target)) hideMenu();
  });
  document.addEventListener("keydown", event => {
    if (event.key === "Escape" && !menu.hidden) {
      hideMenu(); event.stopImmediatePropagation(); event.preventDefault(); toggle?.focus();
    }
    if (event.target === send && (event.key === "ContextMenu" || event.shiftKey && event.key === "F10")) {
      event.preventDefault(); showMenu(send);
    }
  },true);
  window.addEventListener("resize", hideMenu);
  window.visualViewport?.addEventListener("resize", hideMenu);
  window.visualViewport?.addEventListener("scroll", hideMenu);
  silentButton.addEventListener("click", () => { hideMenu(); void window.SovietgramChat?.sendSilently(); });

  function open() {
    hideMenu();
    const chatMenu = $("chatMenu");
    if (chatMenu) chatMenu.hidden = true;
    $("chatMenuButton")?.setAttribute("aria-expanded","false");
    if (!dialog.open) dialog.showModal();
  }
  function setBusy(value) {
    busy = value;
    close.disabled = save.disabled = back.disabled = value;
    for (const node of editor.querySelectorAll("input,textarea,select,button")) node.disabled = value;
    if (!value) updateSpecialControls?.();
    for (const node of listPane.querySelectorAll("button")) node.disabled = value;
  }
  async function request(endpoint, fields = null, keyed = false) {
    const options = { credentials:"same-origin", cache:"no-store", headers:{"X-Requested-With":"XMLHttpRequest"} };
    if (fields) {
      const body = new FormData();
      body.append("csrfmiddlewaretoken",csrf);
      body.append("account_id",account);
      Object.entries(fields).forEach(([key,value]) => body.append(key,value ?? ""));
      Object.assign(options,{method:"POST",body});
    }
    if (!fields) {
      const targetUrl = new URL(endpoint, window.location.origin);
      targetUrl.searchParams.set("account_id", account);
      endpoint = targetUrl.href;
    }
    const response = await (keyed ? window.SovietgramSendRetry.fetchSend(endpoint,options) : fetch(endpoint,options));
    const payload = await response.json().catch(()=>({}));
    if (!response.ok || !payload.ok) throw new Error(payload.error || "Не удалось выполнить действие.");
    return payload;
  }
  function formatDate(value) {
    return new Date(value).toLocaleString("ru-RU",{dateStyle:"medium",timeStyle:"short"});
  }
  function makeButton(label, action, onClick) {
    const button = document.createElement("button");
    button.type = "button"; button.dataset.action = action; button.textContent = label;
    button.addEventListener("click",onClick);
    return button;
  }
  function drawItems(items) {
    const rows = items.map(item => {
      const row = document.createElement("article"); row.className = "scheduled-item";
      const when = document.createElement("time"); when.dateTime = item.scheduled_for;
      when.textContent = formatDate(item.scheduled_for) + (item.silent ? " · Без звука" : "");
      const body = document.createElement("p");
      const labels = {poll:"Опрос", todo:"Список задач", location:"Геопозиция", article:"Статья"};
      body.textContent = item.attachment_type === "sticker" ? "Стикер" :
        (labels[item.special_type] ? labels[item.special_type] + ": " : "") + (item.display_text || item.text);
      if(item.attachments?.length){
        const names=item.attachments.map(a=>a.name).join(", ");
        body.textContent="Вложения ("+item.attachments.length+"): "+names+(item.text?" · "+item.text:"");
      }
      const state = document.createElement("small");
      state.textContent = item.status === "failed" ? "Не отправлено: "+item.error
        : item.error ? item.error+" Следующая попытка: "+formatDate(item.next_attempt_at)
        : "Запланировано"+(item.reply_to ? " · Ответ на сообщение" : "");
      const actions = document.createElement("div"); actions.className = "scheduled-item-actions";
      actions.append(
        makeButton("Изменить","edit",()=>openEditor(item)),
        makeButton("Отправить сейчас","send_now",()=>void mutate(item,"send_now")),
        makeButton("Отменить","cancel",()=>void mutate(item,"cancel")),
      );
      row.append(when,body,state,actions);
      return row;
    });
    if (!rows.length) {
      const empty = document.createElement("p"); empty.className="scheduled-hint"; empty.textContent="Нет отложенных сообщений.";
      rows.push(empty);
    }
    list.replaceChildren(...rows);
  }
  async function loadList() {
    if (!dialog.open || listPane.hidden || busy) return;
    const version = ++listVersion;
    try {
      const payload = await request(url);
      if (version === listVersion && dialog.open && !listPane.hidden && !busy) drawItems(payload.items || []);
    } catch(e) { if (version===listVersion && dialog.open && !listPane.hidden) error(e.message); }
  }
  function showList() {
    ++listVersion; editing=original=stickerDraft=null;collectSpecial=null;updateSpecialControls=null;
    editor.hidden=true; listPane.hidden=false; title.textContent="Отложенные сообщения"; error();
    // Never expose stale buttons with a previous revision after an edit.
    list.replaceChildren();
    open(); void loadList();
  }
  let updateSpecialControls = null;
  function showSpecialFields(item){
    collectSpecial=null;updateSpecialControls=null;
    specialFields.replaceChildren();specialFields.hidden=true;textRow.hidden=false;text.required=true;
    const type=item?.special_type, data=item?.special_data;
    if(!data||!["article","poll","todo","location"].includes(type))return;
    specialFields.hidden=false;textRow.hidden=true;text.required=false;
    const add=(parent,label,kind,value,max=null)=>{
      const row=document.createElement("label"), field=document.createElement(kind==="textarea"?"textarea":"input");
      if(kind!=="textarea")field.type=kind;
      if(kind==="checkbox"){field.checked=Boolean(value);row.className="scheduled-checkbox";row.append(field," "+label);}
      else{field.value=value??"";if(max!==null)field.maxLength=max;row.append(label,field);}
      parent.append(row);return field;
    };
    if(type==="article"){
      const heading=add(specialFields,"Заголовок","text",data.title,200);
      const subtitle=add(specialFields,"Подзаголовок","text",data.subtitle,300);
      const body=add(specialFields,"Текст статьи (Markdown)","textarea",data.body,40000);
      heading.required=body.required=true;body.rows=10;
      collectSpecial=()=>({title:heading.value,subtitle:subtitle.value,body:body.value});
    }else if(type==="location"){
      const label=add(specialFields,"Название","text",data.label,120);
      const lat=add(specialFields,"Широта","number",data.latitude),lon=add(specialFields,"Долгота","number",data.longitude);
      lat.min=-90;lat.max=90;lon.min=-180;lon.max=180;lat.step=lon.step="any";lat.required=lon.required=true;
      collectSpecial=()=>({label:label.value,latitude:lat.value,longitude:lon.value});
    }else{
      const poll=type==="poll";
      const heading=add(specialFields,poll?"Вопрос":"Название списка","text",poll?data.question:data.title,255);
      heading.required=true;
      const anonymous=add(specialFields,poll?"Анонимный опрос":"Участники могут добавлять задачи","checkbox",poll?data.anonymous:data.allow_others_add);
      const multiple=add(specialFields,poll?"Несколько ответов":"Участники могут отмечать задачи","checkbox",poll?data.multiple:data.allow_others_mark);
      const quiz=poll?add(specialFields,"Викторина","checkbox",data.quiz):null;
      const explanation=poll?add(specialFields,"Пояснение к ответу","textarea",data.explanation,500):null;
      const rows=document.createElement("div");rows.className="scheduled-special-rows";specialFields.append(rows);
      const entries=[];
      const min=poll?2:1, max=poll?10:30;
      const addButton=makeButton(poll?"Добавить вариант":"Добавить задачу","add-row",()=>{if(entries.length<max)addEntry({});});
      specialFields.append(addButton);
      function refresh(){
        addButton.disabled=entries.length>=max;
        if(poll){
          multiple.disabled=quiz.checked;if(quiz.checked)multiple.checked=false;
          explanation.parentElement.hidden=!quiz.checked;
        }
        entries.forEach(entry=>{
          entry.remove.disabled=entries.length<=min;
          if(poll)entry.correct.parentElement.hidden=!quiz.checked;
        });
      }
      function addEntry(value,correct=false){
        const row=document.createElement("div");row.className="scheduled-special-row";rows.append(row);
        const field=add(row,poll?"Вариант":"Задача","text",value.text,poll?100:160);
        field.required=true;
        const entry={row,field};
        if(poll){
          entry.correct=add(row,"Правильный ответ","checkbox",correct);
          entry.correct.addEventListener("change",()=>{if(entry.correct.checked)entries.forEach(other=>{if(other!==entry)other.correct.checked=false;});});
        }else entry.due=add(row,"Срок","date",value.due_date||"");
        entry.remove=makeButton("Удалить","remove-row",()=>{
          if(entries.length<=min)return;
          entries.splice(entries.indexOf(entry),1);row.remove();refresh();
        });
        row.append(entry.remove);entries.push(entry);refresh();
      }
      const initial=poll?data.options:data.tasks;
      (initial||[]).forEach((value,i)=>addEntry(value,poll&&i===data.correct_option));
      while(entries.length<min)addEntry({});
      quiz?.addEventListener("change",refresh);updateSpecialControls=refresh;refresh();
      collectSpecial=()=>{
        if(poll){
          const options=entries.map(e=>e.field.value.trim());
          if(options.some(v=>!v)||new Set(options.map(v=>v.toLocaleLowerCase())).size!==options.length)
            throw Error("Варианты ответа должны быть непустыми и различаться.");
          const index=entries.findIndex(e=>e.correct.checked);
          if(quiz.checked&&index<0)throw Error("Выберите правильный ответ викторины.");
          return {question:heading.value,options,anonymous:anonymous.checked,multiple:multiple.checked,
                  quiz:quiz.checked,correct_option:quiz.checked?index:null,explanation:explanation.value};
        }
        return {title:heading.value,tasks:entries.map(e=>({text:e.field.value,due_date:e.due.value})),
                allow_others_add:anonymous.checked,allow_others_mark:multiple.checked};
      };
    }
  }
  function openEditor(item = null, sticker = null) {
    if (busy) return;
    ++listVersion; editing=item; stickerDraft=sticker;
    original=item ? null : {text:input?.value || "",reply:reply?.value || "",quote:window.SovietgramChat?.currentQuote?.() || ""};
    const stickerMode = Boolean(stickerDraft || item?.attachment_type === "sticker");
    text.value=stickerMode ? "Стикер" : item ? (item.display_text || item.text) : original.text;
    text.readOnly=Boolean(item?.special_type || stickerMode);
    showSpecialFields(item);
    const fileSummary=$("scheduledFileSummary"),hasFiles=Boolean(item?.attachments?.length);
    fileSummary.hidden=!hasFiles;
    fileSummary.textContent=hasFiles?item.attachments.map(a=>a.name).join(", "):"";
    if(hasFiles){
      text.required=false;
      text.readOnly=item.attachments.some(a=>["voice","video_note"].includes(a.kind));
      textRow.hidden=text.readOnly;
    }
    const minimum = localDateValue(Date.now()+60000);
    date.min=minimum; date.max=localDateValue(Date.now()+365*86400000-60000);
    date.value=item && new Date(item.scheduled_for).getTime()>Date.now()+60000 ? localDateValue(item.scheduled_for) : localDateValue(Date.now()+300000);
    silent.checked=Boolean(item?.silent);
    removeReply.checked=false; replyRow.hidden=!(item?.reply_to || original?.reply);
    listPane.hidden=true; editor.hidden=false;
    title.textContent=item?"Изменить отложенное сообщение":stickerDraft?"Запланировать стикер":"Отправить позже";
    save.textContent=item?"Сохранить":"Запланировать";
    error();open();(collectSpecial ? specialFields.querySelector("input,textarea") : text.readOnly ? date : text)?.focus();
  }
  window.SovietgramSchedule.openSticker = item => {
    if (!item || !/^\d+$/.test(String(item.id)) || busy) return false;
    openEditor(null, {id:item.id});
    return true;
  };
  async function mutate(item, action) {
    if (busy) return;
    if (!window.confirm(action==="cancel"?"Отменить это отложенное сообщение?":"Отправить это сообщение сейчас?")) return;
    setBusy(true);error();++listVersion;
    let message="";
    try {
      const result=await request(item.action_url,{action,revision:item.revision},action==="send_now");
      if (result.item.status==="sent") {toast("Сообщение отправлено.");void window.SovietgramChat?.syncNow();}
      else if (result.item.status==="canceled") toast("Отправка отменена.");
      else message=result.item.error || "Сообщение пока не отправлено.";
    } catch(e) {message=e.message;}
    finally {list.replaceChildren();setBusy(false);error(message);void loadList();}
  }
  editor.addEventListener("submit",async event=>{
    event.preventDefault();if(busy)return;
    error();
    let when, specialPayload;
    try {
      when=toScheduledISO(date.value);
      if (collectSpecial) specialPayload=collectSpecial();
      else if (!text.value.trim()&&!editing?.attachments?.length) throw new Error("Введите текст сообщения.");
    } catch(e) {error(e.message);return;}
    setBusy(true);
    try {
      const isSticker=Boolean(stickerDraft || editing?.attachment_type === "sticker");
      const fields={text:isSticker?"":text.value,scheduled_for:when,silent:silent.checked?"1":"0"};
      if (editing) {
        Object.assign(fields,{action:"edit",revision:editing.revision,remove_reply:removeReply.checked?"1":"0"});
        if (specialPayload) Object.assign(fields,{special_type:editing.special_type,payload:JSON.stringify(specialPayload)});
        await request(editing.action_url,fields);
        toast("Отложенное сообщение изменено.");
      } else {
        fields.reply_to=removeReply.checked?"":original?.reply||"";
        if (fields.reply_to && original?.quote) fields.reply_quote=original.quote;
        const signature=[fields.text,when,fields.silent,fields.reply_to];
        if (fields.reply_quote) signature.push(fields.reply_quote);
        if (stickerDraft) {
          fields.sticker_id=String(stickerDraft.id);
          signature.push(["sticker",fields.sticker_id]);
        }
        fields.client_message_id=await window.SovietgramSendRetry.textKey(keyScope,signature,keys);
        const result=await request(url,fields,true);
        window.SovietgramSendRetry.clearText(keyScope,keys);
        if (result.item.status==="canceled") throw new Error("Эта отправка уже отменена.");
        if (stickerDraft && original) {
          if ((reply?.value || "") === original.reply &&
              (window.SovietgramChat?.currentQuote?.() || "") === original.quote)
            window.SovietgramChat?.clearReplyState?.();
        } else if (original) window.SovietgramChat?.clearScheduledDraft(original.text,original.reply,original.quote);
        toast(result.item.status==="sent"?"Сообщение уже отправлено.":"Сообщение запланировано.");
      }
      setBusy(false);showList();
    } catch(e) {error(e.message);}
    finally {setBusy(false);}
  });
  document.querySelectorAll("[data-open-scheduled]").forEach(node=>node.addEventListener("click",showList));
  scheduleButton.addEventListener("click",()=>openEditor());
  $("scheduledNew")?.addEventListener("click",()=>openEditor());
  back.addEventListener("click",showList);
  close.addEventListener("click",()=>{if(!busy)dialog.close();});
  dialog.addEventListener("cancel",event=>{if(busy)event.preventDefault();});
  dialog.addEventListener("close",()=>{++listVersion;editing=original=stickerDraft=null;error();});
  window.setInterval(()=>{if(dialog.open&&!listPane.hidden&&!busy&&!document.hidden)void loadList();},5000);
})();
