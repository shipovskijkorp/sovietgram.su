(() => {
  const conversation = document.querySelector(".conversation--chat");
  const form = document.getElementById("messageForm");
  if (!conversation || !form) return;

  const inputs = {
    media: document.getElementById("mediaAttachmentsInput"),
    file: document.getElementById("fileAttachmentsInput"),
    audio: document.getElementById("audioAttachmentsInput"),
  };
  const modeInput = document.getElementById("attachmentModeInput");
  const backdrop = document.getElementById("mediaComposeBackdrop");
  const closeButton = document.getElementById("mediaComposeClose");
  const addButton = document.getElementById("mediaComposeAdd");
  const titleNode = document.getElementById("mediaComposeTitle");
  const summaryNode = document.getElementById("mediaComposeSummary");
  const previewNode = document.getElementById("mediaComposePreview");
  const captionNode = document.getElementById("mediaComposeCaption");
  const hintNode = document.getElementById("mediaComposeHint");
  const sendButton = document.getElementById("mediaComposeSend");
  const groupRow = document.getElementById("mediaComposeGroupRow");
  const groupToggle = document.getElementById("mediaComposeGroup");
  const progressNode = document.getElementById("mediaUploadProgress");
  const progressBar = document.getElementById("mediaUploadProgressBar");
  const messageInput = document.getElementById("messageInput");
  const replyInput = document.getElementById("replyToInput");
  const composerReply = document.getElementById("composerReply");
  const csrfToken = form.querySelector("[name='csrfmiddlewaretoken']")?.value || "";

  const MAX_ATTACHMENTS = 10;
  const MAX_FILE_SIZE = 25 * 1024 * 1024;
  const MAX_TOTAL_SIZE = 100 * 1024 * 1024;
  const MEDIA_EXTENSIONS = new Set(["png","jpg","jpeg","webp","mp4","webm","mov","m4v"]);
  const AUDIO_EXTENSIONS = new Set(["mp3","m4a","aac","ogg","oga","wav","flac","opus"]);

  let selectedFiles = [];
  let selectedMode = "media";
  let appendNextPick = false;
  let objectUrls = [];
  let busy = false;

  function notify(text) {
    if (typeof window.showToast === "function") window.showToast(text);
    else if (typeof showToast === "function") showToast(text);
  }

  function extension(file) {
    const name = (file?.name || "").toLowerCase();
    const index = name.lastIndexOf(".");
    return index >= 0 ? name.slice(index + 1) : "";
  }

  function isMedia(file) {
    const ext = extension(file);
    const type = (file.type || "").toLowerCase();
    return MEDIA_EXTENSIONS.has(ext) && (
      type.startsWith("image/")
      || type.startsWith("video/")
      || (!type && MEDIA_EXTENSIONS.has(ext))
    );
  }

  function isAudio(file) {
    const ext = extension(file);
    const type = (file.type || "").toLowerCase();
    return AUDIO_EXTENSIONS.has(ext) && (type.startsWith("audio/") || !type);
  }

  function formatBytes(bytes) {
    if (!bytes) return "0 Б";
    if (bytes < 1024) return bytes + " Б";
    if (bytes < 1024 * 1024) return Math.round(bytes / 1024) + " КБ";
    return (bytes / (1024 * 1024)).toFixed(1) + " МБ";
  }

  function pluralFiles(count) {
    if (count % 10 === 1 && count % 100 !== 11) return count + " файл";
    if ([2,3,4].includes(count % 10) && ![12,13,14].includes(count % 100)) return count + " файла";
    return count + " файлов";
  }

  function validate(files, mode) {
    if (!files.length) return "Файлы не выбраны.";
    if (files.length > MAX_ATTACHMENTS) return "Можно отправить не больше 10 файлов за раз.";

    let total = 0;
    for (const file of files) {
      if (extension(file) === "gif" || file.type === "image/gif") {
        return "GIF в Sovietgram пока отключены.";
      }
      if (mode === "media" && !isMedia(file)) {
        return "Для «Фото или видео» выберите PNG, JPEG, WebP, MP4, WebM, MOV или M4V.";
      }
      if (mode === "audio" && !isAudio(file)) {
        return "Для «Музыка» выберите MP3, M4A, AAC, OGG, WAV, FLAC или OPUS.";
      }
      if (file.size > MAX_FILE_SIZE) return file.name + ": файл больше 25 МБ.";
      total += file.size;
    }
    if (total > MAX_TOTAL_SIZE) return "Общий размер файлов больше 100 МБ.";
    return "";
  }

  function releaseUrls() {
    objectUrls.forEach((url) => URL.revokeObjectURL(url));
    objectUrls = [];
  }

  function setProgress(active, percent = 0) {
    busy = active;
    if (sendButton) {
      sendButton.disabled = active;
      sendButton.textContent = active ? "Отправка…" : "Отправить";
    }
    if (addButton) addButton.disabled = active;
    if (closeButton) closeButton.disabled = active;
    if (progressNode) progressNode.hidden = !active;
    if (progressBar) progressBar.style.width = Math.max(0, Math.min(100, percent)) + "%";
  }

  function closeComposer() {
    if (busy) return;
    releaseUrls();
    selectedFiles = [];
    appendNextPick = false;
    if (backdrop) backdrop.hidden = true;
    if (captionNode) captionNode.value = "";
    setProgress(false, 0);
  }

  function removeFile(index) {
    if (busy) return;
    selectedFiles.splice(index, 1);
    if (!selectedFiles.length) {
      closeComposer();
      return;
    }
    renderSelection();
  }

  function renderSelection() {
    if (!previewNode) return;
    releaseUrls();
    previewNode.replaceChildren();

    const total = selectedFiles.reduce((sum, file) => sum + file.size, 0);
    if (summaryNode) summaryNode.textContent = pluralFiles(selectedFiles.length) + " · " + formatBytes(total);

    if (titleNode) {
      if (selectedMode === "media") {
        titleNode.textContent = selectedFiles.length > 1
          ? "Отправить медиа"
          : ((selectedFiles[0]?.type || "").startsWith("video/") ? "Отправить видео" : "Отправить фото");
      } else if (selectedMode === "audio") {
        titleNode.textContent = selectedFiles.length > 1 ? "Отправить музыку" : "Отправить трек";
      } else {
        titleNode.textContent = selectedFiles.length > 1 ? "Отправить файлы" : "Отправить файл";
      }
    }

    if (hintNode) {
      hintNode.textContent = selectedMode === "media"
        ? "Фото и видео будут показаны прямо в переписке."
        : selectedMode === "audio"
          ? "Музыка будет отправлена со встроенным проигрывателем."
          : "Документы будут отправлены без обработки.";
    }

    if (groupRow) groupRow.hidden = selectedMode !== "media" || selectedFiles.length < 2;

    if (selectedMode === "media") {
      const grid = document.createElement("div");
      grid.className = "media-preview-grid";
      grid.dataset.count = String(selectedFiles.length);

      selectedFiles.forEach((file, index) => {
        const card = document.createElement("div");
        card.className = "media-preview-card";
        const url = URL.createObjectURL(file);
        objectUrls.push(url);

        if ((file.type || "").startsWith("video/") || ["mp4","webm","mov","m4v"].includes(extension(file))) {
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

        const remove = document.createElement("button");
        remove.type = "button";
        remove.className = "media-preview-remove";
        remove.setAttribute("aria-label", "Убрать файл");
        remove.textContent = "×";
        remove.addEventListener("click", () => removeFile(index));
        card.appendChild(remove);
        grid.appendChild(card);
      });

      previewNode.appendChild(grid);
      return;
    }

    const list = document.createElement("div");
    list.className = "media-preview-files";
    selectedFiles.forEach((file, index) => {
      const row = document.createElement("div");
      row.className = "media-preview-file";

      const icon = document.createElement("span");
      icon.className = "media-preview-file__icon";
      icon.textContent = selectedMode === "audio" ? "♪" : "⌑";

      const copy = document.createElement("span");
      copy.className = "media-preview-file__text";
      const name = document.createElement("strong");
      name.textContent = file.name;
      const meta = document.createElement("small");
      meta.textContent = formatBytes(file.size);
      copy.append(name, meta);

      const remove = document.createElement("button");
      remove.type = "button";
      remove.className = "media-preview-remove";
      remove.setAttribute("aria-label", "Убрать файл");
      remove.textContent = "×";
      remove.addEventListener("click", () => removeFile(index));

      row.append(icon, copy, remove);
      list.appendChild(row);
    });
    previewNode.appendChild(list);
  }

  function openComposer(files, mode, preserveCaption = false) {
    if (conversation.dataset.canSendMedia === "false") {
      notify("Администраторы запретили отправлять медиа и файлы.");
      return;
    }

    const error = validate(files, mode);
    if (error) {
      notify(error);
      return;
    }

    const previousCaption = captionNode?.value || "";
    selectedFiles = files;
    selectedMode = mode;
    if (modeInput) modeInput.value = mode;
    if (groupToggle && !preserveCaption) groupToggle.checked = true;
    if (captionNode) {
      captionNode.value = preserveCaption
        ? previousCaption
        : (messageInput?.value || "");
    }
    renderSelection();
    if (progressNode) progressNode.hidden = true;
    if (progressBar) progressBar.style.width = "0%";
    if (backdrop) backdrop.hidden = false;
    window.setTimeout(() => captionNode?.focus(), 0);
  }

  function pick(mode, append = false) {
    const input = inputs[mode];
    if (!input) {
      notify("Поле выбора файлов не найдено.");
      return;
    }

    appendNextPick = append;
    window.SovietgramAttachmentMenu?.close();

    try {
      if (typeof input.showPicker === "function") {
        input.showPicker();
      } else {
        input.click();
      }
    } catch (_error) {
      input.click();
    }
  }

  function onPicked(input, mode) {
    const files = [...(input.files || [])];
    input.value = "";
    if (!files.length) {
      appendNextPick = false;
      return;
    }

    const next = appendNextPick && selectedFiles.length && selectedMode === mode
      ? [...selectedFiles, ...files]
      : files;
    const preserveCaption = appendNextPick && backdrop && !backdrop.hidden;
    appendNextPick = false;
    openComposer(next, mode, preserveCaption);
  }

  function upload(files, text, mode, replyTo, onProgress) {
    return new Promise((resolve, reject) => {
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

      xhr.upload.addEventListener("progress", (event) => {
        if (event.lengthComputable) onProgress(event.loaded, event.total);
      });

      xhr.addEventListener("load", () => {
        const payload = xhr.response || {};
        if (xhr.status >= 200 && xhr.status < 300 && payload.ok) {
          resolve(payload);
          return;
        }
        const firstError = Object.values(payload.errors || {}).flat()?.[0]?.message;
        reject(new Error(payload.error || firstError || "Не удалось отправить файлы."));
      });
      xhr.addEventListener("error", () => reject(new Error("Не удалось загрузить файлы.")));
      xhr.addEventListener("abort", () => reject(new Error("Загрузка была отменена.")));
      xhr.send(data);
    });
  }

  function renderSent(message) {
    if (typeof window.renderSovietgramChatMessage === "function") {
      window.renderSovietgramChatMessage(message);
    } else {
      window.location.reload();
    }
  }

  async function sendSelected() {
    if (!selectedFiles.length || busy) return;

    const error = validate(selectedFiles, selectedMode);
    if (error) {
      notify(error);
      return;
    }

    const files = [...selectedFiles];
    const caption = captionNode?.value.trim() || "";
    const replyTo = replyInput?.value || "";
    const separate = selectedMode === "media"
      && files.length > 1
      && groupToggle
      && !groupToggle.checked;
    const totalBytes = Math.max(1, files.reduce((sum, file) => sum + file.size, 0));
    let sentBytes = 0;

    setProgress(true, 0);

    try {
      if (separate) {
        for (let index = 0; index < files.length; index += 1) {
          const file = files[index];
          const payload = await upload(
            [file],
            index === files.length - 1 ? caption : "",
            "media",
            index === 0 ? replyTo : "",
            (loaded) => setProgress(true, ((sentBytes + loaded) / totalBytes) * 100),
          );
          renderSent(payload.message);
          sentBytes += file.size;
        }
      } else {
        const payload = await upload(
          files,
          caption,
          selectedMode,
          replyTo,
          (loaded, total) => setProgress(true, total ? (loaded / total) * 100 : 0),
        );
        renderSent(payload.message);
      }

      if (messageInput) {
        messageInput.value = "";
        messageInput.dispatchEvent(new Event("input", { bubbles: true }));
      }
      if (replyInput) replyInput.value = "";
      if (composerReply) composerReply.hidden = true;
      setProgress(false, 100);
      closeComposer();
    } catch (uploadError) {
      setProgress(false, 0);
      notify(uploadError.message);
    }
  }

  // Own attachment file actions before the legacy chat handlers can consume
  // the same event. This isolates file picking from the large chat.js module.
  document.addEventListener("click", (event) => {
    const modeButton = event.target.closest?.("[data-attachment-mode]");
    if (modeButton) {
      event.preventDefault();
      event.stopImmediatePropagation();
      pick(modeButton.dataset.attachmentMode || "media", false);
      return;
    }

    if (event.target.closest?.("#mediaComposeAdd")) {
      event.preventDefault();
      event.stopImmediatePropagation();
      pick(selectedMode, true);
      return;
    }

    if (event.target.closest?.("#mediaComposeSend")) {
      event.preventDefault();
      event.stopImmediatePropagation();
      sendSelected();
      return;
    }

    if (event.target.closest?.("#mediaComposeClose")) {
      event.preventDefault();
      event.stopImmediatePropagation();
      closeComposer();
      return;
    }

    if (event.target === backdrop) {
      event.preventDefault();
      event.stopImmediatePropagation();
      closeComposer();
    }
  }, true);

  document.addEventListener("change", (event) => {
    const entries = Object.entries(inputs);
    const match = entries.find(([, input]) => input === event.target);
    if (!match) return;
    event.stopImmediatePropagation();
    onPicked(match[1], match[0]);
  }, true);

  captionNode?.addEventListener("keydown", (event) => {
    if (event.key !== "Enter" || event.shiftKey) return;
    if (!(event.ctrlKey || event.metaKey || document.body.dataset.enterToSend !== "false")) return;
    event.preventDefault();
    event.stopImmediatePropagation();
    sendSelected();
  }, true);

  window.SovietgramAttachmentFiles = {
    pick,
    close: closeComposer,
    send: sendSelected,
  };
})();
