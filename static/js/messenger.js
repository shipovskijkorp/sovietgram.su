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

const form = document.getElementById("messageForm");
const messageInput = document.getElementById("messageInput");
const messageFlow = document.getElementById("messageFlow");
const messageStage = document.getElementById("messageStage");
const sendButton = document.getElementById("sendButton");
const enterToSend = document.body.dataset.enterToSend !== "false";

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
const MEDIA_EXTENSIONS = new Set(["png", "jpg", "jpeg", "webp", "gif", "mp4", "webm", "mov", "m4v"]);
const FILE_EXTENSIONS = new Set([...MEDIA_EXTENSIONS, "mp3", "ogg", "wav", "m4a", "flac"]);

let selectedFiles = [];
let selectedMode = "media";
let previewObjectUrls = [];
let appendNextPick = false;
let uploadInProgress = false;
let dragDepth = 0;
let newestMessageId = 0;

function formatBytes(bytes) {
  if (bytes < 1024) return `${bytes} Б`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} КБ`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} МБ`;
}

function fileExtension(file) {
  const parts = file.name.toLowerCase().split(".");
  return parts.length > 1 ? parts.pop() : "";
}

function isMediaFile(file) {
  return file.type.startsWith("image/") || file.type.startsWith("video/");
}

function validateSelection(files, mode) {
  if (!files.length) return "Файлы не выбраны.";
  if (files.length > MAX_ATTACHMENTS) return `За раз можно отправить не больше ${MAX_ATTACHMENTS} файлов.`;

  const allowed = mode === "media" ? MEDIA_EXTENSIONS : FILE_EXTENSIONS;
  let total = 0;
  for (const file of files) {
    if (!allowed.has(fileExtension(file))) {
      return mode === "media"
        ? "В режиме фото и видео поддерживаются PNG, JPEG, WebP, MP4, WebM и MOV."
        : "Как файл можно отправить исходник без обработки.";
    }
    if (mode === "media" && !isMediaFile(file)) {
      return "В режиме фото и видео можно выбрать только изображения и видео.";
    }
    if (file.size > MAX_FILE_SIZE) return `${file.name}: файл больше 25 МБ.`;
    total += file.size;
  }
  if (total > MAX_TOTAL_SIZE) return "Общий размер выбранных файлов больше 100 МБ.";
  return "";
}

function showClientError(text) {
  if (typeof showToast === "function") showToast(text);
}

function setAttachmentMenu(open) {
  if (!attachmentMenu || !attachmentButton) return;
  attachmentMenu.hidden = !open;
  attachmentButton.setAttribute("aria-expanded", String(open));
}

attachmentButton?.addEventListener("click", (event) => {
  event.stopPropagation();
  setAttachmentMenu(attachmentMenu?.hidden ?? true);
});

document.querySelectorAll("[data-attachment-mode]").forEach((button) => {
  button.addEventListener("click", () => {
    setAttachmentMenu(false);
    openFilePicker(button.dataset.attachmentMode || "media", false);
  });
});

document.addEventListener("click", (event) => {
  if (!attachmentControl?.contains(event.target)) setAttachmentMenu(false);
});

function openFilePicker(mode, append) {
  appendNextPick = append;
  const input = mode === "file" ? fileAttachmentsInput : mediaAttachmentsInput;
  input?.click();
}

