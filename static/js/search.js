(() => {
  const sidebarInput = document.getElementById("chatFilter");
  const sidebarResults = document.getElementById("sidebarGlobalSearch");
  const chatRows = () => Array.from(document.querySelectorAll("[data-chat-row]"));
  const chatFilterEmpty = () => document.getElementById("chatFilterEmpty");

  const peopleInput = document.getElementById("peopleSearchInput");
  const contactsResults = document.getElementById("contactsLiveSearch");
  const contactsCard = peopleInput ? peopleInput.closest(".contacts-card") : null;

  let sidebarTimer = 0;
  let sidebarController = null;
  let contactsTimer = 0;
  let contactsController = null;

  function toast(text) {
    if (typeof window.showToast === "function") window.showToast(text);
  }

  function csrfToken() {
    const input = document.querySelector('[name="csrfmiddlewaretoken"]');
    if (input && input.value) return input.value;
    const item = document.cookie.split("; ").find((part) => part.startsWith("csrftoken="));
    return item ? decodeURIComponent(item.split("=").slice(1).join("=")) : "";
  }

  async function fetchSearch(input, controller, before = null) {
    const endpoint = input && input.dataset.globalSearchUrl;
    const query = input ? input.value.trim() : "";
    if (!endpoint || !query) return null;
    const url = new URL(endpoint, window.location.origin);
    url.searchParams.set("q", query);
    if (before) {
      url.searchParams.set("before", String(before));
      url.searchParams.set("messages_only", "1");
    }
    const response = await fetch(url, {
      credentials: "same-origin",
      signal: controller.signal,
      headers: { "X-Requested-With": "XMLHttpRequest" },
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok || payload.ok === false) {
      throw new Error(payload.error || "Поиск временно недоступен.");
    }
    return payload;
  }

  function avatarNode(item) {
    const node = document.createElement(item.avatar_url ? "img" : "span");
    node.className = "global-search-result__avatar";
    if (item.avatar_kind === "user" && item.avatar_id != null) {
      node.dataset.avatarUserId = String(item.avatar_id);
    } else if (item.avatar_kind === "chat" && item.avatar_id != null) {
      node.dataset.avatarChatId = String(item.avatar_id);
    }
    if (item.avatar_url) {
      node.src = item.avatar_url;
      node.alt = "";
      node.loading = "lazy";
    } else {
      node.textContent = item.avatar_text || "?";
    }
    return node;
  }

  function resultRow(options) {
    const row = document.createElement("a");
    row.className = "global-search-result" + (options.extraClass ? " " + options.extraClass : "");
    row.href = options.href;
    if (options.profile) row.dataset.userProfile = "";
    row.appendChild(avatarNode(options.item));

    const copy = document.createElement("span");
    copy.className = "global-search-result__copy";
    const strong = document.createElement("strong");
    strong.textContent = options.title;
    const small = document.createElement("small");
    small.textContent = options.meta || "";
    copy.append(strong, small);
    row.appendChild(copy);
    return row;
  }

  function section(title, items, render) {
    if (!items || !items.length) return null;
    const root = document.createElement("section");
    root.className = "global-search-section";
    const heading = document.createElement("div");
    heading.className = "global-search-section__title";
    heading.textContent = title;
    root.appendChild(heading);
    items.forEach((item) => root.appendChild(render(item)));
    return root;
  }

  function messageRow(item) {
    const row = document.createElement("a");
    row.className = "global-search-result global-search-result--message";
    row.href = item.url;

    const marker = document.createElement("span");
    marker.className = "global-search-result__message-icon";
    const icon = document.createElement("span");
    icon.className = "tg-native-icon tg-native-icon--search tg-native-icon--compact";
    icon.setAttribute("aria-hidden", "true");
    marker.appendChild(icon);

    const copy = document.createElement("span");
    copy.className = "global-search-result__copy";
    const strong = document.createElement("strong");
    strong.textContent = item.chat_title;
    const preview = document.createElement("small");
    preview.textContent = item.sender_name + ": " + item.preview;
    const time = document.createElement("em");
    time.textContent = item.time;
    copy.append(strong, preview, time);

    row.append(marker, copy);
    return row;
  }

  function communityRow(item) {
    const row = document.createElement("div");
    row.className = "global-search-result global-search-result--community";
    row.appendChild(avatarNode(item));

    const copy = document.createElement("span");
    copy.className = "global-search-result__copy";
    const strong = document.createElement("strong");
    strong.textContent = item.title;
    const small = document.createElement("small");
    small.textContent = "@" + item.username + " · " + item.status;
    copy.append(strong, small);
    row.appendChild(copy);

    const join = document.createElement("button");
    join.type = "button";
    join.className = "global-search-result__action";
    join.textContent = item.type === "channel" ? "Подписаться" : "Вступить";
    join.addEventListener("click", async () => {
      join.disabled = true;
      try {
        const response = await fetch(item.join_url, {
          method: "POST",
          credentials: "same-origin",
          headers: {
            "X-CSRFToken": csrfToken(),
            "X-Requested-With": "XMLHttpRequest",
          },
        });
        if (!response.ok) throw new Error("Не удалось вступить.");
        window.location.assign(response.url || "/");
      } catch (error) {
        toast(error.message);
        join.disabled = false;
      }
    });
    row.appendChild(join);
    return row;
  }

  function renderSidebar(payload) {
    if (!sidebarResults) return;
    sidebarResults.replaceChildren();

    const blocks = [
      section("Чаты", payload.chats, (item) =>
        resultRow({
          href: item.url,
          item: item,
          title: item.title,
          meta: item.username ? "@" + item.username + " · " + item.status : item.status,
        })
      ),
      section("Люди", payload.people, (item) =>
        resultRow({
          href: item.profile_url,
          item: item,
          title: item.display_name,
          meta: "@" + item.username + " · " + item.status,
          profile: true,
        })
      ),
      section("Сообщества", payload.communities, communityRow),
      section("Сообщения", payload.messages, messageRow),
    ].filter(Boolean);

    if (!blocks.length) {
      const empty = document.createElement("div");
      empty.className = "global-search-empty";
      empty.textContent = "Ничего не найдено.";
      sidebarResults.appendChild(empty);
    } else {
      blocks.forEach((block) => sidebarResults.appendChild(block));
    }
    sidebarResults.hidden = false;
    if (payload.next_before) {
      const more = document.createElement("button");
      more.type = "button";
      more.className = "chat-search-more";
      more.textContent = "Ещё сообщения";
      more.addEventListener("click", async () => {
        if (sidebarInput.value.trim() !== payload.query) return;
        more.disabled = true;
        sidebarController?.abort();
        const controller = new AbortController();
        sidebarController = controller;
        try {
          const page = await fetchSearch(sidebarInput, controller, payload.next_before);
          if (!page || controller !== sidebarController || controller.signal.aborted || sidebarInput.value.trim() !== page.query) return;
          const offset = sidebarResults.scrollTop;
          const messages = payload.messages || [];
          renderSidebar({
            ...payload, next_before: page.next_before,
            messages: [...messages, ...(page.messages || []).filter(item => !messages.some(old => old.id === item.id))],
          });
          sidebarResults.scrollTop = offset;
        } catch (error) {
          if (error.name !== "AbortError" && controller === sidebarController) toast(error.message);
        } finally {
          if (more.isConnected) more.disabled = false;
        }
      });
      sidebarResults.appendChild(more);
    }
  }

  function renderContacts(payload) {
    if (!contactsResults || !contactsCard) return;
    contactsResults.replaceChildren();

    const blocks = [
      section("Чаты", payload.chats, (item) =>
        resultRow({
          href: item.url,
          item: item,
          title: item.title,
          meta: item.username ? "@" + item.username + " · " + item.status : item.status,
        })
      ),
      section("Люди", payload.people, (item) =>
        resultRow({
          href: item.profile_url,
          item: item,
          title: item.display_name,
          meta: "@" + item.username + " · " + item.status,
          profile: true,
        })
      ),
      section("Сообщества", payload.communities, communityRow),
    ].filter(Boolean);

    if (!blocks.length) {
      const empty = document.createElement("div");
      empty.className = "global-search-empty";
      empty.textContent = "Ничего не найдено.";
      contactsResults.appendChild(empty);
    } else {
      blocks.forEach((block) => contactsResults.appendChild(block));
    }
    contactsResults.hidden = false;
    contactsCard.classList.add("contacts-card--live-search");
  }

  const chatTools = document.getElementById("sidebarChatTools");
  const filterControls = Array.from(document.querySelectorAll("[data-chat-filter]"));
  const filterOptions = new Set(["all", "unread", "group", "channel"]);
  const filterStorage = "sovietgram.chat-filter." + (chatTools?.dataset.accountId || "") +
    "." + (chatTools?.dataset.archived || "false") + "." + (chatTools?.dataset.folderId || "");
  let activeChatFilter = "all";
  if (chatTools) {
    try {
      const saved = sessionStorage.getItem(filterStorage);
      if (filterOptions.has(saved)) activeChatFilter = saved;
    } catch (_error) {}
  }

  function matchesChatFilter(row) {
    if (activeChatFilter === "all") return true;
    if (activeChatFilter === "unread") return row.dataset.chatUnread === "true";
    return row.dataset.chatType === activeChatFilter;
  }

  function applyLocalChatFilter() {
    if (!sidebarInput) return;
    const query = sidebarInput.value.trim().toLowerCase().replace(/^@/, "");
    let visible = 0;
    const rows = chatRows();
    rows.forEach((row) => {
      const matches = matchesChatFilter(row) && (!query || (row.dataset.search || "").includes(query));
      row.hidden = !matches;
      if (matches) visible += 1;
    });
    const empty = chatFilterEmpty();
    if (empty) {
      empty.textContent = activeChatFilter === "unread"
        ? "Нет непрочитанных чатов."
        : activeChatFilter === "group" ? "Нет групп."
          : activeChatFilter === "channel" ? "Нет каналов." : "Ничего не найдено.";
      empty.hidden = Boolean(query) || visible !== 0 || rows.length === 0;
    }
    filterControls.forEach(control =>
      control.setAttribute("aria-pressed", String(control.dataset.chatFilter === activeChatFilter))
    );
    if (typeof window !== "undefined") window.SovietgramArchive?.sync();
  }

  filterControls.forEach(control => {
    control.addEventListener("click", () => {
      const filter = control.dataset.chatFilter;
      if (!filterOptions.has(filter)) return;
      activeChatFilter = filter;
      try { sessionStorage.setItem(filterStorage, filter); } catch (_error) {}
      applyLocalChatFilter();
    });
  });
  applyLocalChatFilter();

  function resetSidebarSearch() {
    window.clearTimeout(sidebarTimer);
    if (sidebarController) sidebarController.abort();
    sidebarController = null;
    if (sidebarResults) {
      sidebarResults.hidden = true;
      sidebarResults.replaceChildren();
    }
    applyLocalChatFilter();
  }

  if (sidebarInput) {
    sidebarInput.addEventListener("input", () => {
      window.clearTimeout(sidebarTimer);
      sidebarController?.abort();
      sidebarController = null;
      if (sidebarResults) {
        sidebarResults.hidden = true;
        sidebarResults.replaceChildren();
      }
      applyLocalChatFilter();
      const query = sidebarInput.value.trim();
      if (!query) {
        resetSidebarSearch();
        return;
      }
      sidebarTimer = window.setTimeout(async () => {
        if (sidebarController) sidebarController.abort();
        const controller = new AbortController();
        sidebarController = controller;
        try {
          const payload = await fetchSearch(sidebarInput, controller);
          if (payload && controller === sidebarController && !controller.signal.aborted && sidebarInput.value.trim() === payload.query.trim()) renderSidebar(payload);
        } catch (error) {
          if (error.name !== "AbortError") toast(error.message);
        }
      }, 180);
    });

    sidebarInput.addEventListener("keydown", (event) => {
      if (event.key === "Escape") {
        sidebarInput.value = "";
        resetSidebarSearch();
        sidebarInput.blur();
      }
    });
  }

  const chatList = document.getElementById("chatList");
  if (chatList && sidebarInput) {
    let sidebarRefreshBusy = false;
    let refreshGeneration = 0;
    async function refreshSidebar(force = false) {
      if ((!force && sidebarRefreshBusy) || document.hidden || (!force && sidebarInput.value.trim())) return;
      sidebarRefreshBusy = true;
      const generation = ++refreshGeneration;
      try {
        const response = await fetch(chatList.dataset.refreshUrl, {
          credentials: "same-origin",
          cache: "no-store",
        });
        if (!response.ok || generation !== refreshGeneration || (!force && sidebarInput.value.trim())) return;
        const html = await response.text();
        if (generation !== refreshGeneration || (!force && sidebarInput.value.trim())) return;
        const snapshot = new DOMParser().parseFromString(html, "text/html");
        const next = snapshot.getElementById("chatList");
        if (!next || next.dataset.accountId !== chatList.dataset.accountId) return;
        // The sidebar snapshot is also the lightweight avatar directory for
        // visible conversations. Reuse it to refresh open search/forward
        // results and other mounted surfaces, not only the sidebar itself.
        next.querySelectorAll("[data-avatar-user-id]").forEach((node) => {
          window.SovietgramAvatarSync?.updateUser(
            node.dataset.avatarUserId,
            node.tagName === "IMG" ? node.getAttribute("src") || "" : "",
            node.textContent || "?",
          );
        });
        next.querySelectorAll("[data-avatar-chat-id]").forEach((node) => {
          window.SovietgramAvatarSync?.updateChat(
            node.dataset.avatarChatId,
            node.tagName === "IMG" ? node.getAttribute("src") || "" : "",
            node.textContent || "?",
          );
        });
        next.querySelectorAll("[data-chat-row]").forEach((row) => {
          // DOMParser's detached document may not have the page's base URL.
          const href = row.getAttribute("href");
          if (href && new URL(href, window.location.href).pathname === window.location.pathname) row.classList.add("is-active");
        });
        for (const name of ["archiveCount","archiveUnread","archiveLoudUnread","archiveHidden"]) {
          chatList.dataset[name] = next.dataset[name] || "";
        }
        const tabs = document.getElementById("chatFolderTabs"), nextTabs = snapshot.getElementById("chatFolderTabs");
        if (tabs && nextTabs) {
          const offset = tabs.scrollLeft;
          tabs.replaceChildren(...nextTabs.childNodes);
          tabs.hidden = nextTabs.hidden;
          tabs.scrollLeft = offset;
        }
        chatList.replaceChildren(...next.childNodes);
        chatList.classList.toggle("chat-list--empty", next.classList.contains("chat-list--empty"));
        applyLocalChatFilter();
        window.SovietgramArchive?.onRefresh();
      } catch (_error) {
        // Transient connection failures must not interrupt the conversation.
      } finally {
        if (generation === refreshGeneration) sidebarRefreshBusy = false;
      }
    }
    window.SovietgramSidebar = { refresh: () => refreshSidebar(true) };
    window.setInterval(refreshSidebar, 5000);
    document.addEventListener("visibilitychange", () => {
      if (!document.hidden) refreshSidebar();
    });
  }

  const rowMenu = document.getElementById("sidebarChatContext");
  const rowForm = document.getElementById("sidebarChatReadForm");
  const rowAction = document.getElementById("sidebarChatReadAction");
  const rowNext = document.getElementById("sidebarChatReadNext");
  const rowLabel = document.getElementById("sidebarChatReadLabel");
  const rowButton = document.getElementById("sidebarChatReadButton");
  let menuAnchor = null;

  function closeRowMenu(restoreFocus = false) {
    if (rowMenu) rowMenu.hidden = true;
    if (restoreFocus && menuAnchor?.isConnected) menuAnchor.focus();
    menuAnchor = null;
  }

  function openRowMenu(row, x, y) {
    if (!rowMenu || !rowForm || !rowAction || !rowNext || !rowLabel || !rowButton || !row.dataset.readActionUrl) return;
    menuAnchor = row;
    const unread = row.dataset.chatUnread === "true";
    rowForm.action = row.dataset.readActionUrl;
    rowAction.value = unread ? "mark_read" : "mark_unread";
    rowLabel.textContent = unread ? "Отметить прочитанным" : "Отметить непрочитанным";
    rowMenu.querySelector('[data-read-menu-icon="read"]').hidden = !unread;
    rowMenu.querySelector('[data-read-menu-icon="unread"]').hidden = unread;
    // Marking the open chat unread leaves it, preventing its visible read
    // acknowledgement from immediately removing the personal reminder.
    const current = window.location.pathname;
    const selected = new URL(row.href, window.location.origin).pathname === current;
    rowNext.value = !unread && selected ? "" : current + window.location.search;
    rowMenu.hidden = false;
    window.SovietgramArchive?.prepareRowMenu(row);
    const rect = rowMenu.getBoundingClientRect();
    rowMenu.style.left = Math.max(6, Math.min(x, window.innerWidth - rect.width - 6)) + "px";
    rowMenu.style.top = Math.max(6, Math.min(y, window.innerHeight - rect.height - 6)) + "px";
    rowButton.focus({ preventScroll: true });
  }

  if (chatList && rowMenu) {
    window.SovietgramSidebar = { ...window.SovietgramSidebar, openRowMenu, closeRowMenu };
    chatList.addEventListener("contextmenu", event => {
      const row = event.target.closest?.("[data-chat-row]");
      if (!row) return;
      event.preventDefault();
      const rect = row.getBoundingClientRect();
      openRowMenu(row, event.clientX || rect.left + 12, event.clientY || rect.bottom);
    });
    chatList.addEventListener("keydown", event => {
      if (event.key !== "ContextMenu" && !(event.shiftKey && event.key === "F10")) return;
      const row = event.target.closest?.("[data-chat-row]");
      if (!row) return;
      event.preventDefault();
      const rect = row.getBoundingClientRect();
      openRowMenu(row, rect.left + 12, rect.bottom);
    });
    chatList.addEventListener("scroll", () => closeRowMenu(), { passive: true });
    window.addEventListener("resize", () => closeRowMenu());
    document.addEventListener("pointerdown", event => {
      if (!rowMenu.hidden && !rowMenu.contains(event.target)) closeRowMenu();
    });
    document.addEventListener("keydown", event => {
      if (event.key === "Escape" && !rowMenu.hidden) {
        event.preventDefault();
        event.stopImmediatePropagation();
        closeRowMenu(true);
      }
    }, true);
  }

  document.getElementById("markAllChatsReadForm")?.addEventListener("submit", event => {
    if (chatTools?.dataset.archived === "true" && window.SovietgramArchive) {
      event.preventDefault();
      void window.SovietgramArchive.readAll();
      return;
    }
    if (chatTools?.dataset.folderId) {
      if (!window.confirm("Отметить все чаты этой папки прочитанными?")) event.preventDefault();
      return;
    }
    if (!window.confirm("Отметить все чаты, включая архив, прочитанными?")) event.preventDefault();
  });

  document.addEventListener("click", (event) => {
    if (!sidebarResults || sidebarResults.hidden) return;
    if (event.target === sidebarInput || sidebarResults.contains(event.target)) return;
    sidebarResults.hidden = true;
  });

  function resetContactsSearch() {
    if (contactsController) contactsController.abort();
    contactsController = null;
    if (contactsResults) {
      contactsResults.hidden = true;
      contactsResults.replaceChildren();
    }
    if (contactsCard) contactsCard.classList.remove("contacts-card--live-search");
  }

  if (peopleInput) {
    peopleInput.addEventListener("input", () => {
      window.clearTimeout(contactsTimer);
      const query = peopleInput.value.trim();
      if (!query) {
        resetContactsSearch();
        return;
      }
      contactsTimer = window.setTimeout(async () => {
        if (contactsController) contactsController.abort();
        contactsController = new AbortController();
        try {
          const payload = await fetchSearch(peopleInput, contactsController);
          if (payload && peopleInput.value.trim() === payload.query.trim()) renderContacts(payload);
        } catch (error) {
          if (error.name !== "AbortError") toast(error.message);
        }
      }, 180);
    });

    peopleInput.addEventListener("keydown", (event) => {
      if (event.key === "Escape") {
        peopleInput.value = "";
        resetContactsSearch();
      }
    });

    if (peopleInput.value.trim()) {
      peopleInput.dispatchEvent(new Event("input", { bubbles: true }));
    }
  }
})();
