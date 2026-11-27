(() => {
  const $ = id => document.getElementById(id);
  const chat = document.querySelector(".conversation[data-gallery-url]");
  const gallery = $("chatMediaGallery");
  const viewer = $("imageViewer");
  if (!chat || !gallery || !viewer) return;
  const itemsNode = $("chatGalleryItems"), status = $("chatGalleryStatus"), more = $("chatGalleryMore");
  const tabs = [...gallery.querySelectorAll("[data-gallery-kind]")];
  const img = $("imageViewerImage"), video = $("imageViewerVideo"), error = $("imageViewerError");
  const prev = $("imageViewerPrev"), next = $("imageViewerNext"), download = $("imageViewerDownload");
  let kind = "media", before = null, generation = 0, controller = null, items = [];
  let viewing = [], position = 0, source = null, protectedGallery = false;
  const mediaSelector = "[data-lightbox-image], [data-lightbox-video]";
  const isProtected = () => protectedGallery || chat.dataset.chatProtected === "true";
  const account = $("messageStage")?.dataset.accountId || document.body.dataset.accountId || "";
  function node(tag, text, cls) {
    const n = document.createElement(tag);
    if (text) n.textContent = text;
    if (cls) n.className = cls;
    return n;
  }
  function formatSize(size) {
    const bytes = Number(size) || 0;
    return bytes < 1024 ? bytes + " Б" : bytes < 1048576 ? Math.round(bytes / 1024) + " КБ" : (bytes / 1048576).toFixed(1) + " МБ";
  }
  function mediaData(el) {
    return {
      kind: el.dataset.lightboxVideo ? "video" : "image",
      url: el.dataset.lightboxVideo || el.dataset.lightboxImage || "",
      name: el.dataset.mediaName || el.querySelector("img")?.alt || "",
      download: el.dataset.mediaDownload || "",
    };
  }
  function stopMedia() {
    video.pause(); video.removeAttribute("src"); video.load();
    img.removeAttribute("src");
    img.hidden = video.hidden = error.hidden = true;
  }
  function syncDownload() {
    const item = viewing[position];
    download.hidden = !item?.download || isProtected();
    if (!download.hidden) download.href = item.download;
    else download.removeAttribute("href");
  }
  function showMedia() {
    const item = viewing[position];
    if (!item) return;
    stopMedia();
    $("imageViewerName").textContent = item.name || "Медиа";
    $("imageViewerCount").textContent = (position + 1) + " / " + viewing.length;
    prev.disabled = position === 0;
    next.disabled = position >= viewing.length - 1;
    syncDownload();
    if (item.kind === "video") { video.hidden = false; video.src = item.url; }
    else { img.hidden = false; img.alt = item.name; img.src = item.url; }
  }
  function openViewer(trigger) {
    const scope = trigger.closest(".message-media, .shared-media-grid, .community-profile-media-grid, .chat-gallery-items");
    const links = scope ? [...scope.querySelectorAll(mediaSelector)].filter(el => mediaData(el).url && !window.SovietgramMediaSpoilers?.isHidden(el)) : [trigger];
    viewing = links.map(mediaData);
    position = Math.max(0, links.indexOf(trigger));
    source = trigger;
    if (!viewing[position]?.url) return;
    // Stop inline playback before opening the independent video player.
    trigger.closest(".message-video-wrap")?.querySelector("video")?.pause();
    viewer.hidden = false;
    if (!viewer.open) viewer.showModal();
    showMedia();
  }
  function closeViewer() {
    if (viewer.open) viewer.close();
  }
  viewer.addEventListener("close", () => {
    stopMedia(); viewer.hidden = true; viewing = [];
    if (source?.isConnected) source.focus();
    source = null;
  });
  for (const el of [img, video]) el.addEventListener("error", () => {
    if (viewer.open && el.getAttribute("src")) error.hidden = false;
  });
  prev.addEventListener("click", () => { if (position > 0) { position--; showMedia(); } });
  next.addEventListener("click", () => { if (position + 1 < viewing.length) { position++; showMedia(); } });
  $("imageViewerClose").addEventListener("click", closeViewer);
  viewer.addEventListener("click", e => { if (e.target === viewer) closeViewer(); });
  viewer.addEventListener("keydown", e => {
    if (e.target === video || e.altKey || e.ctrlKey || e.metaKey) return;
    if (e.key === "ArrowLeft" && !prev.disabled) { e.preventDefault(); prev.click(); }
    if (e.key === "ArrowRight" && !next.disabled) { e.preventDefault(); next.click(); }
  });
  function action(label, url, type) {
    const a = node("a", label, "gallery-action");
    a.href = url;
    if (type === "download") { a.download = ""; a.dataset.galleryDownload = ""; }
    return a;
  }
  function card(item) {
    const root = node("article", "", "chat-gallery-card");
    const picture = item.kind === "image" || item.kind === "sticker";
    if (picture || item.kind === "video" || item.kind === "video_note") {
      const button = node("button", "", "chat-gallery-preview");
      button.type = "button";
      button.dataset.mediaName = item.name;
      button.dataset.mediaDownload = item.download_url || "";
      if (item.kind === "video" || item.kind === "video_note") {
        button.dataset.lightboxVideo = item.url;
        button.append(node("span", "▶"));
      } else {
        button.dataset.lightboxImage = item.url;
        const thumbnail = node("img");
        thumbnail.src = item.thumbnail_url || item.url; thumbnail.alt = item.name; thumbnail.loading = "lazy";
        button.append(thumbnail);
      }
      button.setAttribute("aria-label", "Открыть " + item.name);
      if (item.is_spoiler) window.SovietgramMediaSpoilers?.mark(button, item.id);
      root.append(button);
    }
    root.append(node("strong", item.name, "chat-gallery-name"), node("small", item.created_at + " · " + formatSize(item.size)));
    if (item.kind === "audio" || item.kind === "voice") {
      const audio = node("audio"); audio.controls = true; audio.preload = "none"; audio.src = item.url; root.append(audio);
    }
    const actions = node("div", "", "chat-gallery-actions");
    actions.append(action("К сообщению", item.message_url));
    if (item.download_url && !isProtected()) actions.append(action("Скачать", item.download_url, "download"));
    root.append(actions);
    return root;
  }
  function syncProtection() {
    for (const link of gallery.querySelectorAll("[data-gallery-download]")) link.hidden = isProtected();
    if (viewer.open) syncDownload();
  }
  document.addEventListener("sovietgram:chat-protection", event => {
    protectedGallery = Boolean(event.detail?.enabled);
    syncProtection();
  });
  async function load(append = false) {
    controller?.abort();
    const mine = ++generation;
    controller = new AbortController();
    const request = controller;
    const url = new URL(chat.dataset.galleryUrl, location.origin);
    url.searchParams.set("kind", kind);
    if (account) url.searchParams.set("account_id", account);
    if (append && before) url.searchParams.set("before", String(before));
    if (!append) {
      items = []; before = null; itemsNode.replaceChildren();
    }
    status.textContent = "Загрузка…";
    more.hidden = true;
    try {
      const response = await fetch(url, {credentials:"same-origin",cache:"no-store",signal:request.signal});
      const payload = await response.json().catch(() => ({}));
      if (!response.ok || payload.ok !== true || String(payload.account_id) !== account) throw new Error(payload.error || "Не удалось загрузить вложения.");
      if (mine !== generation || !gallery.open) return;
      protectedGallery = Boolean(payload.protected);
      for (const tab of tabs) tab.querySelector("small").textContent = String(payload.counts?.[tab.dataset.galleryKind] || 0);
      const seen = new Set(items.map(item => item.id));
      for (const item of payload.items || []) {
        if (seen.has(item.id)) continue;
        seen.add(item.id); items.push(item); itemsNode.append(card(item));
      }
      itemsNode.classList.toggle("is-media", kind === "media" || kind === "stickers");
      status.textContent = items.length ? "" : "В этом разделе пока пусто.";
      before = payload.next_before || null;
      more.textContent = "Показать ещё";
      more.hidden = !before;
      syncProtection();
    } catch (e) {
      if (mine !== generation || e.name === "AbortError" || !gallery.open) return;
      status.textContent = e.message;
      more.textContent = "Повторить загрузку";
      more.hidden = false;
    }
  }
  function selectKind(value) {
    kind = tabs.some(tab => tab.dataset.galleryKind === value) ? value : "media";
    for (const tab of tabs) tab.setAttribute("aria-pressed", String(tab.dataset.galleryKind === kind));
    void load();
  }
  function openGallery(value) {
    const menu = $("chatMenu"); if (menu) menu.hidden = true;
    $("chatMenuButton")?.setAttribute("aria-expanded","false");
    if (!gallery.open) gallery.showModal();
    selectKind(value);
  }
  tabs.forEach(tab => tab.addEventListener("click", () => selectKind(tab.dataset.galleryKind)));
  more.addEventListener("click", () => { void load(Boolean(before)); });
  $("chatGalleryClose").addEventListener("click", () => gallery.close());
  gallery.addEventListener("close", () => {
    generation++; controller?.abort();
    for (const player of gallery.querySelectorAll("audio, video")) player.pause();
  });
  gallery.addEventListener("play", event => {
    if (event.target.tagName === "AUDIO") for (const player of gallery.querySelectorAll("audio")) if (player !== event.target) player.pause();
  }, true);
  document.addEventListener("click", event => {
    const entry = event.target.closest?.("[data-open-gallery]");
    if (entry) { event.preventDefault(); openGallery(entry.dataset.openGallery); return; }
    const trigger = event.target.closest?.(mediaSelector);
    if (!trigger || !mediaData(trigger).url || event.defaultPrevented || window.SovietgramMediaSpoilers?.isHidden(trigger)) return;
    event.preventDefault(); openViewer(trigger);
  });
})();