function pickerChanged(input, mode) {
  const files = [...(input.files || [])];
  input.value = "";
  if (!files.length) {
    appendNextPick = false;
    return;
  }

  const nextFiles = appendNextPick && selectedFiles.length && selectedMode === mode
    ? [...selectedFiles, ...files]
    : files;
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

function pluralFiles(count, media = false) {
  if (media) return count === 1 ? "1 медиафайл" : `${count} медиафайла`;
  if (count % 10 === 1 && count % 100 !== 11) return `${count} файл`;
  if ([2, 3, 4].includes(count % 10) && ![12, 13, 14].includes(count % 100)) return `${count} файла`;
  return `${count} файлов`;
}

function mediaTitle(files, mode) {
  if (mode === "file") return files.length === 1 ? "Отправить файл" : `Отправить ${files.length} файлов`;
  if (files.length > 1) return `Отправить ${files.length} медиа`;
  return files[0]?.type.startsWith("video/") ? "Отправить видео" : "Отправить фото";
}

function renderMediaSelection() {
  if (!mediaComposePreview) return;
  releasePreviewUrls();
  mediaComposePreview.replaceChildren();

  const totalSize = selectedFiles.reduce((sum, file) => sum + file.size, 0);
  if (mediaComposeTitle) mediaComposeTitle.textContent = mediaTitle(selectedFiles, selectedMode);
  if (mediaComposeSummary) mediaComposeSummary.textContent = `${pluralFiles(selectedFiles.length, selectedMode === "media")} · ${formatBytes(totalSize)}`;
  if (mediaComposeHint) {
    mediaComposeHint.textContent = selectedMode === "file"
      ? "Исходники будут отправлены без сжатия и показаны как файлы."
      : "Фото и видео будут показаны прямо в переписке.";
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
        video.src = url;
        video.muted = true;
        video.playsInline = true;
        video.preload = "metadata";
        card.appendChild(video);
        const badge = document.createElement("span");
        badge.className = "media-preview-video-badge";
        badge.textContent = "▶ Видео";
        card.appendChild(badge);
      } else {
        const image = document.createElement("img");
        image.src = url;
        image.alt = file.name;
        card.appendChild(image);
      }

      card.appendChild(makeRemoveButton(index));
      grid.appendChild(card);
    });
    mediaComposePreview.appendChild(grid);
    return;
  }

  const list = document.createElement("div");
  list.className = "media-preview-files";
  selectedFiles.forEach((file, index) => {
    const row = document.createElement("div");
    row.className = "media-preview-file";

    const icon = document.createElement("span");
    icon.className = "media-preview-file__icon";
    icon.textContent = file.type.startsWith("audio/") ? "♫" : "⌑";

    const text = document.createElement("span");
    text.className = "media-preview-file__text";
    const name = document.createElement("strong");
    name.textContent = file.name;
    const meta = document.createElement("small");
    meta.textContent = formatBytes(file.size);
    text.append(name, meta);

    row.append(icon, text, makeRemoveButton(index));
    list.appendChild(row);
  });
  mediaComposePreview.appendChild(list);
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
    if (!selectedFiles.length) {
      closeMediaComposer();
      return;
    }
    renderMediaSelection();
  });
  return button;
}

function autoSizeCaption() {
  if (!mediaComposeCaption) return;
  mediaComposeCaption.style.height = "auto";
  mediaComposeCaption.style.height = `${Math.min(mediaComposeCaption.scrollHeight, 120)}px`;
}

function openMediaComposer(files, mode, preserveCaption = false) {
  const error = validateSelection(files, mode);
  if (error) {
    showClientError(error);
    return;
  }

  const oldCaption = mediaComposeCaption?.value || "";
  selectedFiles = files;
  selectedMode = mode;
  if (attachmentModeInput) attachmentModeInput.value = mode;
  if (mediaComposeGroup && !preserveCaption) mediaComposeGroup.checked = true;
  if (mediaComposeCaption) mediaComposeCaption.value = preserveCaption ? oldCaption : (messageInput?.value || "");
  renderMediaSelection();
  autoSizeCaption();

  if (mediaUploadProgress) mediaUploadProgress.hidden = true;
  if (mediaUploadProgressBar) mediaUploadProgressBar.style.width = "0%";
  if (mediaComposeBackdrop) mediaComposeBackdrop.hidden = false;
  window.setTimeout(() => mediaComposeCaption?.focus(), 0);
}

function closeMediaComposer() {
  if (uploadInProgress) return;
  releasePreviewUrls();
  selectedFiles = [];
  if (mediaComposeBackdrop) mediaComposeBackdrop.hidden = true;
  if (mediaComposeCaption) mediaComposeCaption.value = "";
}

mediaComposeClose?.addEventListener("click", closeMediaComposer);
mediaComposeBackdrop?.addEventListener("click", (event) => {
  if (event.target === mediaComposeBackdrop) closeMediaComposer();
});

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

messageInput?.addEventListener("input", autoSizeInput);
messageInput?.addEventListener("keydown", (event) => {
  if (!shouldSendOnEnter(event)) return;
  event.preventDefault();
  form?.requestSubmit();
});
mediaComposeCaption?.addEventListener("input", autoSizeCaption);
mediaComposeCaption?.addEventListener("keydown", (event) => {
  if (!shouldSendOnEnter(event)) return;
  event.preventDefault();
  mediaComposeSend?.click();
});

document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && mediaComposeBackdrop && !mediaComposeBackdrop.hidden) closeMediaComposer();
});

function nearBottom() {
  if (!messageStage) return true;
  return messageStage.scrollHeight - messageStage.scrollTop - messageStage.clientHeight < 180;
}

function scrollToBottom(force = false) {
  if (!messageStage || (!force && !nearBottom())) return;
  messageStage.scrollTop = messageStage.scrollHeight;
}

