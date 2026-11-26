/* Count channel posts only while visible, never while prefetching history.
   Repeated acknowledgements are idempotent on the server. */
(() => {
  const conversation = document.querySelector(".conversation--chat");
  const url = conversation?.dataset.channelViewsUrl;
  const stage = document.getElementById("messageStage");
  const flow = document.getElementById("messageFlow");
  if (!url || !stage || !flow) return;
  let busy = false, timer = 0, nextAt = 0, stopped = false;
  const account = stage.dataset.accountId;
  function append(footer) {
    const chip = document.createElement("span");
    chip.className = "channel-post-views";
    chip.title = "Уникальные просмотры";
    chip.setAttribute("aria-label", "Просмотры: нет данных");
    const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.setAttribute("viewBox", "0 0 24 24");
    svg.setAttribute("aria-hidden", "true");
    const path = document.createElementNS(svg.namespaceURI, "path");
    path.setAttribute("d", "M2 12s3.6-6 10-6 10 6 10 6-3.6 6-10 6-10-6-10-6Z");
    const circle = document.createElementNS(svg.namespaceURI, "circle");
    circle.setAttribute("cx", "12");
    circle.setAttribute("cy", "12");
    circle.setAttribute("r", "2.5");
    svg.append(path, circle);
    const count = document.createElement("span");
    count.dataset.channelViewCount = "";
    count.textContent = "—";
    chip.append(svg, count);
    footer.append(chip);
  }
  function inViewport(article, bounds) {
    const rect = article.getBoundingClientRect();
    const top = Math.max(rect.top, bounds.top, 0);
    const bottom = Math.min(rect.bottom, bounds.bottom, window.innerHeight);
    const left = Math.max(rect.left, bounds.left, 0);
    const right = Math.min(rect.right, bounds.right, window.innerWidth);
    if (bottom - top < Math.min(24, rect.height) || right <= left) return false;
    const hit = document.elementFromPoint((left + right) / 2, (top + bottom) / 2);
    return !!hit && (hit === article || article.contains(hit));
  }
  function schedule(delay = 250) {
    if (stopped || document.hidden || timer) return;
    timer = window.setTimeout(() => {
      timer = 0;
      void refresh();
    }, Math.max(delay, nextAt - Date.now()));
  }
  async function refresh() {
    if (stopped || busy || document.hidden || !navigator.onLine) return;
    if (Date.now() < nextAt) { schedule(); return; }
    const bounds = stage.getBoundingClientRect();
    const visible = Array.from(flow.querySelectorAll(".message[data-message-id]"))
      .filter(article => inViewport(article, bounds)).slice(0, 100);
    if (!visible.length) return;
    const token = document.querySelector("#settingsAjaxForm [name='csrfmiddlewaretoken'], [name='csrfmiddlewaretoken']")?.value;
    if (!token) return;
    busy = true;
    nextAt = Date.now() + 2500;
    try {
      const response = await fetch(url, {
        method: "POST", credentials: "same-origin",
        headers: {"X-Requested-With": "XMLHttpRequest"},
        body: new URLSearchParams({
          csrfmiddlewaretoken: token,
          account_id: account,
          ids: visible.map(article => article.dataset.messageId).join(","),
        }),
      });
      if (response.status === 409 || response.status === 403 || response.status === 404 || response.redirected) {
        stopped = true; return;
      }
      if (response.status === 429) {
        nextAt = Date.now() + Math.max(10000, Number(response.headers.get("Retry-After") || 60) * 1000);
        return;
      }
      if (!response.ok) return;
      const payload = await response.json();
      if (!payload.ok || String(payload.account_id) !== account) { stopped = true; return; }
      for (const article of visible) {
        const value = payload.counts?.[article.dataset.messageId];
        if (!Number.isSafeInteger(value) || value < 0) continue;
        const count = article.querySelector("[data-channel-view-count]");
        if (count) {
          count.textContent = new Intl.NumberFormat("ru-RU").format(value);
          count.parentElement.setAttribute("aria-label", "Просмотры: " + value);
          count.parentElement.title = "Уникальные просмотры: " + value;
        }
      }
    } catch (_) { /* Normal polling retries after connectivity returns. */ }
    finally { busy = false; }
  }
  window.SovietgramChannelViews = {append};
  stage.addEventListener("scroll", () => schedule(), {passive:true});
  document.addEventListener("visibilitychange", () => schedule());
  window.addEventListener("online", () => schedule());
  window.addEventListener("resize", () => schedule());
  window.setInterval(() => schedule(), 8000);
  schedule();
})();
