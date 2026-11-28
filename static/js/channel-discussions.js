/* Independent discussion controller: no channel publishing permission required. */
(() => {
  const $ = id => document.getElementById(id);
  const conversation = document.querySelector(".conversation--chat[data-chat-type='channel']");
  const dialog = $("channelDiscussion");
  if (!conversation || !dialog) return;
  const form = $("discussionForm"), input = $("discussionText"), send = $("discussionSend");
  const status = $("discussionStatus"), list = $("discussionList"), scroll = $("discussionScroll");
  const older = $("discussionOlder"), lock = $("discussionLock"), refresh = $("discussionRefresh");
  const searchForm=$("discussionSearchForm"),searchInput=$("discussionSearch"),searchClear=$("discussionSearchClear");
  const fileInput=$("discussionFiles"),fileList=$("discussionAttachmentList");
  const account = document.body.dataset.accountId || $("messageStage")?.dataset.accountId || "";
  const retry = window.SovietgramSendRetry, keys = retry.batch();
  let url = "", source = null, before = null, generation = 0, controller = null;
  let loading = false, busy = false, state = null, rows = [], reply = null, editing = null, expanded = false;
  let query="",files=[],rowSignature=null;

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
    if (dialog.open && (!enabled || !source?.isConnected)) dialog.close();
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
    $("discussionAttachLabel").hidden=false;
    if (clear) {input.value = "";files=[];fileInput.value="";renderFiles();}
  }
  function chooseReply(comment) {
    if (!state?.can_write || busy) return;
    if (editing) resetMode(true);
    reply = comment; editing = null;
    $("discussionReplyText").textContent = "Ответ: " + comment.author + " · " + (comment.text.slice(0,100)||"Медиа");
    $("discussionReply").hidden = false;
    input.focus();
  }
  function chooseEdit(comment) {
    if (!state?.can_write || busy) return;
    if ((input.value.trim()||files.length) && !editing && !window.confirm("Заменить текущий черновик редактируемым комментарием?")) return;
    files=[];fileInput.value="";renderFiles();$("discussionAttachLabel").hidden=true;
    reply = null; editing = comment;
    input.value = comment.text; send.textContent = "Сохранить";
    $("discussionReplyText").textContent = "Редактирование комментария";
    $("discussionReply").hidden = false;
    input.focus();
  }
  function renderFiles(){
    fileList.replaceChildren();
    fileList.hidden=!files.length;
    for(const file of files){
      const chip=el("div","","discussion-file-chip");
      chip.append(el("span",file.name));
      const remove=button("×",()=>{if(!busy){files=files.filter(item=>item!==file);renderFiles();}});
      remove.setAttribute("aria-label","Убрать "+file.name);
      chip.append(remove);fileList.append(chip);
    }
  }
  fileInput.addEventListener("change",()=>{
    if(busy||editing){fileInput.value="";return;}
    const next=[...files,...fileInput.files];
    fileInput.value="";
    if(next.length>4||next.some(file=>!file.size||file.size>16*1048576||!/\.(png|jpe?g|webp|gif|mp4|webm)$/i.test(file.name))||
        next.reduce((sum,file)=>sum+file.size,0)>24*1048576){
      status.textContent="До 4 фото, GIF или видео: 16 МиБ на файл, 24 МиБ суммарно.";return;
    }
    files=next;renderFiles();
  });
  function reactionButton(comment,emoji,enabled){
    if(busy||!(state?.allowed_reactions||[]).includes(emoji))return;
    void mutate({action:"react",comment_id:comment.id,emoji,enabled:enabled?"1":"0"});
  }
  function renderReactions(comment){
    const row=el("div","","discussion-reactions");
    const allowed=state?.allowed_reactions||[];
    const reactions=comment.reactions||[];
    for(const reaction of reactions){
      const chip=button(reaction.emoji+" "+reaction.count,()=>reactionButton(comment,reaction.emoji,!reaction.mine));
      chip.className="discussion-reaction";
      chip.setAttribute("aria-pressed",String(reaction.mine));
      chip.setAttribute("aria-label",reaction.emoji+" · "+reaction.count+(reaction.mine?" · Ваша реакция":""));
      chip.disabled=!allowed.includes(reaction.emoji);
      chip.dataset.commentReaction=reaction.emoji;
      row.append(chip);
    }
    const available=allowed.filter(emoji=>!reactions.some(reaction=>reaction.emoji===emoji&&reaction.mine));
    if(available.length&&reactions.filter(reaction=>reaction.mine).length<3){
      const select=el("select","","discussion-reaction-select");select.setAttribute("aria-label","Добавить реакцию");
      const placeholder=el("option","＋ Реакция");placeholder.value="";placeholder.disabled=true;placeholder.selected=true;select.append(placeholder);
      for(const emoji of available){const option=el("option",emoji);option.value=emoji;select.append(option);}
      select.addEventListener("change",()=>{const emoji=select.value;select.value="";if(emoji)reactionButton(comment,emoji,true);});
      row.append(select);
    }
    return row;
  }
  function renderMedia(comment){
    const grid=el("div","","discussion-media");
    for(const attachment of comment.attachments||[]){
      const target=new URL(attachment.url,location.origin);
      if(target.origin!==location.origin)continue;
      let node;
      if(attachment.kind==="image"){
        node=el("img");node.loading="lazy";node.alt=attachment.name;node.src=target.href;
        if(!state?.protected){
          const link=el("a");link.href=target.href;link.target="_blank";link.rel="noopener noreferrer";link.append(node);node=link;
        }
      }else if(attachment.kind==="video"){
        node=el("video");node.controls=true;node.playsInline=true;node.preload="none";node.src=target.href;
        if(state?.protected)node.setAttribute("controlsList","nodownload");
      }else continue;
      grid.append(node);
    }
    return grid;
  }
  function renderRows() {
    const signature=JSON.stringify([rows,state?.can_write,state?.protected,state?.allowed_reactions,query]);
    if(signature===rowSignature)return;
    rowSignature=signature;
    const oldHeight = scroll.scrollHeight, oldTop = scroll.scrollTop;
    const nearBottom = oldHeight - oldTop - scroll.clientHeight < 90;
    const nodes = rows.map(comment => {
      const row = el("article","","discussion-comment");
      row.dataset.commentId = String(comment.id);
      const header = el("div","","discussion-comment-header");
      const identity = el("span",comment.author + " · @" + comment.username);
      header.append(identity,el("time",comment.time + (comment.edited ? " · изм." : "")));
      row.append(header);
      if (comment.reply) row.append(el("div",comment.reply.author + ": " + (comment.reply.text||"Медиа"),"discussion-comment-reply"));
      if(comment.text)row.append(el("p",comment.text,"discussion-comment-text"));
      if(comment.attachments?.length)row.append(renderMedia(comment));
      const reactions=renderReactions(comment);if(reactions.childElementCount)row.append(reactions);
      const actions = el("div","","discussion-comment-actions");
      if (state?.can_write) actions.append(button("Ответить",()=>chooseReply(comment)));
      if (comment.can_edit) actions.append(button("Изменить",()=>chooseEdit(comment)));
      if (comment.can_delete) actions.append(button("Удалить",()=>{
        if (window.confirm("Удалить комментарий для всех?")) void mutate({action:"delete",comment_id:comment.id});
      }));
      row.append(actions); return row;
    });
    list.replaceChildren(...nodes);
    if (!nodes.length) list.append(el("p",query?"Ничего не найдено.":"Комментариев пока нет.","discussion-empty"));
    if (nearBottom && !expanded) scroll.scrollTop = scroll.scrollHeight;
    else scroll.scrollTop = oldTop;
  }
  function renderState(data) {
    state = data;
    status.textContent = (query ? "Найдено: "+data.matched+" из "+data.total : "Комментарии: " + data.total) + (data.closed ? " · Закрыты" : "");
    if (source?.isConnected) buttonText(source,data.total);
    lock.hidden = !data.can_moderate;
    lock.textContent = data.closed ? "Открыть обсуждение" : "Закрыть обсуждение";
    form.hidden = !data.can_write;
    $("discussionReadOnly").hidden = data.can_write;
    $("discussionReadOnly").textContent = data.closed ? "Обсуждение закрыто администратором." : "Добавление комментариев ограничено.";
    dialog.classList.toggle("is-content-protected", Boolean(data.protected));
    older.hidden = !before;
    older.textContent=query?"Предыдущие результаты":"Предыдущие комментарии";
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
      if(query)endpoint.searchParams.set("q",query);
      if (append && before) endpoint.searchParams.set("before",String(before));
      const response = await fetch(endpoint,{credentials:"same-origin",cache:"no-store",signal:controller.signal});
      if (mine !== generation || !dialog.open) return;
      if ([403,404,409].includes(response.status) || response.redirected) {
        state = null; rows = []; rowSignature=null; list.replaceChildren(); form.hidden = true; lock.hidden = true; older.hidden = true;
        status.textContent = "Обсуждение больше недоступно."; return;
      }
      const data = await response.json().catch(()=>({}));
      if (mine !== generation || !dialog.open) return;
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
    fileInput.disabled=searchInput.disabled=$("discussionSearchSubmit").disabled=searchClear.disabled=true;
    let success = false;
    try {
      const body = new FormData();
      body.set("csrfmiddlewaretoken", form.querySelector("[name=csrfmiddlewaretoken]").value);
      body.set("account_id",account);
      for (const [key,value] of Object.entries(values)) body.set(key,String(value));
      const scope = "sovietgram.comment." + account + "." + url;
      if(values.action==="create"){
        const signature=[values.text,values.reply_to,...files.map(file=>retry.fileIdentity(file))];
        body.set("client_id",files.length?keys.key(scope,signature):await retry.textKey(scope,signature,keys));
        for(const file of files)body.append("attachments",file,file.name);
      }
      const response = await retry.fetchSend(url + "action/",{method:"POST",credentials:"same-origin",body,headers:{"X-Requested-With":"XMLHttpRequest"}});
      const data = await response.json().catch(()=>({}));
      if (!response.ok || !data.ok || response.redirected) throw new Error(data.error || "Не удалось выполнить действие (" + response.status + ").");
      if (values.action === "create") {retry.clearText(scope,keys);query="";searchInput.value="";searchClear.hidden=true;}
      if (values.action === "create" || values.action === "edit") resetMode(true);
      if(values.action==="react"){
        rows=rows.map(row=>String(row.id)===String(data.id)?{...row,reactions:data.reactions}:row);
        if(dialog.open)renderRows();
      }else success = true;
    } catch(error) { status.textContent = error.message; }
    finally {
      busy = false; input.readOnly = false; send.disabled = lock.disabled = false;
      fileInput.disabled=searchInput.disabled=$("discussionSearchSubmit").disabled=searchClear.disabled=false;
      older.disabled = refresh.disabled = false;
      if (success) await fetchPage();
    }
  }
  function open(trigger) {
    if (busy || conversation.dataset.commentsEnabled !== "true") return;
    url = trigger.dataset.discussionUrl; source = trigger; before = null; rows = []; state = null; expanded = false;
    query="";searchInput.value="";searchClear.hidden=true;rowSignature=null;
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
    if (!state?.can_write || (!text && !(editing?.attachments?.length||files.length)) || busy) return;
    if (editing) void mutate({action:"edit",comment_id:editing.id,revision:editing.revision,text});
    else void mutate({action:"create",text,reply_to:reply?.id||0});
  });
  function setQuery(next){
    if(busy||!dialog.open)return;
    controller?.abort();generation++;loading=false;
    query=next.trim();searchClear.hidden=!query;rows=[];before=null;expanded=false;rowSignature=null;
    list.replaceChildren();older.hidden=true;
    void fetchPage();
  }
  searchForm.addEventListener("submit",event=>{event.preventDefault();setQuery(searchInput.value);});
  searchClear.addEventListener("click",()=>{searchInput.value="";setQuery("");});
  $("discussionReplyCancel").addEventListener("click",()=>resetMode(Boolean(editing)));
  older.addEventListener("click",()=>{if(before)void fetchPage(true);});
  refresh.addEventListener("click",()=>{void fetchPage();});
  lock.addEventListener("click",()=>{if(state?.can_moderate)void mutate({action:state.closed?"open":"close"});});
  $("discussionClose").addEventListener("click",()=>{if(!busy)dialog.close();});
  dialog.addEventListener("cancel",event=>{if(busy)event.preventDefault();});
  dialog.addEventListener("close",()=>{
    generation++; controller?.abort(); loading = false; url = ""; state = null;
    rows = []; rowSignature=null; list.replaceChildren(); resetMode(true);
    source?.focus(); source = null;
  });
  dialog.addEventListener("copy",event=>{
    if(dialog.classList.contains("is-content-protected") && !event.target.closest?.("textarea,input"))event.preventDefault();
  });
  dialog.addEventListener("contextmenu",event=>{
    if(dialog.classList.contains("is-content-protected")&&event.target.closest?.(".discussion-media"))event.preventDefault();
  });
  window.setInterval(()=>{
    const playing=[...list.querySelectorAll("video")].some(video=>!video.paused&&!video.ended);
    if(dialog.open && !document.hidden && !expanded && !editing && !busy && !playing && !list.contains(document.activeElement))void fetchPage(false,true);
  },5000);
})();
