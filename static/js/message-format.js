/* Composer-only Markdown editing helpers. Rendering is server-side. */
(() => {
  const styles = {
    bold: ["**", "**"], italic: ["*", "*"], underline: ["++", "++"],
    strike: ["~~", "~~"], spoiler: ["||", "||"],
    code: ["\x60", "\x60"], block: ["\x60\x60\x60\n", "\n\x60\x60\x60"],
    link: ["[", "](https://example.com)"],
    image: ["![", "](https://example.com/image.png)"],
  };
  function sameMarkerRun(text, start, end, left, right) {
    if (left !== right || !["*", "**"].includes(left)) return true;
    const char = left[0];
    let a = 0, b = 0;
    for (let i = start-1; i >= 0 && text[i] === char; i--) a++;
    for (let i = end; i < text.length && text[i] === char; i++) b++;
    // A pair of stars is bold, not italic. Triple stars represent both.
    return a === b && (a === left.length || a === 3);
  }
  function lineSelection(text, start, end, prefix) {
    const first = start === 0 ? 0 : text.lastIndexOf("\n", start-1)+1;
    const boundary = Math.max(first, end>start&&text[end-1]==="\n"?end-1:end);
    const next = text.indexOf("\n", boundary), last = next===-1?text.length:next;
    const lines = text.slice(first,last).split("\n");
    const remove = lines.every(line=>line.startsWith(prefix));
    const replacement = lines.map((line,index)=>remove?line.slice(prefix.length):
      (prefix==="1. "?String(index+1)+". ":prefix)+line).join("\n");
    const caret=Math.max(first,start+(remove?-prefix.length:prefix.length));
    return {text:text.slice(0,first)+replacement+text.slice(last),
      start:start===end?caret:first,end:start===end?caret:first+replacement.length};
  }
  function wrapSelection(value,start,end,style) {
    const text=String(value??"");
    start=Math.max(0,Math.min(text.length,start));
    end=Math.max(start,Math.min(text.length,end));
    const linePrefixes={quote:"> ",heading:"## ",list:"- ",ordered:"1. ",task:"- [ ] "};
    if (linePrefixes[style]) return lineSelection(text,start,end,linePrefixes[style]);
    if (style==="rule"||style==="table") {
      const insert=style==="rule"?"---":"| Столбец 1 | Столбец 2 |\n| --- | --- |\n| Текст | Текст |";
      const before=start&&text[start-1]!=="\n"?"\n\n":"";
      const after=end<text.length&&text[end]!=="\n"?"\n\n":"";
      return {text:text.slice(0,start)+before+insert+after+text.slice(end),
        start:start+before.length,end:start+before.length+insert.length};
    }
    const pair=styles[style];
    if (!pair) return {text,start,end};
    const [left,right]=pair, selection=text.slice(start,end);
    if (style!=="link"&&style!=="image"&&start>=left.length &&
        text.slice(start-left.length,start)===left &&
        text.slice(end,end+right.length)===right &&
        sameMarkerRun(text,start,end,left,right)) {
      return {text:text.slice(0,start-left.length)+selection+text.slice(end+right.length),
        start:start-left.length,end:end-left.length};
    }
    if (style!=="link"&&style!=="image"&&selection.length>=left.length+right.length&&
        selection.startsWith(left)&&selection.endsWith(right)&&
        (style!=="italic"||!selection.startsWith("**"))&&
        (style!=="bold"||!selection.startsWith("***"))) {
      const inner=selection.slice(left.length,selection.length-right.length);
      return {text:text.slice(0,start)+inner+text.slice(end),start,end:start+inner.length};
    }
    return {text:text.slice(0,start)+left+selection+right+text.slice(end),
      start:start+left.length,end:end+left.length};
  }
  window.SovietgramFormat={wrapSelection};
})();
