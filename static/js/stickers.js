/* Account-scoped sticker library and direct sending. */
(() => {
  const $=id=>document.getElementById(id);
  const dialog=$("stickerDialog");
  if(!dialog)return;
  const tabs=$("stickerPackTabs"),grid=$("stickerGrid"),actions=$("stickerPackActions");
  const upload=$("stickerUploadForm"),file=$("stickerFile"),emoji=$("stickerEmoji"),hint=$("stickerHint"),errorNode=$("stickerError");
  const save=$("stickerSaveIncoming"),silentRow=$("stickerSilentRow");
  const csrf=document.querySelector("[name='csrfmiddlewaretoken']")?.value||"";
  let packs=[],favorites=[],recent=[],selected=null,mode="manage",attachmentId=null,removing=false,busy=false;
  function error(value=""){errorNode.textContent=value;errorNode.hidden=!value;}
  function pack(){return packs.find(item=>item.id===selected);}
  function setBusy(value){
    busy=value;
    dialog.querySelectorAll("button,input").forEach(node=>node.disabled=value);
    if(!value)draw();
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
  async function load(){
    const result=await request();packs=result.packs||[];favorites=result.favorites||[];recent=result.recent||[];
    if(!pack() && (mode==="save" || !["favorites","recent"].includes(selected)))selected=mode==="send"&&recent.length?"recent":packs[0]?.id??"favorites";
  }
  function button(text,callback){
    const node=document.createElement("button");node.type="button";node.textContent=text;
    node.addEventListener("click",callback);return node;
  }
  function draw(){
    const current=pack();
    hint.textContent=mode==="save"?"Выберите набор для сохранения полученного стикера.":mode==="send"?"Нажмите на стикер для отправки.": "Создавайте и редактируйте свои наборы.";
    tabs.replaceChildren();
    if(mode!=="save"){
      for(const [id,label] of [["favorites","Избранное"],["recent","Недавние"]]){
        const tab=button(label,()=>{selected=id;removing=false;error();draw();});
        tab.setAttribute("aria-pressed",String(selected===id));tab.disabled=busy;tabs.appendChild(tab);
      }
    }
    $("stickerClearRecent").hidden=selected!=="recent"||!recent.length||mode==="save";
    for(const item of packs){
      const tab=button(item.name,()=>{selected=item.id;removing=false;error();draw();});
      tab.setAttribute("aria-pressed",String(item.id===selected));tab.disabled=busy;tabs.appendChild(tab);
    }
    actions.hidden=!current||mode==="save";
    upload.hidden=!current||mode==="save";
    silentRow.hidden=mode!=="send";
    save.hidden=mode!=="save"||!current;
    $("stickerEditMode").textContent=removing?"Готово":"Удалить стикеры";
    $("stickerEditMode").setAttribute("aria-pressed",String(removing));
    $("stickerCreatePack").disabled=busy||packs.length>=10;
    grid.replaceChildren();
    const items=selected==="favorites"?favorites:selected==="recent"?recent:current?.stickers||[];
    if(!items.length){
      const empty=document.createElement("p");empty.className="sticker-hint";empty.textContent=selected==="favorites"?"Нажмите звёздочку на стикере, чтобы добавить в избранное.":selected==="recent"?"Недавно отправленных стикеров пока нет.":current?"В наборе пока нет стикеров.":"Создайте первый набор.";grid.appendChild(empty);return;
    }
    for(const item of items){
      const cell=document.createElement("div");cell.className="sticker-grid-cell";
      const node=button("",()=>void choose(item));
      node.disabled=busy||mode==="save"||(mode==="manage"&&!removing);
      node.title=removing?"Удалить стикер":mode==="send"?"Отправить стикер":"Стикер";
      node.setAttribute("aria-label",node.title+(item.emoji?" "+item.emoji:""));
      const img=document.createElement("img");img.src=item.url;img.alt=item.emoji||"Стикер";img.loading="lazy";
      node.appendChild(img);
      if(item.emoji){const small=document.createElement("small");small.textContent=item.emoji;node.appendChild(small);}
      if(removing){const remove=document.createElement("span");remove.className="sticker-remove";remove.textContent="×";node.appendChild(remove);}
      cell.appendChild(node);
      if(mode!=="save"&&!removing){
        const star=button(item.favorite?"★":"☆",()=>void mutate("favorite",{sticker_id:item.id,favorite:item.favorite?"0":"1"}));
        star.className="sticker-favorite";star.setAttribute("aria-pressed",String(Boolean(item.favorite)));star.setAttribute("aria-label",item.favorite?"Удалить из избранного":"В избранное");star.title=star.getAttribute("aria-label");star.disabled=busy;cell.appendChild(star);
        if(selected==="recent"){
          const forget=button("×",()=>void mutate("forget_recent",{sticker_id:item.id}));
          forget.className="sticker-forget";forget.title="Убрать из недавних";forget.setAttribute("aria-label",forget.title);forget.disabled=busy;cell.appendChild(forget);
        }
      }
      grid.appendChild(cell);
    }
  }
  async function mutate(action,fields={}){
    if(busy)return;
    error();setBusy(true);
    try{
      const result=await request(action,fields);
      if(result.pack)selected=result.pack.id;
      await load();error();
      return true;
    }catch(e){error(e.message);return false;}
    finally{setBusy(false);}
  }
  async function choose(item){
    if(busy)return;
    if(removing){
      if(window.confirm("Удалить этот стикер из набора?"))await mutate("remove",{pack_id:selected,sticker_id:item.id});
      return;
    }
    if(mode!=="send")return;
    error();setBusy(true);
    try{
      const sent=await window.SovietgramChat?.sendSticker(item.id,$("stickerSilent").checked);
      if(sent){dialog.close();}
      else error("Не удалось отправить стикер. Повторите попытку.");
    }catch(e){error(e.message);}
    finally{setBusy(false);}
  }
  async function open(nextMode,id=null){
    if(busy)return;
    mode=nextMode;attachmentId=id;removing=false;
    packs=[];favorites=[];recent=[];selected=null;draw();
    $("stickerSilent").checked=false;
    if(!dialog.open)dialog.showModal();
    error();setBusy(true);
    try{await load();}catch(e){error(e.message);}finally{setBusy(false);}
  }
  $("stickerDialogClose").addEventListener("click",()=>{if(!busy)dialog.close();});
  dialog.addEventListener("cancel",event=>{if(busy)event.preventDefault();});
  $("stickerCreatePack").addEventListener("click",()=>{
    const name=window.prompt("Название набора");
    if(name?.trim())void mutate("create",{name:name.trim()});
  });
  $("stickerRename").addEventListener("click",()=>{
    const current=pack();if(!current)return;
    const name=window.prompt("Название набора",current.name);
    if(name?.trim())void mutate("rename",{pack_id:current.id,name:name.trim()});
  });
  $("stickerDeletePack").addEventListener("click",()=>{
    const current=pack();if(current&&window.confirm("Удалить набор «"+current.name+"»? Отправленные стикеры сохранятся."))
      void mutate("delete",{pack_id:current.id});
  });
  $("stickerEditMode").addEventListener("click",()=>{removing=!removing;draw();});
  $("stickerClearRecent").addEventListener("click",()=>{
    if(window.confirm("Очистить список недавних стикеров? Избранное и наборы останутся."))void mutate("clear_recent");
  });
  upload.addEventListener("submit",async event=>{
    event.preventDefault();if(!pack()||!file.files[0]||busy)return;
    if(file.files[0].size>2*1024*1024){error("Изображение должно быть не больше 2 МБ.");return;}
    if(await mutate("add",{pack_id:selected,image:file.files[0],emoji:emoji.value})){upload.reset();}
  });
  save.addEventListener("click",async ()=>{
    if(!pack()||!attachmentId||busy)return;
    if(await mutate("save_message",{pack_id:selected,attachment_id:attachmentId})){
      dialog.close();window.showToast?.("Стикер сохранён.");
    }
  });
  document.addEventListener("click",event=>{
    const trigger=event.target.closest?.("[data-open-stickers]");
    const incoming=event.target.closest?.("[data-save-sticker]");
    if(!trigger&&!incoming)return;
    event.preventDefault();event.stopPropagation();
    if(incoming)void open("save",incoming.dataset.saveSticker);
    else void open(trigger.dataset.stickerSend==="true"?"send":"manage");
  });
  const url=new URL(window.location.href);
  if(url.searchParams.get("manage_stickers")==="1"){
    url.searchParams.delete("manage_stickers");window.history.replaceState({},"",url);void open("manage");
  }
})();
