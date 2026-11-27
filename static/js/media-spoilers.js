/* Visual spoiler only: the underlying attachment uses the normal access checks. */
(() => {
  const hiddenSelector = "[data-media-spoiler]:not([data-spoiler-revealed])";
  const revealed = new Set();
  function isHidden(node) { return Boolean(node?.closest?.(hiddenSelector)); }
  function apply(node) {
    if (!node?.dataset.mediaSpoiler) return;
    if (node.tagName === "DIV" && !node.querySelector(".media-spoiler-reveal")) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "media-spoiler-reveal";
      button.textContent = "Показать медиа";
      node.append(button);
    }
    const visible = revealed.has(node.dataset.mediaSpoiler);
    if (visible) {
      node.dataset.spoilerRevealed = "";
      if (node.tagName === "A" || node.tagName === "BUTTON")
        node.setAttribute("aria-label", "Открыть " + (node.dataset.mediaName || "медиа"));
    } else {
      delete node.dataset.spoilerRevealed;
      if (node.tagName === "A" || node.tagName === "BUTTON")
        node.setAttribute("aria-label", "Показать скрытое медиа");
    }
  }
  function mark(node, id) { node.dataset.mediaSpoiler = String(id); apply(node); return node; }
  document.querySelectorAll("[data-media-spoiler]").forEach(apply);
  document.addEventListener("click", event => {
    const root = event.target.closest?.(hiddenSelector);
    if (!root || event.button > 0) return;
    event.preventDefault();
    event.stopImmediatePropagation();
    revealed.add(root.dataset.mediaSpoiler);
    document.querySelectorAll("[data-media-spoiler]").forEach(apply);
    if (root.tagName === "DIV") root.querySelector(".message-video-expand")?.focus({preventScroll:true});
  }, true);
  // Prevent a hidden anchor from being opened by middle-click/context-menu.
  document.addEventListener("auxclick", event => {
    if (isHidden(event.target)) { event.preventDefault(); event.stopImmediatePropagation(); }
  }, true);
  document.addEventListener("contextmenu", event => {
    if (isHidden(event.target)) event.preventDefault();
  });
  window.SovietgramMediaSpoilers = {mark,isHidden};
})();
