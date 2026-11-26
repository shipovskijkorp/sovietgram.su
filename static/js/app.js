const AUTH_THEME_KEY = "sovietgram.theme";
const CLIENT_TIMEZONE_COOKIE = "sovietgram_timezone";
const TIMEZONE_RELOAD_KEY = "sovietgram.timezone-reload";

function readCookie(name) {
  const prefix = `${name}=`;
  const item = document.cookie
    .split(";")
    .map((part) => part.trim())
    .find((part) => part.startsWith(prefix));
  if (!item) return "";
  try {
    return decodeURIComponent(item.slice(prefix.length));
  } catch (_error) {
    return item.slice(prefix.length);
  }
}

function syncClientTimezone() {
  let detected = "";
  try {
    detected = Intl.DateTimeFormat().resolvedOptions().timeZone || "";
  } catch (_error) {
    return;
  }
  if (!detected || readCookie(CLIENT_TIMEZONE_COOKIE) === detected) return;

  const secure = window.location.protocol === "https:" ? "; Secure" : "";
  document.cookie = `${CLIENT_TIMEZONE_COOKIE}=${encodeURIComponent(detected)}; Path=/; Max-Age=31536000; SameSite=Lax${secure}`;

  try {
    if (sessionStorage.getItem(TIMEZONE_RELOAD_KEY) !== detected) {
      sessionStorage.setItem(TIMEZONE_RELOAD_KEY, detected);
      window.location.reload();
    }
  } catch (_error) {
    // Cookie still applies to the next navigation if sessionStorage is blocked.
  }
}

syncClientTimezone();

// A focused authenticated heartbeat doubles as a connectivity check.
if (document.documentElement.dataset.authenticated === "true") {
  const banner = document.getElementById("connectionStatus");
  let pending = false, failures = 0;
  function showConnection(state) {
    if (!banner) return;
    banner.hidden = state === "online";
    banner.textContent = state === "offline" ? "Нет подключения к интернету" : "Подключение к серверу…";
  }
  function success() { failures = 0; showConnection(navigator.onLine ? "online" : "offline"); }
  function failure() {
    failures += 1;
    if (!navigator.onLine) showConnection("offline");
    else if (failures >= 2) showConnection("connecting");
  }
  window.SovietgramConnection = {success, failure};
  async function touchPresence() {
    if (pending || document.hidden || !document.hasFocus() || !navigator.onLine) return;
    pending = true;
    const controller = new AbortController();
    const timeout = window.setTimeout(() => controller.abort(), 8000);
    try {
      const response = await fetch("/presence/heartbeat/", {
        credentials: "same-origin", cache: "no-store", signal: controller.signal,
      });
      const payload = await response.json().catch(() => ({}));
      if (response.ok && payload.ok && String(payload.account_id) === document.body.dataset.accountId) success();
      else if (response.status >= 500) failure();
    } catch (_) { failure(); }
    finally { pending = false; window.clearTimeout(timeout); }
  }
  window.addEventListener("offline", () => showConnection("offline"));
  window.addEventListener("online", () => { showConnection("connecting"); void touchPresence(); });
  window.addEventListener("focus", () => { void touchPresence(); });
  document.addEventListener("visibilitychange", () => { if (!document.hidden) void touchPresence(); });
  window.setInterval(() => {
    if (failures || (banner && !banner.hidden)) void touchPresence();
  }, 4000);
  window.setInterval(touchPresence, 30000);
  if (!navigator.onLine) showConnection("offline");
  else void touchPresence();
}

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

if (easterStar && window.SovietgramEasterStar) {
  let storage = null;
  try { storage = window.localStorage; } catch (_) {}
  const accountId = document.body.dataset.accountId || "default";
  const nextMessage = window.SovietgramEasterStar.createDeck({
    storage, key: "sovietgram.easter-star.v1." + accountId
  });
  easterStar.addEventListener("click", () => showToast(nextMessage()));
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
