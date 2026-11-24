/* Local emoji picker and formatting tools; no third-party scripts. */
(() => {
  const groups = [
    ["Смайлы", "😀 😃 😄 😁 😆 😅 😂 🤣 😊 🙂 🙃 😉 😌 😍 🥰 😘 😋 😛 😜 🤪 😎 🤓 🧐 🤔 🤫 🤭 🤗 🫡 😏 😒 😔 😢 😭 😤 😡 🤬 😳 😱 😨 😴 🥱 🤯 🥺 😬 🙄 😶 😐 😑 🫠 🤡 💀 👻 🤖"],
    ["Жесты и люди", "👍 👎 👌 ✌️ 🤞 🤟 🤘 🤙 👋 🤚 ✋ 🖐️ 🖖 👏 🙌 👐 🤝 🙏 💪 👊 ✊ 🤛 🤜 ☝️ 👆 👇 👈 👉 🫶 🫰 💅 👀 🧠 🫂"],
    ["Сердца и символы", "❤️ 🧡 💛 💚 💙 💜 🖤 🤍 🤎 💔 ❤️‍🔥 ❤️‍🩹 💕 💖 💗 💓 💞 💘 ✨ ⭐ 🌟 💫 🔥 💯 ✅ ❌ ❗ ❓ ⚠️ ☢️ ☭ 🎵 🎶 💤 💬 💭"],
    ["Животные и природа", "🐱 🐈 🐶 🐕 🦊 🐺 🐻 🐼 🐨 🐯 🦁 🐭 🐹 🐰 🐸 🐵 🐧 🦉 🦅 🐦 🐤 🦆 🐝 🦋 🐢 🐍 🐙 🦈 🐬 🐳 🐟 🐾 🌵 🌴 🌳 🌲 🍀 🌱 🌻 🌹 🌸 🍂 🌈 ☀️ 🌤️ ☁️ 🌧️ ⛈️ ❄️ 🌙 🌍"],
    ["Еда и напитки", "🍎 🍐 🍊 🍋 🍌 🍉 🍇 🍓 🍒 🍑 🥭 🍍 🥝 🥑 🍅 🥕 🌽 🥔 🍞 🥐 🧀 🍔 🍟 🍕 🌭 🥪 🌮 🍜 🍝 🍣 🍙 🍰 🎂 🍪 🍫 🍦 ☕ 🫖 🍵 🧃 🥤 🍺 🍷"],
    ["Предметы и занятия", "🎉 🎊 🎁 🎈 🏆 🥇 🎯 🎮 🕹️ ⚽ 🏀 🎲 🎸 🎧 🎤 🎬 📷 💻 🖥️ ⌨️ 🖱️ 📱 🔋 💡 🔧 ⚙️ 🛠️ 🧲 🧪 📚 📖 ✏️ 📝 📌 📎 🔗 🔒 🔑 ⏰ ⌛ 🧭 🗺️ 🚗 🚆 🚀 ✈️ 🚲 🏠 🏭 💎 🪙 📦"],
  ].map(([name, values]) => ({ name, values: values.split(" ") }));
  const recentKey = "sovietgram.emoji.recent.v1";
  const all = new Set(groups.flatMap(group => group.values));
  function addRecent(items, emoji) {
    return all.has(emoji) ? [emoji, ...items.filter(item => item !== emoji && all.has(item))].slice(0,24) : items;
  }
  function insertEmoji(text,start,end,emoji) {
    return {text:text.slice(0,start)+emoji+text.slice(end),start:start+emoji.length,end:start+emoji.length};
  }
  window.SovietgramComposerTools={insertEmoji,addRecent,groups};
  const triggers=Array.from(document.querySelectorAll("[data-compose-panel][data-compose-target]"));
  if (!triggers.length) return;
  const popup=document.createElement("div");
  popup.className="composer-tools-popup";
  popup.id="composerToolsPopup";
  popup.hidden=true;
  popup.setAttribute("role","group");
  document.body.appendChild(popup);
  let trigger=null,target=null,panel="",category="recent",recents=[];
  try {
    const saved=JSON.parse(localStorage.getItem(recentKey)||"[]");
    if (Array.isArray(saved)) recents=[...new Set(saved.filter(item=>all.has(item)))].slice(0,24);
  } catch (_error) {}
  const definitions=[
    ["bold","B","Жирный · Ctrl+B"],["italic","I","Курсив · Ctrl+I"],
    ["underline","U","Подчёркнутый · Ctrl+U"],["strike","S","Зачёркнутый"],
    ["spoiler","◩","Спойлер"],["code","</>","Моноширинный"],
    ["block","{ }","Блок кода"],["quote","❞","Цитата"],
    ["heading","H2","Заголовок"],["list","•","Маркированный список"],
    ["ordered","1.","Нумерованный список"],["task","☑","Список задач"],
    ["link","↗","Ссылка"],["image","▧","Изображение по URL"],
    ["table","▦","Таблица"],["rule","—","Разделитель"],
  ];
  function close(focus=false) {
    if (trigger) trigger.setAttribute("aria-expanded","false");
    popup.hidden=true;
    if (focus&&trigger?.isConnected) trigger.focus();
    trigger=target=null; panel="";
  }
  function position() {
    if (popup.hidden||!trigger) return;
    const rect=trigger.getBoundingClientRect();
    if (!rect.width||!rect.height||!trigger.isConnected) { close(); return; }
    const width=Math.max(0,Math.min(panel==="emoji"?328:270,window.innerWidth-16));
    popup.style.width=width+"px";
    popup.style.left=Math.max(8,Math.min(rect.right-width,window.innerWidth-width-8))+"px";
    const height=popup.offsetHeight;
    const above=rect.top-height-8;
    const below=rect.bottom+8;
    popup.style.top=Math.max(8,Math.min(above>=8?above:below,window.innerHeight-height-8))+"px";
  }
  function apply(editor,change) {
    if (!editor||editor.readOnly||editor.disabled) return false;
    if (editor.maxLength>=0&&change.text.length>editor.maxLength) {
      if (typeof showToast==="function") showToast("Превышена максимальная длина сообщения.");
      return false;
    }
    editor.value=change.text;
    editor.focus({preventScroll:true});
    editor.setSelectionRange(change.start,change.end);
    editor.dispatchEvent(new Event("input",{bubbles:true}));
    return true;
  }
  function format(editor,name) {
    if (!editor||!window.SovietgramFormat) return;
    apply(editor,window.SovietgramFormat.wrapSelection(editor.value,editor.selectionStart,editor.selectionEnd,name));
  }
  function button(label,title,action,className="") {
    const node=document.createElement("button");
    node.type="button";node.className=className;node.textContent=label;node.title=title;
    node.setAttribute("aria-label",title);
    node.addEventListener("pointerdown",event=>event.preventDefault());
    node.addEventListener("click",action);
    return node;
  }
  function drawFormat() {
    const heading=document.createElement("strong");
    heading.textContent="Форматирование текста";
    const grid=document.createElement("div");grid.className="composer-format-grid";
    for (const [name,label,title] of definitions) {
      const item=button(label,title,()=>{
        const editor=target;close();format(editor,name);
      },"composer-format-option");
      item.dataset.formatStyle=name;
      grid.appendChild(item);
    }
    const hint=document.createElement("small");
    hint.textContent="CommonMark / GFM. Выделите текст или вставьте Markdown. Подчёркивание: ++текст++; спойлер: ||текст||.";
    const preview=button("Предпросмотр","Предпросмотр Markdown",()=>void drawPreview(),"composer-markdown-preview-button");
    popup.replaceChildren(heading,grid,hint,preview);
  }
  async function drawPreview() {
    const editor=target;
    const stage=document.getElementById("messageStage");
    const url=stage?.dataset.markdownPreviewUrl;
    if (!editor||!url) return;
    const text=editor.value;
    const heading=document.createElement("strong");heading.textContent="Предпросмотр Markdown";
    const body=document.createElement("div");body.className="message__text markdown-body composer-markdown-preview";
    body.textContent="Загрузка…";
    const back=button("Назад","К форматированию",()=>{drawFormat();position();},"composer-markdown-preview-button");
    popup.replaceChildren(heading,body,back);
    position();
    try {
      const data=new FormData();
      data.append("text",text);
      data.append("csrfmiddlewaretoken",document.querySelector("[name='csrfmiddlewaretoken']")?.value||"");
      const response=await fetch(url,{method:"POST",credentials:"same-origin",body:data,
        headers:{"X-Requested-With":"XMLHttpRequest"}});
      const result=await response.json();
      if (popup.hidden||target!==editor||!body.isConnected) return;
      if (!response.ok||!result.ok||typeof result.markdown_html!=="string") throw new Error(result.error||"Не удалось показать Markdown.");
      if (!text.trim()) body.textContent="Нет текста для предпросмотра.";
      else window.SovietgramSocial.renderText(body,text,result.markdown_html);
      position();
    } catch(error) {
      if (body.isConnected) body.textContent=error.message||"Не удалось показать Markdown.";
    }
  }
  function drawEmoji() {
    const tabs=document.createElement("div");tabs.className="composer-emoji-tabs";
    const options=[["recent","🕘","Недавние"],...groups.map((group,index)=>[String(index),group.values[0],group.name])];
    for (const [id,emoji,name] of options) {
      const tab=button(emoji,name,()=>{category=id;drawEmoji();position();},"composer-emoji-tab");
      tab.setAttribute("aria-pressed",String(category===id));tabs.appendChild(tab);
    }
    const heading=document.createElement("strong");
    const group=groups[Number(category)];
    heading.textContent=category==="recent"?"Недавние":group?.name||"Эмодзи";
    const grid=document.createElement("div");grid.className="composer-emoji-grid";
    const values=category==="recent"?recents:group?.values||[];
    for (const emoji of values) {
      grid.appendChild(button(emoji,emoji,()=>{
        const editor=target;
        if (!editor||!apply(editor,insertEmoji(editor.value,editor.selectionStart,editor.selectionEnd,emoji))) return;
        recents=addRecent(recents,emoji);
        try { localStorage.setItem(recentKey,JSON.stringify(recents)); } catch (_error) {}
        if (category==="recent") {drawEmoji();position();}
      },"composer-emoji-option"));
    }
    if (!values.length) {
      const empty=document.createElement("small");empty.className="composer-emoji-empty";
      empty.textContent="Выберите эмодзи в одной из категорий.";grid.appendChild(empty);
    }
    popup.replaceChildren(tabs,heading,grid);
  }
  for (const node of triggers) {
    node.addEventListener("pointerdown",event=>event.preventDefault());
    node.addEventListener("click",event=>{
      if (trigger===node&&!popup.hidden) {close();return;}
      close();
      const editor=document.getElementById(node.dataset.composeTarget);
      if (!editor||editor.readOnly||editor.disabled) return;
      trigger=node;target=editor;panel=node.dataset.composePanel;
      node.setAttribute("aria-expanded","true");
      popup.setAttribute("aria-label",panel==="emoji"?"Эмодзи":"Форматирование текста");
      if (panel==="emoji") {
        if (category==="recent"&&!recents.length) category="0";
        drawEmoji();
      } else drawFormat();
      popup.hidden=false;position();
      if (event.detail===0) popup.querySelector("button")?.focus();
    });
  }
  document.addEventListener("pointerdown",event=>{
    if (!popup.hidden&&!popup.contains(event.target)&&!event.target.closest?.("[data-compose-panel]")) close();
  });
  document.addEventListener("keydown",event=>{
    if (event.key==="Escape"&&!popup.hidden) {
      event.preventDefault();event.stopImmediatePropagation();close(true);return;
    }
    if (!(event.ctrlKey||event.metaKey)||event.altKey||event.shiftKey||event.isComposing) return;
    const editor=event.target;
    if (!editor||!triggers.some(node=>node.dataset.composeTarget===editor.id)||editor.readOnly||editor.disabled) return;
    const name=({b:"bold",i:"italic",u:"underline"})[event.key.toLowerCase()];
    if (!name) return;
    event.preventDefault();event.stopImmediatePropagation();close();format(editor,name);
  },true);
  window.addEventListener("resize",position);
  document.addEventListener("scroll",position,true);
  document.addEventListener("submit",()=>close(),true);
  document.addEventListener("input",event=>{
    if (event.target===target && !popup.hidden && panel==="format") close();
  });
})();
