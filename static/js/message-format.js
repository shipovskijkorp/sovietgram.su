/* Bounded message markup. Only text nodes and explicitly allowed tags. */
(() => {
  const styles = {
    bold: ["**", "**"], italic: ["*", "*"], underline: ["__", "__"],
    strike: ["~~", "~~"], spoiler: ["||", "||"],
    code: ["\x60", "\x60"], block: ["\x60\x60\x60\n", "\n\x60\x60\x60"],
  };
  const markers = [
    ["\x60\x60\x60", "block"], ["***", "boldItalic"], ["**", "bold"], ["__", "underline"],
    ["~~", "strike"], ["||", "spoiler"], ["\x60", "code"], ["*", "italic"],
  ];
  const escapable = /[\\*_~|\x60>]/;
  const protectedToken = /^(?:(?:https?:\/\/|www\.)[^\s<>"']+|[\p{L}\p{N}._%+-]+@[\p{L}\p{N}.-]+\.[\p{L}]{2,}|@[\p{L}\p{N}_][\p{L}\p{N}_.+-]*|#[\p{L}\p{N}_]+|(?:[\p{L}\p{N}][\p{L}\p{N}-]*\.)+[\p{L}]{2,}(?:[/:?#][^\s<>"']*)?)/iu;
  function escapedAt(text, index) {
    let count = 0;
    for (let i = index-1; i >= 0 && text[i] === "\\"; i--) count++;
    return count % 2 !== 0;
  }
  function closingIndex(text, marker, from, type) {
    let i = from;
    while ((i = text.indexOf(marker, i)) !== -1) {
      if (i > from && !escapedAt(text, i)) {
        if (type === "italic" && (text[i-1] === "*" || text[i+1] === "*")) {
          i += marker.length; continue;
        }
        // Three trailing stars can close inner italic and outer bold.
        if (type === "bold" && text[i+2] === "*" && text.slice(from,i).includes("*")) return i+1;
        return i;
      }
      i += marker.length;
    }
    return -1;
  }
  function parse(value, depth = 0, quotes = true) {
    const text = String(value ?? "");
    if (depth >= 5) return [{ kind: "text", text }];
    const result = [];
    let buffer = "";
    const flush = () => {
      if (buffer) result.push({ kind: "text", text: buffer });
      buffer = "";
    };
    for (let i=0; i<text.length;) {
      if (text[i] === "\\" && escapable.test(text[i+1] || "")) {
        buffer += text[i+1]; i += 2; continue;
      }
      if (quotes && (i===0 || text[i-1]==="\n") && text.startsWith("> ", i)) {
        flush();
        let end=text.indexOf("\n",i);
        if (end<0) end=text.length;
        const lines=[text.slice(i+2,end)];
        while (text.startsWith("> ",end+1)) {
          const start=end+1;
          end=text.indexOf("\n",start);
          if (end<0) end=text.length;
          lines.push(text.slice(start+2,end));
        }
        result.push({ kind:"quote", children:parse(lines.join("\n"),depth+1,false) });
        i=end; continue;
      }
      const match=markers.find(([marker])=>text.startsWith(marker,i));
      if (match) {
        const [marker,kind]=match;
        const start=i+marker.length, end=closingIndex(text,marker,start,kind);
        if (end>=0) {
          let content=text.slice(start,end);
          if (kind==="block") content=content.replace(/^\n|\n$/g,"");
          flush();
          if (["code","block","spoiler"].includes(kind)) result.push({kind,text:content});
          else result.push({kind,children:parse(content,depth+1,false)});
          i=end+marker.length; continue;
        }
        buffer+=marker; i+=marker.length; continue;
      }
      if ((i===0 || !/[\p{L}\p{N}_.+-]/u.test(text[i-1])) &&
          /[@#\p{L}\p{N}]/u.test(text[i])) {
        const token=protectedToken.exec(text.slice(i));
        if (token) { buffer+=token[0]; i+=token[0].length; continue; }
      }
      buffer+=text[i++];
    }
    flush();
    return result;
  }
  const tags={bold:"strong",italic:"em",underline:"u",strike:"s",code:"code",block:"code",quote:"span"};
  function renderNodes(parent,tokens,appendText) {
    for (const token of tokens) {
      if (token.kind==="text") { appendText(parent,token.text); continue; }
      if (token.kind==="spoiler") {
        const button=document.createElement("button");
        button.type="button";
        button.className="message-spoiler";
        button.textContent=token.text;
        button.setAttribute("aria-expanded","false");
        button.setAttribute("aria-label","Показать скрытый текст");
        button.addEventListener("click",()=>{
          const visible=button.getAttribute("aria-expanded")==="true";
          button.setAttribute("aria-expanded",String(!visible));
          button.setAttribute("aria-label",visible?"Показать скрытый текст":token.text+". Скрыть текст");
        });
        parent.appendChild(button);
        continue;
      }
      if (token.kind==="boldItalic") {
        const strong=document.createElement("strong"), em=document.createElement("em");
        renderNodes(em,token.children,appendText);
        strong.appendChild(em);parent.appendChild(strong);continue;
      }
      const node=document.createElement(tags[token.kind]);
      if (token.kind==="block") node.className="message-code-block";
      if (token.kind==="quote") node.className="message-quote";
      if (token.children) renderNodes(node,token.children,appendText);
      else node.textContent=token.text;
      parent.appendChild(node);
    }
  }
  function render(parent,text,appendText) { renderNodes(parent,parse(text),appendText); }
  function wrapSelection(value,start,end,style) {
    const text=String(value??"");
    start=Math.max(0,Math.min(text.length,start));
    end=Math.max(start,Math.min(text.length,end));
    if (style==="quote") {
      const first=start===0?0:text.lastIndexOf("\n",start-1)+1;
      const boundary=Math.max(first,end>start&&text[end-1]==="\n"?end-1:end);
      const next=text.indexOf("\n",boundary), last=next===-1?text.length:next;
      const lines=text.slice(first,last).split("\n");
      const remove=lines.every(line=>line.startsWith("> "));
      const replacement=lines.map(line=>remove?line.slice(2):"> "+line).join("\n");
      const caret=Math.max(first,start+(remove?-2:2));
      return {text:text.slice(0,first)+replacement+text.slice(last),
        start:start===end?caret:first,end:start===end?caret:first+replacement.length};
    }
    const pair=styles[style];
    if (!pair) return {text,start,end};
    const [left,right]=pair, selection=text.slice(start,end);
    if (start>=left.length && text.slice(start-left.length,start)===left &&
        text.slice(end,end+right.length)===right) {
      return {text:text.slice(0,start-left.length)+selection+text.slice(end+right.length),
        start:start-left.length,end:end-left.length};
    }
    if (selection.length>=left.length+right.length && selection.startsWith(left)&&selection.endsWith(right)) {
      const inner=selection.slice(left.length,selection.length-right.length);
      return {text:text.slice(0,start)+inner+text.slice(end),start,end:start+inner.length};
    }
    return {text:text.slice(0,start)+left+selection+right+text.slice(end),
      start:start+left.length,end:end+left.length};
  }
  window.SovietgramFormat={parse,render,wrapSelection};
})();
