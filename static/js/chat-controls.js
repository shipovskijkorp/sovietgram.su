(() => {
  // Keep compose-field geometry independent from the large chat.js module.
  // The wrapper is the visible Telegram-like input field, so its height must
  // track the textarea explicitly rather than relying on flex intrinsic sizing.
  const syncComposerHeight = () => {
    const input = document.getElementById("messageInput");
    const field = input?.closest(".composer__field");
    const composer = input?.closest(".composer");
    if (!input || !field) return;

    const minText = 28;
    const maxText = 224;
    const fieldChrome = 16;

    input.style.height = `${minText}px`;
    input.style.overflowY = "hidden";
    const content = Math.max(minText, input.scrollHeight);
    const textHeight = Math.min(content, maxText);

    input.style.height = `${textHeight}px`;
    input.style.overflowY = content > maxText ? "auto" : "hidden";
    field.style.height = `${textHeight + fieldChrome}px`;
    field.style.maxHeight = `${maxText + fieldChrome}px`;
    composer?.classList.toggle("composer--multiline", textHeight > minText);
  };

  document.addEventListener("input", (event) => {
    if (event.target?.id === "messageInput") syncComposerHeight();
  }, true);
  document.addEventListener("paste", (event) => {
    if (event.target?.id === "messageInput") {
      window.requestAnimationFrame(syncComposerHeight);
    }
  }, true);
  document.addEventListener("cut", (event) => {
    if (event.target?.id === "messageInput") {
      window.requestAnimationFrame(syncComposerHeight);
    }
  }, true);
  document.addEventListener("compositionend", (event) => {
    if (event.target?.id === "messageInput") syncComposerHeight();
  }, true);
  window.addEventListener("resize", syncComposerHeight);
  window.requestAnimationFrame(syncComposerHeight);

  // Composer Enter handling lives in capture phase so no other chat/menu
  // handler can swallow the key before the message form sees it.
  document.addEventListener("keydown", (event) => {
    const input = event.target;
    if (!(input instanceof HTMLTextAreaElement) || input.id !== "messageInput") return;
    if (event.isComposing || event.repeat || event.key !== "Enter" || event.shiftKey) return;

    const enterToSend = document.body.dataset.enterToSend !== "false";
    const explicitSend = event.ctrlKey || event.metaKey;
    if (!enterToSend && !explicitSend) return;

    const form = input.form || document.getElementById("messageForm");
    const sendButton = document.getElementById("sendButton");
    if (!form || !input.value.trim() || sendButton?.disabled) return;

    event.preventDefault();
    event.stopImmediatePropagation();

    // Clicking the real submit control works with both the AJAX chat handler
    // and the browser's native form submission if the main chat script failed.
    if (sendButton) sendButton.click();
    else if (typeof form.requestSubmit === "function") form.requestSubmit();
    else form.submit();
  }, true);

  const conversation = document.querySelector(".conversation--chat");
  if (!conversation) return;

  const chatMenuButton = document.getElementById("chatMenuButton");
  const chatMenu = document.getElementById("chatMenu");
  const searchPanel = document.getElementById("chatSearchPanel");
  const searchInput = document.getElementById("chatSearchInput");
  const contextMenu = document.getElementById("messageContextMenu");
  const messageForm = document.getElementById("messageForm");
  const csrfToken = messageForm?.querySelector("[name='csrfmiddlewaretoken']")?.value
    || document.querySelector("[name='csrfmiddlewaretoken']")?.value || "";

  const chatType = conversation.dataset.chatType || "private";
  const chatRole = conversation.dataset.chatRole || "member";
  const chatSaved = conversation.dataset.chatSaved === "true";
  const chatTitle = conversation.dataset.chatTitle || "чат";
  const peerName = conversation.dataset.chatPeerName || chatTitle;
  const chatActionUrl = conversation.dataset.chatActionUrl || "";
  const chatMenuMuteButton = chatMenu?.querySelector("[data-chat-menu-mute]");
  const chatMenuMuteLabel = chatMenuMuteButton?.querySelector(".chat-menu__label");
  const chatMuteOptions = chatMenu?.querySelector("[data-chat-mute-options]");
  const chatProtectionButton = chatMenu?.querySelector("[data-toggle-chat-protection]");
  const chatProtectionLabel = chatProtectionButton?.querySelector(".chat-menu__label");
  const chatExportLink = chatMenu?.querySelector("[data-chat-export]");
  let chatProtected = conversation.dataset.chatProtected === "true";

  const reactorsDialog = document.getElementById("messageReactorsDialog");
  const reactorsStatus = document.getElementById("messageReactorsStatus");
  const reactorsList = document.getElementById("messageReactorsList");
  const reactorsFilters = document.getElementById("messageReactorsFilters");
  const reactorsMore = document.getElementById("messageReactorsMore");
  let reactorsUrl = "", reactorEmoji = "", reactorsAfter = 0, reactorGeneration = 0, reactorRequest = null;
  function renderReactorFilters(counts) {
    const choices = [{emoji:"", count:counts.reduce((sum, row) => sum + row.count, 0)}, ...counts];
    reactorsFilters.replaceChildren(...choices.map(choice => {
      const button = document.createElement("button");
      button.type = "button";
      button.textContent = (choice.emoji || "Все") + " " + choice.count;
      button.setAttribute("aria-pressed", String(choice.emoji === reactorEmoji));
      button.addEventListener("click", () => {
        reactorEmoji = choice.emoji;
        void loadReactors();
      });
      return button;
    }));
  }
  async function loadReactors(append = false) {
    if (!reactorsDialog?.open || !reactorsUrl) return;
    reactorRequest?.abort();
    const generation = ++reactorGeneration;
    reactorRequest = new AbortController();
    if (!append) { reactorsAfter = 0; reactorsList.replaceChildren(); }
    reactorsStatus.textContent = "Загрузка…";
    reactorsMore.hidden = true;
    try {
      const url = new URL(reactorsUrl, location.origin);
      url.searchParams.set("account_id", document.body.dataset.accountId || "");
      url.searchParams.set("emoji", reactorEmoji);
      url.searchParams.set("after", String(reactorsAfter));
      const response = await fetch(url, {credentials:"same-origin",cache:"no-store",signal:reactorRequest.signal});
      const data = await response.json().catch(() => ({}));
      if (generation !== reactorGeneration || !reactorsDialog.open) return;
      if (!response.ok || !data.ok) throw new Error(data.error || "Реакции недоступны.");
      renderReactorFilters(data.counts || []);
      for (const reactor of data.reactors || []) {
        const row = document.createElement("li");
        const name = document.createElement("strong");
        name.textContent = reactor.emoji + " " + reactor.name;
        const username = document.createElement("small");
        username.textContent = "@" + reactor.username;
        row.append(name, username);
        reactorsList.append(row);
      }
      reactorsStatus.textContent = data.anonymous ? "Реакции в каналах анонимны." : "Участники: " + data.visible_total;
      reactorsAfter = data.next_after || 0;
      reactorsMore.textContent = "Показать ещё";
      reactorsMore.hidden = !reactorsAfter;
    } catch (error) {
      if (generation !== reactorGeneration || error.name === "AbortError") return;
      reactorsStatus.textContent = error.message;
      reactorsMore.textContent = "Повторить";
      reactorsMore.hidden = false;
    }
  }
  function openReactors(article) {
    if (!reactorsDialog || !article.dataset.reactorsUrl) return;
    reactorsUrl = article.dataset.reactorsUrl;
    reactorEmoji = ""; reactorsAfter = 0;
    reactorsFilters.replaceChildren();
    if (!reactorsDialog.open) reactorsDialog.showModal();
    void loadReactors();
  }
  reactorsMore?.addEventListener("click", () => { void loadReactors(Boolean(reactorsAfter)); });
  document.getElementById("messageReactorsClose")?.addEventListener("click", () => reactorsDialog.close());
  reactorsDialog?.addEventListener("close", () => {
    reactorGeneration++; reactorRequest?.abort(); reactorsUrl = ""; reactorsList.replaceChildren();
  });

  const readersDialog = document.getElementById("messageReadersDialog");
  const readersStatus = document.getElementById("messageReadersStatus");
  const readersList = document.getElementById("messageReadersList");
  const readersMore = document.getElementById("messageReadersMore");
  let readersUrl = "", readersAfter = 0, readersController = null, readersGeneration = 0;
  async function loadReaders(append = false) {
    if (!readersUrl || !readersDialog?.open) return;
    readersController?.abort();
    const generation = ++readersGeneration;
    readersController = new AbortController();
    if (!append) { readersAfter = 0; readersList.replaceChildren(); }
    readersMore.hidden = true;
    readersStatus.textContent = "Загрузка…";
    try {
      const url = new URL(readersUrl, location.origin);
      url.searchParams.set("account_id", document.body.dataset.accountId || "");
      url.searchParams.set("after", String(readersAfter));
      const response = await fetch(url, {credentials:"same-origin", cache:"no-store", signal:readersController.signal});
      const result = await response.json().catch(() => ({}));
      if (generation !== readersGeneration || !readersDialog.open) return;
      if (!response.ok || !result.ok) throw new Error(result.error || "Список прочитавших недоступен.");
      for (const reader of result.readers || []) {
        const row = document.createElement("li");
        const name = document.createElement("strong");
        name.textContent = reader.name;
        const username = document.createElement("small");
        username.textContent = "@" + reader.username;
        row.append(name, username);
        readersList.append(row);
      }
      readersStatus.textContent = result.total ? "Прочитали: " + result.total : "Пока никто не прочитал.";
      readersAfter = result.next_after || 0;
      readersMore.textContent = "Показать ещё";
      readersMore.hidden = !readersAfter;
    } catch (error) {
      if (generation !== readersGeneration || error.name === "AbortError") return;
      readersStatus.textContent = error.message;
      readersMore.textContent = "Повторить";
      readersMore.hidden = false;
    }
  }
  function openReaders(article) {
    if (!readersDialog || !article.dataset.readersUrl || !isOwn(article) || chatType !== "group") return;
    readersUrl = article.dataset.readersUrl;
    if (!readersDialog.open) readersDialog.showModal();
    void loadReaders();
  }
  readersMore?.addEventListener("click", () => { void loadReaders(Boolean(readersAfter)); });
  document.getElementById("messageReadersClose")?.addEventListener("click", () => readersDialog.close());
  readersDialog?.addEventListener("close", () => {
    readersGeneration++; readersController?.abort(); readersUrl = ""; readersList.replaceChildren();
  });

  const selectionBar = document.getElementById("messageSelectionBar");
  const selectionCount = document.getElementById("messageSelectionCount");
  const selectionForward = document.getElementById("messageSelectionForward");
  const selectionDelete = document.getElementById("messageSelectionDelete");

  const deleteMessageModal = document.getElementById("deleteMessageModal");
  const deleteMessageTitle = document.getElementById("deleteMessageTitle");
  const deleteMessageText = document.getElementById("deleteMessageText");
  const deleteMessageForEveryoneRow = document.getElementById("deleteMessageForEveryoneRow");
  const deleteMessageForEveryone = document.getElementById("deleteMessageForEveryone");
  const deleteMessageForEveryoneLabel = document.getElementById("deleteMessageForEveryoneLabel");
  const deleteMessageConfirm = document.getElementById("deleteMessageConfirm");

  const clearHistoryModal = document.getElementById("clearHistoryModal");
  const clearHistoryTitle = document.getElementById("clearHistoryTitle");
  const clearHistoryText = document.getElementById("clearHistoryText");
  const clearHistoryForEveryoneRow = document.getElementById("clearHistoryForEveryoneRow");
  const clearHistoryForEveryone = document.getElementById("clearHistoryForEveryone");
  const clearHistoryForEveryoneLabel = document.getElementById("clearHistoryForEveryoneLabel");
  const clearHistoryConfirm = document.getElementById("clearHistoryConfirm");

  const deleteChatModal = document.getElementById("deleteChatModal");
  const deleteChatTitle = document.getElementById("deleteChatTitle");
  const deleteChatText = document.getElementById("deleteChatText");
  const deleteChatForEveryoneRow = document.getElementById("deleteChatForEveryoneRow");
  const deleteChatForEveryone = document.getElementById("deleteChatForEveryone");
  const deleteChatForEveryoneLabel = document.getElementById("deleteChatForEveryoneLabel");
  const deleteChatConfirm = document.getElementById("deleteChatConfirm");

  const editModal = document.getElementById("editMessageModal");
  const editText = document.getElementById("editMessageText");
  const editSave = document.getElementById("editMessageSave");
  const forwardModal = document.getElementById("forwardMessageModal");
  const forwardSearch = document.getElementById("forwardTargetSearch");
  const forwardConfirm = document.getElementById("forwardConfirm");
  const forwardStatus = document.getElementById("forwardStatus");
  const forwardHideSender = document.getElementById("forwardHideSender");
  const forwardSilent = document.getElementById("forwardSilent");
  const forwardTargets = () => [...document.querySelectorAll("[data-forward-target]")];
  let selectedTargets = new Set();
  let forwardCompleted = new Set();
  let forwardStarted = false;

  let contextArticle = null;
  let contextQuote = "";
  let editArticle = null;
  let forwardArticles = [];
  const forwardSendKeys = window.SovietgramSendRetry.batch();
  let forwardBusy = false;
  let deleteArticles = [];
  let selectedArticles = new Set();
  let selectionMode = false;
  let busyDelete = false;

  function notify(text) {
    if (typeof window.showToast === "function") window.showToast(text);
  }

  function setChatMuteOptions(open) {
    if (!chatMuteOptions) return;
    chatMuteOptions.hidden = !open;
    chatMenuMuteButton?.setAttribute("aria-expanded", String(open));
  }

  function setChatMenu(open) {
    if (!chatMenu || !chatMenuButton) return;
    chatMenu.hidden = !open;
    chatMenuButton.setAttribute("aria-expanded", String(open));
    if (!open) setChatMuteOptions(false);
  }

  function applyChatProtection(enabled) {
    chatProtected = Boolean(enabled);
    conversation.dataset.chatProtected = String(chatProtected);
    conversation.classList.toggle("is-content-protected", chatProtected);
    for (const preview of conversation.querySelectorAll("[data-open-sticker-preview]")) preview.disabled = chatProtected;
    if (chatProtected) window.SovietgramStickers?.closeIncoming?.();

    if (chatProtectionLabel) {
      chatProtectionLabel.textContent = chatProtected
        ? "Разрешить копирование"
        : "Запретить копирование";
    }
    if (chatExportLink) chatExportLink.hidden = chatProtected;
    if (selectionForward) {
      selectionForward.hidden = chatProtected;
      selectionForward.disabled = chatProtected || selectedArticles.size === 0;
    }

    const copyButton = contextMenu?.querySelector('[data-message-action="copy"]');
    const forwardButton = contextMenu?.querySelector('[data-message-action="forward"]');
    const copyLink = contextMenu?.querySelector('[data-message-action="copy-link"]');
    if (copyLink) copyLink.hidden = chatProtected;
    if (copyButton) {
      copyButton.hidden = chatProtected
        || !(contextArticle?.dataset.messageText || "").trim();
    }
    if (forwardButton) forwardButton.hidden = chatProtected;
    const stickerSave = contextMenu?.querySelector('[data-message-action="save-sticker"]');
    if (stickerSave) stickerSave.hidden = chatProtected || !contextArticle?.querySelector("[data-sticker-attachment]");
  }

  applyChatProtection(chatProtected);
  document.addEventListener("sovietgram:chat-protection", (event) => {
    const enabled = event.detail?.enabled;
    if (typeof enabled === "boolean" && enabled !== chatProtected) {
      applyChatProtection(enabled);
    }
  });

  function setSearchPanel(open) {
    if (!searchPanel) return;
    searchPanel.hidden = !open;
    if (open) window.setTimeout(() => searchInput?.focus(), 0);
  }

  async function postForm(url, values) {
    const body = new FormData();
    body.append("csrfmiddlewaretoken", csrfToken);
    if (document.body.dataset.accountId) body.append("account_id", document.body.dataset.accountId);
    Object.entries(values || {}).forEach(([key, value]) => {
      body.append(key, value == null ? "" : String(value));
    });
    const transport = values?.client_message_id ? window.SovietgramSendRetry.fetchSend : fetch;
    const response = await transport(url, {
      method: "POST",
      credentials: "same-origin",
      headers: { "X-Requested-With": "XMLHttpRequest" },
      body
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok || response.redirected || payload.ok !== true) {
      const error = new Error(payload.error || (response.redirected ? "Сессия истекла. Обновите страницу." : "Не удалось выполнить действие (" + response.status + ")."));
      error.status = response.status;
      throw error;
    }
    return payload;
  }

  function applyChatMuteState(isMuted, mutedUntil = "") {
    const muted = Boolean(isMuted);
    const wasMuted = conversation.dataset.chatMuted === "true";
    conversation.dataset.chatMuted = String(muted);
    conversation.dataset.chatMutedUntil = mutedUntil || "";
    if (chatMenuMuteLabel) {
      chatMenuMuteLabel.textContent = muted
        ? "Включить уведомления"
        : "Выключить уведомления";
    }
    if (wasMuted !== muted) setChatMuteOptions(false);
  }

  document.addEventListener("sovietgram:chat-mute-state", (event) => {
    const state = event.detail || {};
    if (typeof state.isMuted === "boolean") {
      applyChatMuteState(state.isMuted, state.mutedUntil || "");
    }
  });

  async function setChatMute(duration, trigger = chatMenuMuteButton) {
    if (!chatMenuMuteButton) return;
    if (trigger) trigger.disabled = true;
    try {
      const payload = await postForm(chatActionUrl, {
        action: "mute",
        duration,
      });
      applyChatMuteState(payload.is_muted, payload.muted_until || "");
      notify(payload.message || (
        payload.is_muted ? "Уведомления отключены." : "Уведомления включены."
      ));
      void window.SovietgramSidebar?.refresh?.();
    } catch (error) {
      notify(error.message);
    } finally {
      if (trigger) trigger.disabled = false;
    }
  }

  async function toggleChatProtection() {
    if (!chatProtectionButton) return;
    chatProtectionButton.disabled = true;
    try {
      const payload = await postForm(chatActionUrl, { action: "toggle_protection" });
      applyChatProtection(payload.protect_content);
      notify(payload.message || "Настройки копирования обновлены.");
    } catch (error) {
      notify(error.message);
    } finally {
      chatProtectionButton.disabled = false;
    }
  }

  document.addEventListener("copy", (event) => {
    if (!chatProtected) return;
    const selection = window.getSelection();
    const anchor = selection?.anchorNode;
    const anchorElement = anchor?.nodeType === Node.ELEMENT_NODE
      ? anchor
      : anchor?.parentElement;
    if (!selection?.rangeCount || !anchorElement || !conversation.contains(anchorElement)) return;
    if (anchorElement.closest(".composer, input, textarea, [contenteditable='true']")) return;
    event.preventDefault();
    notify("Копирование запрещено для этой переписки.");
  }, true);

  function isOwn(article) {
    return article?.dataset.messageOwn === "true";
  }

  function isModerator() {
    return conversation.dataset.canModerateMessages === "true";
  }

  function canDeleteArticle(article) {
    if (!article) return false;
    if (chatType === "private") return true;
    return isOwn(article) || isModerator();
  }

  function messagePreview(article) {
    const text = (article?.dataset.messageText || "").trim();
    if (text) return text.replace(/\s+/g, " ").slice(0, 180);
    const fileName = article?.querySelector(".message-file-card strong")?.textContent?.trim();
    if (fileName) return fileName;
    if (article?.querySelector(".message-sticker")) return "Стикер";
    if (article?.querySelector(".message-media")) return "Медиа";
    return "Сообщение";
  }

  function closeMessageMenu() {
    if (contextMenu) contextMenu.hidden = true;
    contextArticle = null;
    contextQuote = "";
    document.querySelectorAll(".message.is-context-target").forEach((node) => {
      node.classList.remove("is-context-target");
    });
  }

  function selectedQuote(article) {
    if (!article || chatProtected || article.dataset.messageKind || conversation.dataset.canSendText === "false") return "";
    const body = article.querySelector(".message__text");
    const selection = window.getSelection();
    if (!body || !selection || selection.rangeCount !== 1 || selection.isCollapsed) return "";
    const range = selection.getRangeAt(0);
    if (!body.contains(range.startContainer) || !body.contains(range.endContainer)) return "";
    const text = selection.toString().trim();
    if (!text || Array.from(text).length > 1024 || !(article.dataset.messageText || "").includes(text)) return "";
    return text;
  }

  // Keep the text selection alive when opening the action button.
  document.addEventListener("pointerdown", event => {
    const trigger = event.target.closest?.(".message-action-trigger");
    if (trigger && selectedQuote(trigger.closest(".message"))) event.preventDefault();
  }, true);

  function openMessageMenu(article, x, y) {
    if (!contextMenu || !article) return;
    contextArticle = article;
    contextQuote = selectedQuote(article);
    const quoteButton = contextMenu.querySelector('[data-message-action="quote"]');
    if (quoteButton) quoteButton.hidden = !contextQuote;
    article.classList.add("is-context-target");

    const saveStickerButton = contextMenu.querySelector('[data-message-action="save-sticker"]');
    if (saveStickerButton) saveStickerButton.hidden = chatProtected || !article.querySelector("[data-sticker-attachment]");
    const editButton = contextMenu.querySelector('[data-message-action="edit"]');
    const copyButton = contextMenu.querySelector('[data-message-action="copy"]');
    const forwardButton = contextMenu.querySelector('[data-message-action="forward"]');
    const copyLink = contextMenu.querySelector('[data-message-action="copy-link"]');
    if (copyLink) copyLink.hidden = chatProtected;
    const deleteButton = contextMenu.querySelector('[data-message-action="delete"]');
    const reportButton = contextMenu.querySelector('[data-message-action="report"]');
    if (reportButton) reportButton.hidden = isOwn(article) || !article.dataset.messageId;
    const pinLabel = document.getElementById("messagePinLabel");
    const reactorsButton = contextMenu.querySelector('[data-message-action="reactors"]');
    if (reactorsButton) {
      reactorsButton.hidden = !article.dataset.reactorsUrl || !article.querySelector("[data-message-reaction]");
      reactorsButton.lastChild.textContent = chatType === "channel" ? "Реакции" : "Кто отреагировал";
    }
    const readersButton = contextMenu.querySelector('[data-message-action="readers"]');
    if (readersButton) readersButton.hidden = chatType !== "group" || !isOwn(article) || !article.dataset.readersUrl;

    if (editButton) editButton.hidden = !isOwn(article) || Boolean(article.dataset.messageKind) || Boolean(article.querySelector(".message-sticker"));
    if (copyButton) copyButton.hidden = chatProtected || !(article.dataset.messageText || "").trim();
    if (forwardButton) forwardButton.hidden = chatProtected;
    if (deleteButton) deleteButton.hidden = !canDeleteArticle(article);
    if (pinLabel) pinLabel.textContent = article.dataset.messagePinned === "true" ? "Открепить" : "Закрепить";
    window.SovietgramSocial?.preparePicker(article);

    // A fixed menu belongs to the viewport, not a scrolling or transformed
    // conversation ancestor. Measure from a known origin before clamping.
    if (contextMenu.parentElement !== document.body) document.body.append(contextMenu);
    const viewport = window.visualViewport;
    const left = viewport?.offsetLeft || 0, top = viewport?.offsetTop || 0;
    const width = viewport?.width || window.innerWidth;
    const height = viewport?.height || window.innerHeight;
    Object.assign(contextMenu.style, {
      position: "fixed", inset: "auto", left: "0px", top: "0px",
      maxWidth: Math.max(0, width - 12) + "px",
      maxHeight: Math.max(0, height - 12) + "px",
      overflowY: "auto", transform: "none",
    });
    contextMenu.hidden = false;
    contextMenu.scrollTop = 0;
    const rect = contextMenu.getBoundingClientRect();
    const targetLeft = Math.max(left + 6, Math.min(x, left + width - rect.width - 6));
    const targetTop = Math.max(top + 6, Math.min(y, top + height - rect.height - 6));
    const scaleX = rect.width / contextMenu.offsetWidth || 1;
    const scaleY = rect.height / contextMenu.offsetHeight || 1;
    contextMenu.style.left = (targetLeft - rect.left) / scaleX + "px";
    contextMenu.style.top = (targetTop - rect.top) / scaleY + "px";
    if (contextQuote && quoteButton) {
      const action = quoteButton.getBoundingClientRect();
      const menu = contextMenu.getBoundingClientRect();
      if (action.bottom > menu.bottom) contextMenu.scrollTop += (action.bottom - menu.bottom + 6) / scaleY;
    }
  }

  function setReply(article, quote = "") {
    window.SovietgramChat?.setReply?.(article, quote);
  }

  async function copyText(value) {
    try {
      await navigator.clipboard.writeText(value);
    } catch (_error) {
      const area = document.createElement("textarea");
      area.value = value;
      area.style.position = "fixed";
      area.style.opacity = "0";
      document.body.appendChild(area);
      area.select();
      try {
        if (!document.execCommand("copy")) throw new Error("Буфер обмена недоступен.");
      } finally { area.remove(); }
    }
  }

  function messageLink(article) {
    const url = new URL(conversation.dataset.chatUrl, window.location.origin);
    url.searchParams.set("message", article.dataset.messageId);
    url.hash = "message-" + article.dataset.messageId;
    return url.href;
  }

  function openEditModal(article) {
    if (!editModal || !editText || !article) return;
    editArticle = article;
    editText.value = article.dataset.messageText || "";
    editModal.hidden = false;
    window.setTimeout(() => editText.focus(), 0);
  }

  function closeEditModal() {
    if (editModal) editModal.hidden = true;
    editArticle = null;
  }

  function forwardRequirements(articles) {
    const list = (articles || []).filter(Boolean);
    return {
      text: list.some((article) => (
        !article.querySelector(".message-media")
        && (
          Boolean((article.dataset.messageText || "").trim())
          || Boolean(article.dataset.messageKind)
        )
      )),
      media: list.some((article) => Boolean(article.querySelector(".message-media"))),
      voice: list.some((article) => Boolean(article.querySelector("[data-voice-player]"))),
    };
  }

  function targetSupportsForward(target, requirements) {
    if (!target || target.dataset.forwardTarget === "saved") return true;
    if (requirements.text && target.dataset.forwardCanText === "false") return false;
    if (requirements.media && target.dataset.forwardCanMedia === "false") return false;
    if (requirements.voice && target.dataset.forwardCanVoice === "false") return false;
    return true;
  }

  function syncForwardTargets() {
    const requirements = forwardRequirements(forwardArticles);
    const query = forwardSearch?.value.trim().toLowerCase() || "";
    for (const target of forwardTargets()) {
      const selected = selectedTargets.has(target.dataset.forwardTarget);
      const matchesSearch = !query || (target.dataset.forwardSearch || "").includes(query);
      target.hidden = !matchesSearch || (!selected && !targetSupportsForward(target, requirements));
      target.classList.toggle("is-selected", selected);
      target.setAttribute("aria-pressed", String(selected));
      target.disabled = forwardBusy || forwardStarted;
    }
    const total = forwardArticles.length * selectedTargets.size;
    if (forwardConfirm) {
      forwardConfirm.disabled = forwardBusy || !total || chatProtected || forwardCompleted.size >= total;
      forwardConfirm.textContent = forwardStarted ? "Повторить оставшиеся" : "Переслать" + (total ? " (" + total + ")" : "");
    }
    if (forwardHideSender) forwardHideSender.disabled = forwardStarted || forwardBusy;
    if (forwardSilent) forwardSilent.disabled = forwardStarted || forwardBusy;
    if (forwardStatus && !forwardStarted) {
      forwardStatus.textContent = selectedTargets.size
        ? "Выбрано чатов: " + selectedTargets.size + " · сообщений: " + forwardArticles.length
        : "Выберите один или несколько чатов (до 10).";
    }
  }

  function openForwardModal(articles) {
    if (chatProtected) {
      notify("Пересылка запрещена для этой переписки.");
      return;
    }
    if (!forwardModal || !articles?.length || forwardBusy || forwardStarted) return;
    forwardArticles = [...new Map(articles.filter(article => article?.isConnected && article.dataset.forwardUrl)
      .map(article => [article.dataset.messageId, article])).values()]
      .sort((a,b) => Number(a.dataset.messageId) - Number(b.dataset.messageId));
    if (!forwardArticles.length) return;
    if (forwardArticles.length > 50) {
      notify("За один раз можно переслать до 50 сообщений.");
      forwardArticles = [];
      return;
    }
    forwardSendKeys.clear();
    selectedTargets = new Set();
    forwardCompleted = new Set();
    forwardStarted = false;
    if (forwardHideSender) forwardHideSender.checked = false;
    if (forwardSilent) forwardSilent.checked = false;
    forwardModal.hidden = false;
    if (forwardSearch) {
      forwardSearch.value = "";
      window.setTimeout(() => forwardSearch.focus(), 0);
    }
    syncForwardTargets();
  }

  function closeForwardModal(force = false) {
    if (forwardBusy && !force) return;
    if (forwardStarted && !force && !window.confirm("Закрыть пересылку? Уже доставленные сообщения останутся, а повтор из нового окна может создать копии.")) return;
    if (forwardModal) forwardModal.hidden = true;
    forwardArticles = [];
    selectedTargets.clear();
    forwardCompleted.clear();
    forwardStarted = false;
    forwardSendKeys.clear();
  }

  function toggleForwardTarget(target) {
    if (forwardBusy || forwardStarted || !targetSupportsForward(target, forwardRequirements(forwardArticles))) return;
    const id = target.dataset.forwardTarget;
    if (selectedTargets.has(id)) selectedTargets.delete(id);
    else if (selectedTargets.size < 10) selectedTargets.add(id);
    else notify("Можно выбрать не более 10 чатов.");
    syncForwardTargets();
  }

  function updateSelectionUi() {
    // Entering via the menu starts with a valid empty selection.
    const hadSelection = selectedArticles.size > 0;
    for (const article of selectedArticles) {
      if (!article.isConnected) selectedArticles.delete(article);
    }
    if (hadSelection && !selectedArticles.size) selectionMode = false;
    const count = selectedArticles.size;
    if (selectionCount) selectionCount.textContent = String(count);
    if (selectionBar) selectionBar.hidden = !selectionMode;
    if (selectionForward) {
      selectionForward.hidden = chatProtected;
      selectionForward.disabled = count === 0 || chatProtected;
    }
    if (selectionDelete) {
      const allDeletable = count > 0 && [...selectedArticles].every(canDeleteArticle);
      selectionDelete.disabled = !allDeletable;
      selectionDelete.title = count && !allDeletable
        ? "В выборе есть сообщения, которые вы не можете удалить."
        : "";
    }
    conversation.classList.toggle("is-message-selection", selectionMode);
  }

  function setSelectionMode(enabled, initialArticle) {
    selectionMode = enabled;
    if (!enabled) {
      selectedArticles.forEach((article) => article.classList.remove("is-selected"));
      selectedArticles = new Set();
    } else if (initialArticle) {
      selectedArticles.add(initialArticle);
      initialArticle.classList.add("is-selected");
    }
    closeMessageMenu();
    setChatMenu(false);
    updateSelectionUi();
  }

  function toggleSelected(article) {
    if (!selectionMode || !article) return;
    if (selectedArticles.has(article)) {
      selectedArticles.delete(article);
      article.classList.remove("is-selected");
    } else {
      selectedArticles.add(article);
      article.classList.add("is-selected");
    }
    if (!selectedArticles.size) setSelectionMode(false);
    else updateSelectionUi();
  }

  function closeConfirmModals(force = false) {
    if (busyDelete && !force) return;
    [deleteMessageModal, clearHistoryModal, deleteChatModal].forEach((modal) => {
      if (modal) modal.hidden = true;
    });
    deleteArticles = [];
    busyDelete = false;
    if (deleteMessageConfirm) deleteMessageConfirm.disabled = false;
    if (clearHistoryConfirm) clearHistoryConfirm.disabled = false;
    if (deleteChatConfirm) deleteChatConfirm.disabled = false;
  }

  async function togglePin(article) {
    if (!article?.dataset.pinUrl) return;
    try {
      const payload = await postForm(article.dataset.pinUrl);
      const pinned = Boolean(payload.pinned);
      article.dataset.messagePinned = String(pinned);
      article.classList.toggle("is-pinned", pinned);

      const pins = payload.pins || [];
      const pinnedBar = document.getElementById("pinnedMessageBar");
      const pinnedCount = document.getElementById("pinnedMessageCount");
      const pinnedPreview = document.getElementById("pinnedMessagePreview");
      if (pinnedBar) {
        pinnedBar.hidden = pins.length === 0;
        pinnedBar.dataset.messageId = pins.length ? String(pins[0].message_id) : "";
      }
      if (pinnedCount) pinnedCount.textContent = pins.length ? String(pins.length) : "";
      if (pinnedPreview) pinnedPreview.textContent = pins.length ? pins[0].preview : "";
      notify(pinned ? "Сообщение закреплено." : "Сообщение откреплено.");
    } catch (error) {
      notify(error.message);
    }
  }

  function configureDeleteMessageModal(articles) {
    if (!deleteMessageModal || !articles?.length) return;
    const valid = articles.filter(Boolean);
    if (!valid.every(canDeleteArticle)) {
      notify("В выборе есть сообщения, которые вы не можете удалить.");
      return;
    }
    deleteArticles = valid;
    const count = valid.length;

    if (deleteMessageTitle) {
      deleteMessageTitle.textContent = count === 1
        ? "Удалить сообщение?"
        : "Удалить сообщения (" + count + ")?";
    }
    if (deleteMessageForEveryone) deleteMessageForEveryone.checked = false;
    if (deleteMessageForEveryoneRow) {
      deleteMessageForEveryoneRow.hidden = chatType !== "private" || chatSaved;
    }
    if (deleteMessageForEveryoneLabel) {
      deleteMessageForEveryoneLabel.textContent = "Также удалить для " + peerName;
    }
    if (deleteMessageText) {
      if (chatType === "private" && !chatSaved) {
        deleteMessageText.textContent = count === 1
          ? "Сообщение исчезнет только у вас. Можно удалить его и у собеседника."
          : "Сообщения исчезнут только у вас. Можно удалить их и у собеседника.";
      } else if (chatType === "private") {
        deleteMessageText.textContent = "Выбранное будет удалено из Избранного.";
      } else {
        deleteMessageText.textContent = count === 1
          ? "Сообщение будет удалено для всех участников."
          : "Сообщения будут удалены для всех участников.";
      }
    }
    deleteMessageModal.hidden = false;
  }

  async function deleteArticlesNow() {
    if (busyDelete || !deleteArticles.length) return;
    busyDelete = true;
    if (deleteMessageConfirm) deleteMessageConfirm.disabled = true;

    const scope = chatType === "private"
      ? ((deleteMessageForEveryone?.checked && !chatSaved) ? "everyone" : "me")
      : "everyone";
    const articles = [...deleteArticles];

    try {
      for (const article of articles) {
        if (article.isConnected && article.dataset.deleteUrl) {
          try { await postForm(article.dataset.deleteUrl, { scope }); }
          catch (error) {
            // A lost successful response or remote deletion makes the next
            // retry return 404. The message is already inaccessible.
            if (error.status !== 404) throw error;
          }
        }
        article.remove();
        selectedArticles.delete(article);
        deleteArticles = deleteArticles.filter(item => item !== article);
      }
      closeConfirmModals(true);
      if (selectionMode) setSelectionMode(false);
      void window.SovietgramChat?.syncNow();
      void window.SovietgramSidebar?.refresh();
      notify(scope === "everyone" ? "Удалено для всех." : "Удалено у вас.");
    } catch (error) {
      notify(error.message + " Осталось: " + deleteArticles.length);
      busyDelete = false;
      if (deleteMessageConfirm) deleteMessageConfirm.disabled = false;
      if (deleteMessageTitle) deleteMessageTitle.textContent = "Удалить оставшиеся (" + deleteArticles.length + ")?";
      updateSelectionUi();
    }
  }

  function configureClearHistoryModal() {
    if (!clearHistoryModal) return;
    if (clearHistoryTitle) {
      clearHistoryTitle.textContent = chatSaved ? "Очистить Избранное?" : "Очистить историю?";
    }
    if (clearHistoryForEveryone) clearHistoryForEveryone.checked = false;
    if (clearHistoryForEveryoneRow) {
      clearHistoryForEveryoneRow.hidden = chatType !== "private" || chatSaved;
    }
    if (clearHistoryForEveryoneLabel) {
      clearHistoryForEveryoneLabel.textContent = "Также удалить для " + peerName;
    }
    if (clearHistoryText) {
      if (chatType === "private" && !chatSaved) {
        clearHistoryText.textContent = "История исчезнет только у вас. Можно удалить её и у собеседника.";
      } else if (chatSaved) {
        clearHistoryText.textContent = "Все сообщения в Избранном будут удалены.";
      } else {
        clearHistoryText.textContent = "История этого сообщества будет скрыта только у вас.";
      }
    }
    clearHistoryModal.hidden = false;
  }

  async function clearHistoryNow() {
    const scope = chatType === "private" && !chatSaved && clearHistoryForEveryone?.checked
      ? "everyone"
      : "me";
    if (clearHistoryConfirm) clearHistoryConfirm.disabled = true;
    try {
      const payload = await postForm(chatActionUrl, { action: "clear", scope });
      notify(payload.message || "История очищена.");
      window.location.reload();
    } catch (error) {
      notify(error.message);
      if (clearHistoryConfirm) clearHistoryConfirm.disabled = false;
    }
  }

  function configureDeleteChatModal() {
    if (!deleteChatModal) return;
    if (deleteChatForEveryone) deleteChatForEveryone.checked = false;

    if (chatType === "private") {
      if (deleteChatTitle) deleteChatTitle.textContent = "Удалить чат с " + peerName + "?";
      if (deleteChatText) {
        deleteChatText.textContent = "Чат и история исчезнут из вашего списка. Если собеседник напишет снова, чат появится заново.";
      }
      if (deleteChatForEveryoneRow) deleteChatForEveryoneRow.hidden = false;
      if (deleteChatForEveryoneLabel) {
        deleteChatForEveryoneLabel.textContent = "Также удалить для " + peerName;
      }
      if (deleteChatConfirm) deleteChatConfirm.textContent = "Удалить чат";
    } else if (chatRole === "owner") {
      const noun = chatType === "channel" ? "канал" : "группу";
      if (deleteChatTitle) deleteChatTitle.textContent = "Удалить " + noun + "?";
      if (deleteChatText) {
        deleteChatText.textContent = "Сообщество, история и настройки будут удалены для всех участников. Это действие нельзя отменить.";
      }
      if (deleteChatForEveryoneRow) deleteChatForEveryoneRow.hidden = true;
      if (deleteChatConfirm) deleteChatConfirm.textContent = chatType === "channel" ? "Удалить канал" : "Удалить группу";
    } else {
      const noun = chatType === "channel" ? "канал" : "группу";
      if (deleteChatTitle) deleteChatTitle.textContent = "Покинуть " + noun + "?";
      if (deleteChatText) {
        deleteChatText.textContent = "Вы потеряете доступ к чату. Вернуться можно будет по ссылке или приглашению.";
      }
      if (deleteChatForEveryoneRow) deleteChatForEveryoneRow.hidden = true;
      if (deleteChatConfirm) deleteChatConfirm.textContent = "Покинуть";
    }
    deleteChatModal.hidden = false;
  }

  async function deleteChatNow() {
    if (deleteChatConfirm) deleteChatConfirm.disabled = true;
    const scope = chatType === "private" && deleteChatForEveryone?.checked ? "everyone" : "me";
    try {
      const payload = await postForm(chatActionUrl, { action: "delete_chat", scope });
      notify(payload.message || "Готово.");
      window.location.assign(payload.redirect_url || "/");
    } catch (error) {
      notify(error.message);
      if (deleteChatConfirm) deleteChatConfirm.disabled = false;
    }
  }

  // chat.js owns the paginated search request, including filters and aborts.
  async function saveEditedMessage() {
    if (!editArticle?.dataset.editUrl || !editText) return;
    if (editSave) editSave.disabled = true;
    try {
      const payload = await postForm(editArticle.dataset.editUrl, { text: editText.value });
      const message = payload.message;
      editArticle.dataset.messageText = message.text || "";
      let paragraph = editArticle.querySelector(".message__text");
      if (message.text) {
        if (!paragraph) {
          paragraph = document.createElement("div");
          paragraph.className = "message__text markdown-body";
          editArticle.insertBefore(paragraph, editArticle.querySelector("[data-message-reactions]") || editArticle.querySelector("footer"));
        }
        window.SovietgramSocial.renderText(paragraph, message.text, message.markdown_html);
      } else {
        paragraph?.remove();
      }
      window.updateSovietgramChatMessage?.(message);
      closeEditModal();
    } catch (error) {
      notify(error.message);
    } finally {
      if (editSave) editSave.disabled = false;
    }
  }

  async function forwardSelected() {
    if (!forwardArticles.length || !selectedTargets.size || forwardBusy || chatProtected) return;
    forwardBusy = true;
    forwardStarted = true;
    const targets = [...selectedTargets];
    const hide = Boolean(forwardHideSender?.checked);
    const silent = Boolean(forwardSilent?.checked);
    const total = forwardArticles.length * targets.length;
    syncForwardTargets();
    const errors = [];
    try {
      for (const targetId of targets) {
        for (const article of forwardArticles) {
          const key = targetId + ":" + article.dataset.messageId;
          if (forwardCompleted.has(key)) continue;
          if (chatProtected) throw new Error("Пересылка запрещена для этой переписки.");
          try {
            const payload = await postForm(article.dataset.forwardUrl, {
              target_chat_id: targetId, hide_sender: hide ? "1" : "0", silent: silent ? "1" : "0",
              client_message_id: forwardSendKeys.key(key, [article.dataset.forwardUrl, hide, silent]),
            });
            forwardCompleted.add(key);
            if (String(payload.target_chat_id) === String(conversation.dataset.chatId)) {
              window.renderSovietgramChatMessage?.(payload.message);
            }
          } catch (error) {
            errors.push(error.message);
            // Do not reorder messages within a destination on failure.
            break;
          }
          if (forwardStatus) forwardStatus.textContent = "Отправлено: " + forwardCompleted.size + " из " + total;
        }
      }
      if (forwardCompleted.size === total) {
        closeForwardModal(true);
        if (selectionMode) setSelectionMode(false);
        notify("Переслано: " + total);
      } else {
        if (forwardStatus) forwardStatus.textContent = "Отправлено: " + forwardCompleted.size + " из " + total + ". " + (errors[0] || "Повторите оставшиеся.");
        notify("Часть сообщений не отправлена. Можно повторить оставшиеся.");
      }
    } catch (error) {
      if (forwardStatus) forwardStatus.textContent = error.message;
      notify(error.message);
    } finally {
      forwardBusy = false;
      syncForwardTargets();
      void window.SovietgramSidebar?.refresh();
    }
  }

  document.addEventListener("sovietgram:forward-message", event => {
    if (event.detail?.article) openForwardModal([event.detail.article]);
  });
  forwardModal?.addEventListener("click", event => {
    if (event.target === forwardModal) closeForwardModal();
  });
  forwardConfirm?.addEventListener("click", () => { void forwardSelected(); });

  // Remove stale selection entries after remote deletes or window replacement.
  const messageFlow = document.getElementById("messageFlow");
  if (messageFlow && typeof MutationObserver !== "undefined") {
    new MutationObserver(() => { if (selectionMode) updateSelectionUi(); })
      .observe(messageFlow, {childList:true});
  }

  document.addEventListener("click", (event) => {
    const target = event.target;

    if (selectionMode) {
      const article = target.closest(".message[data-message-id]");
      if (article && !target.closest(".message-action-trigger")) {
        event.preventDefault();
        event.stopImmediatePropagation();
        toggleSelected(article);
        return;
      }
    }

    if (target.closest("#chatMenuButton")) {
      event.preventDefault();
      event.stopImmediatePropagation();
      setChatMenu(chatMenu ? chatMenu.hidden : true);
      return;
    }

    const muteDurationOption = target.closest("[data-chat-mute-duration]");
    if (muteDurationOption) {
      event.preventDefault();
      event.stopImmediatePropagation();
      const duration = muteDurationOption.dataset.chatMuteDuration || "";
      setChatMenu(false);
      setChatMute(duration, muteDurationOption);
      return;
    }

    if (target.closest("[data-chat-menu-mute]")) {
      event.preventDefault();
      event.stopImmediatePropagation();
      if (conversation.dataset.chatMuted === "true") {
        setChatMenu(false);
        setChatMute("off");
      } else {
        setChatMuteOptions(Boolean(chatMuteOptions?.hidden));
      }
      return;
    }

    if (target.closest("[data-toggle-chat-protection]")) {
      event.preventDefault();
      event.stopImmediatePropagation();
      setChatMenu(false);
      toggleChatProtection();
      return;
    }

    if (target.closest("[data-chat-export]")) {
      setChatMenu(false);
      return;
    }

    if (target.closest("#chatSearchToggle, [data-open-chat-search]")) {
      event.preventDefault();
      event.stopImmediatePropagation();
      setChatMenu(false);
      setSearchPanel(true);
      return;
    }

    if (target.closest("#chatSearchClose")) {
      event.preventDefault();
      event.stopImmediatePropagation();
      setSearchPanel(false);
      return;
    }

    if (target.closest("[data-select-messages]")) {
      event.preventDefault();
      event.stopImmediatePropagation();
      setSelectionMode(true);
      return;
    }

    if (target.closest("[data-clear-chat-history]")) {
      event.preventDefault();
      event.stopImmediatePropagation();
      setChatMenu(false);
      configureClearHistoryModal();
      return;
    }

    if (target.closest("[data-delete-chat]")) {
      event.preventDefault();
      event.stopImmediatePropagation();
      setChatMenu(false);
      configureDeleteChatModal();
      return;
    }

    const trigger = target.closest(".message-action-trigger");
    if (trigger) {
      event.preventDefault();
      event.stopImmediatePropagation();
      document.querySelectorAll(".message.is-context-target").forEach((node) => node.classList.remove("is-context-target"));
      const article = trigger.closest(".message[data-message-id]");
      if (!article) return;
      const rect = trigger.getBoundingClientRect();
      openMessageMenu(article, rect.right, rect.bottom + 4);
      return;
    }

    const reactionButton = target.closest("#messageContextMenu [data-pick-reaction]");
    if (reactionButton) {
      event.preventDefault();
      event.stopImmediatePropagation();
      const article = contextArticle;
      closeMessageMenu();
      if (article) void window.SovietgramSocial?.toggleReaction(article, reactionButton.dataset.pickReaction);
      return;
    }

    const actionButton = target.closest("#messageContextMenu [data-message-action]");
    if (actionButton) {
      event.preventDefault();
      event.stopImmediatePropagation();
      const article = contextArticle;
      const action = actionButton.dataset.messageAction;
      const quote = contextQuote;
      closeMessageMenu();
      if (!article) return;

      if (action === "reply") setReply(article);
      if (action === "quote" && quote && !chatProtected) {
        setReply(article, quote);
        window.getSelection()?.removeAllRanges();
      }
      if (action === "copy") {
        if (chatProtected) {
          notify("Копирование запрещено для этой переписки.");
          return;
        }
        copyText(article.dataset.messageText || "").then(() => notify("Текст скопирован.")).catch(error => notify(error.message));
      }
      if (action === "copy-link" && !chatProtected) {
        copyText(messageLink(article)).then(() => notify("Ссылка скопирована. Доступ только у участников чата.")).catch(error => notify(error.message));
      }
      if (action === "report" && !isOwn(article) && /^\d+$/.test(article.dataset.messageId || "")) {
        window.location.assign(actionButton.dataset.reportTemplate.replace(/\/0\/$/, "/" + article.dataset.messageId + "/"));
      }
      if (action === "save-sticker" && !chatProtected) {
        window.SovietgramStickers?.openIncoming?.(article.querySelector("[data-sticker-attachment]"));
      }
      if (action === "reactors") openReactors(article);
      if (action === "readers") openReaders(article);
      if (action === "edit") openEditModal(article);
      if (action === "forward") openForwardModal([article]);
      if (action === "select") setSelectionMode(true, article);
      if (action === "pin") togglePin(article);
      if (action === "delete") configureDeleteMessageModal([article]);
      return;
    }

    const forwardTarget = target.closest("[data-forward-target]");
    if (forwardTarget && forwardArticles.length) {
      event.preventDefault();
      event.stopImmediatePropagation();
      toggleForwardTarget(forwardTarget);
      return;
    }

    if (target.closest("[data-close-edit]") && editArticle) {
      event.preventDefault();
      event.stopImmediatePropagation();
      closeEditModal();
      return;
    }

    if (target.closest("#editMessageSave") && editArticle) {
      event.preventDefault();
      event.stopImmediatePropagation();
      saveEditedMessage();
      return;
    }

    if (target.closest("[data-close-forward]") && forwardArticles.length) {
      event.preventDefault();
      event.stopImmediatePropagation();
      closeForwardModal();
      return;
    }

    if (target.closest("#messageSelectionClose")) {
      event.preventDefault();
      event.stopImmediatePropagation();
      setSelectionMode(false);
      return;
    }

    if (target.closest("#messageSelectionForward")) {
      event.preventDefault();
      event.stopImmediatePropagation();
      if (selectedArticles.size) openForwardModal([...selectedArticles]);
      return;
    }

    if (target.closest("#messageSelectionDelete")) {
      event.preventDefault();
      event.stopImmediatePropagation();
      if (selectedArticles.size) configureDeleteMessageModal([...selectedArticles]);
      return;
    }

    if (target.closest("#deleteMessageCancel, #clearHistoryCancel, #deleteChatCancel")) {
      event.preventDefault();
      event.stopImmediatePropagation();
      closeConfirmModals();
      return;
    }

    if (target.closest("#deleteMessageConfirm")) {
      event.preventDefault();
      event.stopImmediatePropagation();
      deleteArticlesNow();
      return;
    }

    if (target.closest("#clearHistoryConfirm")) {
      event.preventDefault();
      event.stopImmediatePropagation();
      clearHistoryNow();
      return;
    }

    if (target.closest("#deleteChatConfirm")) {
      event.preventDefault();
      event.stopImmediatePropagation();
      deleteChatNow();
      return;
    }

    if (target === deleteMessageModal || target === clearHistoryModal || target === deleteChatModal) {
      event.preventDefault();
      event.stopImmediatePropagation();
      closeConfirmModals();
      return;
    }

    if (chatMenu && !chatMenu.hidden && !chatMenu.contains(target)) setChatMenu(false);
    if (contextMenu && !contextMenu.hidden && !contextMenu.contains(target)) closeMessageMenu();
  }, true);

  document.addEventListener("contextmenu", (event) => {
    if (selectionMode) return;
    const article = event.target.closest(".message[data-message-id]");
    if (!article) return;
    event.preventDefault();
    event.stopImmediatePropagation();
    document.querySelectorAll(".message.is-context-target").forEach((node) => node.classList.remove("is-context-target"));
    openMessageMenu(article, event.clientX, event.clientY);
  }, true);

  document.addEventListener("sovietgram:search-hashtag", event => {
    if (!searchInput || !event.detail?.tag) return;
    setSearchPanel(true);
    searchInput.value = event.detail.tag;
    searchInput.dispatchEvent(new Event("input", {bubbles:true}));
  });

  forwardSearch?.addEventListener("input", syncForwardTargets);

  editText?.addEventListener("keydown", (event) => {
    if ((event.ctrlKey || event.metaKey) && event.key === "Enter" && editArticle) {
      event.preventDefault();
      event.stopImmediatePropagation();
      saveEditedMessage();
    }
  }, true);

  document.addEventListener("keydown", (event) => {
    // Higher-level overlays own keyboard shortcuts while open.
    if (document.querySelector("dialog[open], #communityProfile:not([hidden]), #telegramSettings:not([hidden]), #userProfileOverlay:not([hidden]), #imageViewer:not([hidden])")) return;
    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "f") {
      event.preventDefault();
      event.stopImmediatePropagation();
      setChatMenu(false);
      setSearchPanel(true);
      return;
    }
    if (event.key !== "Escape") return;

    if ((deleteMessageModal && !deleteMessageModal.hidden)
        || (clearHistoryModal && !clearHistoryModal.hidden)
        || (deleteChatModal && !deleteChatModal.hidden)) {
      event.stopImmediatePropagation();
      closeConfirmModals();
      return;
    }
    if (editArticle) {
      event.stopImmediatePropagation();
      closeEditModal();
      return;
    }
    if (forwardArticles.length) {
      event.stopImmediatePropagation();
      closeForwardModal();
      return;
    }
    if (selectionMode) {
      event.stopImmediatePropagation();
      setSelectionMode(false);
      return;
    }
    if (contextMenu && !contextMenu.hidden) {
      event.stopImmediatePropagation();
      closeMessageMenu();
      return;
    }
    if (chatMenu && !chatMenu.hidden) {
      event.stopImmediatePropagation();
      setChatMenu(false);
      return;
    }
    if (searchPanel && !searchPanel.hidden) {
      event.stopImmediatePropagation();
      setSearchPanel(false);
    }
  }, true);
})();
