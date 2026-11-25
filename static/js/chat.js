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
function enterToSendEnabled() {
  return document.body.dataset.enterToSend !== "false";
}
const csrfToken = form?.querySelector("[name='csrfmiddlewaretoken']")?.value
  || document.querySelector("#settingsAjaxForm [name='csrfmiddlewaretoken']")?.value
  || document.querySelector("[name='csrfmiddlewaretoken']")?.value || "";

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
  const transport = values.client_message_id ? window.SovietgramSendRetry.fetchSend : fetch;
  const response = await transport(url, {
    method: "POST",
    body: data,
    headers: { "X-Requested-With": "XMLHttpRequest" },
    credentials: "same-origin",
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok || payload.ok === false || (values.client_message_id && payload.ok !== true)) throw new Error(errorText(payload));
  return payload;
}

function shouldSendOnEnter(event) {
  if (event.key !== "Enter" || event.shiftKey) return false;
  if (event.ctrlKey || event.metaKey) return true;
  return enterToSendEnabled();
}

const TELEGRAM_COMPOSER_MIN_HEIGHT = 28;
const TELEGRAM_COMPOSER_MAX_HEIGHT = 224;
const TELEGRAM_COMPOSER_FIELD_CHROME = 16; // 7px top/bottom padding + 1px borders.

function autoSizeInput() {
  if (!messageInput) return;

  // Telegram Desktop grows the *visible compose field*, not just its internal
  // text document. Measure from the one-line height every time so deleting
  // text shrinks the field again.
  messageInput.style.height = `${TELEGRAM_COMPOSER_MIN_HEIGHT}px`;
  messageInput.style.overflowY = "hidden";

  const contentHeight = Math.max(
    TELEGRAM_COMPOSER_MIN_HEIGHT,
    messageInput.scrollHeight,
  );
  const textHeight = Math.min(
    contentHeight,
    TELEGRAM_COMPOSER_MAX_HEIGHT,
  );

  messageInput.style.height = `${textHeight}px`;
  messageInput.style.overflowY = contentHeight > TELEGRAM_COMPOSER_MAX_HEIGHT
    ? "auto"
    : "hidden";

  const field = messageInput.closest(".composer__field");
  if (field) {
    const fieldHeight = textHeight + TELEGRAM_COMPOSER_FIELD_CHROME;
    field.style.height = `${fieldHeight}px`;
    field.style.maxHeight = `${TELEGRAM_COMPOSER_MAX_HEIGHT + TELEGRAM_COMPOSER_FIELD_CHROME}px`;
  }

  const composer = messageInput.closest(".composer");
  if (composer) {
    composer.classList.toggle(
      "composer--multiline",
      textHeight > TELEGRAM_COMPOSER_MIN_HEIGHT,
    );
  }
}

function focusMessageInput() {
  if (!messageInput || messageInput.disabled || messageInput.readOnly) return;

  const focus = () => {
    if (!messageInput.isConnected) return;
    try {
      messageInput.focus({ preventScroll: true });
    } catch (_error) {
      messageInput.focus();
    }
    const caret = messageInput.value.length;
    try {
      messageInput.setSelectionRange(caret, caret);
    } catch (_error) {
      // Some browsers can reject selection during transient focus changes.
    }
  };

  // Match Telegram's behaviour: the compose field owns keyboard focus again
  // after the send action and after the UI has finished updating.
  focus();
  window.requestAnimationFrame(focus);
}

autoSizeInput();

window.addEventListener("resize", autoSizeInput);
window.addEventListener("orientationchange", () => {
  window.requestAnimationFrame(autoSizeInput);
});

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
  if (article?.querySelector("[data-voice-player]")) return "Голосовое сообщение";
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