function makeFileCard(attachment) {
  const link = document.createElement("a");
  link.className = "message-file-card";
  link.href = attachment.url;
  link.target = "_blank";
  link.rel = "noopener";

  const icon = document.createElement("span");
  icon.className = "message-file-card__icon";
  icon.textContent = "↓";

  const text = document.createElement("span");
  text.className = "message-file-card__text";
  const name = document.createElement("strong");
  name.textContent = attachment.name;
  const size = document.createElement("small");
  size.textContent = formatBytes(attachment.size || 0);
  text.append(name, size);
  link.append(icon, text);
  return link;
}

function makeMedia(attachment) {
  if (attachment.kind === "image") {
    const link = document.createElement("a");
    link.className = "message-media__item";
    link.href = attachment.url;
    link.target = "_blank";
    link.rel = "noopener";
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
    const wrapper = document.createElement("div");
    wrapper.className = "message-media__audio";
    const name = document.createElement("span");
    name.textContent = attachment.name;
    const audio = document.createElement("audio");
    audio.controls = true;
    audio.preload = "metadata";
    audio.src = attachment.url;
    wrapper.append(name, audio);
    return wrapper;
  }

  return makeFileCard(attachment);
}

function renderMessage(message) {
  if (!messageFlow || document.querySelector(`[data-message-id="${message.id}"]`)) return;

  const shouldFollow = nearBottom();
  const article = document.createElement("article");
  article.className = `message ${message.is_own ? "message--outgoing" : "message--incoming"}`;
  article.dataset.messageId = String(message.id);

  if (message.attachments?.length) {
    const media = document.createElement("div");
    media.className = "message-media";
    media.dataset.count = String(message.attachments.length);
    if (message.attachments.length > 1) media.classList.add("message-media--album");
    message.attachments.forEach((attachment) => media.appendChild(makeMedia(attachment)));
    article.appendChild(media);
  }

  if (message.text) {
    const paragraph = document.createElement("p");
    paragraph.className = "message__text";
    paragraph.textContent = message.text;
    article.appendChild(paragraph);
  }

  const footer = document.createElement("footer");
  const time = document.createElement("time");
  time.textContent = message.time;
  footer.appendChild(time);
  if (message.is_own) {
    const check = document.createElement("span");
    check.className = "message-check";
    check.textContent = "✓✓";
    footer.appendChild(check);
  }
  article.appendChild(footer);
  messageFlow.appendChild(article);

  if (shouldFollow) requestAnimationFrame(() => scrollToBottom(true));
}

function formErrorText(payload) {
  const groups = Object.values(payload?.errors || {});
  const first = groups.flat()[0];
  return first?.message || "Не удалось отправить сообщение.";
}

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
    const payload = await response.json();
    if (!response.ok || !payload.ok) throw new Error(formErrorText(payload));

    renderMessage(payload.message);
    newestMessageId = Math.max(newestMessageId, Number(payload.message.id) || 0);
    messageInput.value = "";
    autoSizeInput();
    messageInput.focus();
    scrollToBottom(true);
  } catch (error) {
    showClientError(error.message || "Не удалось отправить сообщение.");
  } finally {
    sendButton.disabled = false;
  }
}

if (form) {
  form.addEventListener("submit", (event) => {
    event.preventDefault();
    sendTextMessage();
  });
}

function setUploadUi(busy, percent = 0) {
  uploadInProgress = busy;
  if (mediaComposeSend) mediaComposeSend.disabled = busy;
  if (mediaComposeAdd) mediaComposeAdd.disabled = busy;
  if (mediaComposeClose) mediaComposeClose.disabled = busy;
  if (mediaUploadProgress) mediaUploadProgress.hidden = !busy;
  if (mediaUploadProgressBar) mediaUploadProgressBar.style.width = `${Math.max(0, Math.min(100, percent))}%`;
  if (mediaComposeSend) mediaComposeSend.textContent = busy ? "Отправка…" : "Отправить";
}

function uploadMediaRequest(files, text, mode, onProgress) {
  return new Promise((resolve, reject) => {
    if (!form) {
      reject(new Error("Форма отправки недоступна."));
      return;
    }

    const data = new FormData();
    const csrf = form.querySelector("[name='csrfmiddlewaretoken']")?.value || "";
    data.append("csrfmiddlewaretoken", csrf);
    data.append("text", text);
    data.append("attachment_mode", mode);
    files.forEach((file) => data.append("attachments", file, file.name));

    const xhr = new XMLHttpRequest();
    xhr.open("POST", form.action);
    xhr.setRequestHeader("X-Requested-With", "XMLHttpRequest");
    xhr.responseType = "json";
    xhr.upload.addEventListener("progress", (event) => {
      if (event.lengthComputable) onProgress(event.loaded, event.total);
    });
    xhr.addEventListener("load", () => {
      const payload = xhr.response || {};
      if (xhr.status >= 200 && xhr.status < 300 && payload.ok) {
        resolve(payload);
      } else {
        reject(new Error(formErrorText(payload)));
      }
    });
    xhr.addEventListener("error", () => reject(new Error("Не удалось загрузить файлы.")));
    xhr.addEventListener("abort", () => reject(new Error("Отправка отменена.")));
    xhr.send(data);
  });
}

