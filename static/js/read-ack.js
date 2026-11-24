/* Acknowledge actually visible incoming messages independently of chat polling. */
(() => {
  const BLOCKING_OVERLAYS = [
    "#telegramSettings:not([hidden])", "#userProfileOverlay:not([hidden])",
    "#mediaComposeBackdrop:not([hidden])", "#attachSpecialBackdrop:not([hidden])",
    "#articleViewerBackdrop:not([hidden])", "#imageViewer:not([hidden])",
    "#editMessageModal:not([hidden])", "#forwardMessageModal:not([hidden])",
    "#deleteMessageModal:not([hidden])", "#clearHistoryModal:not([hidden])",
    "#deleteChatModal:not([hidden])", "#chatInfoBackdrop:not([hidden])",
    "#communityProfileBackdrop:not([hidden])", "#profileMenu.is-open", "dialog[open]",
  ].join(", ");

  function visibleCandidate(nodes, bounds, cursor) {
    if (bounds.bottom <= bounds.top || bounds.right <= bounds.left) return cursor;
    let candidate = cursor;
    for (const article of nodes) {
      const id = Number(article.dataset.messageId);
      if (!Number.isSafeInteger(id) || id <= candidate ||
          article.dataset.messageOwn !== "false" || article.hidden) continue;
      const rect = article.getBoundingClientRect();
      if (rect.width <= 0 || rect.height <= 0 || rect.right <= bounds.left || rect.left >= bounds.right) continue;
      const visible = Math.min(rect.bottom, bounds.bottom) - Math.max(rect.top, bounds.top);
      if (visible > 0 && visible >= Math.min(rect.height * .6, (bounds.bottom - bounds.top) * .6)) {
        candidate = id;
      }
    }
    return candidate;
  }

  function createTracker({ initialCursor = 0, initialMarker = "", canRead, candidate, send, refreshed, now = Date.now }) {
    let cursor = Number(initialCursor) || 0;
    // A stale tab is only allowed to clear the exact manual mark it opened.
    let openedUnreadMarker = initialMarker;
    let busy = false, retryAt = 0, failures = 0;
    function observeCursor(value) {
      const next = Number(value);
      if (Number.isSafeInteger(next) && next > cursor) cursor = next;
    }
    async function check() {
      if (busy || now() < retryAt || !canRead()) return;
      const next = candidate(cursor);
      if (next <= cursor && !openedUnreadMarker) return;
      busy = true;
      try {
        const result = await send({
          message_id: next > cursor ? next : 0,
          opened_marker: openedUnreadMarker,
        });
        if (!result || result.ok !== true ||
            !Number.isSafeInteger(Number(result.own_last_read_id)) ||
            Number(result.own_last_read_id) < (next > cursor ? next : 0)) {
          throw new Error("Read acknowledgement not confirmed");
        }
        observeCursor(result.own_last_read_id);
        openedUnreadMarker = "";
        retryAt = failures = 0;
        // A sidebar refresh is independent of acknowledgement success.
        try { refreshed?.(result); } catch (_error) {}
      } catch (_error) {
        failures += 1;
        retryAt = now() + Math.min(5000, 500 * (2 ** Math.min(failures, 4)));
      } finally {
        busy = false;
      }
    }
    return { check, observeCursor, get cursor() { return cursor; } };
  }

  window.SovietgramReadAckHelpers = { visibleCandidate, createTracker };
  const stage = document.getElementById("messageStage");
  const flow = document.getElementById("messageFlow");
  if (!stage?.dataset.readUrl || !flow) return;
  const account = stage.dataset.accountId;
  const tracker = createTracker({
    initialCursor: stage.dataset.ownLastRead,
    initialMarker: stage.dataset.openedMarker || "",
    canRead() {
      return stage.isConnected && !document.hidden &&
        document.visibilityState !== "hidden" && document.hasFocus() &&
        stage.dataset.readHistoryBusy !== "true" &&
        !document.querySelector(BLOCKING_OVERLAYS) &&
        stage.getClientRects().length > 0;
    },
    candidate(cursor) {
      const rect = stage.getBoundingClientRect();
      return visibleCandidate(flow.querySelectorAll(".message[data-message-id]"), {
        top: Math.max(0, rect.top), bottom: Math.min(window.innerHeight, rect.bottom),
        left: Math.max(0, rect.left), right: Math.min(window.innerWidth, rect.right),
      }, cursor);
    },
    async send(values) {
      const body = new FormData();
      const csrf = document.querySelector("#messageForm [name='csrfmiddlewaretoken']")?.value
        || document.querySelector("[name='csrfmiddlewaretoken']")?.value || "";
      Object.entries({csrfmiddlewaretoken: csrf, account_id: account, ...values})
        .forEach(([key, value]) => body.append(key, value));
      const controller = new AbortController();
      const timeout = window.setTimeout(() => controller.abort(), 10000);
      try {
        const response = await fetch(stage.dataset.readUrl, {
          method: "POST", credentials: "same-origin", cache: "no-store",
          headers: {"X-Requested-With": "XMLHttpRequest"}, body, signal: controller.signal,
        });
        const result = await response.json();
        if (!response.ok || result.ok !== true || String(result.account_id) !== account) {
          throw new Error("Read acknowledgement rejected");
        }
        return result;
      } finally {
        window.clearTimeout(timeout);
      }
    },
    refreshed() {
      // Do not wait for the next five-second sidebar snapshot.
      void window.SovietgramSidebar?.refresh();
    },
  });

  let timer = 0;
  function schedule() {
    window.clearTimeout(timer);
    timer = window.setTimeout(() => void tracker.check(), 180);
  }
  window.SovietgramReadAck = { schedule, observeCursor: tracker.observeCursor };

  stage.addEventListener("scroll", schedule, {passive: true});
  stage.addEventListener("load", schedule, true); // media changes the visible geometry
  stage.addEventListener("pointerup", schedule, {passive: true});
  document.addEventListener("focusin", schedule);
  window.addEventListener("focus", schedule);
  window.addEventListener("resize", schedule);
  window.addEventListener("online", schedule);
  window.addEventListener("pageshow", schedule);
  document.addEventListener("visibilitychange", schedule);
  if (typeof ResizeObserver === "function") {
    const observer = new ResizeObserver(schedule);
    observer.observe(stage);
    observer.observe(flow);
  }
  // Independent heartbeat also recovers from a failed poll, a closed modal,
  // a late layout change or a request that failed while offline.
  window.setInterval(() => void tracker.check(), 1000);
  // Allow the chat's initial animation frame to restore the scroll position.
  window.requestAnimationFrame(() => window.requestAnimationFrame(schedule));
})();
