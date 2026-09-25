(() => {
  const chatMenuButton = document.getElementById("chatMenuButton");
  const chatMenu = document.getElementById("chatMenu");
  const searchToggle = document.getElementById("chatSearchToggle");
  const searchPanel = document.getElementById("chatSearchPanel");
  const searchInput = document.getElementById("chatSearchInput");
  const searchClose = document.getElementById("chatSearchClose");
  const searchResults = document.getElementById("chatSearchResults");
  const contextMenu = document.getElementById("messageContextMenu");
  const messageForm = document.getElementById("messageForm");
  const csrfToken = messageForm?.querySelector("[name='csrfmiddlewaretoken']")?.value || "";

  if (!chatMenuButton && !searchToggle && !contextMenu) return;

  let contextArticle = null;
  let searchTimer = 0;
  let searchController = null;
  let editArticle = null;
  let forwardArticle = null;

  function notify(text) {
    if (typeof window.showToast === "function") window.showToast(text);
  }

  function setChatMenu(open) {
    if (typeof window.setChatMenu === "function") {
      window.setChatMenu(open);
      return;
    }
    if (!chatMenu || !chatMenuButton) return;
    chatMenu.hidden = !open;
    chatMenuButton.setAttribute("aria-expanded", String(open));
  }

  function setSearchPanel(open) {
    if (typeof window.setSearchPanel === "function") {
      window.setSearchPanel(open);
      return;
    }
    if (!searchPanel) return;
    searchPanel.hidden = !open;
    if (open) window.setTimeout(() => searchInput?.focus(), 0);
  }

  function openMessageMenu(article, x, y) {
    if (typeof window.openMessageMenu === "function") {
      window.openMessageMenu(article, x, y);
      return;
    }
    if (!contextMenu || !article) return;
    contextArticle = article;
    const own = article.dataset.messageOwn === "true";
    const hasText = Boolean((article.dataset.messageText || "").trim());
    const editButton = contextMenu.querySelector('[data-message-action="edit"]');
    const copyButton = contextMenu.querySelector('[data-message-action="copy"]');
    const pinLabel = document.getElementById("messagePinLabel");
    if (editButton) editButton.hidden = !own;
    if (copyButton) copyButton.hidden = !hasText;
    if (pinLabel) pinLabel.textContent = article.dataset.messagePinned === "true" ? "Открепить" : "Закрепить";
    contextMenu.hidden = false;
    const rect = contextMenu.getBoundingClientRect();
    contextMenu.style.left = Math.max(6, Math.min(x, window.innerWidth - rect.width - 6)) + "px";
    contextMenu.style.top = Math.max(6, Math.min(y, window.innerHeight - rect.height - 6)) + "px";
  }

  function closeMessageMenu() {
    if (typeof window.closeMessageMenu === "function") {
      window.closeMessageMenu();
      contextArticle = null;
      return;
    }
    if (contextMenu) contextMenu.hidden = true;
    contextArticle = null;
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
      body,
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok || payload.ok === false) throw new Error(payload.error || "Не удалось выполнить действие.");
    return payload;
  }

  function messagePreview(article) {
    const text = (article?.dataset.messageText || "").trim();
    if (text) return text.replace(/\s+/g, " ").slice(0, 150);
    const fileName = article?.querySelector(".message-file-card strong")?.textContent?.trim();
    if (fileName) return fileName;
    if (article?.querySelector(".message-media")) return "Медиа";
    return "Сообщение";
  }

  function setReply(article) {
    if (typeof window.setReply === "function") {
      window.setReply(article);
      return;
    }
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
    if (typeof window.copyText === "function") {
      await window.copyText(value);
      return;
    }
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
    if (typeof window.openEditModal === "function") {
      window.openEditModal(article);
      return;
    }
    const modal = document.getElementById("editMessageModal");
    const text = document.getElementById("editMessageText");
    if (!modal || !text || !article) return;
    editArticle = article;
    text.value = article.dataset.messageText || "";
    modal.hidden = false;
    window.setTimeout(() => text.focus(), 0);
  }

  function closeEditModal() {
    const modal = document.getElementById("editMessageModal");
    if (typeof window.closeEditModal === "function") {
      window.closeEditModal();
    } else if (modal) {
      modal.hidden = true;
    }
    editArticle = null;
  }

  function openForwardModal(article) {
    if (typeof window.openForwardModal === "function") {
      window.openForwardModal(article);
      return;
    }
    const modal = document.getElementById("forwardMessageModal");
    if (!modal || !article) return;
    forwardArticle = article;
    modal.hidden = false;
    const input = document.getElementById("forwardTargetSearch");
    if (input) {
      input.value = "";
      document.querySelectorAll("[data-forward-target]").forEach((target) => { target.hidden = false; });
      window.setTimeout(() => input.focus(), 0);
    }
  }

  function closeForwardModal() {
    const modal = document.getElementById("forwardMessageModal");
    if (typeof window.closeForwardModal === "function") {
      window.closeForwardModal();
    } else if (modal) {
      modal.hidden = true;
    }
    forwardArticle = null;
  }

  function fallbackApplyMessageUpdate(payload) {
    const message = payload?.message;
    if (!message) return;
    const article = document.querySelector('[data-message-id="' + message.id + '"]');
    if (!article) return;
    if (message.is_deleted) {
      article.remove();
      return;
    }
    article.dataset.messageText = message.text || "";
    const paragraph = article.querySelector(".message__text");
    if (paragraph) paragraph.textContent = message.text || "";
  }

  async function togglePin(article) {
    if (typeof window.toggleMessagePin === "function") {
      await window.toggleMessagePin(article);
      return;
    }
    if (!article?.dataset.pinUrl) return;
    const payload = await postForm(article.dataset.pinUrl);
    const pinned = (payload.pins || []).some((pin) => String(pin.message_id) === article.dataset.messageId);
    article.dataset.messagePinned = String(pinned);
    article.classList.toggle("is-pinned", pinned);
    notify(pinned ? "Сообщение закреплено." : "Сообщение откреплено.");
  }

  async function deleteMessage(article) {
    if (typeof window.deleteMessage === "function") {
      await window.deleteMessage(article);
      return;
    }
    if (!article?.dataset.deleteUrl || !window.confirm("Удалить это сообщение?")) return;
    const payload = await postForm(article.dataset.deleteUrl);
    fallbackApplyMessageUpdate(payload);
    notify("Сообщение удалено.");
  }

  async function handleMessageAction(button) {
    const article = contextArticle || document.querySelector(".message.is-context-target");
    if (!article) return;
    const action = button.dataset.messageAction;
    closeMessageMenu();
    try {
      if (action === "reply") setReply(article);
      if (action === "copy") {
        await copyText(article.dataset.messageText || "");
        notify("Текст скопирован.");
      }
      if (action === "edit") openEditModal(article);
      if (action === "forward") openForwardModal(article);
      if (action === "pin") await togglePin(article);
      if (action === "delete") await deleteMessage(article);
    } catch (error) {
      notify(error.message);
    }
  }

  function renderSearchResults(results) {
    if (!searchResults) return;
    searchResults.replaceChildren();
    if (!results.length) {
      const empty = document.createElement("div");
      empty.className = "chat-search-empty";
      empty.textContent = searchInput?.value.trim() ? "Ничего не нашлось." : "Введите текст сообщения или название файла.";
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
        if (typeof window.jumpToMessage === "function") window.jumpToMessage(result.id);
        else article.scrollIntoView({ behavior: "smooth", block: "center" });
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
          headers: { "X-Requested-With": "XMLHttpRequest" },
        });
        const payload = await response.json().catch(() => ({}));
        if (!response.ok) throw new Error(payload.error || "Поиск временно недоступен.");
        renderSearchResults(payload.results || []);
      } catch (error) {
        if (error.name !== "AbortError") notify(error.message);
      }
    }, 180);
  }

  document.addEventListener("click", (event) => {
    const target = event.target;
    const headerMenu = target.closest("#chatMenuButton");
    if (headerMenu) {
      event.preventDefault();
      event.stopImmediatePropagation();
      setChatMenu(chatMenu ? chatMenu.hidden : true);
      return;
    }

    const searchButton = target.closest("#chatSearchToggle, [data-open-chat-search]");
    if (searchButton) {
      event.preventDefault();
      event.stopImmediatePropagation();
      setChatMenu(false);
      setSearchPanel(true);
      return;
    }

    const closeSearch = target.closest("#chatSearchClose");
    if (closeSearch) {
      event.preventDefault();
      event.stopImmediatePropagation();
      setSearchPanel(false);
      return;
    }

    const messageTrigger = target.closest(".message-action-trigger");
    if (messageTrigger) {
      event.preventDefault();
      event.stopImmediatePropagation();
      document.querySelectorAll(".message.is-context-target").forEach((node) => node.classList.remove("is-context-target"));
      const article = messageTrigger.closest(".message[data-message-id]");
      if (!article) return;
      article.classList.add("is-context-target");
      contextArticle = article;
      const rect = messageTrigger.getBoundingClientRect();
      openMessageMenu(article, rect.right, rect.bottom + 4);
      return;
    }

    const actionButton = target.closest("#messageContextMenu [data-message-action]");
    if (actionButton) {
      event.preventDefault();
      event.stopImmediatePropagation();
      handleMessageAction(actionButton);
      return;
    }

    if (chatMenu && !chatMenu.hidden && !chatMenu.contains(target)) setChatMenu(false);
    if (contextMenu && !contextMenu.hidden && !contextMenu.contains(target)) closeMessageMenu();
  }, true);

  document.addEventListener("contextmenu", (event) => {
    const article = event.target.closest(".message[data-message-id]");
    if (!article) return;
    event.preventDefault();
    event.stopImmediatePropagation();
    document.querySelectorAll(".message.is-context-target").forEach((node) => node.classList.remove("is-context-target"));
    article.classList.add("is-context-target");
    contextArticle = article;
    openMessageMenu(article, event.clientX, event.clientY);
  }, true);

  searchInput?.addEventListener("input", scheduleSearch);

  document.querySelectorAll("[data-close-edit]").forEach((button) => {
    button.addEventListener("click", (event) => {
      if (typeof window.closeEditModal === "function") return;
      event.preventDefault();
      event.stopImmediatePropagation();
      closeEditModal();
    }, true);
  });

  document.getElementById("editMessageSave")?.addEventListener("click", async (event) => {
    if (typeof window.openEditModal === "function") return;
    event.preventDefault();
    event.stopImmediatePropagation();
    const article = editArticle;
    const text = document.getElementById("editMessageText");
    if (!article?.dataset.editUrl || !text) return;
    try {
      const payload = await postForm(article.dataset.editUrl, { text: text.value });
      fallbackApplyMessageUpdate(payload);
      closeEditModal();
    } catch (error) {
      notify(error.message);
    }
  }, true);

  document.querySelectorAll("[data-close-forward]").forEach((button) => {
    button.addEventListener("click", (event) => {
      if (typeof window.closeForwardModal === "function") return;
      event.preventDefault();
      event.stopImmediatePropagation();
      closeForwardModal();
    }, true);
  });

  const forwardSearch = document.getElementById("forwardTargetSearch");
  forwardSearch?.addEventListener("input", () => {
    if (typeof window.openForwardModal === "function") return;
    const query = forwardSearch.value.trim().toLowerCase();
    document.querySelectorAll("[data-forward-target]").forEach((target) => {
      target.hidden = Boolean(query) && !(target.dataset.forwardSearch || "").includes(query);
    });
  });

  document.querySelectorAll("[data-forward-target]").forEach((target) => {
    target.addEventListener("click", async (event) => {
      if (typeof window.openForwardModal === "function") return;
      event.preventDefault();
      event.stopImmediatePropagation();
      if (!forwardArticle?.dataset.forwardUrl) return;
      target.disabled = true;
      try {
        await postForm(forwardArticle.dataset.forwardUrl, { target_chat_id: target.dataset.forwardTarget || "" });
        notify("Сообщение переслано.");
        closeForwardModal();
      } catch (error) {
        notify(error.message);
      } finally {
        target.disabled = false;
      }
    }, true);
  });

  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
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
    }
    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "f" && searchPanel) {
      event.preventDefault();
      event.stopImmediatePropagation();
      setSearchPanel(true);
    }
  }, true);
})();