async function sendSelectedMedia() {
  if (!selectedFiles.length || uploadInProgress) return;
  const error = validateSelection(selectedFiles, selectedMode);
  if (error) {
    showClientError(error);
    return;
  }

  const files = [...selectedFiles];
  const caption = mediaComposeCaption?.value.trim() || "";
  const sendSeparately = selectedMode === "media" && files.length > 1 && mediaComposeGroup && !mediaComposeGroup.checked;
  const totalBytes = Math.max(1, files.reduce((sum, file) => sum + file.size, 0));
  let uploadedBefore = 0;
  setUploadUi(true, 0);

  try {
    if (sendSeparately) {
      for (let index = 0; index < files.length; index += 1) {
        const file = files[index];
        const payload = await uploadMediaRequest(
          [file],
          index === files.length - 1 ? caption : "",
          "media",
          (loaded) => setUploadUi(true, ((uploadedBefore + loaded) / totalBytes) * 100),
        );
        renderMessage(payload.message);
        newestMessageId = Math.max(newestMessageId, Number(payload.message.id) || 0);
        uploadedBefore += file.size;
      }
    } else {
      const payload = await uploadMediaRequest(
        files,
        caption,
        selectedMode,
        (loaded, total) => setUploadUi(true, total ? (loaded / total) * 100 : 0),
      );
      renderMessage(payload.message);
      newestMessageId = Math.max(newestMessageId, Number(payload.message.id) || 0);
    }

    setUploadUi(false, 100);
    if (messageInput) {
      messageInput.value = "";
      autoSizeInput();
    }
    closeMediaComposer();
    scrollToBottom(true);
    messageInput?.focus();
  } catch (error) {
    setUploadUi(false, 0);
    showClientError(error.message || "Не удалось отправить медиа.");
  }
}

mediaComposeSend?.addEventListener("click", sendSelectedMedia);

function filesFromTransfer(transfer) {
  return [...(transfer?.files || [])].filter((file) => file.size > 0);
}

if (messageStage && chatDropOverlay) {
  document.addEventListener("dragenter", (event) => {
    if (![...(event.dataTransfer?.types || [])].includes("Files")) return;
    dragDepth += 1;
    chatDropOverlay.hidden = false;
  });
  document.addEventListener("dragover", (event) => {
    if (![...(event.dataTransfer?.types || [])].includes("Files")) return;
    event.preventDefault();
    if (event.dataTransfer) event.dataTransfer.dropEffect = "copy";
  });
  document.addEventListener("dragleave", () => {
    dragDepth = Math.max(0, dragDepth - 1);
    if (!dragDepth) chatDropOverlay.hidden = true;
  });
  document.addEventListener("drop", (event) => {
    const files = filesFromTransfer(event.dataTransfer);
    if (!files.length) return;
    event.preventDefault();
    dragDepth = 0;
    chatDropOverlay.hidden = true;
    const mode = files.every(isMediaFile) ? "media" : "file";
    openMediaComposer(files, mode);
  });
}

messageInput?.addEventListener("paste", (event) => {
  const files = filesFromTransfer(event.clipboardData);
  if (!files.length) return;
  event.preventDefault();
  const mode = files.every(isMediaFile) ? "media" : "file";
  openMediaComposer(files, mode);
});

document.querySelectorAll("[data-message-id]").forEach((node) => {
  newestMessageId = Math.max(newestMessageId, Number(node.dataset.messageId) || 0);
});

let pollBusy = false;
async function pollMessages() {
  if (!messageStage?.dataset.pollUrl || pollBusy || document.hidden) return;
  pollBusy = true;
  try {
    const url = new URL(messageStage.dataset.pollUrl, window.location.origin);
    url.searchParams.set("after", String(newestMessageId));
    const response = await fetch(url, { credentials: "same-origin" });
    if (!response.ok) return;
    const payload = await response.json();
    for (const message of payload.messages || []) {
      newestMessageId = Math.max(newestMessageId, Number(message.id) || 0);
      renderMessage(message);
    }
  } finally {
    pollBusy = false;
  }
}

if (messageStage) {
  requestAnimationFrame(() => scrollToBottom(true));
  window.setInterval(pollMessages, 2500);
  document.addEventListener("visibilitychange", () => {
    if (!document.hidden) pollMessages();
  });
}
