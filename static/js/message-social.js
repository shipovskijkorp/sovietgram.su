/* Shared renderer, reaction controls, and member mention autocomplete. */
(() => {
  const stage = document.getElementById("messageStage");
  const profilePrefix = stage?.dataset.mentionProfilePrefix || "/u/";
  // Consume URLs/email addresses before @mentions or #hashtags so their
  // fragments are never accidentally treated as social tokens.
  const tokenPattern = /https?:\/\/[^\s<>"']+|www\.[^\s<>"']+|[\p{L}\p{N}._%+-]+@[\p{L}\p{N}.-]+\.[\p{L}]{2,}|(?<![\p{L}\p{N}_@.+/-])@[\p{L}\p{N}_](?:[\p{L}\p{N}_.+-]*[\p{L}\p{N}_+-])?|(?<![\p{L}\p{N}_#/@])#[\p{L}\p{N}_]+|(?<![\p{L}\p{N}_@.-])(?:[\p{L}\p{N}][\p{L}\p{N}-]*\.)+[\p{L}]{2,}(?:[/:?#][^\s<>"']*)?/giu;

  function tokenize(text) {
    const tokens = [];
    let cursor = 0;
    text = String(text || "");
    for (const match of text.matchAll(tokenPattern)) {
      if (match.index > cursor) tokens.push({ kind: "text", value: text.slice(cursor, match.index) });
      let value = match[0];
      let kind = value.startsWith("@") ? "mention" : value.startsWith("#") ? "hashtag" : "url";
      if (kind === "url") value = value.replace(/[.,!?;:)}\]]+$/, "");
      if (kind === "mention" && value.length > 151) kind = "text";
      if (kind === "hashtag" && value.length > 120) kind = "text";
      if (value) tokens.push({ kind, value });
      const trailing = match[0].slice(value.length);
      if (trailing) tokens.push({ kind: "text", value: trailing });
      cursor = match.index + match[0].length;
    }
    if (cursor < text.length) tokens.push({ kind: "text", value: text.slice(cursor) });
    return tokens;
  }

  function appendSocialText(element, value) {
    for (const token of tokenize(value)) {
      if (token.kind === "text") {
        element.appendChild(document.createTextNode(token.value));
      } else if (token.kind === "hashtag") {
        const button = document.createElement("button");
        button.type = "button";
        button.className = "message-hashtag";
        button.dataset.messageHashtag = token.value;
        button.textContent = token.value;
        element.appendChild(button);
      } else {
        const link = document.createElement("a");
        if (token.kind === "mention") {
          link.href = profilePrefix + encodeURIComponent(token.value.slice(1)) + "/";
          link.dataset.userProfile = "";
        } else {
          link.href = /^https?:\/\//i.test(token.value)
            ? token.value : token.value.includes("@") && !token.value.includes("/")
              ? "mailto:" + token.value : "https://" + token.value;
          link.target = "_blank";
          link.rel = "noopener noreferrer";
        }
        link.textContent = token.value;
        element.appendChild(link);
      }
    }
  }

  function renderText(element, text, markdownHtml) {
    const value = String(text || "");
    const serverRendered = typeof markdownHtml === "string";
    if (element.dataset.socialText === value &&
        (!serverRendered || element.dataset.markdownRendered === "true")) return;
    if (serverRendered) {
      // Only the server's independent Markdown renderer + sanitizer may
      // provide HTML. Never substitute the raw message or draft here.
      element.innerHTML = markdownHtml;
      element.dataset.markdownRendered = "true";
    } else {
      element.replaceChildren();
      appendSocialText(element, value);
      delete element.dataset.markdownRendered;
    }
    element.dataset.socialText = value;
  }

  function renderReactions(article, message) {
    if (!Array.isArray(message?.reactions)) return;
    const version = Number(message.reaction_version) || 0;
    const previous = article.dataset.reactionVersion === undefined
      ? -1 : Number(article.dataset.reactionVersion);
    // A late poll must never roll back a more recent local response.
    if (version <= previous) return;
    let container = article.querySelector("[data-message-reactions]");
    if (!container) {
      container = document.createElement("div");
      container.className = "message-reactions";
      container.dataset.messageReactions = "";
      article.insertBefore(container, article.querySelector("footer"));
    }
    const buttons = message.reactions.filter(item => item.count > 0).map(item => {
      const button = document.createElement("button");
      button.className = "message-reaction";
      button.type = "button";
      button.dataset.messageReaction = item.emoji;
      button.setAttribute("aria-pressed", String(Boolean(item.selected)));
      button.setAttribute("aria-label", item.emoji + " · " + item.count);
      const emoji = document.createElement("span");
      emoji.textContent = item.emoji;
      const count = document.createElement("small");
      count.textContent = String(item.count);
      button.append(emoji, count);
      return button;
    });
    container.replaceChildren(...buttons);
    container.hidden = buttons.length === 0;
    article.dataset.reactionVersion = String(version);
  }

  function selectedReactions(article) {
    return new Set(Array.from(article.querySelectorAll('[data-message-reaction][aria-pressed="true"]'),
      button => button.dataset.messageReaction));
  }

  function allowedReactions() {
    const conversation = stage?.closest(".conversation--chat");
    const value = conversation?.dataset.allowedReactions;
    return value === undefined ? null : new Set(value.split(",").filter(Boolean));
  }

  function setAllowedReactions(values) {
    const conversation = stage?.closest(".conversation--chat");
    if (!conversation || !Array.isArray(values)) return;
    conversation.dataset.allowedReactions = values.join(",");
    // If a menu is currently open, hide forbidden additions immediately.
    const article = document.querySelector(".message.is-context-target");
    if (article) preparePicker(article);
  }

  function preparePicker(article) {
    const picker = document.getElementById("messageReactionPicker");
    if (!picker) return;
    const selected = selectedReactions(article);
    const allowed = allowedReactions();
    let visible = 0;
    picker.querySelectorAll("[data-pick-reaction]").forEach(button => {
      const emoji = button.dataset.pickReaction;
      // Keep an existing selected reaction removable even if it is now forbidden.
      button.hidden = !selected.has(emoji) && allowed !== null && !allowed.has(emoji);
      button.setAttribute("aria-pressed", String(selected.has(emoji)));
      if (!button.hidden) visible++;
    });
    picker.hidden = !article.dataset.reactionUrl || !visible;
  }

  const pending = new WeakSet();
  async function toggleReaction(article, emoji) {
    if (!article?.dataset.reactionUrl || pending.has(article)) return;
    const selected = selectedReactions(article);
    const removing = selected.has(emoji);
    const allowed = allowedReactions();
    if (!removing && allowed !== null && !allowed.has(emoji)) {
      window.showToast?.("Эта реакция недоступна в переписке.");
      return;
    }
    if (!removing && selected.size >= 3) {
      window.showToast?.("Можно поставить не больше трёх реакций. Снимите одну из выбранных.");
      return;
    }
    pending.add(article);
    try {
      const body = new FormData();
      body.append("emoji", emoji);
      body.append("action", removing ? "remove" : "add");
      if (document.body.dataset.accountId) body.append("account_id", document.body.dataset.accountId);
      const csrf = document.querySelector("[name='csrfmiddlewaretoken']")?.value || "";
      body.append("csrfmiddlewaretoken", csrf);
      const response = await fetch(article.dataset.reactionUrl, {
        method: "POST", credentials: "same-origin", body,
        headers: { "X-Requested-With": "XMLHttpRequest" },
      });
      const result = await response.json().catch(() => ({}));
      if (!response.ok || !result.ok) throw new Error(result.error || "Не удалось поставить реакцию.");
      renderReactions(article, result);
    } catch (error) {
      window.showToast?.(error.message);
    } finally {
      pending.delete(article);
    }
  }

  function mentionToken(text, start, end = start) {
    if (start !== end) return null;
    const before = text.slice(0, start);
    const match = /(?:^|[^\p{L}\p{N}_@.+/-])@([\p{L}\p{N}_.+-]{0,150})$/u.exec(before);
    if (!match) return null;
    const suffix = /^[\p{L}\p{N}_.+-]*/u.exec(text.slice(start))[0];
    if (match[1].length + suffix.length > 150) return null;
    return { query: match[1], start: start - match[1].length - 1, end: start + suffix.length };
  }

  function insertMention(text, token, username) {
    const tail = text.slice(token.end);
    const value = "@" + username + (/^\s/.test(tail) ? "" : " ");
    return { text: text.slice(0, token.start) + value + tail, caret: token.start + value.length };
  }

  window.SovietgramSocial = { tokenize, renderText, renderReactions, preparePicker, toggleReaction, mentionToken, insertMention, setAllowedReactions };

  if (!stage) return;
  document.querySelectorAll(".message[data-message-id]").forEach(article => {
    const paragraph = article.querySelector(".message__text");
    if (!paragraph) return;
    if (paragraph.dataset.markdownRendered === "true") {
      paragraph.dataset.socialText = article.dataset.messageText || "";
    } else renderText(paragraph, article.dataset.messageText || "");
  });

  document.addEventListener("click", event => {
    const spoiler = event.target.closest?.(".markdown-body .message-spoiler");
    if (spoiler) {
      event.preventDefault();
      const expanded = spoiler.getAttribute("aria-expanded") === "true";
      spoiler.setAttribute("aria-expanded", String(!expanded));
      spoiler.setAttribute("aria-label", expanded ? "Показать скрытый текст" : spoiler.textContent + ". Скрыть текст");
      return;
    }
    const imageButton = event.target.closest?.(".markdown-body [data-markdown-image-url]");
    if (imageButton) {
      event.preventDefault();
      try {
        const url = new URL(imageButton.dataset.markdownImageUrl);
        if (!["https:", "http:"].includes(url.protocol)) return;
        const image = document.createElement("img");
        image.className = "markdown-inline-image";
        image.alt = imageButton.dataset.markdownImageAlt || "Изображение";
        image.referrerPolicy = "no-referrer";
        image.loading = "lazy";
        image.decoding = "async";
        image.addEventListener("error", () => {
          if (image.isConnected) image.replaceWith(imageButton);
        }, { once: true });
        image.src = url.href;
        imageButton.replaceWith(image);
      } catch (_error) { /* Invalid URLs remain inert. */ }
      return;
    }
    const reaction = event.target.closest?.("[data-message-reaction]");
    if (reaction) {
      event.preventDefault();
      void toggleReaction(reaction.closest(".message"), reaction.dataset.messageReaction);
      return;
    }
    const tag = event.target.closest?.("[data-message-hashtag]");
    if (tag) {
      event.preventDefault();
      document.dispatchEvent(new CustomEvent("sovietgram:search-hashtag", {
        detail: { tag: tag.dataset.messageHashtag },
      }));
    }
  });

  const input = document.getElementById("messageInput");
  if (!input || input.readOnly || !stage.dataset.mentionUrl) return;
  const popup = document.createElement("div");
  popup.id = "mentionSuggestions";
  popup.className = "mention-suggestions";
  popup.setAttribute("role", "listbox");
  popup.setAttribute("aria-label", "Участники чата");
  popup.hidden = true;
  document.body.appendChild(popup);
  input.setAttribute("aria-controls", popup.id);
  input.setAttribute("aria-autocomplete", "list");
  input.setAttribute("aria-expanded", "false");

  let timer, controller, generation = 0, candidates = [], current = -1;
  function close() {
    clearTimeout(timer);
    controller?.abort();
    generation += 1;
    candidates = [];
    current = -1;
    popup.hidden = true;
    input.setAttribute("aria-expanded", "false");
    input.removeAttribute("aria-activedescendant");
  }

  function position() {
    if (popup.hidden) return;
    const rect = input.getBoundingClientRect();
    const width = Math.min(Math.max(rect.width, 220), window.innerWidth - 16);
    popup.style.width = width + "px";
    popup.style.left = Math.max(8, Math.min(rect.left, window.innerWidth - width - 8)) + "px";
    popup.style.top = Math.max(8, rect.top - popup.offsetHeight - 8) + "px";
  }

  function select(index, scroll = false) {
    current = index;
    Array.from(popup.children).forEach((button, i) => {
      button.setAttribute("aria-selected", String(i === index));
      if (i === index) {
        input.setAttribute("aria-activedescendant", button.id);
        if (scroll) button.scrollIntoView({ block: "nearest" });
      }
    });
  }

  function choose(index) {
    const candidate = candidates[index];
    const token = mentionToken(input.value, input.selectionStart, input.selectionEnd);
    if (!candidate || !token) { close(); return; }
    const next = insertMention(input.value, token, candidate.username);
    if (next.text.length > input.maxLength && input.maxLength > 0) { close(); return; }
    close();
    input.value = next.text;
    input.focus();
    input.setSelectionRange(next.caret, next.caret);
    input.dispatchEvent(new Event("input", { bubbles: true }));
  }

  function show(results) {
    candidates = results;
    if (!candidates.length) { close(); return; }
    const buttons = candidates.map((candidate, index) => {
      const button = document.createElement("button");
      button.id = "mention-option-" + index;
      button.type = "button";
      button.tabIndex = -1;
      button.setAttribute("role", "option");
      const name = document.createElement("strong");
      name.textContent = candidate.display_name;
      const username = document.createElement("small");
      username.textContent = "@" + candidate.username;
      button.append(name, username);
      button.addEventListener("pointerdown", event => event.preventDefault());
      button.addEventListener("click", () => choose(index));
      return button;
    });
    popup.replaceChildren(...buttons);
    popup.hidden = false;
    input.setAttribute("aria-expanded", "true");
    select(0);
    position();
  }

  function schedule(event) {
    if (event?.isComposing) return;
    close();
    const token = mentionToken(input.value, input.selectionStart, input.selectionEnd);
    if (!token || document.activeElement !== input) return;
    const requestGeneration = generation;
    timer = window.setTimeout(async () => {
      controller = new AbortController();
      try {
        const url = new URL(stage.dataset.mentionUrl, window.location.origin);
        url.searchParams.set("q", token.query);
        const response = await fetch(url, {
          credentials: "same-origin", signal: controller.signal, cache: "no-store",
        });
        const result = await response.json();
        const latest = mentionToken(input.value, input.selectionStart, input.selectionEnd);
        if (response.ok && result.ok && requestGeneration === generation &&
            document.activeElement === input && latest?.query === token.query) show(result.results || []);
      } catch (_error) { /* Suggestions are optional; never block typing. */ }
    }, 180);
  }

  input.addEventListener("input", schedule);
  input.addEventListener("compositionend", schedule);
  input.addEventListener("click", schedule);
  input.addEventListener("keyup", event => {
    if (["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) schedule(event);
  });
  input.addEventListener("blur", close);
  window.addEventListener("resize", position);
  document.addEventListener("keydown", event => {
    if (event.target !== input || popup.hidden || event.isComposing || event.ctrlKey || event.metaKey || event.shiftKey) return;
    if (!["ArrowDown", "ArrowUp", "Enter", "Tab", "Escape"].includes(event.key)) return;
    event.preventDefault();
    event.stopImmediatePropagation();
    if (event.key === "Escape") close();
    else if (event.key === "Enter" || event.key === "Tab") choose(current);
    else select((current + (event.key === "ArrowDown" ? 1 : -1) + candidates.length) % candidates.length, true);
  }, true);
})();
