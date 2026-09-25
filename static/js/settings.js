(() => {
  const root = document.getElementById("telegramSettings");
  if (!root) return;

  const endpoint = root.dataset.settingsUrl || "/settings/";
  const searchEndpoint = root.dataset.userSearchUrl || "";
  const csrfToken = root.querySelector("#settingsAjaxForm [name='csrfmiddlewaretoken']")?.value || "";
  const scroll = document.getElementById("settingsScroll");
  const topbar = document.getElementById("settingsTopbar");
  const title = document.getElementById("settingsTopbarTitle");
  const backButton = document.getElementById("settingsSectionBack");
  const menuButton = document.getElementById("settingsMenuButton");
  const menu = document.getElementById("settingsMenu");
  const status = document.getElementById("settingsStatus");
  const themeMeta = document.querySelector('meta[name="theme-color"]');
  const screens = [...root.querySelectorAll("[data-settings-screen]")];
  const passwordForm = document.getElementById("settingsPasswordForm");
  const passwordError = document.getElementById("settingsPasswordError");

  const parseJsonScript = (id, fallback) => {
    const node = document.getElementById(id);
    if (!node) return fallback;
    try {
      return JSON.parse(node.textContent || "");
    } catch (_error) {
      return fallback;
    }
  };

  let privacyRules = parseJsonScript("settingsPrivacyData", {});
  let blockedUsers = parseJsonScript("settingsBlockedData", []);
  let sessions = parseJsonScript("settingsSessionsData", []);

  const screenTitles = {
    main: "Настройки",
    privacy: "Конфиденциальность и безопасность",
    chat: "Настройки чатов",
    archive: "Настройки архива",
    password: "Пароль",
    blocked: "Заблокированные пользователи",
    sessions: "Активные сеансы",
    "privacy-rule": "Конфиденциальность",
    "privacy-exceptions": "Исключения",
    inactive: "Удаление аккаунта",
    "auto-delete": "Автоудаление сообщений",
  };

  const parentScreen = {
    privacy: "main",
    chat: "main",
    archive: "chat",
    password: "privacy",
    blocked: "privacy",
    sessions: "privacy",
    "privacy-rule": "privacy",
    "privacy-exceptions": "privacy-rule",
    inactive: "privacy",
    "auto-delete": "privacy",
  };

  const hashAliases = {
    archiveSettings: "archive",
    newChatsSettings: "privacy",
  };

  const currentValues = new Map();
  let currentScreen = "main";
  let toastTimer = 0;
  let activePrivacyKey = "";
  let activeExceptionKind = "";
  let privacySearchTimer = 0;
  let blockSearchTimer = 0;

  const privacyQuestion = document.getElementById("privacyRuleQuestion");
  const privacyAlwaysCount = document.getElementById("privacyAlwaysCount");
  const privacyNeverCount = document.getElementById("privacyNeverCount");
  const privacyExceptionTitle = document.getElementById("privacyExceptionTitle");
  const privacyExceptionSearch = document.getElementById("privacyExceptionSearch");
  const privacyExceptionSelected = document.getElementById("privacyExceptionSelected");
  const privacyExceptionResults = document.getElementById("privacyExceptionResults");
  const privacyExceptionEmpty = document.getElementById("privacyExceptionEmpty");
  const blockedUserSearch = document.getElementById("blockedUserSearch");
  const blockedUsersList = document.getElementById("blockedUsersList");
  const blockedSearchResults = document.getElementById("blockedSearchResults");
  const blockedUsersEmpty = document.getElementById("blockedUsersEmpty");
  const privacySessionsList = document.getElementById("privacySessionsList");
  const terminateOtherSessions = document.getElementById("terminateOtherSessions");

  function normalizeScreen(value) {
    const aliased = hashAliases[value] || value;
    return Object.hasOwn(screenTitles, aliased) ? aliased : "main";
  }

  function currentUrl() {
    return new URL(window.location.href);
  }

  function setUrlScreen(screen, mode = "push") {
    const url = currentUrl();
    url.searchParams.set("settings", normalizeScreen(screen));
    url.hash = "";
    const method = mode === "replace" ? "replaceState" : "pushState";
    window.history[method]({ settingsScreen: screen }, "", url);
  }

  function clearUrlScreen(mode = "push") {
    const url = currentUrl();
    url.searchParams.delete("settings");
    if (url.hash === "#archiveSettings" || url.hash === "#newChatsSettings") url.hash = "";
    const method = mode === "replace" ? "replaceState" : "pushState";
    window.history[method]({}, "", url);
  }

  function controlsFor(setting) {
    return [...root.querySelectorAll("[data-setting]")].filter(
      (control) => control.dataset.setting === setting,
    );
  }

  function controlValue(control) {
    if (control.type === "checkbox") return control.checked ? "true" : "false";
    return control.dataset.value ?? control.value;
  }

  function initializeValues() {
    root.querySelectorAll("[data-setting]").forEach((control) => {
      if (control.type === "radio" && !control.checked) return;
      currentValues.set(control.dataset.setting, controlValue(control));
    });
  }

  function showStatus(message, isError = false) {
    if (!status) return;
    window.clearTimeout(toastTimer);
    status.textContent = message;
    status.classList.toggle("is-error", isError);
    status.hidden = false;
    toastTimer = window.setTimeout(() => {
      status.hidden = true;
    }, isError ? 4200 : 1400);
  }

  async function post(data) {
    const body = new FormData();
    body.append("csrfmiddlewaretoken", csrfToken);
    Object.entries(data).forEach(([key, value]) => body.append(key, String(value)));
    const response = await fetch(endpoint, {
      method: "POST",
      credentials: "same-origin",
      headers: { "X-Requested-With": "XMLHttpRequest" },
      body,
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok || !payload.ok) {
      throw new Error(payload.error || "Не удалось сохранить настройку.");
    }
    return payload;
  }

  function closeMenu() {
    if (!menu || !menuButton) return;
    menu.hidden = true;
    menuButton.setAttribute("aria-expanded", "false");
  }

  function toggleMenu() {
    if (!menu || !menuButton || menuButton.hidden) return;
    const opening = menu.hidden;
    menu.hidden = !opening;
    menuButton.setAttribute("aria-expanded", opening ? "true" : "false");
  }

  function renderScreen(value) {
    const next = normalizeScreen(value);
    currentScreen = next;
    screens.forEach((screen) => {
      screen.hidden = screen.dataset.settingsScreen !== next;
    });
    if (title) title.textContent = screenTitles[next];
    if (backButton) backButton.hidden = next === "main";
    topbar?.classList.toggle("has-back", next !== "main");
    if (menuButton) menuButton.hidden = next !== "main";
    closeMenu();
    if (scroll) scroll.scrollTop = 0;
  }

  function openSettings(screen = "main", options = {}) {
    const next = normalizeScreen(screen);
    const profileMenu = document.getElementById("profileMenu");
    const profileBackdrop = document.getElementById("profileMenuBackdrop");
    profileMenu?.classList.remove("is-open");
    profileBackdrop?.classList.remove("is-open");

    root.hidden = false;
    document.body.classList.add("settings-open");
    renderScreen(next);
    if (options.history === "replace") setUrlScreen(next, "replace");
    if (options.history === "push") setUrlScreen(next, "push");
  }

  function closeSettings(options = {}) {
    closeMenu();
    root.hidden = true;
    document.body.classList.remove("settings-open");
    if (options.history === "replace") clearUrlScreen("replace");
    if (options.history === "push") clearUrlScreen("push");
  }

  function previewTheme(theme) {
    document.body.dataset.theme = theme;
    document.documentElement.dataset.theme = theme;
    try {
      localStorage.setItem("sovietgram.theme", theme);
    } catch (_error) {
      // Theme persistence is best-effort in private browsing.
    }
    root.querySelectorAll("[data-theme-option]").forEach((option) => {
      option.classList.toggle("is-selected", option.dataset.themeOption === theme);
    });
    if (themeMeta) themeMeta.content = theme === "dark" ? "#171412" : "#cc0000";
  }

  function updateSendMode(value) {
    document.body.dataset.enterToSend = value === "true" ? "true" : "false";
  }

  function applyValue(setting, value) {
    controlsFor(setting).forEach((control) => {
      if (control.type === "checkbox") control.checked = value === "true";
      else if (control.type === "radio") control.checked = controlValue(control) === value;
      else control.value = value;
    });
    if (setting === "theme") previewTheme(value);
    if (setting === "enter_to_send") updateSendMode(value);
  }

  function setSaving(setting, saving) {
    controlsFor(setting).forEach((control) => {
      const row = control.closest(".tg-settings-toggle-row, .tg-settings-radio-row, .tg-settings-theme");
      row?.classList.toggle("is-saving", saving);
      control.disabled = saving;
    });
  }

  async function saveSetting(control) {
    const setting = control.dataset.setting;
    if (!setting) return;
    const nextValue = controlValue(control);
    const previousValue = currentValues.get(setting);
    if (previousValue === nextValue) {
      applyValue(setting, nextValue);
      return;
    }

    applyValue(setting, nextValue);
    setSaving(setting, true);
    try {
      const payload = await post({ setting, value: nextValue });
      const savedValue = typeof payload.value === "boolean"
        ? (payload.value ? "true" : "false")
        : String(payload.value);
      currentValues.set(setting, savedValue);
      applyValue(setting, savedValue);
      if (setting === "delete_after_inactive_days") {
        const target = document.getElementById("privacyInactiveValue");
        if (target) target.textContent = payload.label || savedValue;
      }
      if (setting === "default_auto_delete_seconds") {
        const target = document.getElementById("privacyAutoDeleteValue");
        if (target) target.textContent = payload.label || savedValue;
      }
      showStatus("Сохранено");
    } catch (error) {
      if (previousValue != null) applyValue(setting, previousValue);
      showStatus(error.message || "Не удалось сохранить настройку.", true);
    } finally {
      setSaving(setting, false);
    }
  }

  function privacyLabel(rule) {
    if (!rule) return "";
    const additions = [];
    if (rule.never?.length) additions.push(`-${rule.never.length}`);
    if (rule.always?.length) additions.push(`+${rule.always.length}`);
    return additions.length ? `${rule.option_label} (${additions.join(", ")})` : rule.option_label;
  }

  function syncPrivacyRows() {
    Object.entries(privacyRules).forEach(([key, rule]) => {
      const node = root.querySelector(`[data-privacy-label="${CSS.escape(key)}"]`);
      if (node) node.textContent = privacyLabel(rule);
    });
  }

  function updatePrivacyEditor() {
    const rule = privacyRules[activePrivacyKey];
    if (!rule) return;
    if (privacyQuestion) privacyQuestion.textContent = rule.question;
    root.querySelectorAll('input[name="privacy-rule-option"]').forEach((radio) => {
      radio.checked = radio.value === rule.option;
    });
    if (privacyAlwaysCount) privacyAlwaysCount.textContent = rule.always?.length ? String(rule.always.length) : "Нет";
    if (privacyNeverCount) privacyNeverCount.textContent = rule.never?.length ? String(rule.never.length) : "Нет";
    if (title) title.textContent = rule.title;
  }

  async function savePrivacyRule() {
    const rule = privacyRules[activePrivacyKey];
    if (!rule) return;
    try {
      const payload = await post({
        action: "privacy_rule",
        key: activePrivacyKey,
        option: rule.option,
        always: JSON.stringify((rule.always || []).map((item) => item.id)),
        never: JSON.stringify((rule.never || []).map((item) => item.id)),
      });
      privacyRules[activePrivacyKey] = payload.rule;
      updatePrivacyEditor();
      syncPrivacyRows();
      showStatus("Сохранено");
    } catch (error) {
      showStatus(error.message, true);
    }
  }

  function avatarNode(person) {
    if (person.avatar_url) {
      const image = document.createElement("img");
      image.className = "tg-settings-person__avatar";
      image.src = person.avatar_url;
      image.alt = "";
      return image;
    }
    const avatar = document.createElement("span");
    avatar.className = "tg-settings-person__avatar";
    avatar.textContent = person.initials || (person.display_name || person.username || "?").slice(0, 2).toUpperCase();
    return avatar;
  }

  function personRow(person, actionText, action) {
    const row = document.createElement("div");
    row.className = "tg-settings-person";
    row.appendChild(avatarNode(person));

    const copy = document.createElement("span");
    copy.className = "tg-settings-person__copy";
    const strong = document.createElement("strong");
    strong.textContent = person.display_name || person.username;
    const small = document.createElement("small");
    small.textContent = `@${person.username}`;
    copy.append(strong, small);
    row.appendChild(copy);

    if (actionText) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "tg-settings-person__action";
      button.textContent = actionText;
      button.addEventListener("click", (event) => {
        event.stopPropagation();
        action?.(person, row);
      });
      row.appendChild(button);
    }
    return row;
  }

  function exceptionSelected() {
    const rule = privacyRules[activePrivacyKey];
    return rule?.[activeExceptionKind] || [];
  }

  function renderExceptionSelected() {
    if (!privacyExceptionSelected) return;
    privacyExceptionSelected.replaceChildren();
    const selected = exceptionSelected();
    selected.forEach((person) => {
      privacyExceptionSelected.appendChild(
        personRow(person, "Убрать", async () => {
          const rule = privacyRules[activePrivacyKey];
          rule[activeExceptionKind] = rule[activeExceptionKind].filter((item) => item.id !== person.id);
          renderExceptionSelected();
          await savePrivacyRule();
        }),
      );
    });
  }

  function personFromSearch(item) {
    return {
      id: Number(item.id),
      username: item.username,
      display_name: item.display_name,
      initials: item.avatar_text || (item.display_name || item.username || "?").slice(0, 2).toUpperCase(),
      avatar_url: item.avatar_url || "",
    };
  }

  async function searchPeople(query) {
    if (!searchEndpoint || !query.trim()) return [];
    const url = new URL(searchEndpoint, window.location.origin);
    url.searchParams.set("q", query.trim());
    const response = await fetch(url, { credentials: "same-origin" });
    if (!response.ok) return [];
    const payload = await response.json().catch(() => ({}));
    return (payload.people || []).map(personFromSearch);
  }

  async function renderExceptionSearch(query) {
    if (!privacyExceptionResults) return;
    const people = await searchPeople(query);
    privacyExceptionResults.replaceChildren();
    const selectedIds = new Set(exceptionSelected().map((item) => item.id));
    const otherKind = activeExceptionKind === "always" ? "never" : "always";
    const rule = privacyRules[activePrivacyKey];

    people.forEach((person) => {
      if (selectedIds.has(person.id)) return;
      privacyExceptionResults.appendChild(
        personRow(person, "Добавить", async () => {
          rule[otherKind] = (rule[otherKind] || []).filter((item) => item.id !== person.id);
          rule[activeExceptionKind] = [...(rule[activeExceptionKind] || []), person];
          renderExceptionSelected();
          await savePrivacyRule();
          privacyExceptionSearch.value = "";
          privacyExceptionResults.replaceChildren();
          if (privacyExceptionEmpty) privacyExceptionEmpty.hidden = false;
        }),
      );
    });
    if (privacyExceptionEmpty) privacyExceptionEmpty.hidden = Boolean(people.length);
  }

  function openExceptionPicker(kind) {
    const rule = privacyRules[activePrivacyKey];
    if (!rule) return;
    activeExceptionKind = kind;
    if (privacyExceptionTitle) {
      privacyExceptionTitle.textContent = kind === "always" ? "Всегда разрешать" : "Никогда не разрешать";
    }
    if (privacyExceptionSearch) privacyExceptionSearch.value = "";
    if (privacyExceptionResults) privacyExceptionResults.replaceChildren();
    if (privacyExceptionEmpty) privacyExceptionEmpty.hidden = false;
    renderExceptionSelected();
    renderScreen("privacy-exceptions");
    setUrlScreen("privacy-exceptions", "push");
    window.setTimeout(() => privacyExceptionSearch?.focus(), 0);
  }

  function renderBlocked() {
    if (!blockedUsersList || !blockedUsersEmpty) return;
    blockedUsersList.replaceChildren();
    blockedUsers.forEach((person) => {
      blockedUsersList.appendChild(
        personRow(person, "Разблокировать", async () => {
          try {
            const payload = await post({ action: "unblock", username: person.username });
            blockedUsers = payload.blocked || [];
            renderBlocked();
            showStatus("Пользователь разблокирован");
          } catch (error) {
            showStatus(error.message, true);
          }
        }),
      );
    });
    blockedUsersEmpty.hidden = blockedUsers.length > 0;
    const count = document.getElementById("privacyBlockedCount");
    if (count) count.textContent = blockedUsers.length ? String(blockedUsers.length) : "Нет";
  }

  async function renderBlockedSearch(query) {
    if (!blockedSearchResults) return;
    const people = await searchPeople(query);
    const blockedIds = new Set(blockedUsers.map((item) => item.id));
    blockedSearchResults.replaceChildren();
    people.forEach((person) => {
      if (blockedIds.has(person.id)) return;
      blockedSearchResults.appendChild(
        personRow(person, "Заблокировать", async () => {
          try {
            const payload = await post({ action: "block", username: person.username });
            blockedUsers = payload.blocked || [];
            renderBlocked();
            blockedUserSearch.value = "";
            blockedSearchResults.replaceChildren();
            showStatus("Пользователь заблокирован");
          } catch (error) {
            showStatus(error.message, true);
          }
        }),
      );
    });
  }

  function renderSessions() {
    if (!privacySessionsList) return;
    privacySessionsList.replaceChildren();
    sessions.forEach((session) => {
      const row = document.createElement("div");
      row.className = `tg-settings-session${session.current ? " is-current" : ""}`;

      const icon = document.createElement("span");
      icon.className = "tg-settings-session__icon";
      icon.textContent = session.current ? "●" : "◉";

      const copy = document.createElement("span");
      copy.className = "tg-settings-session__copy";
      const strong = document.createElement("strong");
      strong.textContent = session.current ? "Этот сеанс" : session.user_agent;
      const small = document.createElement("small");
      small.textContent = [session.current ? session.user_agent : "", session.ip, `до ${session.expires}`].filter(Boolean).join(" · ");
      copy.append(strong, small);

      row.append(icon, copy);
      if (!session.current) {
        const button = document.createElement("button");
        button.type = "button";
        button.className = "tg-settings-session__action";
        button.textContent = "Завершить";
        button.addEventListener("click", async () => {
          try {
            const payload = await post({ action: "terminate_session", token: session.token });
            sessions = payload.sessions || [];
            renderSessions();
            showStatus("Сеанс завершён");
          } catch (error) {
            showStatus(error.message, true);
          }
        });
        row.appendChild(button);
      }
      privacySessionsList.appendChild(row);
    });
    const count = document.getElementById("privacySessionCount");
    if (count) count.textContent = String(sessions.length);
    if (terminateOtherSessions) terminateOtherSessions.hidden = sessions.filter((item) => !item.current).length === 0;
  }

  function passwordErrorsText(errors) {
    if (!errors || typeof errors !== "object") return "Не удалось изменить пароль.";
    const messages = [];
    Object.values(errors).forEach((fieldErrors) => {
      if (!Array.isArray(fieldErrors)) return;
      fieldErrors.forEach((entry) => {
        if (typeof entry === "string") messages.push(entry);
        else if (entry?.message) messages.push(entry.message);
      });
    });
    return messages.join(" ") || "Не удалось изменить пароль.";
  }

  async function submitPassword(event) {
    event.preventDefault();
    if (!passwordForm || !passwordError) return;
    passwordError.hidden = true;
    passwordError.textContent = "";
    const submit = passwordForm.querySelector('button[type="submit"]');
    if (submit) submit.disabled = true;
    try {
      const response = await fetch(passwordForm.action, {
        method: "POST",
        credentials: "same-origin",
        headers: { "X-Requested-With": "XMLHttpRequest" },
        body: new FormData(passwordForm),
      });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok || !payload.ok) throw new Error(passwordErrorsText(payload.errors));
      passwordForm.reset();
      renderScreen("privacy");
      setUrlScreen("privacy", "replace");
      showStatus("Пароль изменён");
    } catch (error) {
      passwordError.textContent = error.message || "Не удалось изменить пароль.";
      passwordError.hidden = false;
    } finally {
      if (submit) submit.disabled = false;
    }
  }

  document.querySelectorAll("[data-open-settings]").forEach((control) => {
    control.addEventListener("click", (event) => {
      event.preventDefault();
      openSettings(control.dataset.openSettings || "main", { history: "push" });
    });
  });

  root.querySelectorAll("[data-settings-target]").forEach((control) => {
    control.addEventListener("click", () => {
      const next = normalizeScreen(control.dataset.settingsTarget || "main");
      renderScreen(next);
      setUrlScreen(next, "push");
      if (next === "blocked") renderBlocked();
      if (next === "sessions") renderSessions();
    });
  });

  root.querySelectorAll("[data-privacy-open]").forEach((control) => {
    control.addEventListener("click", () => {
      activePrivacyKey = control.dataset.privacyOpen || "";
      if (!privacyRules[activePrivacyKey]) return;
      updatePrivacyEditor();
      renderScreen("privacy-rule");
      setUrlScreen("privacy-rule", "push");
    });
  });

  root.querySelectorAll("[data-privacy-exception]").forEach((control) => {
    control.addEventListener("click", () => openExceptionPicker(control.dataset.privacyException));
  });

  root.querySelectorAll('input[name="privacy-rule-option"]').forEach((radio) => {
    radio.addEventListener("change", async () => {
      if (!radio.checked || !privacyRules[activePrivacyKey]) return;
      privacyRules[activePrivacyKey].option = radio.value;
      await savePrivacyRule();
    });
  });

  privacyExceptionSearch?.addEventListener("input", () => {
    window.clearTimeout(privacySearchTimer);
    const query = privacyExceptionSearch.value;
    if (!query.trim()) {
      privacyExceptionResults?.replaceChildren();
      if (privacyExceptionEmpty) privacyExceptionEmpty.hidden = false;
      return;
    }
    privacySearchTimer = window.setTimeout(() => renderExceptionSearch(query), 220);
  });

  blockedUserSearch?.addEventListener("input", () => {
    window.clearTimeout(blockSearchTimer);
    const query = blockedUserSearch.value;
    if (!query.trim()) {
      blockedSearchResults?.replaceChildren();
      return;
    }
    blockSearchTimer = window.setTimeout(() => renderBlockedSearch(query), 220);
  });

  terminateOtherSessions?.addEventListener("click", async () => {
    try {
      const payload = await post({ action: "terminate_other_sessions" });
      sessions = payload.sessions || [];
      renderSessions();
      showStatus("Другие сеансы завершены");
    } catch (error) {
      showStatus(error.message, true);
    }
  });

  root.querySelectorAll("[data-settings-close]").forEach((control) => {
    control.addEventListener("click", () => closeSettings({ history: "push" }));
  });

  root.querySelectorAll("[data-settings-close-on-follow]").forEach((control) => {
    control.addEventListener("click", () => closeSettings({ history: "replace" }));
  });

  backButton?.addEventListener("click", () => {
    const next = parentScreen[currentScreen] || "main";
    renderScreen(next);
    setUrlScreen(next, "replace");
    if (next === "privacy-rule") updatePrivacyEditor();
  });

  menuButton?.addEventListener("click", (event) => {
    event.stopPropagation();
    toggleMenu();
  });
  menu?.addEventListener("click", (event) => event.stopPropagation());
  document.addEventListener("click", closeMenu);

  root.querySelectorAll("[data-setting]").forEach((control) => {
    control.addEventListener("change", () => {
      if (control.type === "radio" && !control.checked) return;
      saveSetting(control);
    });
  });

  passwordForm?.addEventListener("submit", submitPassword);

  window.addEventListener("popstate", () => {
    const url = currentUrl();
    const requested = url.searchParams.get("settings");
    if (requested) openSettings(requested);
    else closeSettings();
  });

  document.addEventListener("keydown", (event) => {
    if (event.key !== "Escape" || root.hidden) return;
    if (menu && !menu.hidden) {
      event.preventDefault();
      closeMenu();
      return;
    }
    if (currentScreen !== "main") {
      event.preventDefault();
      const next = parentScreen[currentScreen] || "main";
      renderScreen(next);
      setUrlScreen(next, "replace");
      if (next === "privacy-rule") updatePrivacyEditor();
      return;
    }
    event.preventDefault();
    closeSettings({ history: "push" });
  });

  initializeValues();
  syncPrivacyRows();
  renderBlocked();
  renderSessions();
  previewTheme(currentValues.get("theme") || document.body.dataset.theme || "light");
  updateSendMode(currentValues.get("enter_to_send") || "true");

  const url = currentUrl();
  const requested = root.dataset.autoOpen || url.searchParams.get("settings");
  if (requested) openSettings(requested);
})();
