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
    next.className = node.className || "";
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
    const selector = `[${attribute}]`;
    const expected = String(id);
    let changed = 0;
    document.querySelectorAll(selector).forEach((node) => {
      if (node.dataset[attribute.slice(5).replace(/-([a-z])/g, (_m, char) => char.toUpperCase())] !== expected) return;
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
