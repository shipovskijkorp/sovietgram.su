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
  const removeReply = $("scheduledRemoveReply"), replyRow = $("scheduledReplyRow");
  const errorNode = $("scheduledError"), title = $("scheduledTitle");
  const close = $("scheduledClose"), save = $("scheduledSave"), back = $("scheduledBack");
  const menu = $("sendOptionsMenu"), toggle = $("sendOptionsToggle"), send = $("sendButton");
  const input = $("messageInput"), reply = $("replyToInput");
  const scheduleButton = $("scheduleCurrentMessage"), silentButton = $("sendWithoutSound");
  const keys = window.SovietgramSendRetry.batch();
  const keyScope = "sovietgram.pending-schedule."+account+"."+url;
  let editing = null, original = null, busy = false, listVersion = 0;

  function toast(value) { window.showToast?.(value); }
  function error(value = "") { errorNode.textContent = value; errorNode.hidden = !value; }
  function hideMenu() { menu.hidden = true; toggle?.setAttribute("aria-expanded","false"); }
  function showMenu(anchor) {
    if (!anchor || !input || input.readOnly || send?.disabled || $("voiceRecordingBar")?.hidden === false) return;
    const hasText = Boolean(input.value.trim());
    silentButton.disabled = scheduleButton.disabled = !hasText;
    menu.hidden = false;
    toggle?.setAttribute("aria-expanded","true");
    const rect = anchor.getBoundingClientRect(), box = menu.getBoundingClientRect();
    menu.style.left = Math.max(6,Math.min(rect.right-box.width,window.innerWidth-box.width-6))+"px";
    menu.style.top = Math.max(6,Math.min(rect.top-box.height-8,window.innerHeight-box.height-6))+"px";
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
    for (const node of editor.querySelectorAll("input,textarea")) node.disabled = value;
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
      const body = document.createElement("p"); body.textContent = item.text;
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
    ++listVersion; editing=original=null;
    editor.hidden=true; listPane.hidden=false; title.textContent="Отложенные сообщения"; error();
    open(); void loadList();
  }
  function openEditor(item = null) {
    if (busy) return;
    ++listVersion; editing=item;
    original=item ? null : {text:input?.value || "",reply:reply?.value || ""};
    text.value=item ? item.text : original.text;
    const minimum = localDateValue(Date.now()+60000);
    date.min=minimum; date.max=localDateValue(Date.now()+365*86400000-60000);
    date.value=item && new Date(item.scheduled_for).getTime()>Date.now()+60000 ? localDateValue(item.scheduled_for) : localDateValue(Date.now()+300000);
    silent.checked=Boolean(item?.silent);
    removeReply.checked=false; replyRow.hidden=!(item?.reply_to || original?.reply);
    listPane.hidden=true; editor.hidden=false;
    title.textContent=item?"Изменить отложенное сообщение":"Отправить позже";
    save.textContent=item?"Сохранить":"Запланировать";
    error();open();text.focus();
  }
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
    finally {setBusy(false);error(message);void loadList();}
  }
  editor.addEventListener("submit",async event=>{
    event.preventDefault();if(busy)return;
    error();
    let when;
    try {
      when=toScheduledISO(date.value);
      if (!text.value.trim()) throw new Error("Введите текст сообщения.");
    } catch(e) {error(e.message);return;}
    setBusy(true);
    try {
      const fields={text:text.value,scheduled_for:when,silent:silent.checked?"1":"0"};
      if (editing) {
        Object.assign(fields,{action:"edit",revision:editing.revision,remove_reply:removeReply.checked?"1":"0"});
        await request(editing.action_url,fields);
        toast("Отложенное сообщение изменено.");
      } else {
        fields.reply_to=removeReply.checked?"":original?.reply||"";
        fields.client_message_id=await window.SovietgramSendRetry.textKey(keyScope,
          [fields.text,when,fields.silent,fields.reply_to],keys);
        const result=await request(url,fields,true);
        window.SovietgramSendRetry.clearText(keyScope,keys);
        if (result.item.status==="canceled") throw new Error("Эта отправка уже отменена.");
        if (original) window.SovietgramChat?.clearScheduledDraft(original.text,original.reply);
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
  dialog.addEventListener("close",()=>{++listVersion;editing=original=null;error();});
  window.setInterval(()=>{if(dialog.open&&!listPane.hidden&&!busy&&!document.hidden)void loadList();},5000);
})();
