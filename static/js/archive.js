/* Archive folder, personal chat operations and selection. Server is authoritative. */
(() => {
  const MAX_SELECTION = 200;
  function nextSelection(previous, id, limit = MAX_SELECTION) {
    const next = new Set(previous);
    if (next.has(id)) next.delete(id);
    else if (next.size < limit) next.add(id);
    return next;
  }
  function archiveVisible(hidden, revealed, search, filter, unread) {
    return !search && (filter === "all" || filter === "unread" && unread > 0) && (!hidden || revealed);
  }
  window.SovietgramArchiveHelpers = { nextSelection, archiveVisible };
  const $ = id => document.getElementById(id);
  const tools = $("sidebarChatTools"), list = $("chatList");
  if (!tools?.dataset.manageUrl || !list) return;
  const account = tools.dataset.accountId;
  const archived = tools.dataset.archived === "true";
  const home = tools.dataset.homeUrl;
  const search = $("chatFilter"), folderMenu = $("archiveFolderContext");
  const folderButton = $("archiveFolderMenuButton"), rowMenu = $("sidebarChatContext");
  const selectionBar = $("archiveSelectionBar"), help = $("archiveHelpDialog");
  const csrf = document.querySelector("[name='csrfmiddlewaretoken']")?.value || "";
  const allRows = () => Array.from(list.querySelectorAll("[data-chat-row][data-chat-id]"));
  const archiveRow = () => list.querySelector("[data-archive-folder]");
  let selecting = false, selected = new Set(), busy = false, revealed = false, targetId = null;
  let suppressClickUntil = 0, gesture = null, pressTimer = null;
  function toast(value) { window.showToast?.(value); }
  function hiddenArchive() { return list.dataset.archiveHidden === "true"; }
  function selectedRow() { return allRows().find(row => row.dataset.chatId === targetId); }
  function isOpenChat(row) {
    return !!row && new URL(row.href, window.location.origin).pathname === window.location.pathname;
  }
  function folderUrl() { return home + (archived ? "?archived=1" : ""); }
  function sync() {
    const count = Number(list.dataset.archiveCount) || 0;
    const unread = Number(list.dataset.archiveUnread) || 0;
    const hidden = hiddenArchive();
    const activeFilter = tools.querySelector('[data-chat-filter][aria-pressed="true"]')?.dataset.chatFilter || "all";
    const row = archiveRow();
    if (row) row.hidden = selecting || !archiveVisible(hidden,revealed,Boolean(search?.value.trim()),activeFilter,unread);
    const drawer = $("archiveDrawerEntry"), badge = $("archiveDrawerBadge"), heading = $("archiveHeadingCount");
    if (drawer) drawer.hidden = count > 0 && !hidden;
    if (badge) {
      badge.textContent = String(unread);
      badge.hidden = !unread;
      badge.classList.toggle("archive-folder-row__badge--muted", list.dataset.archiveLoudUnread !== "true");
    }
    if (heading) heading.textContent = "Чатов: "+count+" · Непрочитанных: "+unread;
    list.classList.toggle("is-selecting",selecting);
    selectionBar.hidden = !selecting;
    $("sidebarSelectChats")?.setAttribute("aria-pressed",String(selecting));
    for (const chat of allRows()) {
      const marker = chat.querySelector("[data-archive-select-marker]");
      const checked = selecting && selected.has(chat.dataset.chatId);
      chat.classList.toggle("is-selected", checked);
      if (marker) marker.hidden = !selecting;
      if (selecting) {
        chat.setAttribute("role","checkbox");
        chat.setAttribute("aria-checked",String(checked));
      } else {
        chat.removeAttribute("role");
        chat.removeAttribute("aria-checked");
      }
    }
    $("archiveSelectionCount").textContent = String(selected.size);
    selectionBar.querySelectorAll("[data-batch-action]").forEach(button => button.disabled = busy || !selected.size);
    $("archiveSelectAll").disabled = busy;
    $("archiveSelectionClose").disabled = busy;
    const visible = allRows().filter(chat => !chat.hidden);
    $("archiveSelectAll").textContent = visible.length && visible.every(chat => selected.has(chat.dataset.chatId)) ? "Снять выбор" : "Выбрать все";
  }
  function closeFolderMenu() {
    folderMenu.hidden=true; folderButton?.setAttribute("aria-expanded","false");
  }
  function closeRowMenu() { window.SovietgramSidebar?.closeRowMenu(); }
  function openFolderMenu(x,y) {
    closeRowMenu();
    $("archiveVisibilityLabel").textContent = hiddenArchive() ? "Показать архив в списке" : "Скрыть архив из списка";
    folderMenu.hidden=false;
    folderButton?.setAttribute("aria-expanded","true");
    const rect=folderMenu.getBoundingClientRect();
    folderMenu.style.left=Math.max(6,Math.min(x,window.innerWidth-rect.width-6))+"px";
    folderMenu.style.top=Math.max(6,Math.min(y,window.innerHeight-rect.height-6))+"px";
    folderMenu.querySelector("button")?.focus({preventScroll:true});
  }
  function prepareRowMenu(row) {
    closeFolderMenu();
    targetId=row.dataset.chatId;
    const inArchive=row.dataset.chatArchived==="true";
    const pinned=row.dataset.chatPinned==="true", muted=row.dataset.chatMuted==="true";
    const archive=$("sidebarChatArchiveAction"), pin=$("sidebarChatPinAction"), mute=$("sidebarChatMuteAction");
    archive.dataset.listAction=inArchive?"unarchive":"archive";
    archive.querySelector(".chat-menu__label").textContent=inArchive?"Вернуть из архива":"В архив";
    const archiveIcon=archive.querySelector(".tg-native-icon");
    archiveIcon.classList.toggle("tg-native-icon--archive",!inArchive);
    archiveIcon.classList.toggle("tg-native-icon--unarchive",inArchive);
    pin.dataset.listAction=pinned?"unpin":"pin";
    pin.querySelector(".chat-menu__label").textContent=pinned?"Открепить чат":inArchive?"Закрепить в архиве":"Закрепить чат";
    mute.dataset.listAction=muted?"unmute":"mute";
    mute.querySelector(".chat-menu__label").textContent=muted?"Включить уведомления":"Выключить уведомления";
    $("sidebarMuteDurations").hidden=true;
    const pins=allRows().filter(item=>item.dataset.chatPinned==="true");
    const index=pins.findIndex(item=>item.dataset.chatId===targetId);
    rowMenu.querySelector('[data-list-action="move_up"]').hidden=!pinned||index<=0;
    rowMenu.querySelector('[data-list-action="move_down"]').hidden=!pinned||index<0||index>=pins.length-1;
  }
  function beginSelection(id = null) {
    if (busy) return;
    closeFolderMenu();closeRowMenu();
    if (!selecting) {selecting=true;selected.clear();}
    if (id && !selected.has(id)) selected=nextSelection(selected,id);
    sync();
  }
  function endSelection() {
    if(busy)return;
    selecting=false;selected.clear();sync();
  }
  function toggleSelection(id) {
    if(busy)return;
    if(!selected.has(id)&&selected.size>=MAX_SELECTION) {toast("Можно выбрать до 200 чатов за раз.");return;}
    selected=nextSelection(selected,id);sync();
  }
  async function post(action, fields={}) {
    const data=new FormData();
    Object.entries({csrfmiddlewaretoken:csrf,account_id:account,action,...fields}).forEach(([k,v])=>data.append(k,v));
    const response=await fetch(tools.dataset.manageUrl,{method:"POST",credentials:"same-origin",
      headers:{"X-Requested-With":"XMLHttpRequest"},body:data});
    const payload=await response.json().catch(()=>({}));
    if(!response.ok||!payload.ok)throw new Error(payload.error||"Не удалось выполнить действие.");
    return payload;
  }
  const labels={
    archive:"Перенесено в архив",unarchive:"Возвращено из архива",pin:"Закреплено",unpin:"Откреплено",
    mute:"Уведомления отключены",unmute:"Уведомления включены",mark_read:"Отмечено прочитанным",
    mark_unread:"Отмечено непрочитанным",move_up:"Порядок изменён",move_down:"Порядок изменён",
  };
  async function applyAction(action, ids, duration="forever") {
    if(busy||!ids.length)return;
    const numbers=ids.map(Number);
    if(numbers.some(id=>!Number.isSafeInteger(id)||id<=0)) {toast("Некорректный идентификатор чата.");return;}
    const active=allRows().some(row=>ids.includes(row.dataset.chatId)&&isOpenChat(row));
    closeFolderMenu();closeRowMenu();busy=true;sync();
    try {
      const result=await post(action,{folder:archived?"archive":"main",chat_ids:JSON.stringify(numbers),duration});
      toast(labels[action]+(result.count>1?": "+result.count:"."));
      if(active&&["archive","unarchive","mark_unread"].includes(action)){
        window.location.assign(folderUrl());return;
      }
      if(selecting){selecting=false;selected.clear();}
      await window.SovietgramSidebar?.refresh();
    } catch(error){
      toast(error.message);await window.SovietgramSidebar?.refresh();
    } finally {busy=false;sync();}
  }
  async function setHidden(value) {
    if(busy)return;
    closeFolderMenu();busy=true;
    try {
      const result=await post("archive_visibility",{hidden:value?"1":"0"});
      list.dataset.archiveHidden=String(Boolean(result.archive_hidden));
      revealed=false;
      document.querySelectorAll('[data-setting="archive_in_main_menu"]').forEach(control=>control.checked=Boolean(result.archive_hidden));
      sync();
      await window.SovietgramSidebar?.refresh();
      toast(value?"Архив скрыт из списка. Он доступен в главном меню.":"Архив снова в списке чатов.");
    } catch(error){toast(error.message);} finally{busy=false;sync();}
  }
  async function readAll() {
    if(busy||!window.confirm("Отметить все чаты в архиве прочитанными?"))return;
    closeFolderMenu();busy=true;sync();
    try{
      await post("archive_read_all");
      toast("Весь архив отмечен прочитанным.");
      await window.SovietgramSidebar?.refresh();
    }catch(error){toast(error.message);}finally{busy=false;sync();}
  }
  function onRefresh() {
    const ids=new Set(allRows().map(row=>row.dataset.chatId));
    selected=new Set([...selected].filter(id=>ids.has(id)));
    if(!rowMenu.hidden){
      const row=selectedRow();
      if(!row)closeRowMenu();
      // Keep a user's open duration submenu usable while polling.
    }
    if(gesture && gesture.row && !gesture.row.isConnected) clearGesture();
    if(!hiddenArchive())revealed=false;
    sync();
  }
  window.SovietgramArchive={sync,onRefresh,prepareRowMenu,readAll};

  $("sidebarSelectChats")?.addEventListener("click",()=>selecting?endSelection():beginSelection());
  $("archiveSelectionClose").addEventListener("click",endSelection);
  $("archiveSelectAll").addEventListener("click",()=>{
    const ids=allRows().filter(row=>!row.hidden).map(row=>row.dataset.chatId);
    if(ids.every(id=>selected.has(id)))ids.forEach(id=>selected.delete(id));
    else{
      for(const id of ids){if(selected.size>=MAX_SELECTION)break;selected.add(id);}
      if(ids.some(id=>!selected.has(id)))toast("Выбрано не более 200 чатов.");
    }
    sync();
  });
  selectionBar.addEventListener("click",event=>{
    const button=event.target.closest?.("[data-batch-action]");
    if(button)void applyAction(button.dataset.batchAction,[...selected]);
  });
  rowMenu.addEventListener("click",event=>{
    const select=event.target.closest?.("#sidebarChatSelect");
    if(select){beginSelection(targetId);return;}
    const button=event.target.closest?.("[data-list-action]");
    if(!button||!targetId||busy)return;
    if(button.id==="sidebarChatMuteAction"&&button.dataset.listAction==="mute"){
      const options=$("sidebarMuteDurations");options.hidden=!options.hidden;
      const rect=rowMenu.getBoundingClientRect();
      rowMenu.style.top=Math.max(6,Math.min(rect.top,window.innerHeight-rect.height-6))+"px";
      return;
    }
    void applyAction(button.dataset.listAction,[targetId],button.dataset.muteDuration||"forever");
  });
  $("sidebarChatReadForm")?.addEventListener("submit",event=>{
    if(!targetId)return;
    event.preventDefault();
    void applyAction($("sidebarChatReadAction").value,[targetId]);
  });
  folderButton?.addEventListener("click",()=>{
    if(!folderMenu.hidden){closeFolderMenu();return;}
    const rect=folderButton.getBoundingClientRect();openFolderMenu(rect.left,rect.bottom+4);
  });
  folderMenu.addEventListener("click",event=>{
    const button=event.target.closest?.("[data-archive-command]");
    if(!button){if(event.target.closest?.("a"))closeFolderMenu();return;}
    const command=button.dataset.archiveCommand;
    if(command==="visibility")void setHidden(!hiddenArchive());
    else if(command==="read_all")void readAll();
    else if(command==="select"){
      closeFolderMenu();
      if(archived)beginSelection();else window.location.assign(home+"?archived=1&select=1");
    }else if(command==="help"){closeFolderMenu();help.showModal();}
  });
  $("archiveHelpClose").addEventListener("click",()=>help.close());
  $("archiveHelpSettings").addEventListener("click",()=>help.close());
  list.addEventListener("contextmenu",event=>{
    const row=event.target.closest?.("[data-archive-folder]");
    if(!row)return;
    event.preventDefault();const rect=row.getBoundingClientRect();
    openFolderMenu(event.clientX||rect.left+12,event.clientY||rect.bottom);
  });
  list.addEventListener("keydown",event=>{
    const folder=event.target.closest?.("[data-archive-folder]");
    if(folder&&(event.key==="ContextMenu"||event.shiftKey&&event.key==="F10")){
      event.preventDefault();const rect=folder.getBoundingClientRect();openFolderMenu(rect.left+12,rect.bottom);
    }
    const row=event.target.closest?.("[data-chat-row]");
    if(selecting&&row&&event.key===" "){event.preventDefault();toggleSelection(row.dataset.chatId);}
  });
  list.addEventListener("click",event=>{
    if(Date.now()<suppressClickUntil){event.preventDefault();event.stopImmediatePropagation();return;}
    if(!selecting)return;
    const row=event.target.closest?.("[data-chat-row]");
    if(row){event.preventDefault();event.stopImmediatePropagation();toggleSelection(row.dataset.chatId);}
  },true);
  document.addEventListener("pointerdown",event=>{
    if(!folderMenu.hidden&&!folderMenu.contains(event.target)&&!folderButton?.contains(event.target))closeFolderMenu();
  });
  document.addEventListener("keydown",event=>{
    if(event.key!=="Escape")return;
    if(!folderMenu.hidden){event.preventDefault();event.stopImmediatePropagation();closeFolderMenu();}
    else if(selecting&&!busy){event.preventDefault();event.stopImmediatePropagation();endSelection();}
  },true);
  window.addEventListener("resize",closeFolderMenu);
  list.addEventListener("scroll",closeFolderMenu,{passive:true});

  // A hidden folder can be temporarily revealed without modifying the account preference.
  function canReveal(){return !archived&&!selecting&&!search?.value.trim()&&hiddenArchive()&&!!archiveRow();}
  list.addEventListener("wheel",event=>{
    if(canReveal()&&list.scrollTop<=1&&event.deltaY<0){revealed=true;sync();}
    else if(revealed&&event.deltaY>0){revealed=false;sync();}
  },{passive:true});

  function clearGesture(){clearTimeout(pressTimer);pressTimer=null;gesture=null;}
  list.addEventListener("touchstart",event=>{
    clearGesture();
    if(event.touches.length!==1||selecting||busy)return;
    const touch=event.touches[0], row=event.target.closest?.("[data-chat-row], [data-archive-folder]");
    gesture={x:touch.clientX,y:touch.clientY,row,atTop:list.scrollTop<=1,long:false};
    if(row)pressTimer=setTimeout(()=>{
      if(!gesture||gesture.row!==row||!row.isConnected)return;
      gesture.long=true;suppressClickUntil=Date.now()+1100;
      const rect=row.getBoundingClientRect();
      if(row.hasAttribute("data-archive-folder"))openFolderMenu(rect.left+12,rect.bottom);
      else window.SovietgramSidebar?.openRowMenu(row,rect.left+12,rect.bottom);
    },550);
  },{passive:true});
  list.addEventListener("touchmove",event=>{
    if(!gesture||event.touches.length!==1)return;
    const touch=event.touches[0], dx=touch.clientX-gesture.x,dy=touch.clientY-gesture.y;
    if(Math.abs(dx)>10||Math.abs(dy)>10)clearTimeout(pressTimer);
    if(gesture.atTop&&canReveal()&&dy>15&&Math.abs(dy)>Math.abs(dx)&&event.cancelable)event.preventDefault();
  },{passive:false});
  list.addEventListener("touchend",event=>{
    if(!gesture)return;
    const current=gesture,touch=event.changedTouches[0];clearGesture();
    if(!touch)return;
    const dx=touch.clientX-current.x,dy=touch.clientY-current.y;
    if(current.long){suppressClickUntil=Date.now()+450;if(event.cancelable)event.preventDefault();return;}
    if(current.atTop&&canReveal()&&dy>55&&Math.abs(dy)>Math.abs(dx)*1.3){
      revealed=true;sync();suppressClickUntil=Date.now()+450;if(event.cancelable)event.preventDefault();return;
    }
    if(dx<-70&&Math.abs(dx)>Math.abs(dy)*1.5&&current.row?.isConnected){
      suppressClickUntil=Date.now()+450;if(event.cancelable)event.preventDefault();
      if(current.row.hasAttribute("data-archive-folder"))void setHidden(true);
      else void applyAction(archived?"unarchive":"archive",[current.row.dataset.chatId]);
    }
  },{passive:false});
  list.addEventListener("touchcancel",clearGesture,{passive:true});
  const page=new URL(window.location.href);
  if(archived&&page.searchParams.get("select")==="1"){
    page.searchParams.delete("select");window.history.replaceState({}, "",page);beginSelection();
  }
  sync();
})();
