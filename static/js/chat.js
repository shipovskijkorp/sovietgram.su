const chatFilter = document.getElementById("chatFilter");
const chatRows = [...document.querySelectorAll("[data-chat-row]")];
const chatFilterEmpty = document.getElementById("chatFilterEmpty");

if (chatFilter) {
  chatFilter.addEventListener("input", () => {
    const query = chatFilter.value.trim().toLowerCase().replace(/^@/, "");
    let visible = 0;
    chatRows.forEach((row) => {
      const matches = !query || (row.dataset.search || "").includes(query);
      row.hidden = !matches;
      if (matches) visible += 1;
    });
    if (chatFilterEmpty) chatFilterEmpty.hidden = visible !== 0 || chatRows.length === 0;
  });
}

const conversation = document.querySelector(".conversation--chat");
const form = document.getElementById("messageForm");
const messageInput = document.getElementById("messageInput");
const messageFlow = document.getElementById("messageFlow");
const messageStage = document.getElementById("messageStage");
const sendButton = document.getElementById("sendButton");
const replyToInput = document.getElementById("replyToInput");
const composerReply = document.getElementById("composerReply");
const composerReplyName = document.getElementById("composerReplyName");
const composerReplyPreview = document.getElementById("composerReplyPreview");
const composerReplyClose = document.getElementById("composerReplyClose");
const enterToSend = document.body.dataset.enterToSend !== "false";
const csrfToken = form?.querySelector("[name='csrfmiddlewaretoken']")?.value || "";

function notify(text) {
  if (typeof showToast === "function") showToast(text);
}

function formatBytes(bytes) {
  if (!bytes) return "0 Б";
  if (bytes < 1024) return `${bytes} Б`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} КБ`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} МБ`;
}

function errorText(payload, fallback = "Не удалось выполнить действие.") {
  if (payload?.error) return payload.error;
  const groups = Object.values(payload?.errors || {});
  const first = groups.flat()[0];
  return first?.message || fallback;
}

