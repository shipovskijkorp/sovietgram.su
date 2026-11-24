/* Personal chat folder management. The server owns rules, membership and rank. */
(() => {
  const categories = {contacts:"Контакты",noncontacts:"Не из контактов",groups:"Группы",channels:"Каналы",saved:"Избранное"};
  function modeOf(folder, chatId) {
    return folder.excluded.includes(chatId)?"exclude":folder.included.includes(chatId)?"include":"auto";
  }
  function matches(folder, chat) {
    const mode = modeOf(folder,chat.id);
    return mode==="include" || mode!=="exclude" && folder.categories.includes(chat.category)
      && !(folder.exclude_muted&&chat.muted) && !(folder.exclude_read&&!chat.unread)
      && !(folder.exclude_archived&&chat.archived);
  }
  function changeMode(included, excluded, id, mode) {
    const inc=included.filter(pk=>pk!==id), exc=excluded.filter(pk=>pk!==id);
    if(mode==="include")inc.push(id);
    if(mode==="exclude")exc.push(id);
    if(inc.length>200||exc.length>200)throw new Error("Не более 200 чатов в каждом списке.");
    return {included:inc,excluded:exc};
  }
  window.SovietgramFolderHelpers={modeOf,matches,changeMode};
  const $=id=>document.getElementById(id);
  const dialog=$("chatFoldersDialog");
  if(!dialog)return;
  const listPane=$("chatFoldersListPane"),editor=$("chatFoldersEditor"),memberPane=$("chatFolderMembershipPane");
  const list=$("chatFoldersList"),choices=$("chatFolderChatChoices"),memberChoices=$("chatFolderMembershipChoices");
  const name=$("chatFolderName"),search=$("chatFolderSearch"),title=$("chatFoldersTitle"),errorNode=$("chatFoldersError");
  const csrf=document.querySelector("[name='csrfmiddlewaretoken']")?.value||"";
  let folders=[],chats=[],editing=null,membershipChat=null,draft=null,busy=false,generation=0;
  const flags=["exclude_muted","exclude_read","exclude_archived"];
  function error(value=""){errorNode.textContent=value;errorNode.hidden=!value;}
  function toast(value){window.showToast?.(value);}
  function pane(which){
    listPane.hidden=which!=="list";editor.hidden=which!=="edit";memberPane.hidden=which!=="membership";
    title.textContent=which==="edit"?(editing?"Изменить папку":"Создать папку"):which==="membership"?"Папки чата":"Папки чатов";
  }
  function setBusy(value){
    busy=value;
    dialog.querySelectorAll("button,input,select").forEach(node=>node.disabled=value);
  }
  async function request(action,payload={}){
    const url=new URL(dialog.dataset.url,window.location.origin);
    const options={credentials:"same-origin",cache:"no-store",headers:{"X-Requested-With":"XMLHttpRequest"}};
    if(action){
      const data=new FormData();
      Object.entries({csrfmiddlewaretoken:csrf,account_id:dialog.dataset.accountId,action,payload:JSON.stringify(payload)})
        .forEach(([key,value])=>data.append(key,value));
      options.method="POST";options.body=data;
    }else url.searchParams.set("account_id",dialog.dataset.accountId);
    const response=await fetch(url,options);
    const result=await response.json().catch(()=>({}));
    if(!response.ok||!result.ok||(!action&&String(result.account_id)!==dialog.dataset.accountId))
      throw new Error(result.error||"Не удалось загрузить папки.");
    return result;
  }
  async function load(){
    const result=await request();
    folders=result.folders||[];chats=result.chats||[];
  }
  function button(label,action,className=""){
    const item=document.createElement("button");item.type="button";item.textContent=label;item.className=className;
    item.addEventListener("click",action);return item;
  }
  function selectMode(value,label,onChange){
    const select=document.createElement("select");select.setAttribute("aria-label",label);
    for(const [key,text] of [["auto","Автоматически"],["include","Включить"],["exclude","Исключить"]]){
      const option=document.createElement("option");option.value=key;option.textContent=text;select.appendChild(option);
    }
    select.value=value;select.addEventListener("change",()=>onChange(select.value,select));return select;
  }
  function showList(){
    editing=null;membershipChat=null;pane("list");
    list.replaceChildren();
    if(!folders.length){const p=document.createElement("p");p.className="folder-hint";p.textContent="Пока нет папок.";list.appendChild(p);}
    folders.forEach((folder,index)=>{
      const card=document.createElement("article");card.className="folder-card";
      const heading=document.createElement("strong");heading.textContent=folder.name;
      const detail=document.createElement("small");
      const count=chats.filter(chat=>matches(folder,chat)).length;
      detail.textContent=count+" чатов · "+folder.pinned.length+" закреплено";
      const actions=document.createElement("div");actions.className="folder-card-actions";
      const open=button("Открыть",()=>window.location.assign(dialog.dataset.homeUrl+"?folder="+folder.id));
      const up=button("↑",()=>void mutate("move_up",folder));up.title="Переместить выше";
      const down=button("↓",()=>void mutate("move_down",folder));down.title="Переместить ниже";
      up.disabled=index===0;down.disabled=index===folders.length-1;
      actions.append(open,button("Изменить",()=>openEditor(folder)),up,down,
        button("Удалить",()=>{if(window.confirm("Удалить папку «"+folder.name+"»? Чаты останутся."))void mutate("delete",folder);},"folder-danger"));
      card.append(heading,detail,actions);list.appendChild(card);
    });
    $("chatFoldersNew").disabled=folders.length>=20;
  }
  function openEditor(folder=null){
    editing=folder;membershipChat=null;
    draft=folder?{...folder,categories:[...folder.categories],included:[...folder.included],excluded:[...folder.excluded]}:
      {name:"",categories:[],included:[],excluded:[],exclude_muted:false,exclude_read:false,exclude_archived:false};
    name.value=draft.name;search.value="";
    editor.querySelectorAll("[data-folder-category]").forEach(node=>node.checked=draft.categories.includes(node.dataset.folderCategory));
    flags.forEach(flag=>editor.querySelector('[data-folder-flag="'+flag+'"]').checked=Boolean(draft[flag]));
    error();pane("edit");drawChoices();name.focus();
  }
  function updateDraft(){
    draft.name=name.value;
    draft.categories=[...editor.querySelectorAll("[data-folder-category]:checked")].map(node=>node.dataset.folderCategory);
    flags.forEach(flag=>draft[flag]=editor.querySelector('[data-folder-flag="'+flag+'"]').checked);
  }
  function drawChoices(){
    if(!draft)return;
    updateDraft();
    const query=search.value.trim().toLocaleLowerCase("ru-RU");
    const rows=chats.filter(chat=>chat.name.toLocaleLowerCase("ru-RU").includes(query));
    choices.replaceChildren();
    for(const chat of rows){
      const label=document.createElement("label");label.className="folder-choice";
      const desc=document.createElement("span");desc.textContent=chat.name;
      const meta=document.createElement("small");meta.textContent=categories[chat.category]+(chat.archived?" · Архив":"")+(chat.muted?" · Без звука":"");desc.appendChild(meta);
      const select=selectMode(modeOf(draft,chat.id),"Правило для "+chat.name,(value,node)=>{
        try{Object.assign(draft,changeMode(draft.included,draft.excluded,chat.id,value));error();}
        catch(e){node.value=modeOf(draft,chat.id);error(e.message);}
      });
      label.append(desc,select);choices.appendChild(label);
    }
    if(!rows.length){const p=document.createElement("p");p.className="folder-hint";p.textContent="Чаты не найдены.";choices.appendChild(p);}
  }
  function showMembership(chatId){
    membershipChat=chats.find(chat=>chat.id===Number(chatId));
    if(!membershipChat){showList();error("Чат больше недоступен.");return;}
    editing=null;pane("membership");
    $("chatFolderMembershipHint").textContent=membershipChat.name+" — выберите правило для каждой папки.";
    memberChoices.replaceChildren();
    if(!folders.length){const p=document.createElement("p");p.className="folder-hint";p.textContent="Сначала создайте папку.";memberChoices.appendChild(p);return;}
    for(const folder of folders){
      const label=document.createElement("label");label.className="folder-choice";
      const desc=document.createElement("span");desc.textContent=folder.name;
      const info=document.createElement("small");info.textContent=matches(folder,membershipChat)?"В папке":"Не в папке";desc.appendChild(info);
      const select=selectMode(modeOf(folder,membershipChat.id),"Правило для "+folder.name,(value)=>{
        void mutate("membership",folder,{chat_id:membershipChat.id,mode:value},membershipChat.id);
      });
      label.append(desc,select);memberChoices.appendChild(label);
    }
  }
  async function mutate(action,folder,payload={},chatId=null){
    if(busy)return;
    setBusy(true);error();
    try{
      await request(action,{id:folder.id,revision:folder.revision,...payload});
      if(action==="delete"&&new URL(window.location.href).searchParams.get("folder")===String(folder.id)){
        window.location.assign(dialog.dataset.homeUrl);return;
      }
      await load();
      setBusy(false);
      if(chatId!==null)showMembership(chatId);else showList();
      void window.SovietgramSidebar?.refresh();
    }catch(e){error(e.message);setBusy(false);}
  }
  editor.addEventListener("submit",async event=>{
    event.preventDefault();if(busy||!draft)return;
    updateDraft();setBusy(true);error();
    try{
      await request(editing?"edit":"create",{...draft,name:draft.name.trim()});
      await load();setBusy(false);showList();toast("Папка сохранена.");
      void window.SovietgramSidebar?.refresh();
    }catch(e){error(e.message);setBusy(false);}
  });
  search.addEventListener("input",drawChoices);
  $("chatFoldersNew").addEventListener("click",()=>openEditor());
  dialog.querySelectorAll("[data-folder-back],#chatFolderMembershipDone").forEach(node=>node.addEventListener("click",()=>{if(!busy){error();showList();}}));
  $("chatFoldersClose").addEventListener("click",()=>{if(!busy)dialog.close();});
  dialog.addEventListener("cancel",event=>{if(busy)event.preventDefault();});
  dialog.addEventListener("close",()=>{generation++;error();});
  async function open({chatId=null,folderId=null}={}){
    if(busy)return;
    // Close the underlying context menu, not the current conversation.
    window.SovietgramSidebar?.closeRowMenu();
    const menu=$("chatMenu");if(menu)menu.hidden=true;
    $("chatMenuButton")?.setAttribute("aria-expanded","false");
    if(!dialog.open)dialog.showModal();
    const current=++generation;
    pane("list");list.textContent="Загрузка…";error();setBusy(true);
    try{
      await load();
      if(!dialog.open||current!==generation)return;
      setBusy(false);
      if(chatId!==null)showMembership(chatId);
      else if(folderId!==null&&folders.some(folder=>folder.id===Number(folderId)))openEditor(folders.find(folder=>folder.id===Number(folderId)));
      else showList();
    }catch(e){error(e.message);setBusy(false);}
  }
  window.SovietgramFolders={openForChat:id=>void open({chatId:id})};
  document.addEventListener("click",event=>{
    const manager=event.target.closest?.("[data-manage-folders]");
    const chat=event.target.closest?.("[data-chat-folders]");
    if(!manager&&!chat)return;
    event.preventDefault();
    if(chat)void open({chatId:chat.dataset.chatFolders});
    else void open({folderId:manager.dataset.editFolder||null});
  });
  const url=new URL(window.location.href);
  if(url.searchParams.get("manage_folders")==="1"){
    url.searchParams.delete("manage_folders");window.history.replaceState({},"",url);
    void open();
  }
})();
