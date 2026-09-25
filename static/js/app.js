const AUTH_THEME_KEY = "sovietgram.theme";

function applyClientTheme(theme, persist = true) {
  const next = theme === "dark" ? "dark" : "light";
  document.documentElement.dataset.theme = next;
  document.documentElement.style.colorScheme = next === "dark" ? "dark" : "light";
  document.body.dataset.theme = next;
  const meta = document.querySelector('meta[name="theme-color"]');
  if (meta) meta.content = next === "dark" ? "#171412" : "#cc0000";
  document.querySelectorAll("[data-auth-theme-icon]").forEach((icon) => {
    icon.textContent = next === "dark" ? "☀" : "☾";
  });
  document.querySelectorAll("[data-auth-theme-toggle]").forEach((button) => {
    button.setAttribute(
      "aria-label",
      next === "dark" ? "Включить светлую тему" : "Включить тёмную тему",
    );
    button.title = next === "dark" ? "Светлая тема" : "Тёмная тема";
  });
  if (persist) {
    try {
      localStorage.setItem(AUTH_THEME_KEY, next);
    } catch (_error) {
      // Storage can be disabled; the current page still keeps the theme.
    }
  }
  return next;
}

if (document.body.classList.contains("auth-body")) {
  applyClientTheme(document.documentElement.dataset.theme || document.body.dataset.theme || "light", false);
  document.querySelectorAll("[data-auth-theme-toggle]").forEach((button) => {
    button.addEventListener("click", () => {
      applyClientTheme(document.body.dataset.theme === "dark" ? "light" : "dark");
    });
  });
}

const toast = document.getElementById("toast");
const easterStar = document.getElementById("easterStar");
let toastTimeout;

function showToast(text) {
  if (!toast) return;
  clearTimeout(toastTimeout);
  toast.textContent = text;
  toast.classList.add("is-visible");
  toastTimeout = setTimeout(() => toast.classList.remove("is-visible"), 2200);
}

if (easterStar) {
  easterStar.addEventListener("click", () => {
    const messages = [
      "Одобрено Госпланом ★",
      "Производительность интерфейса повышена на 146%",
      "Дефицита сообщений не обнаружено",
      "Товарищ, ваш онлайн учтён статистикой",
      "Пятилетний план по регистрации выполняется досрочно"
    ];
    showToast(messages[Math.floor(Math.random() * messages.length)]);
  });
}

const NAVIGATION_STACK_KEY = "sovietgram.navigation.stack.v1";
const LAST_WORKSPACE_KEY = "sovietgram.navigation.workspace.v1";
const MAX_NAVIGATION_DEPTH = 32;

function currentInternalUrl() {
  return `${window.location.pathname}${window.location.search}${window.location.hash}`;
}

function readNavigationStack() {
  try {
    const value = JSON.parse(sessionStorage.getItem(NAVIGATION_STACK_KEY) || "[]");
    return Array.isArray(value) ? value.filter((item) => typeof item === "string") : [];
  } catch (_) {
    return [];
  }
}

function writeNavigationStack(stack) {
  try {
    sessionStorage.setItem(NAVIGATION_STACK_KEY, JSON.stringify(stack.slice(-MAX_NAVIGATION_DEPTH)));
  } catch (_) {
    // Navigation still works through the links' normal href values when storage is unavailable.
  }
}

function rememberWorkspace() {
  if (!document.body.classList.contains("app-body")) return;
  try {
    sessionStorage.setItem(LAST_WORKSPACE_KEY, currentInternalUrl());
  } catch (_) {
    // Ignore private-mode/storage failures.
  }
}

function getLastWorkspace() {
  try {
    return sessionStorage.getItem(LAST_WORKSPACE_KEY) || "/";
  } catch (_) {
    return "/";
  }
}

function isInternalSection(pathname) {
  return pathname === "/profile/"
    || pathname === "/settings/"
    || pathname === "/contacts/"
    || pathname === "/calls/"
    || pathname === "/accounts/add/"
    || pathname === "/profile/password/"
    || pathname.startsWith("/u/");
}

function pushNavigationLocation() {
  const current = currentInternalUrl();
  const stack = readNavigationStack();
  if (stack[stack.length - 1] !== current) stack.push(current);
  writeNavigationStack(stack);
}

function popNavigationLocation() {
  const current = currentInternalUrl();
  const stack = readNavigationStack();

  while (stack.length && stack[stack.length - 1] === current) stack.pop();
  const previous = stack.pop() || getLastWorkspace();
  writeNavigationStack(stack);
  return previous;
}

function isPlainLeftClick(event) {
  return event.button === 0
    && !event.ctrlKey
    && !event.metaKey
    && !event.shiftKey
    && !event.altKey;
}

function isBackControl(link) {
  return link.matches(".settings-back")
    || link.matches(".contacts-topbar > a:first-child")
    || link.matches(".public-profile-topbar > a:first-child")
    || link.matches(".profile-actions > .secondary-button");
}

function isWorkspaceControl(link, url) {
  return link.matches(".settings-brand")
    || (link.closest(".settings-nav") && url.pathname === "/");
}

rememberWorkspace();

document.addEventListener("click", (event) => {
  if (!isPlainLeftClick(event)) return;

  const link = event.target.closest("a[href]");
  if (!link || link.target === "_blank" || link.hasAttribute("download")) return;

  let url;
  try {
    url = new URL(link.href, window.location.href);
  } catch (_) {
    return;
  }

  if (url.origin !== window.location.origin) return;

  if (isBackControl(link) && url.pathname !== "/login/") {
    event.preventDefault();
    window.location.assign(popNavigationLocation() || link.href);
    return;
  }

  if (isWorkspaceControl(link, url)) {
    event.preventDefault();
    writeNavigationStack([]);
    window.location.assign(getLastWorkspace());
    return;
  }

  if (isInternalSection(url.pathname)) pushNavigationLocation();
}, true);

const sidebarComposeButton = document.getElementById("sidebarComposeButton");
const sidebarComposeMenu = document.getElementById("sidebarComposeMenu");

function closeSidebarComposeMenu() {
  if (!sidebarComposeButton || !sidebarComposeMenu) return;
  sidebarComposeMenu.hidden = true;
  sidebarComposeButton.setAttribute("aria-expanded", "false");
}

if (sidebarComposeButton && sidebarComposeMenu) {
  sidebarComposeButton.addEventListener("click", (event) => {
    event.stopPropagation();
    const willOpen = sidebarComposeMenu.hidden;
    sidebarComposeMenu.hidden = !willOpen;
    sidebarComposeButton.setAttribute("aria-expanded", String(willOpen));
  });

  sidebarComposeMenu.addEventListener("click", (event) => event.stopPropagation());
  document.addEventListener("click", closeSidebarComposeMenu);
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") closeSidebarComposeMenu();
  });
}

const communityTypeSwitch = document.querySelector(".community-type-switch");
const communityMembersField = document.getElementById("communityMembersField");

if (communityTypeSwitch) {
  const radios = Array.from(communityTypeSwitch.querySelectorAll('input[name="type"]'));

  function syncCommunityType() {
    const selected = radios.find((radio) => radio.checked);
    communityTypeSwitch.querySelectorAll("label").forEach((label) => {
      label.classList.toggle("is-selected", label.contains(selected));
    });
    if (communityMembersField) {
      communityMembersField.hidden = selected?.value === "channel";
    }
  }

  radios.forEach((radio) => radio.addEventListener("change", syncCommunityType));
  syncCommunityType();
}
