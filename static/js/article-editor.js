(() => {
  const conversation = document.querySelector(".conversation--chat");
  const modal = document.getElementById("attachSpecialBackdrop");
  const titleInput = document.getElementById("attachArticleTitle");
  const subtitleInput = document.getElementById("attachArticleSubtitle");
  const bodyInput = document.getElementById("attachArticleBody");
  const toolbar = document.getElementById("attachArticleToolbar");
  const previewToggle = document.getElementById("attachArticlePreviewToggle");
  const sourceWrap = document.getElementById("attachArticleSourceWrap");
  const preview = document.getElementById("attachArticlePreview");
  const counter = document.getElementById("attachArticleCounter");
  const sendButton = document.getElementById("attachSpecialSend");
  const modalTitle = document.getElementById("attachSpecialTitle");
  const hint = document.getElementById("attachSpecialHint");
  const csrfToken = document.querySelector("#messageForm [name='csrfmiddlewaretoken']")?.value || "";

  const viewer = document.getElementById("articleViewerBackdrop");
  const viewerClose = document.getElementById("articleViewerClose");
  const viewerTitle = document.getElementById("articleViewerTitle");
  const viewerSubtitle = document.getElementById("articleViewerSubtitle");
  const viewerBody = document.getElementById("articleViewerBody");
  const viewerEdit = document.getElementById("articleViewerEdit");

  if (!conversation || !modal || !titleInput || !bodyInput) return;

  const tick = String.fromCharCode(96);
  let editState = null;
  let viewedCard = null;
  let previewMode = false;
  let busy = false;
  let history = [];
  let historyIndex = -1;
  let historyTimer = 0;

  function notify(text) {
    if (typeof window.showToast === "function") window.showToast(text);
    else if (typeof showToast === "function") showToast(text);
  }

  function articlePanel() {
    return document.querySelector("[data-special-panel='article']");
  }

  function articlePanelVisible() {
    const panel = articlePanel();
    return Boolean(panel && !panel.hidden && !modal.hidden);
  }

  function snapshot() {
    return {
      title: titleInput.value || "",
      subtitle: subtitleInput?.value || "",
      body: bodyInput.value || "",
    };
  }

  function sameState(a, b) {
    return a && b && a.title === b.title && a.subtitle === b.subtitle && a.body === b.body;
  }

  function pushHistory(force = false) {
    const state = snapshot();
    if (!force && sameState(state, history[historyIndex])) return;
    history = history.slice(0, historyIndex + 1);
    history.push(state);
    if (history.length > 80) history.shift();
    historyIndex = history.length - 1;
  }

  function scheduleHistory() {
    window.clearTimeout(historyTimer);
    historyTimer = window.setTimeout(() => pushHistory(), 250);
  }

  function restore(state) {
    if (!state) return;
    titleInput.value = state.title;
    if (subtitleInput) subtitleInput.value = state.subtitle;
    bodyInput.value = state.body;
    updateCounter();
    if (previewMode) renderPreview();
  }

  function undo() {
    pushHistory();
    if (historyIndex <= 0) return;
    historyIndex -= 1;
    restore(history[historyIndex]);
  }

  function redo() {
    if (historyIndex >= history.length - 1) return;
    historyIndex += 1;
    restore(history[historyIndex]);
  }

  function resetHistory() {
    history = [];
    historyIndex = -1;
    pushHistory(true);
  }

  function updateCounter() {
    if (counter) counter.textContent = String(bodyInput.value.length);
  }

  function setPreviewMode(next) {
    previewMode = Boolean(next);
    if (sourceWrap) sourceWrap.hidden = previewMode;
    if (preview) preview.hidden = !previewMode;
    if (previewToggle) previewToggle.textContent = previewMode ? "Редактировать" : "Предпросмотр";
    if (previewMode) renderPreview();
    else window.setTimeout(() => bodyInput.focus(), 0);
  }

  function selection() {
    return {
      start: bodyInput.selectionStart || 0,
      end: bodyInput.selectionEnd || 0,
      text: bodyInput.value.slice(bodyInput.selectionStart || 0, bodyInput.selectionEnd || 0),
    };
  }

  function replaceRange(start, end, value, selectStart = null, selectEnd = null) {
    bodyInput.focus();
    bodyInput.setRangeText(value, start, end, "end");
    const from = selectStart == null ? start + value.length : selectStart;
    const to = selectEnd == null ? from : selectEnd;
    bodyInput.setSelectionRange(from, to);
    updateCounter();
    pushHistory();
    if (previewMode) renderPreview();
  }

  function wrap(prefix, suffix, placeholder) {
    const range = selection();
    const chosen = range.text || placeholder;
    const value = prefix + chosen + suffix;
    replaceRange(
      range.start,
      range.end,
      value,
      range.start + prefix.length,
      range.start + prefix.length + chosen.length,
    );
  }

  function transformLines(transform) {
    const value = bodyInput.value;
    const range = selection();
    const start = value.lastIndexOf("\n", Math.max(0, range.start - 1)) + 1;
    let end = value.indexOf("\n", range.end);
    if (end < 0) end = value.length;
    const lines = value.slice(start, end).split("\n");
    const result = lines.map(transform).join("\n");
    replaceRange(start, end, result, start, start + result.length);
  }

  function insertBlock(value) {
    const range = selection();
    const before = bodyInput.value.slice(0, range.start);
    const after = bodyInput.value.slice(range.end);
    const lead = before && !before.endsWith("\n") ? "\n" : "";
    const trail = after && !after.startsWith("\n") ? "\n" : "";
    replaceRange(
      range.start,
      range.end,
      lead + value + trail,
      range.start + lead.length,
      range.start + lead.length + value.length,
    );
  }

  function command(name) {
    if (name === "undo") return undo();
    if (name === "redo") return redo();
    if (name === "bold") return wrap("**", "**", "жирный текст");
    if (name === "italic") return wrap("*", "*", "курсив");
    if (name === "underline") return wrap("__", "__", "подчёркнутый текст");
    if (name === "strike") return wrap("~~", "~~", "зачёркнутый текст");
    if (name === "subscript") return wrap("~", "~", "нижний индекс");
    if (name === "superscript") return wrap("^", "^", "верхний индекс");
    if (name === "marked") return wrap("==", "==", "выделенный текст");
    if (name === "spoiler") return wrap("||", "||", "спойлер");
    if (name === "code-inline") return wrap(tick, tick, "код");
    if (name === "math") return wrap("$", "$", "x^2 + y^2");
    if (name === "plain") {
      const range = selection();
      if (!range.text) return;
      const clean = range.text
        .replace(/\*\*|__|~~|\|\||==/g, "")
        .replace(/(^|\s)[*~^$](?=\S)|(?<=\S)[*~^$](?=\s|$)/g, "$1")
        .split(tick).join("");
      return replaceRange(range.start, range.end, clean, range.start, range.start + clean.length);
    }
    if (/^h[1-6]$/.test(name)) {
      const level = Number(name.slice(1));
      return transformLines((line) => "#".repeat(level) + " " + line.replace(/^#{1,6}\s+/, ""));
    }
    if (name === "quote") return transformLines((line) => "> " + line.replace(/^>+\s?/, ""));
    if (name === "pullquote") return transformLines((line) => ">> " + line.replace(/^>+\s?/, ""));
    if (name === "bullet-list") return transformLines((line) => "- " + line.replace(/^[-*]\s+/, ""));
    if (name === "ordered-list") return transformLines((line, index) => String(index + 1) + ". " + line.replace(/^\d+\.\s+/, ""));
    if (name === "task-list") return transformLines((line) => "- [ ] " + line.replace(/^-\s+\[[ xX]\]\s+/, ""));
    if (name === "code-block") return wrap(tick + tick + tick + "\n", "\n" + tick + tick + tick, "код");
    if (name === "details") {
      return insertBlock(":::details Заголовок\nСкрываемый текст\n:::");
    }
    if (name === "divider") return insertBlock("---");
    if (name === "table") {
      return insertBlock(
        "| Колонка 1 | Колонка 2 |\n"
        + "| --- | --- |\n"
        + "| Значение 1 | Значение 2 |"
      );
    }
    if (name === "link") {
      const range = selection();
      const label = range.text || "текст ссылки";
      const value = window.prompt("Ссылка (https://…):", "https://");
      if (!value) return;
      let url;
      try {
        url = new URL(value);
      } catch (_error) {
        notify("Некорректная ссылка.");
        return;
      }
      if (url.protocol !== "http:" && url.protocol !== "https:") {
        notify("Разрешены только http/https ссылки.");
        return;
      }
      return replaceRange(range.start, range.end, "[" + label + "](" + url.href + ")");
    }
    if (name === "image") {
      const value = window.prompt("Ссылка на изображение (https://…):", "https://");
      if (!value) return;
      let url;
      try {
        url = new URL(value);
      } catch (_error) {
        notify("Некорректная ссылка.");
        return;
      }
      if (url.protocol !== "http:" && url.protocol !== "https:") {
        notify("Разрешены только http/https ссылки.");
        return;
      }
      const alt = window.prompt("Подпись изображения:", "Изображение") || "Изображение";
      return insertBlock("![" + alt.replace(/[\[\]]/g, "") + "](" + url.href + ")");
    }
    if (name === "location") {
      const lat = Number(window.prompt("Широта:", ""));
      if (!Number.isFinite(lat) || lat < -90 || lat > 90) return notify("Некорректная широта.");
      const lon = Number(window.prompt("Долгота:", ""));
      if (!Number.isFinite(lon) || lon < -180 || lon > 180) return notify("Некорректная долгота.");
      const label = (window.prompt("Название места:", "Геопозиция") || "Геопозиция").replace(/[(),]/g, " ");
      return insertBlock("@geo(" + lat.toFixed(6) + "," + lon.toFixed(6) + "," + label + ")");
    }
  }

  function appendInline(parent, source) {
    const patterns = [
      { type: "image", regex: /!\[([^\]\n]*)\]\((https?:\/\/[^\s)]+)\)/ },
      { type: "link", regex: /\[([^\]\n]+)\]\((https?:\/\/[^\s)]+)\)/ },
      { type: "bold", regex: /\*\*([^*\n]+)\*\*/ },
      { type: "underline", regex: /__([^_\n]+)__/ },
      { type: "strike", regex: /~~([^~\n]+)~~/ },
      { type: "marked", regex: /==([^=\n]+)==/ },
      { type: "spoiler", regex: /\|\|([^|\n]+)\|\|/ },
      { type: "code", regex: new RegExp(tick + "([^" + tick + "\\n]+)" + tick) },
      { type: "math", regex: /\$([^$\n]+)\$/ },
      { type: "sup", regex: /\^([^\^\n]+)\^/ },
      { type: "sub", regex: /~([^~\n]+)~/ },
      { type: "italic", regex: /\*([^*\n]+)\*/ },
    ];

    let cursor = 0;
    while (cursor < source.length) {
      let best = null;
      const tail = source.slice(cursor);
      patterns.forEach((pattern) => {
        const match = pattern.regex.exec(tail);
        if (!match) return;
        const index = cursor + match.index;
        if (!best || index < best.index || (index === best.index && match[0].length > best.match[0].length)) {
          best = { type: pattern.type, match, index };
        }
      });

      if (!best) {
        parent.appendChild(document.createTextNode(source.slice(cursor)));
        break;
      }
      if (best.index > cursor) {
        parent.appendChild(document.createTextNode(source.slice(cursor, best.index)));
      }

      let node;
      if (best.type === "image") {
        node = document.createElement("img");
        node.className = "article-embedded-image";
        node.src = best.match[2];
        node.alt = best.match[1] || "Изображение";
        node.loading = "lazy";
        node.referrerPolicy = "no-referrer";
      } else if (best.type === "link") {
        node = document.createElement("a");
        node.href = best.match[2];
        node.target = "_blank";
        node.rel = "noopener noreferrer";
        node.textContent = best.match[1];
      } else if (best.type === "bold") {
        node = document.createElement("strong");
        node.textContent = best.match[1];
      } else if (best.type === "underline") {
        node = document.createElement("u");
        node.textContent = best.match[1];
      } else if (best.type === "strike") {
        node = document.createElement("s");
        node.textContent = best.match[1];
      } else if (best.type === "marked") {
        node = document.createElement("mark");
        node.textContent = best.match[1];
      } else if (best.type === "spoiler") {
        node = document.createElement("span");
        node.className = "article-spoiler";
        node.textContent = best.match[1];
        node.tabIndex = 0;
        node.title = "Показать спойлер";
      } else if (best.type === "code") {
        node = document.createElement("code");
        node.textContent = best.match[1];
      } else if (best.type === "math") {
        node = document.createElement("span");
        node.className = "article-math";
        node.textContent = best.match[1];
      } else if (best.type === "sup") {
        node = document.createElement("sup");
        node.textContent = best.match[1];
      } else if (best.type === "sub") {
        node = document.createElement("sub");
        node.textContent = best.match[1];
      } else {
        node = document.createElement("em");
        node.textContent = best.match[1];
      }

      parent.appendChild(node);
      cursor = best.index + best.match[0].length;
    }
  }

  function isTableSeparator(line) {
    return /^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?\s*$/.test(line);
  }

  function splitTableRow(line) {
    return line.trim().replace(/^\|/, "").replace(/\|$/, "").split("|").map((cell) => cell.trim());
  }

  function renderMarkdown(source, target) {
    if (!target) return;
    target.replaceChildren();
    const lines = String(source || "").replace(/\r\n?/g, "\n").split("\n");
    let index = 0;

    while (index < lines.length) {
      const line = lines[index];
      if (!line.trim()) {
        index += 1;
        continue;
      }

      if (line.startsWith(tick + tick + tick)) {
        const language = line.slice(3).trim();
        index += 1;
        const values = [];
        while (index < lines.length && !lines[index].startsWith(tick + tick + tick)) {
          values.push(lines[index]);
          index += 1;
        }
        if (index < lines.length) index += 1;
        const pre = document.createElement("pre");
        pre.className = "article-code-block";
        const code = document.createElement("code");
        if (language) code.dataset.language = language;
        code.textContent = values.join("\n");
        pre.appendChild(code);
        target.appendChild(pre);
        continue;
      }

      if (/^:::details\s*/.test(line)) {
        const details = document.createElement("details");
        details.className = "article-details";
        const summary = document.createElement("summary");
        summary.textContent = line.replace(/^:::details\s*/, "").trim() || "Подробнее";
        details.appendChild(summary);
        index += 1;
        const content = [];
        while (index < lines.length && lines[index].trim() !== ":::") {
          content.push(lines[index]);
          index += 1;
        }
        if (index < lines.length) index += 1;
        const inner = document.createElement("div");
        renderMarkdown(content.join("\n"), inner);
        details.appendChild(inner);
        target.appendChild(details);
        continue;
      }

      const geo = line.match(/^@geo\((-?\d+(?:\.\d+)?),(-?\d+(?:\.\d+)?),(.+)\)$/);
      if (geo) {
        const lat = Number(geo[1]);
        const lon = Number(geo[2]);
        if (Number.isFinite(lat) && Number.isFinite(lon) && lat >= -90 && lat <= 90 && lon >= -180 && lon <= 180) {
          const link = document.createElement("a");
          link.className = "article-location";
          link.target = "_blank";
          link.rel = "noopener noreferrer";
          link.href = "https://www.openstreetmap.org/?mlat=" + encodeURIComponent(lat)
            + "&mlon=" + encodeURIComponent(lon)
            + "#map=16/" + encodeURIComponent(lat) + "/" + encodeURIComponent(lon);
          const pin = document.createElement("span");
          pin.textContent = "⌖";
          const copy = document.createElement("span");
          const strong = document.createElement("strong");
          strong.textContent = geo[3].trim();
          const small = document.createElement("small");
          small.textContent = lat + ", " + lon;
          copy.append(strong, small);
          link.append(pin, copy);
          target.appendChild(link);
        }
        index += 1;
        continue;
      }

      const heading = line.match(/^(#{1,6})\s+(.+)$/);
      if (heading) {
        const node = document.createElement("h" + String(heading[1].length));
        appendInline(node, heading[2]);
        target.appendChild(node);
        index += 1;
        continue;
      }

      if (/^>>\s?/.test(line)) {
        const quote = document.createElement("blockquote");
        quote.className = "article-pullquote";
        while (index < lines.length && /^>>\s?/.test(lines[index])) {
          if (quote.childNodes.length) quote.appendChild(document.createElement("br"));
          appendInline(quote, lines[index].replace(/^>>\s?/, ""));
          index += 1;
        }
        target.appendChild(quote);
        continue;
      }

      if (/^>\s?/.test(line)) {
        const quote = document.createElement("blockquote");
        while (index < lines.length && /^>\s?/.test(lines[index]) && !/^>>\s?/.test(lines[index])) {
          if (quote.childNodes.length) quote.appendChild(document.createElement("br"));
          appendInline(quote, lines[index].replace(/^>\s?/, ""));
          index += 1;
        }
        target.appendChild(quote);
        continue;
      }

      if (/^-\s+\[[ xX]\]\s+/.test(line)) {
        const list = document.createElement("ul");
        list.className = "article-task-list";
        while (index < lines.length && /^-\s+\[[ xX]\]\s+/.test(lines[index])) {
          const match = lines[index].match(/^-\s+\[([ xX])\]\s+(.+)$/);
          const item = document.createElement("li");
          if (match && match[1].toLowerCase() === "x") item.classList.add("is-done");
          const marker = document.createElement("span");
          marker.className = "article-task-mark";
          marker.textContent = item.classList.contains("is-done") ? "✓" : "";
          const copy = document.createElement("span");
          appendInline(copy, match?.[2] || "");
          item.append(marker, copy);
          list.appendChild(item);
          index += 1;
        }
        target.appendChild(list);
        continue;
      }

      if (/^[-*]\s+/.test(line)) {
        const list = document.createElement("ul");
        while (index < lines.length && /^[-*]\s+/.test(lines[index])) {
          const item = document.createElement("li");
          appendInline(item, lines[index].replace(/^[-*]\s+/, ""));
          list.appendChild(item);
          index += 1;
        }
        target.appendChild(list);
        continue;
      }

      if (/^\d+\.\s+/.test(line)) {
        const list = document.createElement("ol");
        while (index < lines.length && /^\d+\.\s+/.test(lines[index])) {
          const item = document.createElement("li");
          appendInline(item, lines[index].replace(/^\d+\.\s+/, ""));
          list.appendChild(item);
          index += 1;
        }
        target.appendChild(list);
        continue;
      }

      if (/^-{3,}\s*$/.test(line)) {
        target.appendChild(document.createElement("hr"));
        index += 1;
        continue;
      }

      if (line.includes("|") && isTableSeparator(lines[index + 1] || "")) {
        const table = document.createElement("table");
        const thead = document.createElement("thead");
        const tbody = document.createElement("tbody");
        const headerRow = document.createElement("tr");
        splitTableRow(line).forEach((cell) => {
          const th = document.createElement("th");
          appendInline(th, cell);
          headerRow.appendChild(th);
        });
        thead.appendChild(headerRow);
        table.appendChild(thead);
        index += 2;

        while (index < lines.length && lines[index].includes("|") && lines[index].trim()) {
          const row = document.createElement("tr");
          splitTableRow(lines[index]).forEach((cell) => {
            const td = document.createElement("td");
            appendInline(td, cell);
            row.appendChild(td);
          });
          tbody.appendChild(row);
          index += 1;
        }
        table.appendChild(tbody);
        target.appendChild(table);
        continue;
      }

      const paragraph = document.createElement("p");
      appendInline(paragraph, line);
      index += 1;
      while (
        index < lines.length
        && lines[index].trim()
        && !/^#{1,6}\s+/.test(lines[index])
        && !/^>\s?/.test(lines[index])
        && !/^[-*]\s+/.test(lines[index])
        && !/^\d+\.\s+/.test(lines[index])
        && !/^-{3,}\s*$/.test(lines[index])
        && !/^:::details\s*/.test(lines[index])
        && !/^@geo\(/.test(lines[index])
        && !lines[index].startsWith(tick + tick + tick)
        && !(lines[index].includes("|") && isTableSeparator(lines[index + 1] || ""))
      ) {
        paragraph.appendChild(document.createElement("br"));
        appendInline(paragraph, lines[index]);
        index += 1;
      }
      target.appendChild(paragraph);
    }
  }

  function renderPreview() {
    renderMarkdown(bodyInput.value, preview);
  }

  function articleData(card) {
    const source = card?.querySelector(".message-article__source");
    return {
      title: card?.querySelector(".message-special__title")?.textContent?.trim() || "Статья",
      subtitle: card?.querySelector(".message-article__subtitle")?.textContent?.trim() || "",
      body: source?.value ?? source?.textContent ?? "",
      actionUrl: card?.dataset.articleActionUrl || card?.dataset.actionUrl || "",
      canEdit: card?.dataset.articleCanEdit === "true",
    };
  }

  function closeViewer() {
    if (viewer) viewer.hidden = true;
    viewedCard = null;
  }

  function openViewer(card) {
    if (!viewer || !card) return;
    const data = articleData(card);
    viewedCard = card;
    if (viewerTitle) viewerTitle.textContent = data.title;
    if (viewerSubtitle) {
      viewerSubtitle.textContent = data.subtitle;
      viewerSubtitle.hidden = !data.subtitle;
    }
    renderMarkdown(data.body, viewerBody);
    if (viewerEdit) viewerEdit.hidden = !data.canEdit;
    viewer.hidden = false;
  }

  function configureEditor(initial = null, edit = null) {
    editState = edit;
    titleInput.value = initial?.title || "";
    if (subtitleInput) subtitleInput.value = initial?.subtitle || "";
    bodyInput.value = initial?.body || "";
    setPreviewMode(false);
    updateCounter();
    resetHistory();
    if (modalTitle) modalTitle.textContent = edit ? "Редактирование статьи" : "Новая статья";
    if (sendButton) sendButton.textContent = edit ? "Сохранить" : "Отправить";
    if (hint) hint.textContent = "Форматирование, ссылки, код, цитаты, списки, задачи, таблицы и предпросмотр.";
  }

  function showArticleEditor(initial = null, edit = null) {
    document.querySelectorAll("[data-special-panel]").forEach((panel) => {
      panel.hidden = panel.dataset.specialPanel !== "article";
    });
    configureEditor(initial, edit);
    modal.hidden = false;
    window.SovietgramAttachmentMenu?.close();
    window.setTimeout(() => titleInput.focus(), 0);
  }

  function openEditorFromCard(card) {
    const data = articleData(card);
    if (!data.canEdit || !data.actionUrl) return;
    closeViewer();
    showArticleEditor(
      { title: data.title, subtitle: data.subtitle, body: data.body },
      { actionUrl: data.actionUrl },
    );
  }

  function articleExcerpt(source) {
    const plain = String(source || "")
      .replace(/!\[([^\]]*)\]\([^)]+\)/g, "$1")
      .replace(/\[([^\]]+)\]\([^)]+\)/g, "$1")
      .replace(/@geo\([^)]*\)/g, " Геопозиция ")
      .replace(/:::details[^\n]*/g, " ")
      .replace(/[*_~|>#\[\]^=$-]/g, " ")
      .replace(/\s+/g, " ")
      .trim();
    return plain.length > 360 ? plain.slice(0, 359) + "…" : plain;
  }

  function buildArticleCard(data) {
    const card = document.createElement("section");
    card.className = "message-special message-article";
    card.dataset.specialMessage = "";
    card.dataset.specialType = "article";
    card.dataset.articleActionUrl = data.action_url || "";
    card.dataset.articleCanEdit = data.can_edit ? "true" : "false";
    card.dataset.actionUrl = data.action_url || "";

    const eyebrow = document.createElement("small");
    eyebrow.className = "message-special__eyebrow";
    eyebrow.textContent = "Статья";
    const title = document.createElement("strong");
    title.className = "message-special__title";
    title.textContent = data.title || "Статья";
    card.append(eyebrow, title);

    if (data.subtitle) {
      const subtitle = document.createElement("span");
      subtitle.className = "message-article__subtitle";
      subtitle.textContent = data.subtitle;
      card.appendChild(subtitle);
    }

    const excerpt = document.createElement("p");
    excerpt.className = "message-article__excerpt";
    excerpt.textContent = articleExcerpt(data.body || "");
    card.appendChild(excerpt);

    const source = document.createElement("textarea");
    source.className = "message-article__source";
    source.hidden = true;
    source.value = data.body || "";
    card.appendChild(source);

    const open = document.createElement("button");
    open.type = "button";
    open.className = "message-article__open";
    open.dataset.articleOpen = "";
    open.textContent = "Открыть статью";
    card.appendChild(open);

    if (data.can_edit) {
      const edit = document.createElement("button");
      edit.type = "button";
      edit.className = "message-article__edit";
      edit.dataset.articleEdit = "";
      edit.textContent = "Изменить";
      card.appendChild(edit);
    }
    return card;
  }

  const previousBuilder = window.buildSovietgramSpecialMessage;
  window.buildSovietgramSpecialMessage = (data) => {
    if (data?.type === "article") return buildArticleCard(data);
    return typeof previousBuilder === "function" ? previousBuilder(data) : null;
  };
  window.renderSovietgramArticleMarkdown = renderMarkdown;

  async function postArticle() {
    if (!articlePanelVisible() || busy) return;
    const payload = {
      title: titleInput.value.trim(),
      subtitle: subtitleInput?.value.trim() || "",
      body: bodyInput.value.trim(),
    };
    if (!payload.title) return notify("Введите заголовок статьи.");
    if (!payload.body) return notify("Введите текст статьи.");
    if (payload.body.length > 40000) return notify("Текст статьи превышает 40 000 символов.");

    busy = true;
    sendButton.disabled = true;
    sendButton.textContent = editState ? "Сохранение…" : "Отправка…";

    const data = new FormData();
    data.append("csrfmiddlewaretoken", csrfToken);
    data.append("payload", JSON.stringify(payload));

    let url;
    if (editState?.actionUrl) {
      url = editState.actionUrl;
      data.append("action", "edit");
    } else {
      url = conversation.dataset.specialSendUrl;
      data.append("special_type", "article");
      const reply = document.getElementById("replyToInput")?.value;
      if (reply) data.append("reply_to", reply);
    }

    try {
      const response = await fetch(url, {
        method: "POST",
        credentials: "same-origin",
        headers: { "X-Requested-With": "XMLHttpRequest" },
        body: data,
      });
      const result = await response.json().catch(() => ({}));
      if (!response.ok || !result.ok) throw new Error(result.error || "Не удалось сохранить статью.");

      if (editState?.actionUrl) {
        window.updateSovietgramChatMessage?.(result.message);
        notify("Статья обновлена.");
      } else {
        window.renderSovietgramChatMessage?.(result.message);
        const replyInput = document.getElementById("replyToInput");
        const replyBox = document.getElementById("composerReply");
        if (replyInput) replyInput.value = "";
        if (replyBox) replyBox.hidden = true;
      }

      modal.hidden = true;
      editState = null;
    } catch (error) {
      notify(error.message);
    } finally {
      busy = false;
      sendButton.disabled = false;
      sendButton.textContent = editState ? "Сохранить" : "Отправить";
    }
  }

  // Let the existing special-message controller open a fresh article, then
  // initialize the extra Telegram-style editor state after its reset.
  document.addEventListener("click", (event) => {
    const newArticle = event.target.closest?.("[data-attach-special='article']");
    if (newArticle) {
      editState = null;
      window.setTimeout(() => configureEditor(null, null), 0);
      return;
    }

    const open = event.target.closest?.("[data-article-open]");
    if (open) {
      event.preventDefault();
      openViewer(open.closest("[data-special-type='article']"));
      return;
    }

    const edit = event.target.closest?.("[data-article-edit]");
    if (edit) {
      event.preventDefault();
      openEditorFromCard(edit.closest("[data-special-type='article']"));
      return;
    }

    const spoiler = event.target.closest?.(".article-spoiler");
    if (spoiler) {
      spoiler.classList.toggle("is-revealed");
    }
  });

  // Capture the send button only while the article panel is active so the
  // older generic special-message handler cannot submit a reduced payload.
  document.addEventListener("click", (event) => {
    if (!event.target.closest?.("#attachSpecialSend") || !articlePanelVisible()) return;
    event.preventDefault();
    event.stopImmediatePropagation();
    postArticle();
  }, true);

  toolbar?.addEventListener("click", (event) => {
    const button = event.target.closest("[data-article-command]");
    if (!button) return;
    event.preventDefault();
    command(button.dataset.articleCommand || "");
  });

  previewToggle?.addEventListener("click", () => setPreviewMode(!previewMode));
  [titleInput, subtitleInput, bodyInput].forEach((field) => {
    field?.addEventListener("input", () => {
      updateCounter();
      scheduleHistory();
      if (previewMode) renderPreview();
    });
  });

  bodyInput.addEventListener("keydown", (event) => {
    if (!(event.ctrlKey || event.metaKey)) return;
    const key = event.key.toLowerCase();
    if (key === "b" || key === "i" || key === "u") {
      event.preventDefault();
      command(key === "b" ? "bold" : key === "i" ? "italic" : "underline");
      return;
    }
    if (key === "z" && !event.shiftKey) {
      event.preventDefault();
      undo();
      return;
    }
    if (key === "y" || (key === "z" && event.shiftKey)) {
      event.preventDefault();
      redo();
    }
  });

  viewerClose?.addEventListener("click", closeViewer);
  viewer?.addEventListener("click", (event) => {
    if (event.target === viewer) closeViewer();
  });
  viewerEdit?.addEventListener("click", () => {
    if (viewedCard) openEditorFromCard(viewedCard);
  });

  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && viewer && !viewer.hidden) {
      event.preventDefault();
      closeViewer();
    }
  });
})();
