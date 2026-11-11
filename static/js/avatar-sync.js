(() => {
  "use strict";

  function replaceAvatar(node, url, fallback) {
    if (!node) return null;
    const wantsImage = Boolean(url);
    const isImage = String(node.tagName || "").toLowerCase() === "img";

    if (wantsImage && isImage) {
      if (node.getAttribute("src") !== url) node.src = url;
      node.alt = "";
      return node;
    }
    if (!wantsImage && !isImage) {
      node.textContent = fallback || "?";
      return node;
    }

    const next = document.createElement(wantsImage ? "img" : "span");
    const fallbackClasses = {
      "conversation-header__avatar": "conversation-header__avatar--fallback",
      "chat-row__avatar": "chat-row__avatar--fallback",
      "chat-info-avatar": "chat-info-avatar--fallback",
      "forward-target__avatar": "forward-target__avatar--fallback",
    };
    const classes = String(node.className || "").split(/\s+/).filter(Boolean);
    const normalized = classes.filter((name) => !Object.values(fallbackClasses).includes(name));
    if (!wantsImage) {
      Object.entries(fallbackClasses).forEach(([base, fallbackClass]) => {
        if (normalized.includes(base) && !normalized.includes(fallbackClass)) {
          normalized.push(fallbackClass);
        }
      });
    }
    next.className = normalized.join(" ");
    Object.entries(node.dataset || {}).forEach(([key, value]) => {
      next.dataset[key] = value;
    });
    if (wantsImage) {
      next.src = url;
      next.alt = "";
      next.loading = "lazy";
    } else {
      next.textContent = fallback || "?";
    }
    node.replaceWith(next);
    return next;
  }

  function update(kind, id, url, fallback) {
    if (id == null || id === "") return 0;
    const attribute = `data-avatar-${kind}-id`;
    const datasetKey = kind === "user" ? "avatarUserId" : "avatarChatId";
    const selector = `[${attribute}]`;
    const expected = String(id);
    let changed = 0;
    document.querySelectorAll(selector).forEach((node) => {
      if (node.dataset[datasetKey] !== expected) return;
      replaceAvatar(node, url || "", fallback || "?");
      changed += 1;
    });
    return changed;
  }

  window.SovietgramAvatarSync = Object.freeze({
    replace: replaceAvatar,
    updateUser(id, url, fallback) {
      return update("user", id, url, fallback);
    },
    updateChat(id, url, fallback) {
      return update("chat", id, url, fallback);
    },
  });
})();
