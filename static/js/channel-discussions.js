/* Independent discussion controller: no channel publishing permission required. */
(() => {
  const $ = id => document.getElementById(id);
  const conversation = document.querySelector(".conversation--chat[data-chat-type='channel']");
  const dialog = $("channelDiscussion");
  if (!conversation || !dialog) return;
  const form = $("discussionForm"), input = $("discussionText"), send = $("discussionSend");
  const status = $("discussionStatus"), list = $("discussionList"), scroll = $("discussionScroll");
  const older = $("discussionOlder"), lock = $("discussionLock"), refresh = $("discussionRefresh");
  const account = document.body.dataset.accountId || $("messageStage")?.dataset.accountId || "";
  const retry = window.SovietgramSendRetry, keys = retry.batch();
  let url = "", source = null, before = null, generation = 0, controller = null;
  let loading = false, busy = false, state = null, rows = [], reply = null, editing = null, expanded = false;

  function buttonText(button, count) {
    button.dataset.discussionCount = String(count);
    button.querySelector("span").textContent = "Комментарии: " + count;
  }
  function renderButton(article, message) {
    if (!message.urls?.discussion) return;
    let button = article.querySelector("[data-discussion-url]");
    if (!button) {
      button = document.createElement("button");
      button.type = "button"; button.className = "message-discussion";
      const label = document.createElement("span"), arrow = document.createElement("b");
      arrow.textContent = "›"; arrow.setAttribute("aria-hidden","true");
      button.append(label, arrow); article.append(button);
      buttonText(button, 0);
    }
    button.dataset.discussionUrl = message.urls.discussion;
    button.hidden = conversation.dataset.commentsEnabled !== "true";
  }
  function sync(enabled, counts) {
    conversation.dataset.commentsEnabled = String(enabled);
    for (const article of conversation.querySelectorAll(".message[data-message-id]")) {
      const button = article.querySelector("[data-discussion-url]");
      if (!button) continue;
      button.hidden = !enabled;
      if (Object.hasOwn(counts, article.dataset.messageId)) buttonText(button, counts[article.dataset.messageId]);
    }
    if (!enabled && dialog.open) dialog.close();
  }
  window.SovietgramDiscussions = {renderButton, sync};
  function el(tag, value, cls) {
    const element = document.createElement(tag);
    if (value) element.textContent = value;
    if (cls) element.className = cls;
    return element;
  }
  function button(label, action) {
    const element = el("button",label); element.type = "button";
    element.addEventListener("click",action); return element;
  }
  function resetMode(clear = false) {
    reply = editing = null;
    $("discussionReply").hidden = true;
    send.textContent = "Отправить";
    if (clear) input.value = "";
  }
  function chooseReply(comment) {
    if (!state?.can_write || busy) return;
    if (editing) resetMode(true);
    reply = comment; editing = null;
    $("discussionReplyText").textContent = "Ответ: " + comment.author + " · " + comment.text.slice(0,100);
    $("discussionReply").hidden = false;
    input.focus();
  }
  function chooseEdit(comment) {
    if (!state?.can_write || busy) return;
    if (input.value.trim() && !editing && !window.confirm("Заменить текущий черновик редактируемым комментарием?")) return;
    reply = null; editing = comment;
    input.value = comment.text; send.textContent = "Сохранить";
    $("discussionReplyText").textContent = "Редактирование комментария";
    $("discussionReply").hidden = false;
    input.focus();
  }
  function renderRows() {
    const oldHeight = scroll.scrollHeight, oldTop = scroll.scrollTop;
    const nearBottom = oldHeight - oldTop - scroll.clientHeight < 90;
    const nodes = rows.map(comment => {
      const row = el("article","","discussion-comment");
      row.dataset.commentId = String(comment.id);
      const header = el("div","","discussion-comment-header");
      const identity = el("span",comment.author + " · @" + comment.username);
      header.append(identity,el("time",comment.time + (comment.edited ? " · изм." : "")));
      row.append(header);
      if (comment.reply) row.append(el("div",comment.reply.author + ": " + comment.reply.text,"discussion-comment-reply"));
      row.append(el("p",comment.text,"discussion-comment-text"));
      const actions = el("div","","discussion-comment-actions");
      if (state?.can_write) actions.append(button("Ответить",()=>chooseReply(comment)));
      if (comment.can_edit) actions.append(button("Изменить",()=>chooseEdit(comment)));
      if (comment.can_delete) actions.append(button("Удалить",()=>{
        if (window.confirm("Удалить комментарий для всех?")) void mutate({action:"delete",comment_id:comment.id});
      }));
      row.append(actions); return row;
    });
    list.replaceChildren(...nodes);
    if (!nodes.length) list.append(el("p","Комментариев пока нет.","discussion-empty"));
    if (nearBottom && !expanded) scroll.scrollTop = scroll.scrollHeight;
    else scroll.scrollTop = oldTop;
  }
  function renderState(data) {
    state = data;
    status.textContent = "Комментарии: " + data.total + (data.closed ? " · Закрыты" : "");
    if (source?.isConnected) buttonText(source,data.total);
    lock.hidden = !data.can_moderate;
    lock.textContent = data.closed ? "Открыть обсуждение" : "Закрыть обсуждение";
    form.hidden = !data.can_write;
    $("discussionReadOnly").hidden = data.can_write;
    $("discussionReadOnly").textContent = data.closed ? "Обсуждение закрыто администратором." : "Добавление комментариев ограничено.";
    dialog.classList.toggle("is-content-protected", Boolean(data.protected));
    older.hidden = !before;
    renderRows();
  }
  async function fetchPage(append = false, quiet = false) {
    if (!dialog.open || !url || loading || busy) return;
    loading = true;
    const mine = ++generation;
    controller?.abort(); controller = new AbortController();
    const oldHeight = scroll.scrollHeight;
    if (!quiet) status.textContent = "Загрузка…";
    older.disabled = refresh.disabled = true;
    try {
      const endpoint = new URL(url,location.origin);
      endpoint.searchParams.set("account_id",account);
      if (append && before) endpoint.searchParams.set("before",String(before));
      const response = await fetch(endpoint,{credentials:"same-origin",cache:"no-store",signal:controller.signal});
      if (mine !== generation || !dialog.open) return;
      if ([403,404,409].includes(response.status) || response.redirected) {
        state = null; rows = []; list.replaceChildren(); form.hidden = true; lock.hidden = true; older.hidden = true;
        status.textContent = "Обсуждение больше недоступно."; return;
      }
      const data = await response.json().catch(()=>({}));
      if (!response.ok || !data.ok || String(data.account_id) !== account) throw new Error(data.error || "Не удалось загрузить комментарии.");
      if (append) {
        const seen = new Set(rows.map(row=>row.id));
        rows = [...data.comments.filter(row=>!seen.has(row.id)), ...rows];
        expanded = true;
      } else { rows = data.comments; expanded = false; }
      before = data.next_before || null;
      renderState(data);
      if (append) scroll.scrollTop += Math.max(0,scroll.scrollHeight-oldHeight);
    } catch(error) {
      if (mine === generation && error.name !== "AbortError") status.textContent = error.message;
    } finally {
      if (mine === generation) { loading = false; older.disabled = refresh.disabled = false; }
    }
  }
  async function mutate(values) {
    if (!dialog.open || !url || busy) return;
    busy = true;
    controller?.abort(); generation++; loading = false;
    input.readOnly = true; send.disabled = lock.disabled = true;
    let success = false;
    try {
      const body = new FormData();
      body.set("csrfmiddlewaretoken", form.querySelector("[name=csrfmiddlewaretoken]").value);
      body.set("account_id",account);
      for (const [key,value] of Object.entries(values)) body.set(key,String(value));
      const scope = "sovietgram.comment." + account + "." + url;
      if (values.action === "create") body.set("client_id",await retry.textKey(scope,[values.text,values.reply_to],keys));
      const response = await retry.fetchSend(url + "action/",{method:"POST",credentials:"same-origin",body,headers:{"X-Requested-With":"XMLHttpRequest"}});
      const data = await response.json().catch(()=>({}));
      if (!response.ok || !data.ok || response.redirected) throw new Error(data.error || "Не удалось выполнить действие (" + response.status + ").");
      if (values.action === "create") retry.clearText(scope,keys);
      if (values.action === "create" || values.action === "edit") resetMode(true);
      success = true;
    } catch(error) { status.textContent = error.message; }
    finally {
      busy = false; input.readOnly = false; send.disabled = lock.disabled = false;
      older.disabled = refresh.disabled = false;
      if (success) await fetchPage();
    }
  }
  function open(trigger) {
    if (busy || conversation.dataset.commentsEnabled !== "true") return;
    url = trigger.dataset.discussionUrl; source = trigger; before = null; rows = []; state = null; expanded = false;
    list.replaceChildren(); older.hidden = form.hidden = lock.hidden = true;
    $("discussionReadOnly").hidden = true;
    $("discussionPostPreview").textContent = (trigger.closest(".message")?.dataset.messageText || "Публикация").slice(0,150);
    resetMode(true); dialog.showModal(); void fetchPage();
  }
  document.addEventListener("click",event=>{
    const trigger = event.target.closest?.("[data-discussion-url]");
    if (!trigger || event.defaultPrevented) return;
    event.preventDefault(); open(trigger);
  });
  form.addEventListener("submit",event=>{
    event.preventDefault();
    const text = input.value.trim();
    if (!state?.can_write || !text || busy) return;
    if (editing) void mutate({action:"edit",comment_id:editing.id,revision:editing.revision,text});
    else void mutate({action:"create",text,reply_to:reply?.id||0});
  });
  $("discussionReplyCancel").addEventListener("click",()=>resetMode(Boolean(editing)));
  older.addEventListener("click",()=>{if(before)void fetchPage(true);});
  refresh.addEventListener("click",()=>{void fetchPage();});
  lock.addEventListener("click",()=>{if(state?.can_moderate)void mutate({action:state.closed?"open":"close"});});
  $("discussionClose").addEventListener("click",()=>{if(!busy)dialog.close();});
  dialog.addEventListener("cancel",event=>{if(busy)event.preventDefault();});
  dialog.addEventListener("close",()=>{
    generation++; controller?.abort(); loading = false; url = ""; state = null;
    rows = []; list.replaceChildren(); resetMode(true);
    source?.focus(); source = null;
  });
  dialog.addEventListener("copy",event=>{
    if(dialog.classList.contains("is-content-protected") && !event.target.closest?.("textarea,input"))event.preventDefault();
  });
  window.setInterval(()=>{
    if(dialog.open && !document.hidden && !expanded && !editing && !busy)void fetchPage(false,true);
  },5000);
})();
