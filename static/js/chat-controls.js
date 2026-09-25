(() => {
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
  const searchResults = document.getElementById("chatSearchResults");
  const contextMenu = document.getElementById("messageContextMenu");
  const messageForm = document.getElementById("messageForm");
  const csrfToken = messageForm?.querySelector("[name='csrfmiddlewaretoken']")?.value || "";

  const chatType = conversation.dataset.chatType || "private";
  const chatRole = conversation.dataset.chatRole || "member";
  const chatSaved = conversation.dataset.chatSaved === "true";
  const chatTitle = conversation.dataset.chatTitle || "чат";
  const peerName = conversation.dataset.chatPeerName || chatTitle;
  const chatActionUrl = conversation.dataset.chatActionUrl || "";

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

  let contextArticle = null;
  let editArticle = null;
  let forwardArticles = [];
  let deleteArticles = [];
  let selectedArticles = new Set();
  let selectionMode = false;
  let searchTimer = 0;
  let searchController = null;
  let busyDelete = false;

  function notify(text) {
    if (typeof window.showToast === "function") window.showToast(text);
  }

  function setChatMenu(open) {
    if (!chatMenu || !chatMenuButton) return;
    chatMenu.hidden = !open;
    chatMenuButton.setAttribute("aria-expanded", String(open));
  }

  function setSearchPanel(open) {
    if (!searchPanel) return;
    searchPanel.hidden = !open;
    if (open) window.setTimeout(() => searchInput?.focus(), 0);
  }

  async function postForm(url, values) {
    const body = new FormData();
    body.append("csrfmiddlewaretoken", csrfToken);
    Object.entries(values || {}).forEach(([key, value]) => {
      body.append(key, value == null ? "" : String(value));
    });
    const response = await fetch(url, {
      method: "POST",
      credentials: "same-origin",
      headers: { "X-Requested-With": "XMLHttpRequest" },
      body
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok || payload.ok === false) {
      throw new Error(payload.error || "Не удалось выполнить действие.");
    }
    return payload;
  }

  function isOwn(article) {
    return article?.dataset.messageOwn === "true";
  }

  function isModerator() {
    return chatRole === "owner" || chatRole === "admin";
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
    if (article?.querySelector(".message-media")) return "Медиа";
    return "Сообщение";
  }

  function closeMessageMenu() {
    if (contextMenu) contextMenu.hidden = true;
    contextArticle = null;
    document.querySelectorAll(".message.is-context-target").forEach((node) => {
      node.classList.remove("is-context-target");
    });
  }

  function openMessageMenu(article, x, y) {
    if (!contextMenu || !article) return;
    contextArticle = article;
    article.classList.add("is-context-target");

    const editButton = contextMenu.querySelector('[data-message-action="edit"]');
    const copyButton = contextMenu.querySelector('[data-message-action="copy"]');
    const deleteButton = contextMenu.querySelector('[data-message-action="delete"]');
    const pinLabel = document.getElementById("messagePinLabel");

    if (editButton) editButton.hidden = !isOwn(article) || Boolean(article.dataset.messageKind);
    if (copyButton) copyButton.hidden = !(article.dataset.messageText || "").trim();
    if (deleteButton) deleteButton.hidden = !canDeleteArticle(article);
    if (pinLabel) pinLabel.textContent = article.dataset.messagePinned === "true" ? "Открепить" : "Закрепить";

    contextMenu.hidden = false;
    const rect = contextMenu.getBoundingClientRect();
    contextMenu.style.left = Math.max(6, Math.min(x, window.innerWidth - rect.width - 6)) + "px";
    contextMenu.style.top = Math.max(6, Math.min(y, window.innerHeight - rect.height - 6)) + "px";
  }

  function setReply(article) {
    const replyInput = document.getElementById("replyToInput");
    const reply = document.getElementById("composerReply");
    if (!replyInput || !reply || !article) return;
    replyInput.value = article.dataset.messageId || "";
    const name = document.getElementById("composerReplyName");
    const preview = document.getElementById("composerReplyPreview");
    if (name) name.textContent = article.dataset.messageSender || "Ответ";
    if (preview) preview.textContent = messagePreview(article);
    reply.hidden = false;
    document.getElementById("messageInput")?.focus();
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
      document.execCommand("copy");
      area.remove();
    }
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

  function openForwardModal(articles) {
    if (!forwardModal || !articles?.length) return;
    forwardArticles = articles.filter(Boolean);
    forwardModal.hidden = false;
    if (forwardSearch) {
      forwardSearch.value = "";
      document.querySelectorAll("[data-forward-target]").forEach((target) => {
        target.hidden = false;
      });
      window.setTimeout(() => forwardSearch.focus(), 0);
    }
  }

  function closeForwardModal() {
    if (forwardModal) forwardModal.hidden = true;
    forwardArticles = [];
  }

  function updateSelectionUi() {
    const count = selectedArticles.size;
    if (selectionCount) selectionCount.textContent = String(count);
    if (selectionBar) selectionBar.hidden = !selectionMode;
    if (selectionForward) selectionForward.disabled = count === 0;
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

  function closeConfirmModals() {
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
        if (!article.dataset.deleteUrl) continue;
        await postForm(article.dataset.deleteUrl, { scope });
        article.remove();
        selectedArticles.delete(article);
      }
      closeConfirmModals();
      if (selectionMode) setSelectionMode(false);
      notify(scope === "everyone" ? "Удалено для всех." : "Удалено у вас.");
    } catch (error) {
      notify(error.message);
      busyDelete = false;
      if (deleteMessageConfirm) deleteMessageConfirm.disabled = false;
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

  function renderSearchResults(results) {
    if (!searchResults) return;
    searchResults.replaceChildren();
    if (!results.length) {
      const empty = document.createElement("div");
      empty.className = "chat-search-empty";
      empty.textContent = searchInput?.value.trim()
        ? "Ничего не нашлось."
        : "Введите текст сообщения или название файла.";
      searchResults.appendChild(empty);
      return;
    }

    results.forEach((result) => {
      const link = document.createElement("a");
      link.className = "chat-search-result";
      link.href = result.url;
      const name = document.createElement("strong");
      name.textContent = result.sender_name;
      const preview = document.createElement("span");
      preview.textContent = result.preview;
      const time = document.createElement("small");
      time.textContent = result.time;
      link.append(name, preview, time);
      link.addEventListener("click", (event) => {
        const article = document.querySelector('[data-message-id="' + result.id + '"]');
        if (!article) return;
        event.preventDefault();
        setSearchPanel(false);
        article.scrollIntoView({ behavior: "smooth", block: "center" });
        article.classList.add("is-target");
        window.setTimeout(() => article.classList.remove("is-target"), 1500);
      });
      searchResults.appendChild(link);
    });
  }

  function scheduleSearch() {
    if (!searchInput || !searchPanel?.dataset.searchUrl) return;
    window.clearTimeout(searchTimer);
    const query = searchInput.value.trim();
    if (!query) {
      renderSearchResults([]);
      return;
    }
    searchTimer = window.setTimeout(async () => {
      if (searchController) searchController.abort();
      searchController = new AbortController();
      try {
        const url = new URL(searchPanel.dataset.searchUrl, window.location.origin);
        url.searchParams.set("q", query);
        const response = await fetch(url, {
          credentials: "same-origin",
          signal: searchController.signal,
          headers: { "X-Requested-With": "XMLHttpRequest" }
        });
        const payload = await response.json().catch(() => ({}));
        if (!response.ok) throw new Error(payload.error || "Поиск временно недоступен.");
        renderSearchResults(payload.results || []);
      } catch (error) {
        if (error.name !== "AbortError") notify(error.message);
      }
    }, 180);
  }

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
          paragraph = document.createElement("p");
          paragraph.className = "message__text";
          editArticle.insertBefore(paragraph, editArticle.querySelector("footer"));
        }
        paragraph.textContent = message.text;
      } else {
        paragraph?.remove();
      }
      closeEditModal();
    } catch (error) {
      notify(error.message);
    } finally {
      if (editSave) editSave.disabled = false;
    }
  }

  async function forwardSelectedTo(target) {
    if (!forwardArticles.length) return;
    target.disabled = true;
    try {
      for (const article of forwardArticles) {
        if (!article.dataset.forwardUrl) continue;
        await postForm(article.dataset.forwardUrl, {
          target_chat_id: target.dataset.forwardTarget || ""
        });
      }
      notify(forwardArticles.length === 1 ? "Сообщение переслано." : "Сообщения пересланы.");
      closeForwardModal();
      if (selectionMode) setSelectionMode(false);
    } catch (error) {
      notify(error.message);
    } finally {
      target.disabled = false;
    }
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

    const actionButton = target.closest("#messageContextMenu [data-message-action]");
    if (actionButton) {
      event.preventDefault();
      event.stopImmediatePropagation();
      const article = contextArticle;
      const action = actionButton.dataset.messageAction;
      closeMessageMenu();
      if (!article) return;

      if (action === "reply") setReply(article);
      if (action === "copy") {
        copyText(article.dataset.messageText || "").then(() => notify("Текст скопирован."));
      }
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
      forwardSelectedTo(forwardTarget);
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

  searchInput?.addEventListener("input", scheduleSearch);

  forwardSearch?.addEventListener("input", () => {
    if (!forwardArticles.length) return;
    const query = forwardSearch.value.trim().toLowerCase();
    document.querySelectorAll("[data-forward-target]").forEach((target) => {
      target.hidden = Boolean(query) && !(target.dataset.forwardSearch || "").includes(query);
    });
  });

  editText?.addEventListener("keydown", (event) => {
    if ((event.ctrlKey || event.metaKey) && event.key === "Enter" && editArticle) {
      event.preventDefault();
      event.stopImmediatePropagation();
      saveEditedMessage();
    }
  }, true);

  document.addEventListener("keydown", (event) => {
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
