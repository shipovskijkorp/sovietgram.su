(() => {
  const root = document.getElementById("telegramSettings");
  if (!root) return;

  const endpoint = root.dataset.settingsUrl || "/settings/";
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

  const screenTitles = {
    main: "Настройки",
    privacy: "Конфиденциальность и безопасность",
    chat: "Настройки чатов",
    archive: "Настройки архива",
    password: "Пароль",
  };

  const parentScreen = {
    privacy: "main",
    chat: "main",
    archive: "chat",
    password: "privacy",
  };

  const hashAliases = {
    archiveSettings: "archive",
    newChatsSettings: "privacy",
  };

  const currentValues = new Map();
  let currentScreen = "main";
  let toastTimer = 0;

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
    if (url.hash === "#archiveSettings" || url.hash === "#newChatsSettings") {
      url.hash = "";
    }
    const method = mode === "replace" ? "replaceState" : "pushState";
    window.history[method]({}, "", url);
  }

  function controlsFor(setting) {
    return [...root.querySelectorAll("[data-setting]")].filter(
      (control) => control.dataset.setting === setting,
    );
  }

  function controlValue(control) {
    if (control.type === "checkbox") {
      return control.checked ? "true" : "false";
    }
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
    if (typeof window.setProfileMenu === "function") {
      window.setProfileMenu(false);
    } else {
      const profileMenu = document.getElementById("profileMenu");
      const profileBackdrop = document.getElementById("profileMenuBackdrop");
      profileMenu?.classList.remove("is-open");
      profileBackdrop?.classList.remove("is-open");
    }

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
      if (control.type === "checkbox") {
        control.checked = value === "true";
      } else if (control.type === "radio") {
        control.checked = controlValue(control) === value;
      } else {
        control.value = value;
      }
    });

    if (setting === "theme") previewTheme(value);
    if (setting === "enter_to_send") updateSendMode(value);
  }

  function setSaving(setting, saving) {
    controlsFor(setting).forEach((control) => {
      const row = control.closest(
        ".tg-settings-toggle-row, .tg-settings-radio-row, .tg-settings-theme",
      );
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

    const data = new FormData();
    data.append("csrfmiddlewaretoken", csrfToken);
    data.append("setting", setting);
    data.append("value", nextValue);

    try {
      const response = await fetch(endpoint, {
        method: "POST",
        credentials: "same-origin",
        headers: { "X-Requested-With": "XMLHttpRequest" },
        body: data,
      });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok || !payload.ok) {
        throw new Error(payload.error || "Не удалось сохранить настройку.");
      }

      const savedValue = typeof payload.value === "boolean"
        ? (payload.value ? "true" : "false")
        : String(payload.value);

      currentValues.set(setting, savedValue);
      applyValue(setting, savedValue);
      showStatus("Сохранено");
    } catch (error) {
      if (previousValue != null) applyValue(setting, previousValue);
      showStatus(error.message || "Не удалось сохранить настройку.", true);
    } finally {
      setSaving(setting, false);
    }
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
      if (!response.ok || !payload.ok) {
        throw new Error(passwordErrorsText(payload.errors));
      }

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
    });
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
    if (requested) {
      openSettings(requested);
    } else {
      closeSettings();
    }
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
      return;
    }

    event.preventDefault();
    closeSettings({ history: "push" });
  });

  initializeValues();
  previewTheme(currentValues.get("theme") || document.body.dataset.theme || "light");
  updateSendMode(currentValues.get("enter_to_send") || "true");

  const url = currentUrl();
  const requested = root.dataset.autoOpen || url.searchParams.get("settings");
  if (requested) openSettings(requested);
})();
