/* Mobile workspace: move existing controls rather than duplicate handlers. */
(() => {
  const media = window.matchMedia("(max-width: 820px), (max-height: 540px) and (max-width: 1100px)");
  const root = document.documentElement;
  const sidebar = document.querySelector(".app-shell .sidebar");
  const search = document.getElementById("chatFilter");
  const searchToggle = document.getElementById("mobileSearchToggle");
  const drawer = document.getElementById("profileMenu");
  const utility = sidebar?.querySelector(".sidebar__footer");
  const drawerFooter = drawer?.querySelector(".profile-drawer__footer");
  const menuButton = document.getElementById("profileMenuButton");
  const form = document.getElementById("messageForm");
  const tools = document.getElementById("mobileComposerTools");
  const toolsToggle = document.getElementById("mobileComposerToggle");
  const moved = [];
  const utilityAnchor = utility && document.createComment("desktop sidebar footer");
  if (utilityAnchor) utility.before(utilityAnchor);
  if (form && tools && toolsToggle) {
    for (const control of form.querySelectorAll(
      '[data-compose-panel="format"][data-compose-target="messageInput"], #sendOptionsToggle'
    )) {
      const anchor = document.createComment("desktop composer tool");
      control.before(anchor);
      moved.push({control, anchor});
    }
  }

  function setSearch(open, focus = false) {
    if (!sidebar || !searchToggle || !search) return;
    sidebar.classList.toggle("is-mobile-search", open);
    searchToggle.setAttribute("aria-expanded", String(open));
    searchToggle.setAttribute("aria-label", open ? "Закрыть поиск" : "Поиск");
    if (open) {
      if (focus) search.focus({preventScroll: true});
    } else {
      if (search.value) {
        search.value = "";
        search.dispatchEvent(new Event("input", {bubbles: true}));
      }
      search.blur();
    }
  }
  searchToggle?.addEventListener("click", () => {
    setSearch(!sidebar.classList.contains("is-mobile-search"), true);
  });
  search?.addEventListener("keydown", event => {
    if (media.matches && event.key === "Escape") {
      setSearch(false);
      searchToggle?.focus();
    }
  });

  const composeMenu = document.getElementById("sidebarComposeMenu");
  const composeButton = document.getElementById("sidebarComposeButton");
  composeMenu?.addEventListener("click", event => {
    if (event.target.closest("a")) {
      composeMenu.hidden = true;
      composeButton?.setAttribute("aria-expanded", "false");
    }
  });

  function setTools(open) {
    if (!tools || !toolsToggle) return;
    tools.hidden = !open;
    toolsToggle.setAttribute("aria-expanded", String(open));
  }
  toolsToggle?.addEventListener("pointerdown", event => event.preventDefault());
  toolsToggle?.addEventListener("click", () => setTools(tools.hidden));
  form?.addEventListener("submit", () => setTools(false));

  const stage = document.getElementById("messageStage");
  let lastHeight = 0;
  let frame = 0;
  function viewportChanged() {
    if (frame) cancelAnimationFrame(frame);
    frame = requestAnimationFrame(() => {
      frame = 0;
      const viewport = window.visualViewport;
      if (!media.matches || (viewport && Math.abs(viewport.scale - 1) > .02)) return;
      const height = Math.round(viewport?.height || window.innerHeight);
      if (height <= 0) return;
      const keyboard = Boolean(viewport && window.innerHeight - viewport.height > 100);
      root.classList.toggle("sg-keyboard-open", keyboard);
      if (height === lastHeight) return;
      const nearBottom = stage && stage.scrollHeight - stage.scrollTop - stage.clientHeight < 60;
      lastHeight = height;
      root.style.setProperty("--sg-mobile-height", height + "px");
      if (nearBottom && stage) stage.scrollTop = stage.scrollHeight;
    });
  }
  function applyLayout() {
    const mobile = media.matches;
    if (utility && utilityAnchor && drawerFooter && menuButton) {
      if (mobile) drawerFooter.before(utility);
      else utilityAnchor.after(utility);
    }
    if (tools && toolsToggle) {
      for (const {control, anchor} of moved) {
        if (mobile) tools.appendChild(control);
        else anchor.after(control);
      }
      form.classList.toggle("has-mobile-tools", mobile && moved.length > 0);
      toolsToggle.hidden = !mobile || !moved.length;
      setTools(false);
      window.SovietgramChat?.resizeComposer?.();
    }
    if (sidebar && searchToggle && search) {
      if (mobile && search.value.trim()) setSearch(true);
      else if (!mobile) {
        sidebar.classList.remove("is-mobile-search");
        searchToggle.setAttribute("aria-expanded", "false");
        searchToggle.setAttribute("aria-label", "Поиск");
      }
    }
    if (!mobile) {
      lastHeight = 0;
      root.style.removeProperty("--sg-mobile-height");
      root.classList.remove("sg-keyboard-open");
    } else viewportChanged();
  }
  if (media.addEventListener) media.addEventListener("change", applyLayout);
  else media.addListener(applyLayout);
  window.addEventListener("resize", viewportChanged);
  window.visualViewport?.addEventListener("resize", viewportChanged);
  window.visualViewport?.addEventListener("scroll", viewportChanged);
  applyLayout();
})();
