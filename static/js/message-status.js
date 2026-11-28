/* Shared, font-independent delivery/read indicators for all message renderers. */
(() => {
  function set(node, isRead) {
    // Read cursors are monotonic: a stale poll cannot undo a confirmed read.
    isRead = Boolean(isRead || node.dataset.readState === "read");
    const state = isRead ? "read" : "sent";
    const label = isRead ? "Прочитано" : "Отправлено";
    node.dataset.readState = state;
    node.setAttribute("role", "img");
    node.setAttribute("aria-label", label);
    node.title = label;
    return node;
  }

  function create(isRead) {
    const node = document.createElement("span");
    node.className = "message-check";
    return set(node, isRead);
  }

  window.SovietgramReadReceipt = { create, set };
})();
