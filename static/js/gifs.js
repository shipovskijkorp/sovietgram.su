/* Account-scoped library; actual sending uses the standard media composer. */
(() => {
  const $=id=>document.getElementById(id);
  const dialog=$("gifDialog");
  if(!dialog)return;
  const account=dialog.dataset.accountId, endpoint=dialog.dataset.url;
  const search=$("gifSearch"),grid=$("gifGrid"),browse=$("gifBrowse"),editor=$("gifEditor");
  const incoming=$("gifIncoming"),incomingList=$("gifIncomingList"),errorNode=$("gifError");
  const loading=$("gifLoading"),empty=$("gifEmpty"),pagination=$("gifPagination");
  const fileInput=$("gifFile"),nameInput=$("gifName"),tagsInput=$("gifTags");
  const tabs=[...dialog.querySelectorAll("[data-gif-scope]")];
  const csrf=()=>document.querySelector('[name="csrfmiddlewaretoken"]')?.value||"";
  let scope="library",page=1,version=0,controller=null,timer=null,busy=false,editing=null,picker=false;
  function showError(text=""){errorNode.textContent=text;errorNode.hidden=!text;}
  function toast(text){window.showToast?.(text);}
  function setBusy(value){
    busy=value;dialog.setAttribute("aria-busy",String(value));
    for(const node of dialog.querySelectorAll("button,input"))node.disabled=value;
    if(!value)syncPageButtons();
  }
  let canNext=false;
  function syncPageButtons(){
    $("gifPrev").disabled=busy||page<=1;
    $("gifNext").disabled=busy||!canNext;
  }
  function scopedUrl(path,fields={}){
    const url=new URL(path,window.location.origin);
    if(url.origin!==window.location.origin)throw Error("Недопустимый адрес GIF.");
    url.searchParams.set("account_id",account);
    for(const [key,value] of Object.entries(fields))url.searchParams.set(key,value);
    return url.href;
  }
  async function api(fields=null,signal=undefined){
    const options={credentials:"same-origin",cache:"no-store",signal,headers:{"X-Requested-With":"XMLHttpRequest"}};
    let url=scopedUrl(endpoint,{scope,q:search.value,page:String(page)});
    if(fields){
      url=endpoint;const body=fields instanceof FormData?fields:new FormData();
      if(!(fields instanceof FormData))for(const [k,v] of Object.entries(fields))body.append(k,v);
      body.set("csrfmiddlewaretoken",csrf());body.set("account_id",account);
      Object.assign(options,{method:"POST",body});
    }
    const response=await fetch(url,options),payload=await response.json().catch(()=>({}));
    if(!response.ok||!payload.ok)throw Error(payload.error||"Не удалось выполнить действие с GIF.");
    if(!fields&&String(payload.account_id)!==account)throw Error("Аккаунт изменился. Обновите страницу.");
    return payload;
  }
  function button(label,fn,action){
    const node=document.createElement("button");node.type="button";node.textContent=label;
    if(action)node.dataset.gifAction=action;
    node.addEventListener("click",()=>{if(!busy)void fn(node);});
    return node;
  }
  function showBrowse(){
    editor.hidden=true;incoming.hidden=true;browse.hidden=false;
    dialog.querySelector("#gifDialogTitle").textContent=picker?"GIF-анимации":"Мои GIF";
    editing=null;
    for(const tab of tabs)tab.setAttribute("aria-pressed",String(tab.dataset.gifScope===scope));
    $("gifCatalogHint").hidden=scope!=="catalog";
    $("gifUploadToggle").hidden=scope==="catalog";
  }
  function stopLoad(){clearTimeout(timer);timer=null;controller?.abort();++version;loading.hidden=true;}
  function openEditor(item=null){
    if(busy)return;
    stopLoad();showError();editing=item;
    browse.hidden=true;incoming.hidden=true;editor.hidden=false;
    $("gifEditorTitle").textContent=item?"Редактировать GIF":"Добавить GIF";
    $("gifFileRow").hidden=Boolean(item);fileInput.hidden=Boolean(item);fileInput.required=!item;
    fileInput.value="";nameInput.value=item?.name||"";tagsInput.value=item?.tags||"";
    (item?nameInput:fileInput).focus();
  }
  async function mutate(action,item,extra={}){
    if(busy)return false;
    stopLoad();showError();setBusy(true);
    try{
      await api({action,gif_id:String(item.id),...extra});
      return true;
    }catch(error){showError(error.message);return false;}
    finally{setBusy(false);}
  }
  async function send(item){
    if(busy||!picker||dialog.dataset.canSend!=="true"||!window.SovietgramAttachmentFiles?.openGif)return;
    stopLoad();showError();setBusy(true);
    try{
      const response=await fetch(scopedUrl(item.image_url),{credentials:"same-origin",cache:"no-store"});
      if(!response.ok)throw Error("GIF больше недоступен.");
      const blob=await response.blob();
      if(blob.type!=="image/gif"||!blob.size||blob.size>8*1024*1024)throw Error("Некорректный GIF.");
      const name=(item.name||"animation").replace(/[\\/:*?"<>|\u0000-\u001f]/g,"_").replace(/\.gif$/i,"").slice(0,80)||"animation";
      const file=new File([blob],name+".gif",{type:"image/gif",lastModified:Date.now()});
      if(await window.SovietgramAttachmentFiles.openGif(file))dialog.close();
    }catch(error){showError(error.message);}
    finally{setBusy(false);}
  }
  function card(item){
    const root=document.createElement("article");root.className="gif-card";root.dataset.gifId=String(item.id);
    const preview=document.createElement("button");preview.type="button";
    preview.className="gif-preview";
    const image=document.createElement("img");image.loading="lazy";image.alt=item.name;image.src=scopedUrl(item.thumbnail_url);
    const mark=document.createElement("span");mark.className="gif-play";mark.textContent="▶ GIF";
    preview.replaceChildren(image,mark);preview.setAttribute("aria-label","Воспроизвести "+item.name);
    // Avoid a second fetch for every card; only play on request.
    preview.addEventListener("click",()=>{
      if(busy)return;
      const playing=preview.dataset.playing==="true";
      preview.dataset.playing=String(!playing);
      image.src=scopedUrl(playing?item.thumbnail_url:item.image_url);
      mark.textContent=playing?"▶ GIF":"■ GIF";
      preview.setAttribute("aria-label",(playing?"Воспроизвести ":"Остановить ")+item.name);
    });
    const caption=document.createElement("strong");caption.textContent=item.name;caption.title=item.name;
    const tags=document.createElement("small");tags.textContent=item.tags||"\u00a0";tags.title=item.tags;
    const actions=document.createElement("div");actions.className="gif-card-actions";
    if(picker&&dialog.dataset.canSend==="true")actions.append(button("Отправить",()=>send(item),"send"));
    if(item.own){
      actions.append(button(item.favorite?"★":"☆",async()=>{
        if(await mutate("favorite",item,{enabled:item.favorite?"0":"1"}))void load();
      },"favorite"));
      actions.lastChild.setAttribute("aria-label",item.favorite?"Убрать из избранного":"В избранное");
      actions.append(button("Изменить",()=>openEditor(item),"rename"));
      if(item.can_publish)actions.append(button(item.published?"Снять публикацию":"Опубликовать",async()=>{
        if(!window.confirm(item.published?"Убрать GIF из каталога? Сохранённые копии останутся.":
          "Опубликовать GIF, название и теги для всех пользователей Sovietgram?"))return;
        if(await mutate(item.published?"unpublish":"publish",item))void load();
      },"publish"));
      actions.append(button("Удалить",async()=>{
        if(window.confirm("Удалить GIF из библиотеки и каталога?")&&await mutate("delete",item))void load();
      },"delete"));
    }else{
      const save=button(item.saved?"Сохранено":"В избранное",async()=>{
        if(await mutate("save_catalog",item)){toast("GIF сохранён.");void load();}
      },"save");
      // Re-saving is safe and restores the favorite flag on an existing copy.
      actions.append(save);
    }
    root.append(preview,caption,tags,actions);
    return root;
  }
  async function load(){
    if(!dialog.open||browse.hidden||busy)return;
    stopLoad();const current=version;
    controller=new AbortController();
    loading.hidden=false;grid.replaceChildren();empty.hidden=true;pagination.hidden=true;showError();
    try{
      const result=await api(null,controller.signal);
      if(current!==version||!dialog.open||browse.hidden)return;
      page=result.page;canNext=result.has_next;
      grid.replaceChildren(...result.items.map(card));
      empty.hidden=Boolean(result.items.length);
      empty.textContent=search.value?"Ничего не найдено.":scope==="catalog"?"В каталоге пока нет GIF.":scope==="favorites"?"Нет избранных GIF.":"Добавьте GIF с устройства или сохраните из сообщения.";
      $("gifUsage").textContent=result.usage.count+"/"+result.usage.max_count+" · "+(result.usage.bytes/1048576).toFixed(1)+" / 100 МиБ";
      pagination.hidden=page<=1&&!canNext;
      $("gifPage").textContent=String(page);
      syncPageButtons();
    }catch(error){if(current===version&&error.name!=="AbortError")showError(error.message);}
    finally{if(current===version)loading.hidden=true;}
  }
  function open(sendMode=false){
    if(busy)return;
    const stickers=$("stickerDialog");
    if(stickers?.open){
      if(stickers.getAttribute("aria-busy")==="true")return;
      stickers.close();
    }
    window.SovietgramAttachmentMenu?.close();
    if(typeof setProfileMenu==="function")setProfileMenu(false);
    picker=sendMode&&dialog.dataset.canSend==="true";
    scope="library";page=1;search.value="";showBrowse();showError();
    if(!dialog.open)dialog.showModal();
    void load();
  }
  function candidates(article){
    if(!article||document.querySelector(".conversation--chat")?.dataset.chatProtected==="true")return [];
    return [...article.querySelectorAll("[data-gif-attachment]")].filter(node=>
      /^\d+$/.test(node.dataset.gifAttachment||"")&&!window.SovietgramMediaSpoilers?.isHidden(node));
  }
  function openIncoming(article){
    if(busy)return;
    const nodes=candidates(article);if(!nodes.length)return;
    stopLoad();picker=false;browse.hidden=true;editor.hidden=true;incoming.hidden=false;showError();
    $("gifDialogTitle").textContent="Сохранить GIF";
    incomingList.replaceChildren(...nodes.map(node=>{
      const row=document.createElement("div");row.className="gif-incoming-row";
      const label=document.createElement("span");label.textContent=node.dataset.gifName||"GIF";
      const save=button("Сохранить",async()=>{
        if(!candidates(article).some(n=>n.dataset.gifAttachment===node.dataset.gifAttachment)){showError("GIF больше недоступен.");return;}
        stopLoad();setBusy(true);showError();
        try{
          await api({action:"save_message",attachment_id:node.dataset.gifAttachment});
          row.remove();toast("GIF сохранён.");
          if(!incomingList.childElementCount){scope="library";page=1;search.value="";showBrowse();}
        }catch(error){showError(error.message);}
        finally{setBusy(false);if(!browse.hidden)void load();}
      },"save-message");
      row.append(label,save);return row;
    }));
    if(!dialog.open)dialog.showModal();
  }
  window.SovietgramGifs={candidates,openIncoming,closeIncoming(){if(dialog.open&&!incoming.hidden&&!busy)dialog.close();}};
  for(const tab of tabs)tab.addEventListener("click",()=>{
    if(busy)return;scope=tab.dataset.gifScope;page=1;search.value="";showBrowse();void load();
  });
  search.addEventListener("input",()=>{
    if(busy)return;page=1;stopLoad();grid.replaceChildren();empty.hidden=true;pagination.hidden=true;
    timer=setTimeout(()=>void load(),250);
  });
  $("gifPrev").addEventListener("click",()=>{if(!busy&&page>1){page--;void load();}});
  $("gifNext").addEventListener("click",()=>{if(!busy&&canNext){page++;void load();}});
  $("gifUploadToggle").addEventListener("click",()=>openEditor());
  $("gifEditorCancel").addEventListener("click",()=>{if(!busy){showBrowse();void load();}});
  $("gifIncomingBack").addEventListener("click",()=>{if(!busy){scope="library";page=1;search.value="";showBrowse();void load();}});
  $("gifDialogClose").addEventListener("click",()=>{if(!busy)dialog.close();});
  editor.addEventListener("submit",async event=>{
    event.preventDefault();if(busy)return;
    const data=new FormData();
    data.append("action",editing?"rename":"upload");
    data.append("name",nameInput.value);data.append("tags",tagsInput.value);
    if(editing)data.append("gif_id",String(editing.id));
    else{
      const file=fileInput.files?.[0];
      if(!file||file.size>8*1024*1024||!file.name.toLowerCase().endsWith(".gif")){showError("Выберите GIF до 8 МиБ.");return;}
      data.append("file",file,file.name);
    }
    setBusy(true);showError();
    let ok=false;
    try{await api(data);ok=true;toast("GIF сохранён.");}
    catch(error){showError(error.message);}
    finally{setBusy(false);}
    if(ok){scope="library";page=1;search.value="";showBrowse();void load();}
  });
  dialog.addEventListener("cancel",event=>{if(busy)event.preventDefault();});
  dialog.addEventListener("close",()=>{stopLoad();grid.replaceChildren();incomingList.replaceChildren();fileInput.value="";});
  document.addEventListener("click",event=>{
    const trigger=event.target.closest?.("[data-open-gifs]");
    if(!trigger)return;
    event.preventDefault();event.stopPropagation();open(trigger.dataset.gifSend==="true");
  });
  const url=new URL(window.location.href);
  if(url.searchParams.get("manage_gifs")==="1"){
    url.searchParams.delete("manage_gifs");history.replaceState({}, "",url);open();
  }
})();
