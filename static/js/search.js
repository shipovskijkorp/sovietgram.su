(() => {
  const sidebarInput = document.getElementById("chatFilter");
  const sidebarResults = document.getElementById("sidebarGlobalSearch");
  const chatRows = Array.from(document.querySelectorAll("[data-chat-row]"));
  const chatFilterEmpty = document.getElementById("chatFilterEmpty");

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

  async function fetchSearch(input, controller) {
    const endpoint = input && input.dataset.globalSearchUrl;
    const query = input ? input.value.trim() : "";
    if (!endpoint || !query) return null;
    const url = new URL(endpoint, window.location.origin);
    url.searchParams.set("q", query);
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

  function applyLocalChatFilter() {
    if (!sidebarInput) return;
    const query = sidebarInput.value.trim().toLowerCase().replace(/^@/, "");
    let visible = 0;
    chatRows.forEach((row) => {
      const matches = !query || (row.dataset.search || "").includes(query);
      row.hidden = !matches;
      if (matches) visible += 1;
    });
    if (chatFilterEmpty) {
      chatFilterEmpty.hidden = Boolean(query) || visible !== 0 || chatRows.length === 0;
    }
  }

  function resetSidebarSearch() {
    if (sidebarController) sidebarController.abort();
    sidebarController = null;
    if (sidebarResults) {
      sidebarResults.hidden = true;
      sidebarResults.replaceChildren();
    }
    chatRows.forEach((row) => { row.hidden = false; });
    if (chatFilterEmpty) chatFilterEmpty.hidden = true;
  }

  if (sidebarInput) {
    sidebarInput.addEventListener("input", () => {
      window.clearTimeout(sidebarTimer);
      applyLocalChatFilter();
      const query = sidebarInput.value.trim();
      if (!query) {
        resetSidebarSearch();
        return;
      }
      sidebarTimer = window.setTimeout(async () => {
        if (sidebarController) sidebarController.abort();
        sidebarController = new AbortController();
        try {
          const payload = await fetchSearch(sidebarInput, sidebarController);
          if (payload && sidebarInput.value.trim() === payload.query.trim()) renderSidebar(payload);
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
