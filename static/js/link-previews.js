/* Opt-in text-only previews, no third-party client requests. */
(() => {
  const stage=document.getElementById("messageStage"),flow=document.getElementById("messageFlow");
  if(!stage?.dataset.linkPreviewUrl||!flow)return;
  const csrf=document.querySelector("[name='csrfmiddlewaretoken']")?.value||"";
  const metadata=new Map();
  function firstLink(article){
    const anchors=article.querySelectorAll(".message__text a[href]");
    for(const anchor of anchors){
      const href=anchor.getAttribute("href")||"";
      if(/^https?:\/\//.test(href))return href;
    }
    return "";
  }
  function card(article,url){
    const existing=article.querySelector(".link-preview-card");
    if(!url){existing?.remove();return;}
    if(existing?.dataset.previewUrl===url)return;
    existing?.remove();
    const node=document.createElement("section");node.className="link-preview-card";node.dataset.previewUrl=url;
    const domain=document.createElement("small");
    try{domain.textContent=new URL(url).hostname;}catch(_error){return;}
    const button=document.createElement("button");button.type="button";button.dataset.loadLinkPreview="";
    button.textContent="Показать предпросмотр";
    button.title="Запросить описание страницы через сервер Sovietgram";
    node.append(domain,button);
    const paragraph=article.querySelector(".message__text");
    paragraph?.after(node);
    const cached=metadata.get(url);if(cached)draw(node,cached);
  }
  function draw(node,preview){
    const site=document.createElement("small");site.textContent=preview.site_name?preview.site_name+" · "+preview.domain:preview.domain;
    const title=document.createElement("strong");title.textContent=preview.title;
    const desc=document.createElement("p");desc.textContent=preview.description||"";desc.hidden=!preview.description;
    const hide=document.createElement("button");hide.type="button";hide.textContent="Скрыть предпросмотр";
    hide.addEventListener("click",()=>{
      metadata.delete(node.dataset.previewUrl);
      const article=node.closest(".message[data-message-id]");
      const url=node.dataset.previewUrl;node.remove();if(article)card(article,url);
    });
    node.replaceChildren(site,title,desc,hide);
  }
  function hydrate(){
    flow.querySelectorAll(".message[data-message-id]").forEach(article=>card(article,firstLink(article)));
  }
  flow.addEventListener("click",async event=>{
    const trigger=event.target.closest?.("[data-load-link-preview]");if(!trigger)return;
    event.preventDefault();event.stopPropagation();
    const node=trigger.closest(".link-preview-card"),article=node?.closest(".message[data-message-id]");
    if(!article||trigger.disabled)return;
    const url=node.dataset.previewUrl;
    trigger.disabled=true;trigger.textContent="Загрузка…";
    try{
      const data=new FormData();
      Object.entries({csrfmiddlewaretoken:csrf,account_id:stage.dataset.accountId,message_id:article.dataset.messageId,url}).forEach(([key,value])=>data.append(key,value));
      const response=await fetch(stage.dataset.linkPreviewUrl,{method:"POST",credentials:"same-origin",cache:"no-store",headers:{"X-Requested-With":"XMLHttpRequest"},body:data});
      const result=await response.json().catch(()=>({}));
      if(!response.ok||!result.ok||result.url!==url)throw new Error(result.error||"Предпросмотр недоступен.");
      if(!node.isConnected||firstLink(article)!==url)return;
      if(metadata.size>=100)metadata.delete(metadata.keys().next().value);
      metadata.set(url,result.preview);draw(node,result.preview);
    }catch(error){
      if(node.isConnected){trigger.textContent="Повторить предпросмотр";trigger.title=error.message;window.showToast?.(error.message);}
    }finally{trigger.disabled=false;}
  });
  let queued=false;
  const observer=new MutationObserver(records=>{
    if(queued||!records.some(record=>!record.target.closest?.(".link-preview-card")))return;
    queued=true;requestAnimationFrame(()=>{queued=false;hydrate();});
  });
  observer.observe(flow,{childList:true,subtree:true,characterData:true,attributes:true,attributeFilter:["href"]});
  hydrate();
})();
