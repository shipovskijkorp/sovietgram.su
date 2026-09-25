(() => {
  const root = document.getElementById("telegramSettings");
  if (!root) return;

  const endpoint = root.dataset.settingsUrl || window.location.pathname;
  const csrfToken = document.querySelector("#settingsAjaxForm [name='csrfmiddlewaretoken']")?.value || "";
  const screens = [...root.querySelectorAll("[data-settings-screen]")];
  const title = document.getElementById("settingsTopbarTitle");
  const homeBack = root.querySelector(".tg-settings-topbar__home");
  const sectionBack = document.getElementById("settingsSectionBack");
  const menuButton = document.getElementById("settingsMenuButton");
  const menu = document.getElementById("settingsMenu");
  const status = document.getElementById("settingsStatus");
  const themeMeta = document.querySelector('meta[name="theme-color"]');
  const enterHint = document.getElementById("enterModeHint");

  const screenTitles = {
    main: "Настройки",
    privacy: "Конфиденциальность и безопасность",
    chat: "Настройки чатов",
  };

  const currentValues = new Map();
  let currentScreen = "main";
  let toastTimer = 0;

  function settingControls(setting) {
    return [...root.querySelectorAll("[data-setting]")].filter(
      (control) => control.dataset.setting === setting
    );
  }

  function inputValue(input) {
    if (input.type === "checkbox") {
      return input.checked ? "true" : "false";
    }
    return input.dataset.value ?? input.value;
  }

  function initializeValues() {
    root.querySelectorAll("[data-setting]").forEach((input) => {
      if (input.type === "radio" && !input.checked) return;
      currentValues.set(input.dataset.setting, inputValue(input));
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
    }, isError ? 4200 : 1500);
  }

  function closeMenu() {
    if (!menu || !menuButton) return;
    menu.hidden = true;
    menuButton.setAttribute("aria-expanded", "false");
  }

  function toggleMenu() {
    if (!menu || !menuButton) return;
    const opening = menu.hidden;
    menu.hidden = !opening;
    menuButton.setAttribute("aria-expanded", opening ? "true" : "false");
  }

  function normalizedScreen(value) {
    return Object.hasOwn(screenTitles, value) ? value : "main";
  }

  function showScreen(value, options = {}) {
    const next = normalizedScreen(value);
    currentScreen = next;

    screens.forEach((screen) => {
      screen.hidden = screen.dataset.settingsScreen !== next;
    });

    if (title) title.textContent = screenTitles[next];
    if (homeBack) homeBack.hidden = next !== "main";
    if (sectionBack) sectionBack.hidden = next === "main";
    closeMenu();

    if (options.history === "push") {
      const hash = next === "main" ? "" : "#" + next;
      window.history.pushState(
        { settingsScreen: next },
        "",
        window.location.pathname + window.location.search + hash,
      );
    } else if (options.history === "replace") {
      const hash = next === "main" ? "" : "#" + next;
      window.history.replaceState(
        { settingsScreen: next },
        "",
        window.location.pathname + window.location.search + hash,
      );
    }

    const scroll = root.querySelector(".tg-settings-scroll");
    if (scroll) scroll.scrollTop = 0;
    window.scrollTo(0, 0);
  }

  function previewTheme(theme) {
    document.body.dataset.theme = theme;
    root.querySelectorAll("[data-theme-option]").forEach((option) => {
      option.classList.toggle("is-selected", option.dataset.themeOption === theme);
    });
    if (themeMeta) {
      themeMeta.content = theme === "dark" ? "#171412" : "#8d1e28";
    }
  }

  function updateEnterHint(value) {
    const enterSends = value === "true";
    document.body.dataset.enterToSend = enterSends ? "true" : "false";
    if (!enterHint) return;
    enterHint.textContent = enterSends
      ? "Enter отправляет сообщение, Shift+Enter создаёт новую строку."
      : "Enter создаёт новую строку, Ctrl+Enter отправляет сообщение.";
  }

  function applyValue(setting, value) {
    settingControls(setting).forEach((control) => {
      if (control.type === "checkbox") {
        control.checked = value === "true";
      } else if (control.type === "radio") {
        control.checked = inputValue(control) === value;
      } else {
        control.value = value;
      }
    });

    if (setting === "theme") previewTheme(value);
    if (setting === "enter_to_send") updateEnterHint(value);
  }

  function setSaving(setting, saving) {
    settingControls(setting).forEach((control) => {
      const row = control.closest(
        ".tg-settings-toggle-row, .tg-settings-radio-row, .tg-settings-theme"
      );
      row?.classList.toggle("is-saving", saving);
      control.disabled = saving;
    });
  }

  async function saveSetting(control) {
    const setting = control.dataset.setting;
    if (!setting) return;

    const nextValue = inputValue(control);
    const previousValue = currentValues.get(setting);
    if (previousValue === nextValue) {
      if (setting === "theme") previewTheme(nextValue);
      if (setting === "enter_to_send") updateEnterHint(nextValue);
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
        headers: {
          "X-Requested-With": "XMLHttpRequest",
        },
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
    const fromHash = normalizedScreen(window.location.hash.slice(1) || "main");
    if (fromHash !== currentScreen) showScreen(fromHash);
  });

  document.addEventListener("keydown", (event) => {
    if (event.key !== "Escape") return;
    if (menu && !menu.hidden) {
      event.preventDefault();
      closeMenu();
      return;
    }
    if (currentScreen !== "main") {
      event.preventDefault();
      showScreen("main", { history: "replace" });
    }
  });

  initializeValues();
  const initial = normalizedScreen(window.location.hash.slice(1) || "main");
  showScreen(initial, { history: "replace" });
  previewTheme(currentValues.get("theme") || document.body.dataset.theme || "light");
  updateEnterHint(currentValues.get("enter_to_send") || "true");
})();
