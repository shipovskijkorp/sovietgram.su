/* Account-scoped sticker library and direct sending. */
(() => {
  // Sticker delivery must not depend on the initialization of chat.js.
  // Only the optional rendering step uses the chat module.
  function sendError(response, payload) {
    if (response.redirected || response.status === 401)
      return "Сессия истекла. Обновите страницу и войдите снова.";
    if (typeof payload?.error === "string" && payload.error) return payload.error;
    const fields = Object.values(payload?.errors || {}).flat();
    const first = fields.find(field => typeof field?.message === "string" && field.message);
    if (first) return first.message;
    if (response.status === 403) return "Отправка запрещена или сессия устарела (403). Обновите страницу.";
    if (response.status === 404) return "Чат или стикер больше недоступен (404).";
    if (response.status === 409) return "Конфликт отправки (409). Обновите страницу.";
    if (response.status === 429) return "Слишком много отправок. Повторите позже (429).";
    if (response.status >= 500) return "Ошибка сервера (" + response.status + "). Повторите отправку.";
    return "Сервер не подтвердил отправку (" + response.status + "). Повторите попытку.";
  }

  function createStickerSender({retry, csrf, url, accountId, chatId}) {
    if (!retry?.batch || !retry?.textKey || !retry?.fetchSend || !retry?.clearText)
      throw new Error("Не загрузился модуль отправки. Обновите страницу (Ctrl+F5).");
    if (!url || !/^\d+$/.test(String(accountId)) || !/^\d+$/.test(String(chatId)))
      throw new Error("Откройте доступную переписку для отправки стикера.");
    const stickerSendKeys = retry.batch();
    const scope = "sovietgram.pending-sticker." + accountId + "." + chatId;
    let sending = false;

    return async function sendSticker(stickerId, reply = "", silent = false, quote = "") {
      if (sending) throw new Error("Предыдущий стикер ещё отправляется.");
      if (!/^\d+$/.test(String(stickerId))) throw new Error("Стикер недоступен.");
      if (!csrf) throw new Error("Не найден токен защиты сессии. Обновите страницу.");
      sending = true;
      try {
        const data = new FormData();
        data.set("csrfmiddlewaretoken", csrf);
        data.set("account_id", String(accountId));
        data.set("sticker_id", String(stickerId));
        data.set("attachment_mode", "media");
        if (reply) data.set("reply_to", String(reply));
        if (reply && quote) data.set("reply_quote", quote);
        if (silent) data.set("silent", "1");
        // Preserve the existing key format and exact request body for retries
        // of sends initiated by an older version of the client.
        const signature = [stickerId, String(reply || ""), Boolean(silent)];
        if (reply && quote) signature.push(quote);
        data.set("client_message_id", await retry.textKey(scope, signature, stickerSendKeys));
        let response;
        try {
          response = await retry.fetchSend(url, {
            method: "POST", body: data, credentials: "same-origin",
            headers: {"X-Requested-With": "XMLHttpRequest"},
          });
        } catch (_) {
          throw new Error("Нет ответа сервера. Повторите отправку того же стикера.");
        }
        const payload = await response.json().catch(() => ({}));
        if (response.redirected || !response.ok || payload.ok !== true || !payload.message?.id)
          throw new Error(sendError(response, payload));
        // Acknowledgement is independent of DOM rendering and sidebar refresh.
        retry.clearText(scope, stickerSendKeys);
        return payload.message;
      } finally { sending = false; }
    };
  }

  window.SovietgramStickerSend = {createStickerSender, sendError};

  const $=id=>document.getElementById(id);
  const dialog=$("stickerDialog");
  if(!dialog)return;
  const tabs=$("stickerPackTabs"),grid=$("stickerGrid"),actions=$("stickerPackActions");
  const upload=$("stickerUploadForm"),file=$("stickerFile"),emoji=$("stickerEmoji"),hint=$("stickerHint"),errorNode=$("stickerError");
  const body=$("stickerBody"),list=$("stickerLibraryList"),search=$("stickerSearch"),menu=$("stickerItemMenu");
  const promptForm=$("stickerPromptForm"),promptInput=$("stickerPromptInput"),save=$("stickerSaveIncoming");
  const mobile=window.matchMedia("(max-width: 820px), (max-height: 540px) and (max-width: 1100px)");
  const csrf=$("messageForm")?.querySelector("[name='csrfmiddlewaretoken']")?.value
    || document.querySelector("[name='csrfmiddlewaretoken']")?.value || "";
  let stickerSender = null;
  let packs=[],favorites=[],recent=[],selected=null,mode="manage",screen="library",attachmentId=null,removing=false,busy=false;
  let pickerSelection=null,anchor=null,packMenuOpen=false,uploadOpen=false,promptState=null;
  let suppressedClick=null,hold=null;

  function currentSender() {
    if (!stickerSender) {
      stickerSender = createStickerSender({
        retry: window.SovietgramSendRetry,
        csrf, url: dialog.dataset.sendUrl,
        accountId: dialog.dataset.accountId, chatId: dialog.dataset.chatId,
      });
    }
    return stickerSender;
  }

  function showSentSticker(message, sentReply, quote = "") {
    const reply = $("replyToInput");
    if (reply && reply.value === sentReply && (window.SovietgramChat?.currentQuote?.() || "") === quote) {
      if (window.SovietgramChat?.clearReplyState) window.SovietgramChat.clearReplyState();
      else {
        reply.value = "";
        const preview = $("composerReply");
        if (preview) preview.hidden = true;
      }
    }
    try {
      // Do not call acceptSentMessage: that also clears the text draft.
      if (typeof window.renderSovietgramChatMessage !== "function") throw new Error("Chat renderer unavailable");
      window.renderSovietgramChatMessage(message);
    } catch (renderError) {
      console.warn("Sticker delivered; chat rendering failed", renderError);
      // The POST has succeeded. Recover the display without resending.
      window.location.reload();
      return;
    }
    try {
      Promise.resolve(window.SovietgramSidebar?.refresh?.()).catch(() => {});
      Promise.resolve(window.SovietgramChat?.syncNow?.()).catch(() => {});
    } catch (_) {}
  }
  // Presentation is separate from the existing, idempotent sticker transport.
  function error(value=""){errorNode.textContent=value;errorNode.hidden=!value;}
  function pack(){return packs.find(item=>item.id===selected);}
  function button(text,callback){
    const node=document.createElement("button");node.type="button";node.textContent=text;
    node.addEventListener("click",callback);return node;
  }
  const paths={
    star:"M12 3l2.8 5.7 6.2.9-4.5 4.4 1.1 6.2-5.6-2.9-5.6 2.9 1.1-6.2L3 9.6l6.2-.9L12 3Z",
    clock:"M12 8v5l3 2M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0Z",
    sticker:"M4 4h16v10l-6 6H4zM14 20v-6h6M8 8h.01M15 8h.01M8 12c1.5 2 3 2 4 1",
    next:"m9 5 7 7-7 7",
    check:"m5 12 4 4L19 6",
    plus:"M12 5v14M5 12h14"
  };
  function icon(name){
    const svg=document.createElementNS("http://www.w3.org/2000/svg","svg");
    svg.setAttribute("viewBox","0 0 24 24");svg.setAttribute("aria-hidden","true");
    const path=document.createElementNS(svg.namespaceURI,"path");path.setAttribute("d",paths[name]);svg.append(path);return svg;
  }
  function image(item,alt=""){
    const node=document.createElement("img");node.src=item.url;node.alt=alt;node.loading="lazy";node.draggable=false;return node;
  }
  function setBusy(value){
    busy=value;dialog.setAttribute("aria-busy",String(value));
    if(value)dialog.querySelectorAll("button,input").forEach(node=>node.disabled=true);
    else {
      dialog.querySelectorAll("button,input").forEach(node=>node.disabled=false);
      draw();
    }
  }
  async function request(action,fields={}){
    const url=new URL(dialog.dataset.url,window.location.origin);
    const options={credentials:"same-origin",cache:"no-store",headers:{"X-Requested-With":"XMLHttpRequest"}};
    if(action){
      const body=new FormData();
      Object.entries({csrfmiddlewaretoken:csrf,account_id:dialog.dataset.accountId,action,...fields}).forEach(([key,value])=>body.append(key,value));
      options.method="POST";options.body=body;
    }else url.searchParams.set("account_id",dialog.dataset.accountId);
    const response=await fetch(url,options);
    const result=await response.json().catch(()=>({}));
    if(!response.ok||!result.ok||(!action&&String(result.account_id)!==dialog.dataset.accountId))
      throw new Error(result.error||"Не удалось загрузить наборы.");
    return result;
  }
  function normalizeSelection(){
    if(screen==="picker"){
      if(!pack()&&!["favorites","recent"].includes(selected)) selected=recent.length?"recent":packs[0]?.id??"favorites";
    }else if(screen==="pack"&&!pack()){
      screen="library";selected=null;packMenuOpen=false;uploadOpen=false;
    }else if(screen==="save"&&!pack()){
      selected=packs[0]?.id??null;
    }
  }
  async function load(){
    const result=await request();packs=result.packs||[];favorites=result.favorites||[];recent=result.recent||[];
  }
  function closeItemMenu(){menu.hidden=true;menu.replaceChildren();}
  function stopHold(){if(hold){clearTimeout(hold.timer);hold=null;}}
  function switchScreen(next,{scroll=true}={}){
    closeItemMenu();stopHold();packMenuOpen=false;uploadOpen=false;removing=false;
    screen=next;
    if(next==="picker"){selected=pickerSelection;normalizeSelection();}
    if(scroll)body.scrollTop=0;
    error();draw();positionPicker();
  }
  function openPack(id){
    selected=id;switchScreen("pack");
  }
  function drawTabs(){
    const oldScroll=tabs.scrollLeft;
    tabs.replaceChildren();
    for(const item of [{id:"favorites",name:"Избранное",symbol:"star"},{id:"recent",name:"Недавние",symbol:"clock"},...packs]){
      const tab=button("",()=>{
        if(busy)return;
        selected=item.id;pickerSelection=selected;search.value="";closeItemMenu();body.scrollTop=0;draw();
      });
      tab.className="sticker-tab";tab.dataset.stickerTab=String(item.id);
      tab.title=item.name;tab.setAttribute("aria-label",item.name);
      tab.setAttribute("aria-pressed",String(item.id===selected&&!search.value.trim()));
      tab.append(item.stickers?.[0]?image(item.stickers[0]):icon(item.symbol||"sticker"));
      tab.disabled=busy;tabs.append(tab);
    }
    tabs.scrollLeft=oldScroll;
  }
  function drawLibrary(){
    list.replaceChildren();
    for(const item of packs){
      const row=button("",()=>{
        if(busy)return;
        if(screen==="save"){selected=item.id;draw();}
        else openPack(item.id);
      });
      row.className="sticker-library-row";row.dataset.stickerPack=String(item.id);
      row.setAttribute("aria-label",item.name);
      if(screen==="save")row.setAttribute("aria-pressed",String(item.id===selected));
      const cover=document.createElement("span");cover.className="sticker-library-cover";
      cover.append(item.stickers[0]?image(item.stickers[0]):icon("sticker"));
      const copy=document.createElement("span");copy.className="sticker-library-copy";
      const title=document.createElement("strong");title.textContent=item.name;
      const detail=document.createElement("small");detail.textContent=item.stickers.length+" шт."+ (item.share_url?" · Доступ по ссылке":"");
      copy.append(title,detail);row.append(cover,copy,icon(screen==="save"&&selected===item.id?"check":"next"));
      row.disabled=busy;list.append(row);
    }
    if(!packs.length){
      const empty=document.createElement("p");empty.className="sticker-hint";
      empty.textContent="У вас пока нет наборов. Создайте первый набор или установите готовый по ссылке.";
      list.append(empty);
    }
  }
  function gridItems(){
    const query=search.value.trim().toLocaleLowerCase("ru");
    if(screen==="picker"&&query){
      return packs.flatMap(p=>p.stickers.filter(item=>p.name.toLocaleLowerCase("ru").includes(query)||
        (item.emoji||"").toLocaleLowerCase("ru").includes(query)));
    }
    if(screen==="picker"&&selected==="favorites")return favorites;
    if(screen==="picker"&&selected==="recent")return recent;
    return pack()?.stickers||[];
  }
  function drawGrid(){
    grid.replaceChildren();const current=pack(),items=gridItems(),query=screen==="picker"&&search.value.trim();
    $("stickerGridTitle").textContent=query?"Результаты поиска":screen==="picker"&&selected==="favorites"?"Избранное":screen==="picker"&&selected==="recent"?"Недавние":current?.name||"Стикеры";
    $("stickerClearRecent").hidden=screen!=="picker"||selected!=="recent"||Boolean(query)||!recent.length;
    hint.hidden=Boolean(items.length);
    hint.textContent=query?"Ничего не найдено.":selected==="favorites"?"Добавляйте стикеры в избранное через контекстное меню.":selected==="recent"?"Здесь будут недавно отправленные стикеры.":"В наборе пока нет стикеров.";
    for(const item of items){
      const tile=button("",event=>{
        if(busy)return;
        if(suppressedClick?.id===item.id&&Date.now()<suppressedClick.until){suppressedClick=null;return;}
        if(removing){askRemove(item);return;}
        if(screen==="picker")void send(item,false);
        else openItemMenu(item,tile);
      });
      tile.className="sticker-tile"+(removing?" is-removing":"");tile.dataset.stickerId=String(item.id);
      tile.disabled=busy;
      tile.setAttribute("aria-label",(removing?"Удалить стикер":screen==="picker"?"Отправить стикер":"Действия со стикером")+(item.emoji?" "+item.emoji:""));
      tile.title=item.emoji||"Стикер";
      tile.append(image(item,item.emoji||"Стикер"));
      if(item.emoji){
        const label=document.createElement("small");label.className="sticker-tile-emoji";label.textContent=item.emoji;tile.append(label);
      }
      tile.addEventListener("contextmenu",event=>{
        event.preventDefault();event.stopPropagation();
        if(hold)suppressedClick={id:item.id,until:Date.now()+1200};
        stopHold();if(!busy&&!removing)openItemMenu(item,tile);
      });
      tile.addEventListener("keydown",event=>{
        if(event.key==="ContextMenu"||(event.shiftKey&&event.key==="F10")){
          event.preventDefault();openItemMenu(item,tile);
        }
      });
      tile.addEventListener("pointerdown",event=>{
        if(event.pointerType==="mouse"||busy||removing)return;
        stopHold();
        hold={id:item.id,x:event.clientX,y:event.clientY,timer:setTimeout(()=>{
          suppressedClick={id:item.id,until:Date.now()+1200};hold=null;openItemMenu(item,tile);
        },480)};
      });
      tile.addEventListener("pointermove",event=>{
        if(hold&&Math.hypot(event.clientX-hold.x,event.clientY-hold.y)>9)stopHold();
      });
      for(const name of ["pointerup","pointercancel","pointerleave"])tile.addEventListener(name,stopHold);
      grid.append(tile);
    }
  }
  function draw(){
    normalizeSelection();
    const current=pack(),picker=screen==="picker",library=screen==="library",detail=screen==="pack",incoming=screen==="save",editing=screen==="form";
    dialog.classList.toggle("is-picker",picker);
    $("stickerDialogTitle").textContent=editing?promptState?.title||"Настройка":picker?"Стикеры":library?"Мои наборы":incoming?"Добавить стикер":current?.name||"Набор";
    $("stickerSubtitle").textContent=library?packs.length+" из 10 наборов":detail?current.stickers.length+" из 40 стикеров":picker?"":incoming?"Выберите набор":"";
    $("stickerBack").hidden=!(editing||detail||(library&&mode==="send"));
    $("stickerManage").hidden=!picker;
    $("stickerPackMenuToggle").hidden=!detail;
    $("stickerPackMenuToggle").setAttribute("aria-expanded",String(detail&&packMenuOpen));
    $("stickerSearchRow").hidden=!picker;tabs.hidden=!picker;
    $("stickerIncomingPreview").hidden=!incoming;
    list.hidden=!(library||incoming);$("stickerGridSection").hidden=!(picker||detail);
    $("stickerManagerActions").hidden=!(library||incoming);
    $("stickerCreatePack").disabled=busy||packs.length>=10;
    $("stickerInstallLink").hidden=!library;$("stickerInstallLink").disabled=busy||packs.length>=10;
    $("stickerSaveFooter").hidden=!incoming;save.disabled=busy||!current||current.stickers.length>=40;
    $("stickerPackFooter").hidden=!detail;
    $("stickerUploadToggle").disabled=busy||!current||(!removing&&!uploadOpen&&current.stickers.length>=40);
    $("stickerUploadToggle").textContent=removing?"Готово":uploadOpen?"Закрыть добавление":"Добавить стикер";
    upload.hidden=!detail||!uploadOpen;
    actions.hidden=!detail||!packMenuOpen;
    $("stickerEditMode").textContent=removing?"Завершить удаление":"Удалить стикеры";
    $("stickerEditMode").setAttribute("aria-pressed",String(removing));
    $("stickerEditMode").disabled=busy||!current?.stickers.length;
    const shared=Boolean(detail&&current?.share_url);
    $("stickerShare").textContent=shared?"Открыть ссылку":"Поделиться набором";
    $("stickerShare").disabled=busy||!current||(!shared&&!current.stickers.length);
    $("stickerUnshare").hidden=!shared;
    $("stickerSharePanel").hidden=!shared||editing;
    if(shared)$("stickerShareLink").value=new URL(current.share_url,window.location.origin).href;
    else $("stickerShareLink").value="";
    promptForm.hidden=!editing;
    if(picker)drawTabs();
    if(library||incoming)drawLibrary();
    if(picker||detail)drawGrid();
  }
  function positionPicker(){
    if(!dialog.open||screen!=="picker"||mobile.matches){
      for(const name of ["left","top","right","bottom","height"])dialog.style.removeProperty(name);
      return;
    }
    const form=document.getElementById("messageForm"),rect=(anchor||form)?.getBoundingClientRect();
    if(!rect)return;
    const composer=form?.getBoundingClientRect()||rect;
    const vp=window.visualViewport;
    const left=vp?.offsetLeft||0,top=vp?.offsetTop||0,width=vp?.width||innerWidth,height=vp?.height||innerHeight;
    const space=Math.max(120,composer.top-top-10);
    dialog.style.height=Math.min(416,space,height-16)+"px";
    dialog.style.left="0px";dialog.style.top="0px";dialog.style.right="auto";dialog.style.bottom="auto";
    const bounds=dialog.getBoundingClientRect();
    const x=Math.max(left+8,Math.min(rect.right-bounds.width,left+width-bounds.width-8));
    const y=Math.max(top+8,Math.min(composer.top-bounds.height-6,top+height-bounds.height-8));
    dialog.style.left=x+"px";dialog.style.top=y+"px";
  }
  function openItemMenu(item,tile){
    if(busy||!dialog.open||removing)return;
    closeItemMenu();
    const make=(label,callback,extra="")=>{
      const action=button(label,()=>{closeItemMenu();callback();});
      if(extra)action.className=extra;menu.append(action);
    };
    if(screen==="picker"){
      make("Отправить без звука",()=>void send(item,true));
    }
    make(item.favorite?"Убрать из избранного":"Добавить в избранное",()=>void mutate("favorite",{sticker_id:item.id,favorite:item.favorite?"0":"1"}));
    if(screen==="picker"&&selected==="recent")make("Убрать из недавних",()=>void mutate("forget_recent",{sticker_id:item.id}));
    if(screen==="picker"&&packs.some(p=>p.id===item.pack_id))make("Открыть набор",()=>{pickerSelection=selected;openPack(item.pack_id);});
    if(screen==="pack")make("Удалить стикер",()=>askRemove(item),"sticker-danger");
    menu.hidden=false;
    const panel=dialog.getBoundingClientRect(),r=tile.getBoundingClientRect();
    menu.style.left="0px";menu.style.top="0px";
    const bounds=menu.getBoundingClientRect();
    menu.style.left=Math.max(6,Math.min(r.left-panel.left,panel.width-bounds.width-6))+"px";
    menu.style.top=Math.max(6,Math.min(r.bottom-panel.top,panel.height-bounds.height-6))+"px";
    menu.querySelector("button")?.focus({preventScroll:true});
  }
  function openPrompt({title,description="",label="",value="",submit="Сохранить",max=48,action,returnScreen=screen}){
    promptState={title,action,returnScreen};
    $("stickerPromptDescription").textContent=description;
    $("stickerPromptDescription").hidden=!description;
    $("stickerPromptLabel").textContent=label;
    $("stickerPromptLabel").hidden=!label;
    promptInput.hidden=!label;promptInput.required=Boolean(label);promptInput.maxLength=max;promptInput.value=value;
    $("stickerPromptSubmit").textContent=submit;
    switchScreen("form");
    (label?promptInput:$("stickerPromptSubmit")).focus({preventScroll:true});
    if(label)promptInput.select();
  }
  function confirmAction(title,description,submit,action){
    openPrompt({title,description,submit,action});
  }
  function askRemove(item){
    confirmAction("Удалить стикер?","Стикер исчезнет из вашего набора. Уже отправленные сообщения останутся.","Удалить",
      ()=>mutate("remove",{pack_id:selected,sticker_id:item.id},"pack"));
  }
  async function mutate(action,fields={},afterScreen=null){
    if(busy)return false;
    error();closeItemMenu();setBusy(true);
    try{
      const result=await request(action,fields);
      if(result.pack)selected=result.pack.id;
      if(afterScreen)screen=afterScreen;
      await load();
      packMenuOpen=false;
      if(action==="delete"){selected=null;screen="library";}
      if(screen==="picker")pickerSelection=selected;
      error();
      return true;
    }catch(e){error(e.message);return false;}
    finally{setBusy(false);positionPicker();}
  }
  async function send(item,silent){
    if(busy||screen!=="picker")return;
    const sentReply=$("replyToInput")?.value||"";
    const quote=sentReply?window.SovietgramChat?.currentQuote?.()||"":"";
    let message;
    error();closeItemMenu();setBusy(true);
    try{message=await currentSender()(item.id,sentReply,silent,quote);}
    catch(e){error(e.message||"Не удалось отправить стикер.");}
    finally{setBusy(false);}
    if(message){pickerSelection=selected;dialog.close();showSentSticker(message,sentReply,quote);}
  }
  function incomingAllowed(){
    const conversation=document.querySelector(".conversation--chat");
    return Boolean(conversation&&conversation.dataset.chatProtected!=="true"&&!conversation.classList.contains("is-message-selection"));
  }
  async function open(nextMode,id=null,source=null,trigger=null){
    if(busy)return;
    mode=nextMode;attachmentId=id;anchor=trigger;
    if(mode==="save"&&!incomingAllowed())return;
    screen=mode==="send"?"picker":mode==="save"?"save":"library";
    selected=mode==="send"?pickerSelection:null;
    packs=[];favorites=[];recent=[];search.value="";
    packMenuOpen=false;uploadOpen=false;removing=false;promptState=null;closeItemMenu();stopHold();
    if(mode==="save"&&source)$("stickerIncomingImage").src=source;
    else $("stickerIncomingImage").removeAttribute("src");
    draw();
    if(!dialog.open)dialog.showModal();
    if(mode==="send")anchor?.setAttribute("aria-expanded","true");
    positionPicker();body.scrollTop=0;error();setBusy(true);
    try{
      await load();
      if(screen==="picker")selected=pickerSelection??(recent.length?"recent":packs[0]?.id??"favorites");
    }
    catch(e){error(e.message);}
    finally{
      setBusy(false);positionPicker();
      if(mode==="save"&&!incomingAllowed()&&dialog.open)dialog.close();
    }
  }
  function openIncoming(node){
    if(!node||!incomingAllowed())return;
    const id=node.dataset.stickerAttachment,src=node.querySelector("img")?.src;
    if(!/^\d+$/.test(id||"")||!src)return;
    void open("save",id,src);
  }
  window.SovietgramStickers={openIncoming,closeIncoming(){
    if(dialog.open&&mode==="save"&&!busy)dialog.close();
  }};
  function goBack(){
    if(busy)return;
    if(!menu.hidden){closeItemMenu();return;}
    if(screen==="form"){
      const previous=promptState?.returnScreen||"library";promptState=null;switchScreen(previous);return;
    }
    if(screen==="pack"){switchScreen("library");return;}
    if(screen==="library"&&mode==="send"){switchScreen("picker");return;}
    dialog.close();
  }
  $("stickerBack").addEventListener("click",goBack);
  $("stickerDialogClose").addEventListener("click",()=>{if(!busy)dialog.close();});
  $("stickerManage").addEventListener("click",()=>{pickerSelection=selected;switchScreen("library");});
  $("stickerPackMenuToggle").addEventListener("click",()=>{
    packMenuOpen=!packMenuOpen;actions.hidden=!packMenuOpen;
    $("stickerPackMenuToggle").setAttribute("aria-expanded",String(packMenuOpen));
    closeItemMenu();
  });
  dialog.addEventListener("click",event=>{
    const rect=dialog.getBoundingClientRect();
    if(event.target===dialog&&(event.clientX<rect.left||event.clientX>rect.right||event.clientY<rect.top||event.clientY>rect.bottom)){
      if(!busy)dialog.close();return;
    }
    if(!menu.hidden&&!menu.contains(event.target)&&!event.target.closest(".sticker-tile"))closeItemMenu();
    if(packMenuOpen&&!actions.contains(event.target)&&!event.target.closest("#stickerPackMenuToggle")){
      packMenuOpen=false;actions.hidden=true;$("stickerPackMenuToggle").setAttribute("aria-expanded","false");
    }
  });
  dialog.addEventListener("cancel",event=>{
    if(busy){event.preventDefault();return;}
    if(!menu.hidden||packMenuOpen||screen==="form"){
      event.preventDefault();
      if(!menu.hidden)closeItemMenu();
      else if(packMenuOpen){packMenuOpen=false;actions.hidden=true;$("stickerPackMenuToggle").setAttribute("aria-expanded","false");}
      else goBack();
    }
  });
  dialog.addEventListener("close",()=>{
    anchor?.setAttribute("aria-expanded","false");
    anchor=null;stopHold();closeItemMenu();positionPicker();
    $("stickerIncomingImage").removeAttribute("src");
    if(mode==="send"&&!mobile.matches)document.getElementById("messageInput")?.focus({preventScroll:true});
  });
  search.addEventListener("input",()=>{if(!busy){closeItemMenu();body.scrollTop=0;drawTabs();drawGrid();}});
  search.addEventListener("keydown",event=>{if(event.key==="Enter")event.preventDefault();});
  body.addEventListener("scroll",()=>{stopHold();if(!menu.hidden)closeItemMenu();},{passive:true});
  for(const event of ["resize","scroll"])window.visualViewport?.addEventListener(event,positionPicker);
  window.addEventListener("resize",positionPicker);
  if(typeof ResizeObserver!=="undefined"&&$("messageForm"))new ResizeObserver(positionPicker).observe($("messageForm"));
  $("stickerCreatePack").addEventListener("click",()=>{
    const after=screen==="save"?"save":"pack";
    openPrompt({title:"Новый набор",label:"Название",submit:"Создать",action:name=>mutate("create",{name:name.trim()},after)});
  });
  $("stickerInstallLink").addEventListener("click",()=>{
    openPrompt({title:"Установить набор",label:"Ссылка Sovietgram",submit:"Открыть набор",max:300,action:raw=>{
      try{
        const link=new URL(raw.trim(),window.location.origin);
        if(link.origin!==window.location.origin||link.username||link.password||
          !/^\/addstickers\/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\/?$/i.test(link.pathname))throw Error("Invalid link");
        window.location.assign(link.origin+link.pathname.replace(/\/?$/,"/"));return true;
      }catch(_){error("Нужна действительная ссылка на набор этого сервера Sovietgram.");return false;}
    }});
  });
  promptForm.addEventListener("submit",async event=>{
    event.preventDefault();if(busy||!promptState)return;
    const state=promptState;
    const ok=await state.action(promptInput.value);
    if(ok&&screen==="form")switchScreen(state.returnScreen);
    if(ok)promptState=null;
  });
  $("stickerRename").addEventListener("click",()=>{
    const current=pack();if(!current)return;
    openPrompt({title:"Название набора",label:"Название",value:current.name,action:name=>mutate("rename",{pack_id:current.id,name:name.trim()},"pack")});
  });
  $("stickerDeletePack").addEventListener("click",()=>{
    const current=pack();if(!current)return;
    confirmAction("Удалить набор?","Набор «"+current.name+"» будет удалён. Отправленные стикеры сохранятся.","Удалить",
      ()=>mutate("delete",{pack_id:current.id},"library"));
  });
  $("stickerEditMode").addEventListener("click",()=>{
    removing=!removing;packMenuOpen=false;uploadOpen=false;draw();
  });
  $("stickerShare").addEventListener("click",()=>{
    const current=pack();if(!current||busy)return;
    if(current.share_url)window.open(new URL(current.share_url,window.location.origin).href,"_blank","noopener,noreferrer");
    else confirmAction("Поделиться набором","Любой авторизованный пользователь со ссылкой сможет установить отдельную копию набора.","Создать ссылку",
      ()=>mutate("share",{pack_id:current.id},"pack"));
  });
  $("stickerUnshare").addEventListener("click",()=>{
    const current=pack();if(!current?.share_url||busy)return;
    confirmAction("Отозвать ссылку?","Старую ссылку больше нельзя будет использовать. Установленные копии сохранятся.","Отозвать",
      ()=>mutate("unshare",{pack_id:current.id},"pack"));
  });
  $("stickerCopyLink").addEventListener("click",async ()=>{
    const value=$("stickerShareLink").value;if(!value)return;
    try{await navigator.clipboard.writeText(value);window.showToast?.("Ссылка скопирована.");}
    catch(_){$("stickerShareLink").focus();$("stickerShareLink").select();error("Скопируйте выделенную ссылку вручную.");}
  });
  $("stickerClearRecent").addEventListener("click",()=>{
    confirmAction("Очистить недавние?","Избранное и наборы останутся.","Очистить",()=>mutate("clear_recent",{},"picker"));
  });
  $("stickerUploadToggle").addEventListener("click",()=>{
    if(removing){removing=false;draw();return;}
    uploadOpen=!uploadOpen;draw();if(uploadOpen)upload.scrollIntoView({block:"nearest"});
  });
  upload.addEventListener("submit",async event=>{
    event.preventDefault();if(!pack()||!file.files[0]||busy)return;
    if(file.files[0].size>2*1024*1024){error("Изображение должно быть не больше 2 МБ.");return;}
    if(await mutate("add",{pack_id:selected,image:file.files[0],emoji:emoji.value})){upload.reset();uploadOpen=false;draw();}
  });
  save.addEventListener("click",async ()=>{
    if(!pack()||!attachmentId||busy||!incomingAllowed())return;
    if(await mutate("save_message",{pack_id:selected,attachment_id:attachmentId})){
      dialog.close();window.showToast?.("Стикер сохранён.");
    }
  });
  document.addEventListener("click",event=>{
    const trigger=event.target.closest?.("[data-open-stickers]");
    const preview=event.target.closest?.("[data-open-sticker-preview]");
    if(!trigger&&!preview)return;
    if(preview?.disabled)return;
    event.preventDefault();event.stopPropagation();
    if(preview){openIncoming(preview.closest("[data-sticker-attachment]"));return;}
    if(dialog.open&&!busy&&mode==="send"&&screen==="picker"&&trigger===anchor){dialog.close();return;}
    void open(trigger.dataset.stickerSend==="true"?"send":"manage",null,null,trigger);
  });
  const url=new URL(window.location.href);
  if(url.searchParams.get("manage_stickers")==="1"){
    url.searchParams.delete("manage_stickers");window.history.replaceState({},"",url);void open("manage");
  }
})();
