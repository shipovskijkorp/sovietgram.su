(() => {
  const root = document.getElementById("telegramSettings");
  if (!root) return;

  const endpoint = root.dataset.settingsUrl || window.location.pathname;
  const csrfToken = document.querySelector("#settingsAjaxForm [name='csrfmiddlewaretoken']")?.value || "";
  const scroll = document.getElementById("settingsScroll");
  const screens = [...root.querySelectorAll("[data-settings-screen]")];
  const title = document.getElementById("settingsTopbarTitle");
  const sectionBack = document.getElementById("settingsSectionBack");
  const spacer = document.getElementById("settingsTopbarSpacer");
  const menuButton = document.getElementById("settingsMenuButton");
  const menu = document.getElementById("settingsMenu");
  const status = document.getElementById("settingsStatus");
  const themeMeta = document.querySelector('meta[name="theme-color"]');

  const screenTitles = {
    main: "Настройки",
    privacy: "Конфиденциальность и безопасность",
    chat: "Настройки чатов",
    archive: "Настройки архива",
  };

  const hashAliases = {
    archiveSettings: "archive",
    newChatsSettings: "privacy",
  };

  const currentValues = new Map();
  let currentScreen = "main";
  let toastTimer = 0;

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

  function normalizeScreen(value) {
    const aliased = hashAliases[value] || value;
    return Object.hasOwn(screenTitles, aliased) ? aliased : "main";
  }

  function hashForScreen(screen) {
    return screen === "main" ? "" : `#${screen}`;
  }

  function showStatus(message, error = false) {
    if (!status) return;
    window.clearTimeout(toastTimer);
    status.textContent = message;
    status.classList.toggle("is-error", error);
    status.hidden = false;
    toastTimer = window.setTimeout(() => {
      status.hidden = true;
    }, error ? 4200 : 1350);
  }

  function closeMenu() {
    if (!menu || !menuButton) return;
    menu.hidden = true;
    menuButton.setAttribute("aria-expanded", "false");
  }

  function toggleMenu() {
    if (!menu || !menuButton) return;
    const open = menu.hidden;
    menu.hidden = !open;
    menuButton.setAttribute("aria-expanded", open ? "true" : "false");
  }

  function syncTopbar(screen) {
    if (title) title.textContent = screenTitles[screen];
    if (sectionBack) sectionBack.hidden = screen === "main";
    if (spacer) spacer.hidden = screen !== "main";
    if (menuButton) menuButton.hidden = screen !== "main";
  }

  function showScreen(value, options = {}) {
    const next = normalizeScreen(value);
    currentScreen = next;

    screens.forEach((screen) => {
      screen.hidden = screen.dataset.settingsScreen !== next;
    });

    syncTopbar(next);
    closeMenu();

    if (options.history === "push") {
      window.history.pushState(
        { settingsScreen: next },
        "",
        `${window.location.pathname}${window.location.search}${hashForScreen(next)}`,
      );
    } else if (options.history === "replace") {
      window.history.replaceState(
        { settingsScreen: next },
        "",
        `${window.location.pathname}${window.location.search}${hashForScreen(next)}`,
      );
    }

    if (scroll) scroll.scrollTop = 0;
  }

  function previewTheme(theme) {
    document.body.dataset.theme = theme;
    root.querySelectorAll("[data-theme-option]").forEach((option) => {
      option.classList.toggle("is-selected", option.dataset.themeOption === theme);
    });
    if (themeMeta) {
      themeMeta.content = theme === "dark" ? "#171412" : "#cc0000";
    }
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

  root.querySelectorAll("[data-settings-target]").forEach((button) => {
    button.addEventListener("click", () => {
      showScreen(button.dataset.settingsTarget || "main", { history: "push" });
    });
  });

  sectionBack?.addEventListener("click", () => {
    if (currentScreen === "archive") {
      showScreen("chat", { history: "replace" });
      return;
    }
    showScreen("main", { history: "replace" });
  });

  menuButton?.addEventListener("click", (event) => {
    event.stopPropagation();
    toggleMenu();
  });

  menu?.addEventListener("click", (event) => {
    event.stopPropagation();
  });

  document.addEventListener("click", closeMenu);

  root.querySelectorAll("[data-setting]").forEach((control) => {
    control.addEventListener("change", () => {
      if (control.type === "radio" && !control.checked) return;
      saveSetting(control);
    });
  });

  window.addEventListener("popstate", () => {
    showScreen(window.location.hash.slice(1) || "main");
  });

  window.addEventListener("hashchange", () => {
    const next = normalizeScreen(window.location.hash.slice(1) || "main");
    if (next !== currentScreen) showScreen(next);
  });

  document.addEventListener("keydown", (event) => {
    if (event.key !== "Escape") return;

    if (menu && !menu.hidden) {
      event.preventDefault();
      closeMenu();
      return;
    }

    if (currentScreen === "archive") {
      event.preventDefault();
      showScreen("chat", { history: "replace" });
      return;
    }

    if (currentScreen !== "main") {
      event.preventDefault();
      showScreen("main", { history: "replace" });
    }
  });

  initializeValues();

  const rawHash = window.location.hash.slice(1);
  const initial = normalizeScreen(rawHash || "main");
  showScreen(initial, { history: "replace" });

  previewTheme(currentValues.get("theme") || document.body.dataset.theme || "light");
  updateSendMode(currentValues.get("enter_to_send") || "true");
})();