function linkifyInto(element, text, markdownHtml) {
  window.SovietgramSocial.renderText(element, text, markdownHtml);
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

function makeVoiceMessage(attachment, isOwn = false) {
  const root = document.createElement("div");
  root.className = "voice-message";
  root.dataset.voicePlayer = "";
  root.dataset.src = attachment.url || "";
  root.dataset.markPlayedUrl = attachment.mark_played_url || "";
  root.dataset.durationMs = String(Number(attachment.duration_ms) || 0);
  root.dataset.waveform = Array.isArray(attachment.waveform)
    ? attachment.waveform.join(",")
    : "";
  root.dataset.own = isOwn ? "true" : "false";
  root.dataset.listened = attachment.listened ? "true" : "false";

  const play = document.createElement("button");
  play.type = "button";
  play.className = "voice-message__play";
  play.dataset.voicePlay = "";
  play.setAttribute("aria-label", "Воспроизвести голосовое сообщение");
  const glyph = document.createElement("span");
  glyph.className = "voice-message__play-glyph";
  glyph.setAttribute("aria-hidden", "true");
  play.appendChild(glyph);

  const body = document.createElement("div");
  body.className = "voice-message__body";
  const waveform = document.createElement("div");
  waveform.className = "voice-message__waveform";
  waveform.dataset.voiceWaveform = "";
  waveform.tabIndex = 0;
  waveform.setAttribute("role", "slider");
  waveform.setAttribute("aria-label", "Позиция воспроизведения");
  waveform.setAttribute("aria-valuemin", "0");
  waveform.setAttribute("aria-valuemax", "100");
  waveform.setAttribute("aria-valuenow", "0");

  const meta = document.createElement("div");
  meta.className = "voice-message__time";
  const current = document.createElement("span");
  current.dataset.voiceCurrent = "";
  current.textContent = "0:00";
  const duration = document.createElement("span");
  duration.className = "voice-message__duration";
  duration.dataset.voiceDuration = "";
  duration.textContent = "0:00";
  const unread = document.createElement("span");
  unread.className = "voice-message__unread";
  unread.dataset.voiceUnread = "";
  unread.setAttribute("aria-label", "Не прослушано");
  unread.hidden = Boolean(attachment.listened);
  meta.append(current, duration, unread);
  body.append(waveform, meta);

  const speed = document.createElement("button");
  speed.type = "button";
  speed.className = "voice-message__speed";
  speed.dataset.voiceSettings = "";
  speed.setAttribute("aria-label", "Настройки воспроизведения");
  speed.textContent = "1×";

  const audio = document.createElement("audio");
  audio.dataset.voiceAudio = "";
  audio.preload = "metadata";
  audio.src = attachment.url || "";

  root.append(play, body, speed, audio);
  return root;
}

function makeMedia(attachment, isOwn = false) {
  if (attachment.kind === "sticker") {
    const node = document.createElement("div");
    node.className = "message-sticker";
    const image = document.createElement("img");
    image.src = attachment.url;
    image.alt = "Стикер";
    image.loading = "lazy";
    node.appendChild(image);
    if (!conversation?.classList.contains("is-content-protected")) {
      const button = document.createElement("button");
      button.type = "button";
      button.dataset.saveSticker = String(attachment.id);
      button.textContent = "+";
      button.title = "Сохранить стикер в набор";
      button.setAttribute("aria-label", "Сохранить стикер");
      node.appendChild(button);
    }
    return node;
  }
  if (attachment.kind === "voice") {
    return makeVoiceMessage(attachment, isOwn);
  }

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

  if (attachment.kind === "audio") {
    const audio = document.createElement("div");
    audio.className = "message-audio";
    const icon = document.createElement("span");
    icon.className = "message-audio__icon";
    icon.textContent = "♪";
    const copy = document.createElement("span");
    copy.className = "message-audio__copy";
    const name = document.createElement("strong");
    name.textContent = attachment.name;
    const size = document.createElement("small");
    size.textContent = formatBytes(attachment.size || 0);
    copy.append(name, size);
    const player = document.createElement("audio");
    player.controls = true;
    player.preload = "metadata";
    player.src = attachment.url;
    audio.append(icon, copy, player);
    return audio;
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

  if (forwarded.username && forwarded.profile_url) {
    const link = document.createElement("a");
    link.href = forwarded.profile_url;
    link.dataset.userProfile = "";
    link.appendChild(name);
    block.append(label, link);
  } else {
    block.append(label, name);
  }
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
  article.dataset.messageKind = message.special?.type || "";
  article.dataset.messageSender = message.sender_name || "";
  article.dataset.messagePinned = String(Boolean(message.is_pinned));
  article.dataset.editUrl = message.urls?.edit || "";
  article.dataset.deleteUrl = message.urls?.delete || "";
  article.dataset.forwardUrl = message.urls?.forward || "";
  article.dataset.pinUrl = message.urls?.pin || "";
  article.dataset.reactionUrl = message.urls?.reaction || "";

  if (message.forwarded) article.appendChild(makeForwardedBlock(message.forwarded));
  if (message.reply) article.appendChild(makeReplyPreview(message.reply));

  if (message.special && typeof window.buildSovietgramSpecialMessage === "function") {
    const special = window.buildSovietgramSpecialMessage(message.special);
    if (special) article.appendChild(special);
  }

  if (message.attachments?.length) {
    const media = document.createElement("div");
    const album = message.attachments.length > 1 && message.attachments.every((item) => item.kind === "image" || item.kind === "video");
    media.className = `message-media${album ? " message-media--album" : ""}`;
    media.dataset.count = String(message.attachments.length);
    message.attachments.forEach((attachment) => media.appendChild(makeMedia(attachment, message.is_own)));
    article.appendChild(media);
  }

  if (message.text && !message.special) {
    const paragraph = document.createElement("div");
    paragraph.className = "message__text markdown-body";
    linkifyInto(paragraph, message.text, message.markdown_html);
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
    footer.appendChild(window.SovietgramReadReceipt.create(message.is_read));
  }
  article.appendChild(footer);
  window.SovietgramSocial.renderReactions(article, message);

  const actions = document.createElement("button");
  actions.className = "message-action-trigger";
  actions.type = "button";
  actions.setAttribute("aria-label", "Действия с сообщением");
  actions.textContent = "⋮";
  article.appendChild(actions);
  return article;
}

function renderMessage(message) {
  if (!messageFlow || !message || message.is_deleted) return;
  if (document.querySelector(`[data-message-id="${message.id}"]`)) {
    applyMessageUpdate(message);
    return;
  }
  if (historyHasNewer && !pollRendering) {
    // Sending from a historical window must not create an artificial gap.
    if (message.is_own) void loadLatestHistory();
    return;
  }
  const follow = !pollRendering && !historyHasNewer && nearBottom();
  const article = buildMessageArticle(message);
  const next = Array.from(messageFlow.querySelectorAll(".message[data-message-id]"))
    .find(node => Number(node.dataset.messageId) > Number(message.id));
  messageFlow.insertBefore(article, next || document.getElementById("historyNewerControls"));
  window.SovietgramVoice?.hydrate?.(article);
  if (follow) requestAnimationFrame(() => scrollToBottom(true));
  scheduleReadCheck();
}

function syncMessageAttachments(article, message) {
  if (!article) return;

  const current = article.querySelector(".message-media");
  const attachments = Array.isArray(message.attachments) ? message.attachments : [];

  if (!attachments.length) {
    current?.remove();
    return;
  }

  const media = document.createElement("div");
  const album = (
    attachments.length > 1
    && attachments.every((item) => item.kind === "image" || item.kind === "video")
  );
  media.className = `message-media${album ? " message-media--album" : ""}`;
  media.dataset.count = String(attachments.length);
  attachments.forEach((attachment) => {
    media.appendChild(makeMedia(attachment, message.is_own));
  });

  if (current) {
    current.replaceWith(media);
  } else {
    const before = article.querySelector(".message__text") || article.querySelector("footer");
    article.insertBefore(media, before);
  }

  window.SovietgramVoice?.hydrate?.(media);
}

function applyMessageUpdate(message) {
  const article = document.querySelector(`[data-message-id="${message.id}"]`);
  if (message.is_deleted) {
    article?.remove();
    if (replyToInput?.value === String(message.id)) clearReplyState();
    return;
  }
  // Updates can refer to unloaded pages; do not insert a distant old
  // message into the currently loaded, contiguous history window.
  if (!article) return;

  article.dataset.messageText = message.text || "";
  article.dataset.messageKind = message.special?.type || "";
  article.dataset.messagePinned = String(Boolean(message.is_pinned));
  article.classList.toggle("is-pinned", Boolean(message.is_pinned));
  if (message.urls) {
    article.dataset.editUrl = message.urls.edit || article.dataset.editUrl;
    article.dataset.deleteUrl = message.urls.delete || article.dataset.deleteUrl;
    article.dataset.forwardUrl = message.urls.forward || article.dataset.forwardUrl;
    article.dataset.pinUrl = message.urls.pin || article.dataset.pinUrl;
    article.dataset.reactionUrl = message.urls.reaction || article.dataset.reactionUrl;
  }
  window.SovietgramSocial.renderReactions(article, message);

  let special = article.querySelector("[data-special-message]");
  if (message.special && typeof window.buildSovietgramSpecialMessage === "function") {
    const replacement = window.buildSovietgramSpecialMessage(message.special);
    if (special && replacement) special.replaceWith(replacement);
    else if (!special && replacement) article.insertBefore(replacement, article.querySelector("footer"));
  } else {
    special?.remove();
  }

  syncMessageAttachments(article, message);

  let paragraph = article.querySelector(".message__text");
  if (message.text && !message.special) {
    if (!paragraph) {
      paragraph = document.createElement("div");
      paragraph.className = "message__text markdown-body";
      article.insertBefore(paragraph, article.querySelector("[data-message-reactions]") || article.querySelector("footer"));
    }
    linkifyInto(paragraph, message.text, message.markdown_html);
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
  if (check && message.is_own) window.SovietgramReadReceipt.set(check, message.is_read);
}

// Export the renderer immediately after it is defined. Voice/media uploads must
// not depend on the rest of this large file reaching its final lines.
window.renderSovietgramChatMessage = renderMessage;
window.updateSovietgramChatMessage = applyMessageUpdate;
document.addEventListener("sovietgram:message-sent", (event) => {
  const message = event.detail?.message;
  if (!message) return;
  renderMessage(message);
  const article = document.querySelector(`[data-message-id="${message.id}"]`);
  if (article) {
    window.SovietgramVoice?.hydrate?.(article);
    requestAnimationFrame(() => scrollToBottom(true));
  }
});

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
  const forwardButton = contextMenu.querySelector('[data-message-action="forward"]');
  const contentProtected = document.querySelector(".conversation--chat")?.dataset.chatProtected === "true";
  if (editButton) editButton.hidden = !own || Boolean(article.dataset.messageKind);
  if (copyButton) copyButton.hidden = contentProtected || !hasText;
  if (forwardButton) forwardButton.hidden = contentProtected;
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
  if (action === "forward") document.dispatchEvent(new CustomEvent("sovietgram:forward-message", {detail:{article}}));
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

chatMenu?.querySelector("[data-open-community-settings]")?.addEventListener("click", async () => {
  setChatMenu(false);
  if (typeof window.openCommunitySettings === "function") {
    await window.openCommunitySettings();
    return;
  }
  if (typeof window.openCommunityProfile === "function") {
    await window.openCommunityProfile();
    document.getElementById("communityProfileSettingsOpen")?.click();
  }
});

chatMenu?.querySelectorAll("form[data-confirm-form]").forEach((formNode) => {
  formNode.addEventListener("submit", (event) => {
    const text = formNode.dataset.confirmForm || "";
    if (text && !window.confirm(text)) {
      event.preventDefault();
      return;
    }
    setChatMenu(false);
  });
});

chatMenu?.querySelectorAll("form:not([data-confirm-form])").forEach((formNode) => {
  formNode.addEventListener("submit", () => setChatMenu(false));
});

document.addEventListener("keydown", (event) => {
  if (event.key !== "Escape") return;
  if (chatMenu && !chatMenu.hidden) setChatMenu(false);
});

const searchToggle = document.getElementById("chatSearchToggle");
const searchPanel = document.getElementById("chatSearchPanel");
const searchInput = document.getElementById("chatSearchInput");
const searchClose = document.getElementById("chatSearchClose");
const searchResults = document.getElementById("chatSearchResults");
let searchTimer;
let searchController;
let searchGeneration = 0;
let searchItems = [];
let searchBefore = null;
const searchFilters = ["chatSearchSender", "chatSearchKind", "chatSearchFrom", "chatSearchTo"]
  .map(id => document.getElementById(id)).filter(Boolean);
function chatSearchParams() {
  const params = new URLSearchParams();
  if (searchInput?.value.trim()) params.set("q", searchInput.value.trim());
  for (const field of searchFilters) {
    if (field.value.trim()) params.set(field.name, field.value.trim());
  }
  return params;
}

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
    empty.textContent = chatSearchParams().size ? "Ничего не нашлось." : "Введите текст, название файла или выберите фильтры.";
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
  if (searchBefore) {
    const more = document.createElement("button");
    more.type = "button";
    more.className = "chat-search-more";
    more.textContent = "Показать ещё";
    more.addEventListener("click", async () => {
      more.disabled = true;
      await runChatSearch(searchGeneration, true);
      if (more.isConnected) more.disabled = false;
    });
    searchResults.appendChild(more);
  }
}

async function runChatSearch(generation, append = false) {
  const params = chatSearchParams();
  if (!params.size || generation !== searchGeneration) return;
  if (append && searchBefore) params.set("before", String(searchBefore));
  const controller = new AbortController();
  searchController = controller;
  try {
    const url = new URL(searchPanel.dataset.searchUrl, window.location.origin);
    for (const [key, value] of params) url.searchParams.set(key, value);
    const response = await fetch(url, { credentials: "same-origin", signal: controller.signal });
    const payload = await response.json().catch(() => ({}));
    if (generation !== searchGeneration || controller.signal.aborted) return;
    if (!response.ok || !payload.ok) throw new Error(payload.error || "Поиск временно недоступен.");
    const offset = searchResults.scrollTop;
    const items = payload.results || [];
    searchItems = append ? [...searchItems, ...items.filter(item => !searchItems.some(old => old.id === item.id))] : items;
    searchBefore = payload.next_before || null;
    renderSearchResults(searchItems);
    if (append) searchResults.scrollTop = offset;
  } catch (error) {
    if (error.name !== "AbortError" && generation === searchGeneration) notify(error.message);
  }
}

function restartChatSearch() {
  clearTimeout(searchTimer);
  searchController?.abort();
  const generation = ++searchGeneration;
  searchItems = [];
  searchBefore = null;
  if (!chatSearchParams().size) {
    renderSearchResults([]);
    return;
  }
  searchResults.replaceChildren();
  const waiting = document.createElement("div");
  waiting.className = "chat-search-empty";
  waiting.textContent = "Поиск…";
  searchResults.appendChild(waiting);
  searchTimer = window.setTimeout(() => runChatSearch(generation), 220);
}
searchInput?.addEventListener("input", restartChatSearch);
for (const field of searchFilters) {
  field.addEventListener(field.tagName === "SELECT" || field.type === "date" ? "change" : "input", restartChatSearch);
}
document.getElementById("chatSearchReset")?.addEventListener("click", () => {
  searchFilters.forEach(field => { field.value = ""; });
  restartChatSearch();
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
  data.append("account_id", messageStage.dataset.accountId);
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
  data.append("account_id", messageStage.dataset.accountId);
  navigator.sendBeacon?.(messageStage.dataset.draftUrl, data);
});

const pendingTextList = document.getElementById("pendingTextMessages");
const queueScope = "sovietgram.outbox.v1." + (messageStage?.dataset.accountId || "") + "." + (conversation?.dataset.chatId || "");
let textOutbox = null;

function renderPendingText(items, saved = true) {
  if (!pendingTextList) return;
  const follow = !historyHasNewer && nearBottom();
  pendingTextList.replaceChildren();
  pendingTextList.hidden = !items.length;
  if (!items.length) return;
  const caption = document.createElement("small");
  caption.className = "pending-text-caption";
  caption.textContent = saved ? "Исходящие · очередь этой вкладки" : "Исходящие · хранение недоступно, не закрывайте вкладку";
  pendingTextList.appendChild(caption);
  for (const item of items) {
    const card = document.createElement("article");
    card.className = "pending-text-card";
    const body = document.createElement("div");
    body.className = "pending-text-body";
    body.textContent = item.text;
    const footer = document.createElement("div");
    footer.className = "pending-text-footer";
    const status = document.createElement("span");
    const time = new Date(item.createdAt).toLocaleTimeString([], {hour:"2-digit", minute:"2-digit"});
    status.textContent = time + " · " + (item.state === "sending" ? "Отправляется…" :
      item.state === "failed" ? "Ошибка: " + item.error :
      item.error ? "Ожидает повторной отправки" : "Ожидает отправки");
    status.title = item.error || "";
    if (item.silent) status.textContent += " · Без звука";
    footer.appendChild(status);
    if (item.state !== "sending") {
      const again = document.createElement("button");
      again.type = "button"; again.textContent = "Повторить";
      again.addEventListener("click", () => { textOutbox.retryItem(item.id); void flushTextOutbox(); });
      const cancel = document.createElement("button");
      cancel.type = "button"; cancel.textContent = "Убрать";
      cancel.addEventListener("click", () => {
        if (item.attempts && !window.confirm("Прекратить повторные попытки? Уже принятое сервером сообщение не удалится.")) return;
        textOutbox.discard(item.id); void flushTextOutbox();
      });
      footer.append(again, cancel);
    }
    card.append(body, footer);
    pendingTextList.appendChild(card);
  }
  if (follow) requestAnimationFrame(() => scrollToBottom(true));
}

async function transmitQueuedText(item) {
  const data = new FormData();
  data.set("csrfmiddlewaretoken", form?.querySelector("[name='csrfmiddlewaretoken']")?.value || csrfToken);
  data.set("account_id", messageStage.dataset.accountId);
  data.set("client_message_id", item.id);
  data.set("text", item.text);
  data.set("reply_to", item.reply);
  data.set("attachment_mode", "media");
  data.set("preserve_draft", "1");
  if (item.silent) data.set("silent", "1");
  const controller = new AbortController();
  const timer = window.setTimeout(() => controller.abort(), 15000);
  try {
    const response = await fetch(form.action, {
      method: "POST", body: data, credentials: "same-origin", signal: controller.signal,
      headers: {"X-Requested-With": "XMLHttpRequest"},
    });
    const payload = await response.json().catch(() => ({}));
    if (response.ok && payload.ok && payload.message) {
      window.SovietgramConnection?.success();
      return payload;
    }
    if (response.status >= 500 || response.status === 429) {
      if (response.status >= 500) window.SovietgramConnection?.failure();
      const delay = Math.max(0, Number(response.headers.get("Retry-After")) || 0) * 1000;
      return {retry: true, delay, error: errorText(payload, "Сервер временно недоступен")};
    }
    if (response.redirected || (response.ok && !payload.ok))
      return {error: "Сессия истекла или аккаунт изменился. Обновите страницу."};
    return {error: errorText(payload, "Сообщение не принято сервером")};
  } catch (_) {
    window.SovietgramConnection?.failure();
    return {retry: true, error: "Нет ответа сервера"};
  } finally { window.clearTimeout(timer); }
}

async function flushTextOutbox() {
  if (!textOutbox || !form || messageInput?.readOnly || document.hidden || !navigator.onLine) return;
  // Continue in order until the first blocked item or temporary failure.
  while (await textOutbox.flush()) {
    if (document.hidden || !navigator.onLine) break;
  }
}

async function sendTextMessage(silent = false) {
  if (!form || !messageInput?.value.trim() || messageInput.readOnly || !textOutbox) return;
  if (!textOutbox.enqueue(messageInput.value, replyToInput?.value || "", silent)) {
    notify("Очередь заполнена (20 сообщений). Повторите или удалите ожидающие сообщения.");
    return;
  }
  messageInput.value = "";
  messageInput.dispatchEvent(new Event("input", {bubbles:true}));
  autoSizeInput();
  clearReplyState();
  clearDraftState();
  focusMessageInput();
  void flushTextOutbox();
}

form?.addEventListener("submit", (event) => { event.preventDefault(); sendTextMessage(); });

sendButton?.addEventListener("mousedown", (event) => {
  // Clicking Telegram's send control does not transfer typing focus away from
  // the compose field. Keep the same behaviour in the web client.
  event.preventDefault();
});

const attachmentControl = document.getElementById("attachmentControl");
const attachmentButton = document.getElementById("attachmentButton");
const attachmentMenu = document.getElementById("attachmentMenu");
const mediaAttachmentsInput = document.getElementById("mediaAttachmentsInput");
const fileAttachmentsInput = document.getElementById("fileAttachmentsInput");
const audioAttachmentsInput = document.getElementById("audioAttachmentsInput");
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
const MEDIA_EXTENSIONS = new Set(["png", "jpg", "jpeg", "webp", "gif", "mp4", "webm", "mov", "m4v"]);
const AUDIO_EXTENSIONS = new Set(["mp3", "m4a", "aac", "ogg", "oga", "wav", "flac", "opus"]);
let selectedFiles = [];
let selectedMode = "media";
let previewObjectUrls = [];
let appendNextPick = false;
let uploadInProgress = false;
const legacyMediaKeys = window.SovietgramSendRetry.batch();
let dragDepth = 0;

function fileExtension(file) {
  const parts = file.name.toLowerCase().split(".");
  return parts.length > 1 ? parts.pop() : "";
}
function isMediaFile(file) {
  const type = (file.type || "").toLowerCase();
  return MEDIA_EXTENSIONS.has(fileExtension(file)) && (!type || type.startsWith("image/") || type.startsWith("video/"));
}
function validateSelection(files, mode) {
  if (!files.length) return "Файлы не выбраны.";
  if (files.length > MAX_ATTACHMENTS) return `За раз можно отправить не больше ${MAX_ATTACHMENTS} файлов.`;
  let total = 0;
  for (const file of files) {
    if (mode === "media" && !isMediaFile(file)) return "В режиме фото и видео поддерживаются PNG, JPEG, WebP, GIF, MP4, WebM и MOV.";
    if (mode === "audio" && !(file.type.startsWith("audio/") || AUDIO_EXTENSIONS.has(fileExtension(file)))) {
      return "В разделе «Музыка» поддерживаются MP3, M4A, AAC, OGG, WAV, FLAC и OPUS.";
    }
    if (file.size > MAX_FILE_SIZE) return `${file.name}: файл больше 25 МБ.`;
    total += file.size;
  }
  if (total > MAX_TOTAL_SIZE) return "Общий размер выбранных файлов больше 100 МБ.";
  return "";
}
document.querySelectorAll("[data-attachment-mode]").forEach((button) => button.addEventListener("click", () => {
  window.SovietgramAttachmentMenu?.close();
  openFilePicker(button.dataset.attachmentMode || "media", false);
}));

function openFilePicker(mode, append) {
  appendNextPick = append;
  const input = mode === "file"
    ? fileAttachmentsInput
    : mode === "audio"
      ? audioAttachmentsInput
      : mediaAttachmentsInput;
  input?.click();
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
audioAttachmentsInput?.addEventListener("change", () => pickerChanged(audioAttachmentsInput, "audio"));
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
  if (mode === "audio") return files.length === 1 ? "Отправить музыку" : `Отправить треки: ${files.length}`;
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
  if (mediaComposeHint) {
    mediaComposeHint.textContent = selectedMode === "file"
      ? "Файлы будут отправлены без обработки."
      : selectedMode === "audio"
        ? "Аудио будет отправлено как музыка с встроенным проигрывателем."
        : "Фото, GIF и видео будут показаны прямо в переписке.";
  }
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
      const icon = document.createElement("span"); icon.className = "media-preview-file__icon"; icon.textContent = selectedMode === "audio" ? "♪" : "⌑";
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
  if (!preserveCaption && document.getElementById("mediaComposeSilent")) document.getElementById("mediaComposeSilent").checked = false;
  if (mediaComposeCaption) mediaComposeCaption.value = preserveCaption ? oldCaption : (messageInput?.value || "");
  renderMediaSelection(); autoSizeCaption();
  if (mediaUploadProgress) mediaUploadProgress.hidden = true;
  if (mediaUploadProgressBar) mediaUploadProgressBar.style.width = "0%";
  if (mediaComposeBackdrop) mediaComposeBackdrop.hidden = false;
  window.setTimeout(() => mediaComposeCaption?.focus(), 0);
}
function closeMediaComposer() {
  if (uploadInProgress) return;
  legacyMediaKeys.clear();
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
  const silentToggle = document.getElementById("mediaComposeSilent");
  if (silentToggle) silentToggle.disabled = busy;
  if (mediaUploadProgress) mediaUploadProgress.hidden = !busy;
  if (mediaUploadProgressBar) mediaUploadProgressBar.style.width = `${Math.max(0, Math.min(100, percent))}%`;
}
function uploadMediaRequest(files, text, mode, replyTo, onProgress, clientId, silent = false) {
  return new Promise((resolve, reject) => {
    if (!form) { reject(new Error("Форма отправки недоступна.")); return; }
    const data = new FormData();
    data.append("csrfmiddlewaretoken", csrfToken);
    data.append("text", text);
    data.append("attachment_mode", mode);
    data.append("client_message_id", clientId);
    if (silent) data.append("silent", "1");
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
  const caption = mediaComposeCaption?.value || "";
  const replyId = replyToInput?.value || "";
  const separately = selectedMode === "media" && files.length > 1 && mediaComposeGroup && !mediaComposeGroup.checked;
  const totalBytes = Math.max(1, files.reduce((sum, file) => sum + file.size, 0));
  let uploadedBefore = 0;
  const silent = Boolean(document.getElementById("mediaComposeSilent")?.checked);
  const signature = [files.map(window.SovietgramSendRetry.fileIdentity), caption, selectedMode, replyId, separately, silent];
  setUploadUi(true, 0);
  try {
    if (separately) {
      for (let index = 0; index < files.length; index += 1) {
        const file = files[index];
        const payload = await uploadMediaRequest(
          [file], index === files.length - 1 ? caption : "", "media", index === 0 ? replyId : "",
          (loaded) => setUploadUi(true, ((uploadedBefore + loaded) / totalBytes) * 100),
          legacyMediaKeys.key(index, signature), silent,
        );
        renderMessage(payload.message);
        uploadedBefore += file.size;
      }
    } else {
      const payload = await uploadMediaRequest(files, caption, selectedMode, replyId, (loaded, total) => setUploadUi(true, total ? (loaded / total) * 100 : 0), legacyMediaKeys.key("album", signature), silent);
      renderMessage(payload.message);
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
    if (check) window.SovietgramReadReceipt.set(check, Number(article.dataset.messageId) <= value);
  });
}
const conversationStatus = document.getElementById("conversationStatus");
function localConversationPresence(status, isExact, lastSeenAt, isOnline) {
  // profile.js is included by base.html before this script.
  if (!isExact || typeof formatProfileLastSeen !== "function") return status;
  return formatProfileLastSeen({
    status,
    last_seen_exact: true,
    last_seen_at: lastSeenAt || "",
    is_online: Boolean(isOnline),
  });
}
if (conversationStatus?.dataset.presenceExact === "true") {
  conversationStatus.textContent = localConversationPresence(
    conversationStatus.textContent,
    true,
    conversationStatus.dataset.lastSeenAt,
    conversationStatus.dataset.isOnline === "true",
  );
}
function updateConversationStatus(typing, status, presence = null) {
  if (!conversationStatus) return;
  const localized = presence ? localConversationPresence(
    status,
    presence.other_last_seen_exact,
    presence.other_last_seen_at,
    presence.other_is_online,
  ) : status;
  const names = Array.isArray(presence?.typing_names) ? presence.typing_names : [];
  const typingLabel = names.length ? names.join(", ") + (names.length === 1 ? " печатает…" : " печатают…") : "печатает…";
  conversationStatus.textContent = typing ? typingLabel : (localized || conversationStatus.textContent);
  conversationStatus.classList.toggle("is-typing", Boolean(typing));
}

function updateLiveChatIdentity(payload) {
  if (!payload || Number(payload.chat_id) !== Number(conversation?.dataset.chatId)) return;
  const avatarSync = window.SovietgramAvatarSync;
  const header = document.querySelector(".conversation-header__identity");
  const headerName = header?.querySelector(".conversation-header__text strong");
  const info = document.getElementById("chatInfoDrawer");
  const infoName = info?.querySelector(".chat-info-identity h2");

  if (payload.chat_type === "private" && payload.other_user_id != null) {
    avatarSync?.updateUser(
      payload.other_user_id,
      payload.other_user_avatar_url || "",
      payload.other_user_initials || "?",
    );
    const displayName = payload.other_user_display_name || payload.chat_title || "";
    if (headerName) headerName.textContent = displayName;
    if (infoName) infoName.textContent = displayName;
    if (conversation) {
      conversation.dataset.chatPeerName = displayName;
      conversation.dataset.chatTitle = displayName;
    }
    if (payload.other_user_profile_url) {
      header?.setAttribute("href", payload.other_user_profile_url);
      info?.querySelector("[data-user-profile]")?.setAttribute(
        "href", payload.other_user_profile_url,
      );
    }
    const infoUsername = info?.querySelector(".chat-info-identity p");
    if (infoUsername && payload.other_user_username) {
      infoUsername.textContent = "@" + payload.other_user_username;
    }
    return;
  }

  avatarSync?.updateChat(
    payload.chat_id,
    payload.chat_avatar_url || "",
    payload.chat_avatar_text || "?",
  );
  const title = payload.chat_title || "";
  if (headerName) headerName.textContent = title;
  if (infoName) infoName.textContent = title;
  if (conversation) conversation.dataset.chatTitle = title;
  const infoMeta = info?.querySelector(".chat-info-identity p");
  if (infoMeta && payload.chat_type !== "private") {
    infoMeta.textContent = payload.chat_username
      ? "@" + payload.chat_username + " · " + (payload.other_status || "")
      : (payload.other_status || "");
  }
}

// The loaded window is contiguous. Only server history/poll responses may
// advance its cursor, never an optimistic send acknowledgement.
const historyOlderButton = document.getElementById("historyOlder");
const historyNewerControls = document.getElementById("historyNewerControls");
const historyNewerButton = document.getElementById("historyNewer");
const historyLatestButton = document.getElementById("historyLatest");
const dialogStart = messageFlow?.querySelector(".dialog-start");
const historyStorageKey = "sovietgram.scroll." + (messageStage?.dataset.accountId || "") + "." + (conversation?.dataset.chatId || "");
const historyNodes = () => Array.from(messageFlow?.querySelectorAll(".message[data-message-id]") || []);
const nodeId = node => Number(node?.dataset.messageId) || 0;
let historyHasOlder = messageStage?.dataset.historyOlder === "true";
let historyHasNewer = messageStage?.dataset.historyNewer === "true";
let historyBusy = false;
let historyInitialized = false;
let pendingLatest = false;
let historyGeneration = 0;
let newestMessageId = nodeId(historyNodes().at(-1));
let newestUpdateAt = messageStage?.dataset.serverTime || new Date().toISOString();
let newestUpdateId = 0;
let reactionCursorAt = newestUpdateAt;
let reactionCursorId = 0;
let pollBusy = false;
let pollRendering = false;
// Rotate over mounted messages, not the entire chat history. Bounded requests
// recover even hard deletes and per-user visibility changes missed offline.
let knownMessageCursor = 0;
function knownMessageBatch() {
  const ids = historyNodes().map(nodeId).filter(id => Number.isSafeInteger(id) && id > 0).sort((a,b) => a-b);
  const next = ids.filter(id => id > knownMessageCursor);
  return (next.length ? next : ids).slice(0, 100);
}
let scrollTimer = 0;

function updateHistoryControls() {
  if (historyOlderButton) {
    historyOlderButton.hidden = !historyHasOlder;
    historyOlderButton.disabled = historyBusy;
  }
  if (dialogStart) dialogStart.hidden = historyHasOlder;
  if (historyNewerControls) historyNewerControls.hidden = !historyHasNewer;
  if (historyNewerButton) historyNewerButton.disabled = historyBusy;
  if (historyLatestButton) historyLatestButton.disabled = historyBusy;
}

function visibleAnchor() {
  if (!messageStage) return null;
  const bounds = messageStage.getBoundingClientRect();
  const node = historyNodes().find(item => {
    const rect = item.getBoundingClientRect();
    return rect.bottom > bounds.top && rect.top < bounds.bottom;
  });
  return node ? { id: nodeId(node), offset: node.getBoundingClientRect().top - bounds.top } : null;
}

function restoreAnchor(anchor) {
  if (!anchor || !messageStage) return false;
  const nodes = historyNodes();
  const node = nodes.find(item => nodeId(item) === anchor.id)
    || nodes.find(item => nodeId(item) > anchor.id) || nodes.at(-1);
  if (!node) return false;
  const actual = node.getBoundingClientRect().top - messageStage.getBoundingClientRect().top;
  messageStage.scrollTop += actual - anchor.offset;
  return true;
}

function storeScrollPosition() {
  if (!historyInitialized || !messageStage) return;
  const distance = messageStage.scrollHeight - messageStage.scrollTop - messageStage.clientHeight;
  const anchor = visibleAnchor();
  try {
    if (!historyHasNewer && distance < 36) {
      localStorage.setItem(historyStorageKey, JSON.stringify({ bottom: true }));
    } else if (anchor) {
      localStorage.setItem(historyStorageKey, JSON.stringify(anchor));
    }
  } catch (_error) {}
}

function scheduleReadCheck() {
  window.SovietgramReadAck?.schedule();
}

function insertHistoryMessages(items, replaceWindow = false) {
  if (replaceWindow) historyNodes().forEach(node => node.remove());
  // Insert only new nodes. Reparenting mounted media would interrupt playback.
  const existing = new Map(historyNodes().map(node => [nodeId(node), node]));
  const mounted = Array.from(existing.values());
  const fragment = document.createDocumentFragment();
  let cursor = 0;
  for (const message of items) {
    const id = Number(message.id);
    if (message.is_deleted || existing.has(id)) continue;
    while (cursor < mounted.length && nodeId(mounted[cursor]) < id) {
      if (fragment.childNodes.length) messageFlow.insertBefore(fragment, mounted[cursor]);
      cursor += 1;
    }
    const article = buildMessageArticle(message);
    existing.set(id, article);
    fragment.appendChild(article);
  }
  if (fragment.childNodes.length) messageFlow.insertBefore(fragment, mounted[cursor] || historyNewerControls);
  window.SovietgramVoice?.hydrate?.(messageFlow);
}

async function fetchHistory(params) {
  const url = new URL(messageStage.dataset.historyUrl, window.location.origin);
  for (const [key, value] of Object.entries(params)) url.searchParams.set(key, String(value));
  const response = await fetch(url, { credentials: "same-origin", cache: "no-store" });
  const payload = await response.json();
  if (!response.ok || !payload.ok) throw new Error(payload.error || "Не удалось загрузить историю.");
  return payload;
}

async function loadHistoryPage(direction) {
  if (historyBusy || !historyInitialized || !messageStage?.dataset.historyUrl) return;
  if (direction === "before" && !historyHasOlder) return;
  if (direction === "after" && !historyHasNewer) return;
  const nodes = historyNodes();
  const cursor = nodeId(direction === "before" ? nodes[0] : nodes.at(-1));
  if (!cursor) return;
  historyBusy = true;
  if (messageStage) messageStage.dataset.readHistoryBusy = "true";
  historyGeneration += 1; // Ignore any poll started before this window changes.
  updateHistoryControls();
  try {
    const payload = await fetchHistory({ [direction]: cursor });
    const anchor = visibleAnchor();
    insertHistoryMessages(payload.messages || []);
    if (direction === "before") {
      historyHasOlder = Boolean(payload.has_older);
    } else {
      historyHasNewer = Boolean(payload.has_newer);
      newestMessageId = Math.max(newestMessageId, nodeId(historyNodes().at(-1)));
    }
    window.SovietgramReadAck?.observeCursor(payload.own_last_read_id);
    updateHistoryControls();
    restoreAnchor(anchor);
  } catch (error) {
    notify(error.message || "Не удалось загрузить историю. Повторите.");
  } finally {
    historyBusy = false;
    if (messageStage) messageStage.dataset.readHistoryBusy = "false";
    updateHistoryControls();
    scheduleReadCheck();
    if (pendingLatest) { pendingLatest = false; void loadLatestHistory(); }
  }
}

async function replaceHistoryWindow(params, anchor = null) {
  if (historyBusy || !messageStage?.dataset.historyUrl) return false;
  historyBusy = true;
  if (messageStage) messageStage.dataset.readHistoryBusy = "true";
  historyGeneration += 1;
  updateHistoryControls();
  try {
    const payload = await fetchHistory(params);
    insertHistoryMessages(payload.messages || [], true);
    historyHasOlder = Boolean(payload.has_older);
    historyHasNewer = Boolean(payload.has_newer);
    newestMessageId = nodeId(historyNodes().at(-1));
    newestUpdateAt = payload.server_time || new Date().toISOString();
    newestUpdateId = 0;
    reactionCursorAt = newestUpdateAt;
    reactionCursorId = 0;
    window.SovietgramReadAck?.observeCursor(payload.own_last_read_id);
    updateReadReceipts(payload.other_last_read_id);
    updateHistoryControls();
    if (!anchor || !restoreAnchor(anchor)) scrollToBottom(true);
    return true;
  } catch (error) {
    notify(error.message || "Не удалось восстановить историю.");
    return false;
  } finally {
    historyBusy = false;
    if (messageStage) messageStage.dataset.readHistoryBusy = "false";
    updateHistoryControls();
    scheduleReadCheck();
    if (pendingLatest) { pendingLatest = false; void loadLatestHistory(); }
  }
}

async function loadLatestHistory() {
  if (historyBusy) { pendingLatest = true; return; }
  if (await replaceHistoryWindow({})) {
    scrollToBottom(true);
    storeScrollPosition();
    scheduleReadCheck();
  }
}

function onHistoryScroll() {
  if (!historyInitialized || historyBusy) return;
  scheduleReadCheck();
  clearTimeout(scrollTimer);
  scrollTimer = window.setTimeout(() => {
    storeScrollPosition();
    if (!messageStage || historyBusy) return;
    if (messageStage.scrollTop < 180 && historyHasOlder) void loadHistoryPage("before");
    else if (historyHasNewer && nearBottom()) void loadHistoryPage("after");
  }, 140);
}

async function initializeHistory() {
  updateHistoryControls();
  const focus = Number(messageStage.dataset.focusMessage) || 0;
  const unread = Number(messageStage.dataset.unreadAnchor) || 0;
  let saved = null;
  try { saved = JSON.parse(localStorage.getItem(historyStorageKey) || "null"); } catch (_error) {}
  if (focus) {
    const node = historyNodes().find(item => nodeId(item) === focus);
    if (node) {
      node.scrollIntoView({ block: "center" });
      node.classList.add("is-target");
      window.setTimeout(() => node.classList.remove("is-target"), 1500);
    }
  } else if (saved && !saved.bottom && Number.isSafeInteger(saved.id) && Number.isFinite(saved.offset)) {
    if (!historyNodes().some(item => nodeId(item) === saved.id)) {
      await replaceHistoryWindow({ around: saved.id }, saved);
    } else {
      restoreAnchor(saved);
    }
  } else if (unread) {
    // Even with a previous bottom position, open at the first unread message.
    restoreAnchor({ id: unread, offset: 12 });
  } else {
    scrollToBottom(true);
  }
  historyInitialized = true;
  scheduleReadCheck();
  void pollMessages();
  if (textOutbox) {
    renderPendingText(textOutbox.snapshot(), textOutbox.saved);
    void flushTextOutbox();
  }
}

async function pollMessages() {
  if (!messageStage?.dataset.pollUrl || pollBusy || document.hidden || !historyInitialized || historyBusy) return;
  pollBusy = true;
  const generation = historyGeneration;
  try {
    const url = new URL(messageStage.dataset.pollUrl, window.location.origin);
    const knownIds = knownMessageBatch();
    if (knownIds.length) url.searchParams.set("known_ids", knownIds.join(","));
    if (messageStage.dataset.accountId) url.searchParams.set("account_id", messageStage.dataset.accountId);
    url.searchParams.set("after", String(newestMessageId));
    url.searchParams.set("since", newestUpdateAt);
    url.searchParams.set("after_update_id", String(newestUpdateId));
    url.searchParams.set("reaction_since", reactionCursorAt);
    url.searchParams.set("reaction_after_id", String(reactionCursorId));
    if (historyHasNewer) url.searchParams.set("skip_new", "1");
    const response = await fetch(url, { credentials: "same-origin", cache: "no-store" });
    if (generation !== historyGeneration) return;
    if (response.status === 404 || response.status === 409) {
      // Membership/chat may have been removed or another tab switched accounts.
      window.location.assign("/");
      return;
    }
    if (!response.ok) {
      if (response.status >= 500) window.SovietgramConnection?.failure();
      return;
    }
    const payload = await response.json();
    if (generation !== historyGeneration) return;
    if (!payload.ok) return;
    window.SovietgramConnection?.success();
    knownMessageCursor = knownIds.at(-1) || 0;
    document.dispatchEvent(new CustomEvent("sovietgram:chat-protection", {
      detail: { enabled: Boolean(payload.protect_content) },
    }));
    document.dispatchEvent(new CustomEvent("sovietgram:chat-mute-state", {
      detail: { isMuted: Boolean(payload.is_muted), mutedUntil: payload.muted_until || "" },
    }));
    pollRendering = true;
    const follow = !historyHasNewer && nearBottom();
    const anchor = follow ? null : visibleAnchor();
    for (const message of payload.messages || []) renderMessage(message);
    for (const message of payload.updates || []) applyMessageUpdate(message);
    const requestedIds = new Set(knownIds);
    for (const id of payload.removed_ids || []) {
      if (requestedIds.has(Number(id))) applyMessageUpdate({id: Number(id), is_deleted: true});
    }
    if (!historyNodes().length && (historyHasOlder || historyHasNewer)) {
      // A whole mounted window can disappear after remote history clearing.
      // Reload the latest visible page so pagination cannot get stuck.
      void loadLatestHistory();
      return;
    }
    for (const update of payload.reaction_updates || []) {
      const article = historyNodes().find(node => nodeId(node) === Number(update.message_id));
      if (article) window.SovietgramSocial.renderReactions(article, update);
    }
    reactionCursorAt = payload.reaction_cursor_time || reactionCursorAt;
    reactionCursorId = Number(payload.reaction_cursor_id) || 0;
    if (!historyHasNewer) newestMessageId = Math.max(newestMessageId, Number(payload.high_watermark) || 0);
    window.SovietgramReadAck?.observeCursor(payload.own_last_read_id);
    updateReadReceipts(payload.other_last_read_id);
    updateLiveChatIdentity(payload);
    updateConversationStatus(payload.other_typing, payload.other_status, payload);
    renderPinnedMessages(payload.pins || []);
    newestUpdateAt = payload.updates_cursor_time || payload.server_time || newestUpdateAt;
    newestUpdateId = Number(payload.updates_cursor_id) || 0;
    if (follow) scrollToBottom(true);
    else if (anchor) restoreAnchor(anchor);
    scheduleReadCheck();
  } catch (_error) {
    window.SovietgramConnection?.failure();
    // The next polling cycle retries.
  } finally {
    pollRendering = false;
    pollBusy = false;
    // Read acknowledgement must not depend on a successful poll/render.
    scheduleReadCheck();
  }
}

if (messageStage) {
  if (pendingTextList && messageStage.dataset.accountId && conversation?.dataset.chatId) {
    let storage;
    try { storage = window.sessionStorage; } catch (_) { storage = null; }
    textOutbox = window.SovietgramSendRetry.createOutbox({
      storage, key: queueScope, send: transmitQueuedText, changed: renderPendingText,
      delivered(payload) {
        renderMessage(payload.message);
        void window.SovietgramSidebar?.refresh();
      },
    });
    window.setInterval(flushTextOutbox, 2000);
    window.addEventListener("online", () => { void flushTextOutbox(); });
    window.addEventListener("focus", () => { void flushTextOutbox(); });
    document.addEventListener("visibilitychange", () => { if (!document.hidden) void flushTextOutbox(); });
  }
  historyOlderButton?.addEventListener("click", () => loadHistoryPage("before"));
  historyNewerButton?.addEventListener("click", () => loadHistoryPage("after"));
  historyLatestButton?.addEventListener("click", loadLatestHistory);
  messageStage.addEventListener("scroll", onHistoryScroll, { passive: true });
  window.addEventListener("pagehide", storeScrollPosition);
  window.addEventListener("focus", () => { scheduleReadCheck(); void pollMessages(); });
  window.addEventListener("resize", scheduleReadCheck);
  document.addEventListener("visibilitychange", () => {
    if (!document.hidden) { scheduleReadCheck(); void pollMessages(); }
  });
  window.addEventListener("online", () => { scheduleReadCheck(); void pollMessages(); });
  // Wait until attachment-special.js has installed its renderer.
  window.requestAnimationFrame(initializeHistory);
  window.setInterval(pollMessages, 2200);
}

document.addEventListener("keydown", (event) => {
  if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "f" && conversation) {
    event.preventDefault(); setSearchPanel(true); return;
  }
  if (event.key !== "Escape") return;
  if (imageViewer && !imageViewer.hidden) { closeImageViewer(); return; }
  if (editModal && !editModal.hidden) { closeEditModal(); return; }

  if (mediaComposeBackdrop && !mediaComposeBackdrop.hidden) { closeMediaComposer(); return; }
  if (chatInfoDrawer && !chatInfoDrawer.hidden) { setChatInfo(false); return; }
  if (searchPanel && !searchPanel.hidden) { setSearchPanel(false); return; }
  closeMessageMenu(); setChatMenu(false);
});


window.renderSovietgramChatMessage = renderMessage;
window.updateSovietgramChatMessage = applyMessageUpdate;
window.SovietgramChat = {
  acceptSentMessage(message) {
    if (!message) return false;

    renderMessage(message);

    // A message may have been inserted by polling a fraction earlier than the
    // upload response. In that case renderMessage() routes through the update
    // path, which must also synchronize attachments such as voice players.
    const article = document.querySelector(`[data-message-id="${message.id}"]`);
    if (!article) {
      // Do not advance the high-water mark when the DOM insert failed. The
      // next poll then remains able to recover the just-sent message.
      window.setTimeout(pollMessages, 0);
      return false;
    }

    applyMessageUpdate(message);
    window.SovietgramVoice?.hydrate?.(article);

    if (messageInput) {
      messageInput.value = "";
      messageInput.dispatchEvent(new Event("input", { bubbles: true }));
      autoSizeInput();
    }
    clearReplyState();
    clearDraftState();
    focusMessageInput();
    if (!historyHasNewer) requestAnimationFrame(() => scrollToBottom(true));
    return true;
  },
  syncNow: pollMessages,
  sendSilently: () => sendTextMessage(true),
  clearScheduledDraft(originalText, originalReply) {
    if (!messageInput || messageInput.value !== originalText ||
        (replyToInput?.value || "") !== originalReply) return;
    messageInput.value = "";
    messageInput.dispatchEvent(new Event("input", { bubbles: true }));
    autoSizeInput();
    clearReplyState();
    clearDraftState();
  },
  focusComposer: focusMessageInput,
  resizeComposer: autoSizeInput,
};
