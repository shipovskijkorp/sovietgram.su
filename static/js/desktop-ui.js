/* Desktop chat-list width is a local, per-account preference.
   The mobile layout always keeps its full-width, single-pane navigation. */
(() => {
  const shell = document.querySelector(".app-shell");
  const sidebar = document.getElementById("desktopChatSidebar");
  const handle = document.getElementById("desktopSidebarResizer");
  if (!shell || !sidebar || !handle) return;
  const desktop = window.matchMedia("(min-width: 821px) and (min-height: 541px), (min-width: 1101px)");
  const key = "sovietgram.desktop.sidebar-width.v1." + (document.body.dataset.accountId || "default");
  const min = 280;
  const maximum = () => Math.max(min, Math.min(520, Math.floor(shell.clientWidth * .4)));
  const defaultWidth = () => Math.round(Math.min(400, Math.max(300, shell.clientWidth * .28)));
  const clamp = width => Math.max(min, Math.min(maximum(), Math.round(width)));
  let preferred = null;
  try {
    const stored = localStorage.getItem(key);
    const value = Number(stored);
    if (stored && Number.isFinite(value) && value >= min && value <= 520) preferred = value;
  } catch (_error) { /* Layout works without storage. */ }

  let pointer = null;
  let startX = 0;
  let startWidth = 0;
  let current = 0;
  let frame = 0;
  const stage = document.getElementById("messageStage");
  const bottomBar = shell.querySelector(".conversation--chat > #messageForm, .conversation--chat > .channel-readonly");
  const heightProperty = "--sg-desktop-bottom-height";

  // The footer's border box follows the actual composer, including a
  // multiline draft, replies and other in-flow composer controls.
  // Observe only the right-hand bar: updating the sidebar cannot trigger
  // an independent resize loop on the footer itself.
  function syncBottomBar() {
    if (!desktop.matches || !bottomBar) {
      shell.style.removeProperty(heightProperty);
      return;
    }
    const height = bottomBar.getBoundingClientRect().height;
    if (height <= 0) return;
    const value = height + "px";
    if (shell.style.getPropertyValue(heightProperty) !== value) {
      shell.style.setProperty(heightProperty, value);
    }
  }
  if (bottomBar && typeof ResizeObserver !== "undefined") {
    const observer = new ResizeObserver(syncBottomBar);
    observer.observe(bottomBar, {box:"border-box"});
  }
  function setWidth(width) {
    if (!desktop.matches) return;
    const follow = stage && stage.scrollHeight - stage.scrollTop - stage.clientHeight < 60;
    current = clamp(width);
    shell.style.setProperty("--sg-desktop-sidebar", current + "px");
    handle.setAttribute("aria-valuemin", String(min));
    handle.setAttribute("aria-valuemax", String(maximum()));
    handle.setAttribute("aria-valuenow", String(current));
    if (frame) cancelAnimationFrame(frame);
    frame = requestAnimationFrame(() => {
      frame = 0;
      window.SovietgramChat?.resizeComposer?.();
      syncBottomBar();
      if (follow && stage) stage.scrollTop = stage.scrollHeight;
    });
  }
  function persist() {
    preferred = current;
    try { localStorage.setItem(key, String(preferred)); } catch (_error) {}
  }
  function reset() {
    preferred = null;
    try { localStorage.removeItem(key); } catch (_error) {}
    setWidth(defaultWidth());
  }
  function finish(save = true) {
    if (pointer === null) return;
    const id = pointer;
    pointer = null;
    if (handle.hasPointerCapture(id)) handle.releasePointerCapture(id);
    document.body.classList.remove("is-resizing-sidebar");
    if (save && desktop.matches) persist();
  }
  handle.addEventListener("pointerdown", event => {
    if (!desktop.matches || event.button !== 0 || pointer !== null) return;
    event.preventDefault();
    handle.focus({preventScroll: true});
    pointer = event.pointerId;
    startX = event.clientX;
    startWidth = sidebar.getBoundingClientRect().width;
    handle.setPointerCapture(pointer);
    document.body.classList.add("is-resizing-sidebar");
  });
  handle.addEventListener("pointermove", event => {
    if (event.pointerId !== pointer) return;
    setWidth(startWidth + event.clientX - startX);
  });
  handle.addEventListener("pointerup", event => {
    if (event.pointerId === pointer) finish();
  });
  handle.addEventListener("pointercancel", event => {
    if (event.pointerId === pointer) {
      finish(false);
      setWidth(preferred ?? defaultWidth());
    }
  });
  handle.addEventListener("lostpointercapture", event => {
    if (event.pointerId === pointer) finish();
  });
  handle.addEventListener("dblclick", event => {
    event.preventDefault();
    reset();
  });
  handle.addEventListener("keydown", event => {
    if (!desktop.matches) return;
    const step = event.shiftKey ? 48 : 24;
    let width;
    switch (event.key) {
      case "ArrowLeft": width = current - step; break;
      case "ArrowRight": width = current + step; break;
      case "Home": width = min; break;
      case "End": width = maximum(); break;
      case "Enter": case " ": event.preventDefault(); reset(); return;
      default: return;
    }
    event.preventDefault();
    setWidth(width);
    persist();
  });
  function updateLayout() {
    if (!desktop.matches) {
      finish(false);
      shell.style.removeProperty("--sg-desktop-sidebar");
      syncBottomBar();
      return;
    }
    setWidth(preferred ?? defaultWidth());
    syncBottomBar();
  }
  if (desktop.addEventListener) desktop.addEventListener("change", updateLayout);
  else desktop.addListener(updateLayout);
  window.addEventListener("resize", updateLayout);
  window.addEventListener("pagehide", () => finish());
  updateLayout();
})();
