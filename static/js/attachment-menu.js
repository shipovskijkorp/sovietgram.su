(() => {
  const button = document.getElementById("attachmentButton");
  const menu = document.getElementById("attachmentMenu");
  if (!button || !menu) return;

  let open = false;

  function position() {
    if (!open || menu.hidden) return;
    const rect = button.getBoundingClientRect();
    const menuRect = menu.getBoundingClientRect();
    const viewport = window.visualViewport;
    const viewportWidth = viewport?.width || window.innerWidth || document.documentElement.clientWidth;
    const viewportHeight = viewport?.height || window.innerHeight || document.documentElement.clientHeight;
    const viewportLeft = viewport?.offsetLeft || 0;
    const viewportTop = viewport?.offsetTop || 0;
    const gutter = 8;
    const gap = 7;

    let left = rect.left;
    if (left + menuRect.width > viewportLeft + viewportWidth - gutter) {
      left = viewportLeft + viewportWidth - menuRect.width - gutter;
    }
    left = Math.max(viewportLeft + gutter, left);

    let top = rect.top - menuRect.height - gap;
    if (top < viewportTop + gutter) {
      top = rect.bottom + gap;
    }
    if (top + menuRect.height > viewportTop + viewportHeight - gutter) {
      top = Math.max(viewportTop + gutter, viewportTop + viewportHeight - menuRect.height - gutter);
    }

    menu.style.left = Math.round(left) + "px";
    menu.style.top = Math.round(top) + "px";
    menu.style.right = "auto";
    menu.style.bottom = "auto";
  }

  function show() {
    if (menu.parentElement !== document.body) {
      document.body.appendChild(menu);
    }
    menu.classList.add("attachment-menu--portal");
    menu.hidden = false;
    open = true;
    button.setAttribute("aria-expanded", "true");
    position();
  }

  function hide() {
    menu.hidden = true;
    open = false;
    button.setAttribute("aria-expanded", "false");
  }

  function toggle() {
    if (open && !menu.hidden) hide();
    else show();
  }

  // Own the trigger in capture phase so legacy/general chat click handlers
  // cannot toggle the menu a second time and immediately close it.
  document.addEventListener("click", (event) => {
    const trigger = event.target.closest?.("#attachmentButton");
    if (trigger) {
      event.preventDefault();
      event.stopImmediatePropagation();
      toggle();
      return;
    }

    if (open && !menu.contains(event.target)) {
      hide();
    }
  }, true);

  button.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && open) {
      event.preventDefault();
      hide();
      return;
    }
    if (!["ArrowDown", "ArrowUp"].includes(event.key)) return;
    event.preventDefault();
    show();
    const items = [...menu.querySelectorAll("button:not([disabled])")];
    (event.key === "ArrowUp" ? items.at(-1) : items[0])?.focus();
  });

  menu.addEventListener("keydown", (event) => {
    const items = [...menu.querySelectorAll("button:not([disabled])")];
    const current = items.indexOf(document.activeElement);

    if (event.key === "Escape") {
      event.preventDefault();
      hide();
      button.focus();
      return;
    }

    if (!["ArrowDown", "ArrowUp", "Home", "End"].includes(event.key)) return;
    event.preventDefault();

    let next = current;
    if (event.key === "Home") next = 0;
    else if (event.key === "End") next = items.length - 1;
    else if (event.key === "ArrowDown") next = current < 0 ? 0 : (current + 1) % items.length;
    else next = current < 0 ? items.length - 1 : (current - 1 + items.length) % items.length;

    items[next]?.focus();
  });

  window.addEventListener("resize", position);
  window.visualViewport?.addEventListener("resize", position);
  window.visualViewport?.addEventListener("scroll", position);
  window.addEventListener("scroll", position, true);

  window.SovietgramAttachmentMenu = {
    open: show,
    close: hide,
    toggle,
    reposition: position,
    isOpen: () => open && !menu.hidden,
  };
})();