async function postForm(url, values = {}) {
  const data = new FormData();
  data.append("csrfmiddlewaretoken", csrfToken);
  Object.entries(values).forEach(([key, value]) => data.append(key, value ?? ""));
  const response = await fetch(url, {
    method: "POST",
    body: data,
    headers: { "X-Requested-With": "XMLHttpRequest" },
    credentials: "same-origin",
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok || payload.ok === false) throw new Error(errorText(payload));
  return payload;
}

function shouldSendOnEnter(event) {
  if (event.key !== "Enter" || event.shiftKey) return false;
  if (event.ctrlKey || event.metaKey) return true;
  return enterToSend;
}

function autoSizeInput() {
  if (!messageInput) return;
  messageInput.style.height = "auto";
  messageInput.style.height = `${Math.min(messageInput.scrollHeight, 132)}px`;
}

autoSizeInput();

function nearBottom() {
  if (!messageStage) return true;
  return messageStage.scrollHeight - messageStage.scrollTop - messageStage.clientHeight < 180;
}

function scrollToBottom(force = false) {
  if (!messageStage || (!force && !nearBottom())) return;
  messageStage.scrollTop = messageStage.scrollHeight;
}

function jumpToMessage(messageId) {
  const node = document.querySelector(`[data-message-id="${messageId}"]`);
  if (!node) {
    const base = conversation?.dataset.chatUrl;
    if (base) window.location.href = `${base}?message=${encodeURIComponent(messageId)}#message-${messageId}`;
    return;
  }
  node.scrollIntoView({ behavior: "smooth", block: "center" });
  node.classList.remove("is-target");
  requestAnimationFrame(() => node.classList.add("is-target"));
  window.setTimeout(() => node.classList.remove("is-target"), 1500);
}

document.addEventListener("click", (event) => {
  const jump = event.target.closest("[data-jump-message]");
  if (!jump) return;
  event.preventDefault();
  jumpToMessage(jump.dataset.jumpMessage);
});

function messagePreview(article) {
  const text = (article?.dataset.messageText || "").trim();
  if (text) return text.replace(/\s+/g, " ").slice(0, 150);
  const fileName = article?.querySelector(".message-file-card strong")?.textContent?.trim();
  if (fileName) return fileName;
  if (article?.querySelector(".message-media")) return "Медиа";
  return "Сообщение";
}

function setReply(article) {
  if (!article || !replyToInput || !composerReply) return;
  replyToInput.value = article.dataset.messageId || "";
  if (composerReplyName) composerReplyName.textContent = article.dataset.messageSender || "Ответ";
  if (composerReplyPreview) composerReplyPreview.textContent = messagePreview(article);
  composerReply.hidden = false;
  messageInput?.focus();
}

function clearReplyState() {
  if (replyToInput) replyToInput.value = "";
  if (composerReply) composerReply.hidden = true;
}

composerReplyClose?.addEventListener("click", clearReplyState);

function linkifyInto(element, text) {
  element.replaceChildren();
  const expression = /(https?:\/\/[^\s]+)/gi;
  let cursor = 0;
  for (const match of text.matchAll(expression)) {
    if (match.index > cursor) element.appendChild(document.createTextNode(text.slice(cursor, match.index)));
    const link = document.createElement("a");
    link.href = match[0];
    link.target = "_blank";
    link.rel = "noopener noreferrer";
    link.textContent = match[0];
    element.appendChild(link);
    cursor = match.index + match[0].length;
  }
  if (cursor < text.length) element.appendChild(document.createTextNode(text.slice(cursor)));
}

function makeFileCard(attachment) {
  const link = document.createElement("a");
  link.className = "message-file-card";
  link.href = attachment.url;

  const icon = document.createElement("span");
  icon.className = "message-file-card__icon";
  icon.textContent = "↓";

  const copy = document.createElement("span");
  copy.className = "message-file-card__text";
  const name = document.createElement("strong");
  name.textContent = attachment.name;
  const size = document.createElement("small");
  size.textContent = formatBytes(attachment.size || 0);
  copy.append(name, size);
  link.append(icon, copy);
  return link;
}

function makeMedia(attachment) {
  if (attachment.kind === "image") {
    const link = document.createElement("a");
    link.className = "message-media__item";
    link.href = attachment.url;
    link.target = "_blank";
    link.rel = "noopener";
    link.dataset.lightboxImage = attachment.url;
    const image = document.createElement("img");
    image.className = "message-media__image";
    image.src = attachment.url;
    image.alt = attachment.name;
    image.loading = "lazy";
    image.addEventListener("load", () => scrollToBottom());
    link.appendChild(image);
    return link;
  }

  if (attachment.kind === "video") {
    const video = document.createElement("video");
    video.className = "message-media__video";
    video.controls = true;
    video.preload = "metadata";
    video.src = attachment.url;
    return video;
  }

  return makeFileCard(attachment);
}

function makeReplyPreview(reply) {
  const button = document.createElement("button");
  button.className = "message-reply-preview";
  button.type = "button";
  button.dataset.jumpMessage = String(reply.id);
  const name = document.createElement("strong");
  name.textContent = reply.sender_name;
  const preview = document.createElement("span");
  preview.textContent = reply.preview;
  button.append(name, preview);
  return button;
}

function makeForwardedBlock(forwarded) {
  const block = document.createElement("div");
  block.className = "message-forwarded";
  const label = document.createElement("span");
  label.textContent = "Переслано от";
  const name = document.createElement("strong");
  name.textContent = forwarded.username ? `${forwarded.name} · @${forwarded.username}` : forwarded.name;
  block.append(label, name);
  return block;
}

function buildMessageArticle(message) {
  const article = document.createElement("article");
  article.id = `message-${message.id}`;
  article.className = `message ${message.is_own ? "message--outgoing" : "message--incoming"}`;
  if (message.is_pinned) article.classList.add("is-pinned");
  article.dataset.messageId = String(message.id);
  article.dataset.messageOwn = String(Boolean(message.is_own));
  article.dataset.messageText = message.text || "";
  article.dataset.messageSender = message.sender_name || "";
  article.dataset.messagePinned = String(Boolean(message.is_pinned));
  article.dataset.editUrl = message.urls?.edit || "";
  article.dataset.deleteUrl = message.urls?.delete || "";
  article.dataset.forwardUrl = message.urls?.forward || "";
  article.dataset.pinUrl = message.urls?.pin || "";

  if (message.forwarded) article.appendChild(makeForwardedBlock(message.forwarded));
  if (message.reply) article.appendChild(makeReplyPreview(message.reply));

  if (message.attachments?.length) {
    const media = document.createElement("div");
    const album = message.attachments.length > 1 && message.attachments.every((item) => item.kind === "image" || item.kind === "video");
    media.className = `message-media${album ? " message-media--album" : ""}`;
    media.dataset.count = String(message.attachments.length);
    message.attachments.forEach((attachment) => media.appendChild(makeMedia(attachment)));
    article.appendChild(media);
  }

  if (message.text) {
    const paragraph = document.createElement("p");
    paragraph.className = "message__text";
    linkifyInto(paragraph, message.text);
    article.appendChild(paragraph);
  }

  const footer = document.createElement("footer");
  if (message.signature_name) {
    const signature = document.createElement("span");
    signature.className = "message-channel-signature";
    signature.textContent = message.signature_name;
    footer.appendChild(signature);
  }
  if (message.is_edited) {
    const edited = document.createElement("span");
    edited.className = "message-edited";
    edited.textContent = "изм.";
    footer.appendChild(edited);
  }
  const time = document.createElement("time");
  time.textContent = message.time;
  footer.appendChild(time);
  if (message.is_own) {
    const check = document.createElement("span");
    check.className = "message-check";
    check.textContent = message.is_read ? "✓✓" : "✓";
    footer.appendChild(check);
  }
  article.appendChild(footer);

  const actions = document.createElement("button");
  actions.className = "message-action-trigger";
  actions.type = "button";
  actions.setAttribute("aria-label", "Действия с сообщением");
  actions.textContent = "⋮";
  article.appendChild(actions);
  return article;
}

function renderMessage(message) {
  if (!messageFlow || message.is_deleted) return;
  if (document.querySelector(`[data-message-id="${message.id}"]`)) {
    applyMessageUpdate(message);
    return;
  }
  const follow = nearBottom();
  messageFlow.appendChild(buildMessageArticle(message));
  if (follow) requestAnimationFrame(() => scrollToBottom(true));
}

function applyMessageUpdate(message) {
  const article = document.querySelector(`[data-message-id="${message.id}"]`);
  if (message.is_deleted) {
    article?.remove();
    if (replyToInput?.value === String(message.id)) clearReplyState();
    return;
  }
  if (!article) {
    renderMessage(message);
    return;
  }

  article.dataset.messageText = message.text || "";
  article.dataset.messagePinned = String(Boolean(message.is_pinned));
  article.classList.toggle("is-pinned", Boolean(message.is_pinned));
  if (message.urls) {
    article.dataset.editUrl = message.urls.edit || article.dataset.editUrl;
    article.dataset.deleteUrl = message.urls.delete || article.dataset.deleteUrl;
    article.dataset.forwardUrl = message.urls.forward || article.dataset.forwardUrl;
    article.dataset.pinUrl = message.urls.pin || article.dataset.pinUrl;
  }

  let paragraph = article.querySelector(".message__text");
  if (message.text) {
    if (!paragraph) {
      paragraph = document.createElement("p");
      paragraph.className = "message__text";
      article.insertBefore(paragraph, article.querySelector("footer"));
    }
    linkifyInto(paragraph, message.text);
  } else {
    paragraph?.remove();
  }

  const footer = article.querySelector("footer");
  let edited = footer?.querySelector(".message-edited");
  if (message.is_edited && footer && !edited) {
    edited = document.createElement("span");
    edited.className = "message-edited";
    edited.textContent = "изм.";
    footer.insertBefore(edited, footer.firstChild);
  } else if (!message.is_edited) {
    edited?.remove();
  }
  const check = footer?.querySelector(".message-check");
  if (check && message.is_own) check.textContent = message.is_read ? "✓✓" : "✓";
}

const contextMenu = document.getElementById("messageContextMenu");
const pinLabel = document.getElementById("messagePinLabel");
let contextArticle = null;

function closeMessageMenu() {
  if (contextMenu) contextMenu.hidden = true;
  contextArticle = null;
}

function openMessageMenu(article, x, y) {
  if (!contextMenu || !article) return;
  contextArticle = article;
  const own = article.dataset.messageOwn === "true";
  const hasText = Boolean((article.dataset.messageText || "").trim());
  const editButton = contextMenu.querySelector('[data-message-action="edit"]');
  const copyButton = contextMenu.querySelector('[data-message-action="copy"]');
  if (editButton) editButton.hidden = !own;
  if (copyButton) copyButton.hidden = !hasText;
  if (pinLabel) pinLabel.textContent = article.dataset.messagePinned === "true" ? "Открепить" : "Закрепить";

  contextMenu.hidden = false;
  const rect = contextMenu.getBoundingClientRect();
  const left = Math.max(6, Math.min(x, window.innerWidth - rect.width - 6));
  const top = Math.max(6, Math.min(y, window.innerHeight - rect.height - 6));
  contextMenu.style.left = `${left}px`;
  contextMenu.style.top = `${top}px`;
}

document.addEventListener("contextmenu", (event) => {
  const article = event.target.closest(".message[data-message-id]");
  if (!article) return;
  event.preventDefault();
  openMessageMenu(article, event.clientX, event.clientY);
});

document.addEventListener("click", (event) => {
  const trigger = event.target.closest(".message-action-trigger");
  if (trigger) {
    event.preventDefault();
    event.stopPropagation();
    const article = trigger.closest(".message[data-message-id]");
    const rect = trigger.getBoundingClientRect();
    openMessageMenu(article, rect.right, rect.bottom + 4);
    return;
  }
  if (contextMenu && !contextMenu.contains(event.target)) closeMessageMenu();
});

async function copyText(text) {
  try {
    await navigator.clipboard.writeText(text);
  } catch (_error) {
    const area = document.createElement("textarea");
    area.value = text;
    area.style.position = "fixed";
    area.style.opacity = "0";
    document.body.appendChild(area);
    area.select();
    document.execCommand("copy");
    area.remove();
  }
}

const editModal = document.getElementById("editMessageModal");
const editText = document.getElementById("editMessageText");
const editSave = document.getElementById("editMessageSave");
let editArticle = null;

function openEditModal(article) {
  if (!editModal || !editText || !article) return;
  editArticle = article;
  editText.value = article.dataset.messageText || "";
  editModal.hidden = false;
  window.setTimeout(() => {
    editText.focus();
    editText.setSelectionRange(editText.value.length, editText.value.length);
  }, 0);
}

function closeEditModal() {
  if (editModal) editModal.hidden = true;
  editArticle = null;
}

document.querySelectorAll("[data-close-edit]").forEach((button) => button.addEventListener("click", closeEditModal));
editModal?.addEventListener("click", (event) => { if (event.target === editModal) closeEditModal(); });

editSave?.addEventListener("click", async () => {
  if (!editArticle?.dataset.editUrl) return;
  editSave.disabled = true;
  try {
    const payload = await postForm(editArticle.dataset.editUrl, { text: editText?.value || "" });
    applyMessageUpdate(payload.message);
    closeEditModal();
  } catch (error) {
    notify(error.message);
  } finally {
    editSave.disabled = false;
  }
});

editText?.addEventListener("keydown", (event) => {
  if ((event.ctrlKey || event.metaKey) && event.key === "Enter") {
    event.preventDefault();
    editSave?.click();
  }
});

const forwardModal = document.getElementById("forwardMessageModal");
const forwardSearch = document.getElementById("forwardTargetSearch");
const forwardTargets = [...document.querySelectorAll("[data-forward-target]")];
let forwardArticle = null;

function openForwardModal(article) {
  if (!forwardModal || !article) return;
  forwardArticle = article;
  forwardModal.hidden = false;
  if (forwardSearch) {
    forwardSearch.value = "";
    forwardTargets.forEach((target) => { target.hidden = false; });
    window.setTimeout(() => forwardSearch.focus(), 0);
  }
}

function closeForwardModal() {
  if (forwardModal) forwardModal.hidden = true;
  forwardArticle = null;
}

document.querySelectorAll("[data-close-forward]").forEach((button) => button.addEventListener("click", closeForwardModal));
forwardModal?.addEventListener("click", (event) => { if (event.target === forwardModal) closeForwardModal(); });
forwardSearch?.addEventListener("input", () => {
  const query = forwardSearch.value.trim().toLowerCase();
  forwardTargets.forEach((target) => {
    target.hidden = Boolean(query) && !(target.dataset.forwardSearch || "").includes(query);
  });
});
forwardTargets.forEach((target) => {
  target.addEventListener("click", async () => {
    if (!forwardArticle?.dataset.forwardUrl) return;
    target.disabled = true;
    try {
      const payload = await postForm(forwardArticle.dataset.forwardUrl, { target_chat_id: target.dataset.forwardTarget || "" });
      if (String(payload.target_chat_id) === String(conversation?.dataset.chatId)) renderMessage(payload.message);
      notify("Сообщение переслано.");
      closeForwardModal();
    } catch (error) {
      notify(error.message);
    } finally {
      target.disabled = false;
    }
  });
});

async function toggleMessagePin(article) {
  if (!article?.dataset.pinUrl) return;
  try {
    const payload = await postForm(article.dataset.pinUrl);
    renderPinnedMessages(payload.pins || []);
  } catch (error) {
    notify(error.message);
  }
}

async function deleteMessage(article) {
  if (!article?.dataset.deleteUrl) return;
  if (!window.confirm("Удалить это сообщение?")) return;
  try {
    const payload = await postForm(article.dataset.deleteUrl);
    applyMessageUpdate(payload.message);
    notify("Сообщение удалено.");
    window.setTimeout(pollMessages, 50);
  } catch (error) {
    notify(error.message);
  }
}

contextMenu?.addEventListener("click", async (event) => {
  const button = event.target.closest("[data-message-action]");
  if (!button || !contextArticle) return;
  const article = contextArticle;
  const action = button.dataset.messageAction;
  closeMessageMenu();
  if (action === "reply") setReply(article);
  if (action === "copy") {
    await copyText(article.dataset.messageText || "");
    notify("Текст скопирован.");
  }
  if (action === "edit") openEditModal(article);
  if (action === "forward") openForwardModal(article);
  if (action === "pin") await toggleMessagePin(article);
  if (action === "delete") await deleteMessage(article);
});

const pinnedBar = document.getElementById("pinnedMessageBar");
const pinnedCount = document.getElementById("pinnedMessageCount");
const pinnedPreview = document.getElementById("pinnedMessagePreview");
let currentPins = [];

function renderPinnedMessages(pins) {
  currentPins = pins || [];
  document.querySelectorAll(".message[data-message-id]").forEach((article) => {
    const pinned = currentPins.some((pin) => String(pin.message_id) === article.dataset.messageId);
    article.dataset.messagePinned = String(pinned);
    article.classList.toggle("is-pinned", pinned);
  });
  if (!pinnedBar) return;
  if (!currentPins.length) {
    pinnedBar.hidden = true;
    pinnedBar.dataset.messageId = "";
    messageStage?.classList.remove("has-pins");
    return;
  }
  const pin = currentPins[0];
  pinnedBar.hidden = false;
  pinnedBar.dataset.messageId = String(pin.message_id);
  if (pinnedCount) pinnedCount.textContent = String(currentPins.length);
  if (pinnedPreview) pinnedPreview.textContent = pin.preview;
  messageStage?.classList.add("has-pins");
}

pinnedBar?.addEventListener("click", () => {
  if (pinnedBar.dataset.messageId) jumpToMessage(pinnedBar.dataset.messageId);
});

const chatMenuButton = document.getElementById("chatMenuButton");
const chatMenu = document.getElementById("chatMenu");
function setChatMenu(open) {
  if (!chatMenu || !chatMenuButton) return;
  chatMenu.hidden = !open;
  chatMenuButton.setAttribute("aria-expanded", String(open));
}
chatMenuButton?.addEventListener("click", (event) => {
  event.stopPropagation();
  setChatMenu(chatMenu?.hidden ?? true);
});
document.addEventListener("click", (event) => {
  if (chatMenu && !chatMenu.contains(event.target) && event.target !== chatMenuButton) setChatMenu(false);
});

const searchToggle = document.getElementById("chatSearchToggle");
const searchPanel = document.getElementById("chatSearchPanel");
const searchInput = document.getElementById("chatSearchInput");
const searchClose = document.getElementById("chatSearchClose");
const searchResults = document.getElementById("chatSearchResults");
let searchTimer;
let searchController;

function setSearchPanel(open) {
  if (!searchPanel) return;
  searchPanel.hidden = !open;
  if (open) window.setTimeout(() => searchInput?.focus(), 0);
}

searchToggle?.addEventListener("click", () => setSearchPanel(searchPanel?.hidden ?? true));
document.querySelector("[data-open-chat-search]")?.addEventListener("click", () => {
  setChatMenu(false);
  setSearchPanel(true);
});
searchClose?.addEventListener("click", () => setSearchPanel(false));

function renderSearchResults(results) {
  if (!searchResults) return;
  searchResults.replaceChildren();
  if (!results.length) {
    const empty = document.createElement("div");
    empty.className = "chat-search-empty";
    empty.textContent = searchInput?.value.trim() ? "Ничего не нашлось." : "Введите текст сообщения или название файла.";
    searchResults.appendChild(empty);
    return;
  }
  results.forEach((result) => {
    const link = document.createElement("a");
    link.className = "chat-search-result";
    link.href = result.url;
    const name = document.createElement("strong");
    name.textContent = result.sender_name;
    const preview = document.createElement("span");
    preview.textContent = result.preview;
    const time = document.createElement("small");
    time.textContent = result.time;
    link.append(name, preview, time);
    link.addEventListener("click", (event) => {
      if (document.querySelector(`[data-message-id="${result.id}"]`)) {
        event.preventDefault();
        setSearchPanel(false);
        jumpToMessage(result.id);
      }
    });
    searchResults.appendChild(link);
  });
}

searchInput?.addEventListener("input", () => {
  clearTimeout(searchTimer);
  const query = searchInput.value.trim();
  if (!query) {
    renderSearchResults([]);
    return;
  }
  searchTimer = window.setTimeout(async () => {
    searchController?.abort();
    searchController = new AbortController();
    try {
      const url = new URL(searchPanel.dataset.searchUrl, window.location.origin);
      url.searchParams.set("q", query);
      const response = await fetch(url, { credentials: "same-origin", signal: searchController.signal });
      if (!response.ok) return;
      const payload = await response.json();
      renderSearchResults(payload.results || []);
    } catch (error) {
      if (error.name !== "AbortError") notify("Поиск временно недоступен.");
    }
  }, 220);
});

const chatInfoBackdrop = document.getElementById("chatInfoBackdrop");
const chatInfoDrawer = document.getElementById("chatInfoDrawer");
const chatInfoClose = document.getElementById("chatInfoClose");
function setChatInfo(open) {
  if (!chatInfoBackdrop || !chatInfoDrawer) return;
  chatInfoBackdrop.hidden = !open;
  chatInfoDrawer.hidden = !open;
}
document.querySelector("[data-open-chat-info]")?.addEventListener("click", () => { setChatMenu(false); setChatInfo(true); });
chatInfoBackdrop?.addEventListener("click", () => setChatInfo(false));
chatInfoClose?.addEventListener("click", () => setChatInfo(false));

const imageViewer = document.getElementById("imageViewer");
const imageViewerImage = document.getElementById("imageViewerImage");
const imageViewerClose = document.getElementById("imageViewerClose");
function closeImageViewer() {
  if (imageViewer) imageViewer.hidden = true;
  if (imageViewerImage) imageViewerImage.src = "";
}
document.addEventListener("click", (event) => {
  const link = event.target.closest("[data-lightbox-image]");
  if (!link || !imageViewer || !imageViewerImage) return;
  event.preventDefault();
  imageViewerImage.src = link.dataset.lightboxImage;
  imageViewer.hidden = false;
});
imageViewer?.addEventListener("click", (event) => { if (event.target === imageViewer) closeImageViewer(); });
imageViewerClose?.addEventListener("click", closeImageViewer);

let draftTimer;
let typingSentAt = 0;
async function saveDraft(text, keepalive = false) {
  if (!messageStage?.dataset.draftUrl) return;
  const data = new FormData();
  data.append("csrfmiddlewaretoken", csrfToken);
  data.append("text", text);
  try {
    await fetch(messageStage.dataset.draftUrl, {
      method: "POST",
      body: data,
      credentials: "same-origin",
      keepalive,
    });
  } catch (_error) {
    // Draft sync is best-effort; the next input event retries it.
  }
}

function scheduleDraftSave() {
  clearTimeout(draftTimer);
  draftTimer = window.setTimeout(() => saveDraft(messageInput?.value || ""), 650);
}

function clearDraftState() {
  clearTimeout(draftTimer);
  saveDraft("");
}

function sendTypingState() {
  if (!messageStage?.dataset.typingUrl || !messageInput?.value.trim()) return;
  const now = Date.now();
  if (now - typingSentAt < 1900) return;
  typingSentAt = now;
  postForm(messageStage.dataset.typingUrl).catch(() => {});
}

messageInput?.addEventListener("input", () => {
  autoSizeInput();
  scheduleDraftSave();
  sendTypingState();
});
messageInput?.addEventListener("keydown", (event) => {
  if (!shouldSendOnEnter(event)) return;
  event.preventDefault();
  form?.requestSubmit();
});
window.addEventListener("beforeunload", () => {
  if (!messageStage?.dataset.draftUrl || !messageInput) return;
  const data = new FormData();
  data.append("csrfmiddlewaretoken", csrfToken);
  data.append("text", messageInput.value);
  navigator.sendBeacon?.(messageStage.dataset.draftUrl, data);
});

async function sendTextMessage() {
  if (!form || !messageInput?.value.trim()) return;
  sendButton.disabled = true;
  const data = new FormData(form);
  data.delete("attachments");
  data.set("attachment_mode", "media");
  try {
    const response = await fetch(form.action, {
      method: "POST",
      body: data,
      headers: { "X-Requested-With": "XMLHttpRequest" },
      credentials: "same-origin",
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok || !payload.ok) throw new Error(errorText(payload, "Не удалось отправить сообщение."));
    renderMessage(payload.message);
    newestMessageId = Math.max(newestMessageId, Number(payload.message.id) || 0);
    messageInput.value = "";
    autoSizeInput();
    clearReplyState();
    clearDraftState();
    messageInput.focus();
    scrollToBottom(true);
  } catch (error) {
    notify(error.message);
  } finally {
    sendButton.disabled = false;
  }
}
form?.addEventListener("submit", (event) => { event.preventDefault(); sendTextMessage(); });

const attachmentControl = document.getElementById("attachmentControl");
const attachmentButton = document.getElementById("attachmentButton");
const attachmentMenu = document.getElementById("attachmentMenu");
const mediaAttachmentsInput = document.getElementById("mediaAttachmentsInput");
const fileAttachmentsInput = document.getElementById("fileAttachmentsInput");
const attachmentModeInput = document.getElementById("attachmentModeInput");
const mediaComposeBackdrop = document.getElementById("mediaComposeBackdrop");
const mediaComposeClose = document.getElementById("mediaComposeClose");
const mediaComposeAdd = document.getElementById("mediaComposeAdd");
const mediaComposeTitle = document.getElementById("mediaComposeTitle");
const mediaComposeSummary = document.getElementById("mediaComposeSummary");
const mediaComposePreview = document.getElementById("mediaComposePreview");
const mediaComposeCaption = document.getElementById("mediaComposeCaption");
const mediaComposeHint = document.getElementById("mediaComposeHint");
const mediaComposeSend = document.getElementById("mediaComposeSend");
const mediaComposeGroupRow = document.getElementById("mediaComposeGroupRow");
const mediaComposeGroup = document.getElementById("mediaComposeGroup");
const mediaUploadProgress = document.getElementById("mediaUploadProgress");
const mediaUploadProgressBar = document.getElementById("mediaUploadProgressBar");
const chatDropOverlay = document.getElementById("chatDropOverlay");

const MAX_ATTACHMENTS = 10;
const MAX_FILE_SIZE = 25 * 1024 * 1024;
const MAX_TOTAL_SIZE = 100 * 1024 * 1024;
const MEDIA_EXTENSIONS = new Set(["png", "jpg", "jpeg", "webp", "mp4", "webm", "mov", "m4v"]);
let selectedFiles = [];
let selectedMode = "media";
let previewObjectUrls = [];
let appendNextPick = false;
let uploadInProgress = false;
let dragDepth = 0;

function fileExtension(file) {
  const parts = file.name.toLowerCase().split(".");
  return parts.length > 1 ? parts.pop() : "";
}
function isGif(file) { return fileExtension(file) === "gif" || file.type.toLowerCase() === "image/gif"; }
function isMediaFile(file) {
  return !isGif(file) && MEDIA_EXTENSIONS.has(fileExtension(file)) && (file.type.startsWith("image/") || file.type.startsWith("video/"));
}
function validateSelection(files, mode) {
  if (!files.length) return "Файлы не выбраны.";
  if (files.length > MAX_ATTACHMENTS) return `За раз можно отправить не больше ${MAX_ATTACHMENTS} файлов.`;
  let total = 0;
  for (const file of files) {
    if (isGif(file)) return "GIF в Stalingram пока отключены.";
    if (mode === "media" && !isMediaFile(file)) return "В режиме фото и видео поддерживаются PNG, JPEG, WebP, MP4, WebM и MOV.";
    if (file.size > MAX_FILE_SIZE) return `${file.name}: файл больше 25 МБ.`;
    total += file.size;
  }
  if (total > MAX_TOTAL_SIZE) return "Общий размер выбранных файлов больше 100 МБ.";
  return "";
}
function setAttachmentMenu(open) {
  if (!attachmentMenu || !attachmentButton) return;
  attachmentMenu.hidden = !open;
  attachmentButton.setAttribute("aria-expanded", String(open));
}
attachmentButton?.addEventListener("click", (event) => { event.stopPropagation(); setAttachmentMenu(attachmentMenu?.hidden ?? true); });
document.querySelectorAll("[data-attachment-mode]").forEach((button) => button.addEventListener("click", () => {
  setAttachmentMenu(false);
  openFilePicker(button.dataset.attachmentMode || "media", false);
}));
document.addEventListener("click", (event) => { if (!attachmentControl?.contains(event.target)) setAttachmentMenu(false); });
function openFilePicker(mode, append) {
  appendNextPick = append;
  (mode === "file" ? fileAttachmentsInput : mediaAttachmentsInput)?.click();
}
function pickerChanged(input, mode) {
  const files = [...(input.files || [])];
  input.value = "";
  if (!files.length) { appendNextPick = false; return; }
  const nextFiles = appendNextPick && selectedFiles.length && selectedMode === mode ? [...selectedFiles, ...files] : files;
  const preserveCaption = appendNextPick && !mediaComposeBackdrop?.hidden;
  appendNextPick = false;
  openMediaComposer(nextFiles, mode, preserveCaption);
}
mediaAttachmentsInput?.addEventListener("change", () => pickerChanged(mediaAttachmentsInput, "media"));
fileAttachmentsInput?.addEventListener("change", () => pickerChanged(fileAttachmentsInput, "file"));
mediaComposeAdd?.addEventListener("click", () => openFilePicker(selectedMode, true));

function releasePreviewUrls() {
  previewObjectUrls.forEach((url) => URL.revokeObjectURL(url));
  previewObjectUrls = [];
}
function pluralFiles(count) {
  if (count % 10 === 1 && count % 100 !== 11) return `${count} файл`;
  if ([2,3,4].includes(count % 10) && ![12,13,14].includes(count % 100)) return `${count} файла`;
  return `${count} файлов`;
}
function mediaTitle(files, mode) {
  if (mode === "file") return files.length === 1 ? "Отправить файл" : `Отправить ${files.length} файлов`;
  if (files.length > 1) return `Отправить ${files.length} медиа`;
  return files[0]?.type.startsWith("video/") ? "Отправить видео" : "Отправить фото";
}
function makeRemoveButton(index) {
  const button = document.createElement("button");
  button.className = "media-preview-remove";
  button.type = "button";
  button.setAttribute("aria-label", "Убрать файл");
  button.textContent = "×";
  button.addEventListener("click", () => {
    if (uploadInProgress) return;
    selectedFiles.splice(index, 1);
    if (!selectedFiles.length) closeMediaComposer(); else renderMediaSelection();
  });
  return button;
}
function renderMediaSelection() {
  if (!mediaComposePreview) return;
  releasePreviewUrls();
  mediaComposePreview.replaceChildren();
  const totalSize = selectedFiles.reduce((sum, file) => sum + file.size, 0);
  if (mediaComposeTitle) mediaComposeTitle.textContent = mediaTitle(selectedFiles, selectedMode);
  if (mediaComposeSummary) mediaComposeSummary.textContent = `${pluralFiles(selectedFiles.length)} · ${formatBytes(totalSize)}`;
  if (mediaComposeHint) mediaComposeHint.textContent = selectedMode === "file" ? "Файлы будут отправлены без обработки." : "Фото и видео будут показаны прямо в переписке.";
  if (mediaComposeGroupRow) mediaComposeGroupRow.hidden = selectedMode !== "media" || selectedFiles.length < 2;

  if (selectedMode === "media") {
    const grid = document.createElement("div");
    grid.className = "media-preview-grid";
    grid.dataset.count = String(selectedFiles.length);
    selectedFiles.forEach((file, index) => {
      const card = document.createElement("div");
      card.className = "media-preview-card";
      const url = URL.createObjectURL(file);
      previewObjectUrls.push(url);
      if (file.type.startsWith("video/")) {
        const video = document.createElement("video");
        video.src = url; video.muted = true; video.playsInline = true; video.preload = "metadata";
        card.appendChild(video);
        const badge = document.createElement("span");
        badge.className = "media-preview-video-badge"; badge.textContent = "▶ Видео"; card.appendChild(badge);
      } else {
        const image = document.createElement("img"); image.src = url; image.alt = file.name; card.appendChild(image);
      }
      card.appendChild(makeRemoveButton(index));
      grid.appendChild(card);
    });
    mediaComposePreview.appendChild(grid);
  } else {
    const list = document.createElement("div");
    list.className = "media-preview-files";
    selectedFiles.forEach((file, index) => {
      const row = document.createElement("div"); row.className = "media-preview-file";
      const icon = document.createElement("span"); icon.className = "media-preview-file__icon"; icon.textContent = "⌑";
      const copy = document.createElement("span"); copy.className = "media-preview-file__text";
      const name = document.createElement("strong"); name.textContent = file.name;
      const meta = document.createElement("small"); meta.textContent = formatBytes(file.size);
      copy.append(name, meta); row.append(icon, copy, makeRemoveButton(index)); list.appendChild(row);
    });
    mediaComposePreview.appendChild(list);
  }
}
function autoSizeCaption() {
  if (!mediaComposeCaption) return;
  mediaComposeCaption.style.height = "auto";
  mediaComposeCaption.style.height = `${Math.min(mediaComposeCaption.scrollHeight, 120)}px`;
}
function openMediaComposer(files, mode, preserveCaption = false) {
  if (conversation?.dataset.canSendMedia === "false") {
    notify("Администраторы запретили участникам отправлять медиа и файлы.");
    return;
  }
  const validationError = validateSelection(files, mode);
  if (validationError) { notify(validationError); return; }
  const oldCaption = mediaComposeCaption?.value || "";
  selectedFiles = files; selectedMode = mode;
  if (attachmentModeInput) attachmentModeInput.value = mode;
  if (mediaComposeGroup && !preserveCaption) mediaComposeGroup.checked = true;
  if (mediaComposeCaption) mediaComposeCaption.value = preserveCaption ? oldCaption : (messageInput?.value || "");
  renderMediaSelection(); autoSizeCaption();
  if (mediaUploadProgress) mediaUploadProgress.hidden = true;
  if (mediaUploadProgressBar) mediaUploadProgressBar.style.width = "0%";
  if (mediaComposeBackdrop) mediaComposeBackdrop.hidden = false;
  window.setTimeout(() => mediaComposeCaption?.focus(), 0);
}
function closeMediaComposer() {
  if (uploadInProgress) return;
  releasePreviewUrls(); selectedFiles = [];
  if (mediaComposeBackdrop) mediaComposeBackdrop.hidden = true;
  if (mediaComposeCaption) mediaComposeCaption.value = "";
}
mediaComposeClose?.addEventListener("click", closeMediaComposer);
mediaComposeBackdrop?.addEventListener("click", (event) => { if (event.target === mediaComposeBackdrop) closeMediaComposer(); });
mediaComposeCaption?.addEventListener("input", autoSizeCaption);
mediaComposeCaption?.addEventListener("keydown", (event) => { if (shouldSendOnEnter(event)) { event.preventDefault(); mediaComposeSend?.click(); } });

function setUploadUi(busy, percent = 0) {
  uploadInProgress = busy;
  if (mediaComposeSend) { mediaComposeSend.disabled = busy; mediaComposeSend.textContent = busy ? "Отправка…" : "Отправить"; }
  if (mediaComposeAdd) mediaComposeAdd.disabled = busy;
  if (mediaComposeClose) mediaComposeClose.disabled = busy;
  if (mediaUploadProgress) mediaUploadProgress.hidden = !busy;
  if (mediaUploadProgressBar) mediaUploadProgressBar.style.width = `${Math.max(0, Math.min(100, percent))}%`;
}
function uploadMediaRequest(files, text, mode, replyTo, onProgress) {
  return new Promise((resolve, reject) => {
    if (!form) { reject(new Error("Форма отправки недоступна.")); return; }
    const data = new FormData();
    data.append("csrfmiddlewaretoken", csrfToken);
    data.append("text", text);
    data.append("attachment_mode", mode);
    if (replyTo) data.append("reply_to", replyTo);
    files.forEach((file) => data.append("attachments", file, file.name));
    const xhr = new XMLHttpRequest();
    xhr.open("POST", form.action);
    xhr.setRequestHeader("X-Requested-With", "XMLHttpRequest");
    xhr.responseType = "json";
    xhr.upload.addEventListener("progress", (event) => { if (event.lengthComputable) onProgress(event.loaded, event.total); });
    xhr.addEventListener("load", () => {
      const payload = xhr.response || {};
      if (xhr.status >= 200 && xhr.status < 300 && payload.ok) resolve(payload);
      else reject(new Error(errorText(payload, "Не удалось отправить файлы.")));
    });
    xhr.addEventListener("error", () => reject(new Error("Не удалось загрузить файлы.")));
    xhr.send(data);
  });
}
async function sendSelectedMedia() {
  if (!selectedFiles.length || uploadInProgress) return;
  const validationError = validateSelection(selectedFiles, selectedMode);
  if (validationError) { notify(validationError); return; }
  const files = [...selectedFiles];
  const caption = mediaComposeCaption?.value.trim() || "";
  const replyId = replyToInput?.value || "";
  const separately = selectedMode === "media" && files.length > 1 && mediaComposeGroup && !mediaComposeGroup.checked;
  const totalBytes = Math.max(1, files.reduce((sum, file) => sum + file.size, 0));
  let uploadedBefore = 0;
  setUploadUi(true, 0);
  try {
    if (separately) {
      for (let index = 0; index < files.length; index += 1) {
        const file = files[index];
        const payload = await uploadMediaRequest(
          [file], index === files.length - 1 ? caption : "", "media", index === 0 ? replyId : "",
          (loaded) => setUploadUi(true, ((uploadedBefore + loaded) / totalBytes) * 100),
        );
        renderMessage(payload.message);
        newestMessageId = Math.max(newestMessageId, Number(payload.message.id) || 0);
        uploadedBefore += file.size;
      }
    } else {
      const payload = await uploadMediaRequest(files, caption, selectedMode, replyId, (loaded, total) => setUploadUi(true, total ? (loaded / total) * 100 : 0));
      renderMessage(payload.message);
      newestMessageId = Math.max(newestMessageId, Number(payload.message.id) || 0);
    }
    setUploadUi(false, 100);
    if (messageInput) { messageInput.value = ""; autoSizeInput(); }
    clearReplyState(); clearDraftState(); closeMediaComposer(); scrollToBottom(true); messageInput?.focus();
  } catch (error) {
    setUploadUi(false, 0); notify(error.message);
  }
}
mediaComposeSend?.addEventListener("click", sendSelectedMedia);

function filesFromTransfer(transfer) { return [...(transfer?.files || [])].filter((file) => file.size > 0); }
if (messageStage && chatDropOverlay) {
  document.addEventListener("dragenter", (event) => {
    if (![...(event.dataTransfer?.types || [])].includes("Files")) return;
    dragDepth += 1; chatDropOverlay.hidden = false;
  });
  document.addEventListener("dragover", (event) => {
    if (![...(event.dataTransfer?.types || [])].includes("Files")) return;
    event.preventDefault(); if (event.dataTransfer) event.dataTransfer.dropEffect = "copy";
  });
  document.addEventListener("dragleave", () => { dragDepth = Math.max(0, dragDepth - 1); if (!dragDepth) chatDropOverlay.hidden = true; });
  document.addEventListener("drop", (event) => {
    const files = filesFromTransfer(event.dataTransfer); if (!files.length) return;
    event.preventDefault(); dragDepth = 0; chatDropOverlay.hidden = true;
    openMediaComposer(files, files.every(isMediaFile) ? "media" : "file");
  });
}
messageInput?.addEventListener("paste", (event) => {
  const files = filesFromTransfer(event.clipboardData); if (!files.length) return;
  event.preventDefault(); openMediaComposer(files, files.every(isMediaFile) ? "media" : "file");
});

function updateReadReceipts(lastReadId) {
  const value = Number(lastReadId) || 0;
  document.querySelectorAll('.message[data-message-own="true"]').forEach((article) => {
    const check = article.querySelector(".message-check");
    if (check) check.textContent = Number(article.dataset.messageId) <= value ? "✓✓" : "✓";
  });
}
const conversationStatus = document.getElementById("conversationStatus");
function updateConversationStatus(typing, status) {
  if (!conversationStatus) return;
  conversationStatus.textContent = typing ? "печатает…" : (status || conversationStatus.textContent);
  conversationStatus.classList.toggle("is-typing", Boolean(typing));
}

let newestMessageId = 0;
document.querySelectorAll("[data-message-id]").forEach((node) => { newestMessageId = Math.max(newestMessageId, Number(node.dataset.messageId) || 0); });
let newestUpdateAt = messageStage?.dataset.serverTime || new Date().toISOString();
let pollBusy = false;
async function pollMessages() {
  if (!messageStage?.dataset.pollUrl || pollBusy || document.hidden) return;
  pollBusy = true;
  try {
    const url = new URL(messageStage.dataset.pollUrl, window.location.origin);
    url.searchParams.set("after", String(newestMessageId));
    url.searchParams.set("since", newestUpdateAt);
    const response = await fetch(url, { credentials: "same-origin" });
    if (!response.ok) return;
    const payload = await response.json();
    for (const message of payload.messages || []) renderMessage(message);
    for (const message of payload.updates || []) applyMessageUpdate(message);
    newestMessageId = Math.max(newestMessageId, Number(payload.high_watermark) || 0, ...(payload.messages || []).map((item) => Number(item.id) || 0));
    updateReadReceipts(payload.other_last_read_id);
    updateConversationStatus(payload.other_typing, payload.other_status);
    renderPinnedMessages(payload.pins || []);
    newestUpdateAt = payload.server_time || newestUpdateAt;
  } catch (_error) {
    // The next polling cycle retries silently.
  } finally {
    pollBusy = false;
  }
}

if (messageStage) {
  requestAnimationFrame(() => {
    scrollToBottom(true);
    const focus = messageStage.dataset.focusMessage;
    if (focus) jumpToMessage(focus);
  });
  window.setInterval(pollMessages, 2200);
  document.addEventListener("visibilitychange", () => { if (!document.hidden) pollMessages(); });
  window.setTimeout(pollMessages, 300);
}

document.addEventListener("keydown", (event) => {
  if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "f" && conversation) {
    event.preventDefault(); setSearchPanel(true); return;
  }
  if (event.key !== "Escape") return;
  if (imageViewer && !imageViewer.hidden) { closeImageViewer(); return; }
  if (editModal && !editModal.hidden) { closeEditModal(); return; }
  if (forwardModal && !forwardModal.hidden) { closeForwardModal(); return; }
  if (mediaComposeBackdrop && !mediaComposeBackdrop.hidden) { closeMediaComposer(); return; }
  if (chatInfoDrawer && !chatInfoDrawer.hidden) { setChatInfo(false); return; }
  if (searchPanel && !searchPanel.hidden) { setSearchPanel(false); return; }
  closeMessageMenu(); setChatMenu(false);
});
