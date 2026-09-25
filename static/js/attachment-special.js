(() => {
  const conversation = document.querySelector(".conversation--chat");
  const attachmentMenu = document.getElementById("attachmentMenu");
  const attachmentButton = document.getElementById("attachmentButton");
  const modal = document.getElementById("attachSpecialBackdrop");
  const modalTitle = document.getElementById("attachSpecialTitle");
  const modalClose = document.getElementById("attachSpecialClose");
  const modalSend = document.getElementById("attachSpecialSend");
  const modalHint = document.getElementById("attachSpecialHint");
  const panels = [...document.querySelectorAll("[data-special-panel]")];
  const replyInput = document.getElementById("replyToInput");
  const csrfToken = document.querySelector("#messageForm [name='csrfmiddlewaretoken']")?.value || "";

  if (!conversation) return;

  let activeType = "";
  let busy = false;

  function notify(text) {
    if (typeof window.showToast === "function") window.showToast(text);
  }

  function closeAttachmentMenu() {
    if (attachmentMenu) attachmentMenu.hidden = true;
    attachmentButton?.setAttribute("aria-expanded", "false");
  }

  function setBusy(next) {
    busy = next;
    if (modalSend) modalSend.disabled = next;
    if (modalClose) modalClose.disabled = next;
    if (modalSend) modalSend.textContent = next ? "Отправка…" : "Отправить";
  }

  function clearNode(node) {
    while (node?.firstChild) node.removeChild(node.firstChild);
  }

  const pollQuestion = document.getElementById("attachPollQuestion");
  const pollOptions = document.getElementById("attachPollOptions");
  const pollAdd = document.getElementById("attachPollAddOption");
  const pollAnonymous = document.getElementById("attachPollAnonymous");
  const pollMultiple = document.getElementById("attachPollMultiple");
  const pollQuiz = document.getElementById("attachPollQuiz");
  const pollExplanationRow = document.getElementById("attachPollExplanationRow");
  const pollExplanation = document.getElementById("attachPollExplanation");

  const todoTitle = document.getElementById("attachTodoTitle");
  const todoItems = document.getElementById("attachTodoItems");
  const todoAdd = document.getElementById("attachTodoAddItem");
  const todoAllowAdd = document.getElementById("attachTodoAllowAdd");
  const todoAllowMark = document.getElementById("attachTodoAllowMark");

  const articleTitle = document.getElementById("attachArticleTitle");
  const articleBody = document.getElementById("attachArticleBody");

  const locationLabel = document.getElementById("attachLocationLabel");
  const locationLatitude = document.getElementById("attachLocationLatitude");
  const locationLongitude = document.getElementById("attachLocationLongitude");
  const locationDetect = document.getElementById("attachLocationDetect");
  const locationStatus = document.getElementById("attachLocationStatus");

  function makeRemoveButton(row) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "attach-special-row__remove";
    button.setAttribute("aria-label", "Удалить");
    button.textContent = "×";
    button.addEventListener("click", () => {
      const parent = row.parentElement;
      row.remove();
      [...(parent?.children || [])].forEach((child, index) => {
        const input = child.querySelector("input[type='radio']");
        if (input) input.value = String(index);
      });
    });
    return button;
  }

  function makePollOption(value = "") {
    const row = document.createElement("div");
    row.className = "attach-special-row attach-special-row--poll";

    const correct = document.createElement("label");
    correct.className = "attach-poll-correct";
    correct.title = "Правильный ответ";
    const radio = document.createElement("input");
    radio.type = "radio";
    radio.name = "attachPollCorrect";
    radio.value = String(pollOptions?.children.length || 0);
    const mark = document.createElement("span");
    mark.textContent = "✓";
    correct.append(radio, mark);

    const input = document.createElement("input");
    input.type = "text";
    input.maxLength = 100;
    input.placeholder = "Вариант ответа";
    input.value = value;

    row.append(correct, input, makeRemoveButton(row));
    pollOptions?.appendChild(row);
    refreshPollRows();
    return row;
  }

  function refreshPollRows() {
    const rows = [...(pollOptions?.children || [])];
    const quiz = Boolean(pollQuiz?.checked);
    rows.forEach((row, index) => {
      row.classList.toggle("is-quiz", quiz);
      const radio = row.querySelector("input[type='radio']");
      if (radio) radio.value = String(index);
      const remove = row.querySelector(".attach-special-row__remove");
      if (remove) remove.hidden = rows.length <= 2;
    });
    if (pollAdd) pollAdd.disabled = rows.length >= 10;
  }

  function resetPoll() {
    if (pollQuestion) pollQuestion.value = "";
    if (pollAnonymous) pollAnonymous.checked = true;
    if (pollMultiple) {
      pollMultiple.checked = false;
      pollMultiple.disabled = false;
    }
    if (pollQuiz) pollQuiz.checked = false;
    if (pollExplanation) pollExplanation.value = "";
    if (pollExplanationRow) pollExplanationRow.hidden = true;
    clearNode(pollOptions);
    makePollOption();
    makePollOption();
    refreshPollRows();
  }

  function makeTodoItem(value = "") {
    const row = document.createElement("div");
    row.className = "attach-special-row attach-special-row--todo";

    const marker = document.createElement("span");
    marker.className = "attach-todo-marker";
    marker.textContent = "✓";

    const input = document.createElement("input");
    input.type = "text";
    input.maxLength = 160;
    input.placeholder = "Задача";
    input.value = value;

    row.append(marker, input, makeRemoveButton(row));
    todoItems?.appendChild(row);
    refreshTodoRows();
    return row;
  }

  function refreshTodoRows() {
    const rows = [...(todoItems?.children || [])];
    rows.forEach((row) => {
      const remove = row.querySelector(".attach-special-row__remove");
      if (remove) remove.hidden = rows.length <= 1;
    });
    if (todoAdd) todoAdd.disabled = rows.length >= 30;
  }

  function resetTodo() {
    if (todoTitle) todoTitle.value = "";
    if (todoAllowAdd) todoAllowAdd.checked = false;
    if (todoAllowMark) todoAllowMark.checked = true;
    clearNode(todoItems);
    makeTodoItem();
    makeTodoItem();
    refreshTodoRows();
  }

  function resetArticle() {
    if (articleTitle) articleTitle.value = "";
    if (articleBody) articleBody.value = "";
  }

  function resetLocation() {
    if (locationLabel) locationLabel.value = "";
    if (locationLatitude) locationLatitude.value = "";
    if (locationLongitude) locationLongitude.value = "";
    if (locationStatus) locationStatus.textContent = "Укажите координаты или определите текущее местоположение.";
    if (locationDetect) {
      locationDetect.disabled = false;
      locationDetect.textContent = "Определить моё местоположение";
    }
  }

  function resetType(type) {
    if (type === "poll") resetPoll();
    if (type === "todo") resetTodo();
    if (type === "article") resetArticle();
    if (type === "location") resetLocation();
  }

  const titles = {
    poll: "Новый опрос",
    todo: "Новый список задач",
    article: "Новая статья",
    location: "Геопозиция",
  };
  const hints = {
    poll: "Опрос появится в чате как интерактивное сообщение.",
    todo: "Участники смогут отмечать задачи и, если разрешено, добавлять новые.",
    article: "Статья отправится отдельной компактной карточкой.",
    location: "Координаты будут отправлены в чат и откроются на карте.",
  };

  function openSpecial(type) {
    if (!modal || !titles[type]) return;
    activeType = type;
    resetType(type);
    panels.forEach((panel) => {
      panel.hidden = panel.dataset.specialPanel !== type;
    });
    if (modalTitle) modalTitle.textContent = titles[type];
    if (modalHint) modalHint.textContent = hints[type] || "";
    modal.hidden = false;
    closeAttachmentMenu();

    const focus = type === "poll"
      ? pollQuestion
      : type === "todo"
        ? todoTitle
        : type === "article"
          ? articleTitle
          : locationLabel;
    window.setTimeout(() => focus?.focus(), 0);
  }

  function closeSpecial() {
    if (busy) return;
    activeType = "";
    if (modal) modal.hidden = true;
  }

  function collectPayload() {
    if (activeType === "poll") {
      const options = [...(pollOptions?.querySelectorAll("input[type='text']") || [])]
        .map((input) => input.value.trim())
        .filter(Boolean);
      const quiz = Boolean(pollQuiz?.checked);
      const correct = pollOptions?.querySelector("input[type='radio']:checked");
      return {
        question: pollQuestion?.value.trim() || "",
        options,
        anonymous: Boolean(pollAnonymous?.checked),
        multiple: Boolean(pollMultiple?.checked) && !quiz,
        quiz,
        correct_option: quiz && correct ? Number(correct.value) : null,
        explanation: pollExplanation?.value.trim() || "",
      };
    }
    if (activeType === "todo") {
      return {
        title: todoTitle?.value.trim() || "",
        tasks: [...(todoItems?.querySelectorAll("input[type='text']") || [])]
          .map((input) => input.value.trim())
          .filter(Boolean),
        allow_others_add: Boolean(todoAllowAdd?.checked),
        allow_others_mark: Boolean(todoAllowMark?.checked),
      };
    }
    if (activeType === "article") {
      return {
        title: articleTitle?.value.trim() || "",
        body: articleBody?.value.trim() || "",
      };
    }
    if (activeType === "location") {
      return {
        label: locationLabel?.value.trim() || "",
        latitude: locationLatitude?.value || "",
        longitude: locationLongitude?.value || "",
      };
    }
    return {};
  }

  function validatePayload(type, payload) {
    if (type === "poll") {
      if (!payload.question) return "Введите вопрос.";
      if (payload.options.length < 2) return "Добавьте хотя бы два варианта ответа.";
      if (payload.quiz && payload.correct_option == null) return "Для викторины выберите правильный ответ.";
    }
    if (type === "todo") {
      if (!payload.title) return "Введите название списка.";
      if (!payload.tasks.length) return "Добавьте хотя бы одну задачу.";
    }
    if (type === "article") {
      if (!payload.title) return "Введите заголовок.";
      if (!payload.body) return "Введите текст статьи.";
    }
    if (type === "location") {
      const lat = Number(payload.latitude);
      const lon = Number(payload.longitude);
      if (!Number.isFinite(lat) || lat < -90 || lat > 90) return "Введите корректную широту.";
      if (!Number.isFinite(lon) || lon < -180 || lon > 180) return "Введите корректную долготу.";
    }
    return "";
  }

  async function sendSpecial() {
    const url = conversation.dataset.specialSendUrl;
    if (!url || !activeType || busy) return;

    const payload = collectPayload();
    const error = validatePayload(activeType, payload);
    if (error) {
      notify(error);
      return;
    }

    setBusy(true);
    const data = new FormData();
    data.append("csrfmiddlewaretoken", csrfToken);
    data.append("special_type", activeType);
    data.append("payload", JSON.stringify(payload));
    if (replyInput?.value) data.append("reply_to", replyInput.value);

    try {
      const response = await fetch(url, {
        method: "POST",
        credentials: "same-origin",
        headers: { "X-Requested-With": "XMLHttpRequest" },
        body: data,
      });
      const result = await response.json().catch(() => ({}));
      if (!response.ok || !result.ok) {
        throw new Error(result.error || "Не удалось отправить вложение.");
      }

      if (typeof window.renderSovietgramChatMessage === "function") {
        window.renderSovietgramChatMessage(result.message);
      } else {
        window.location.reload();
        return;
      }

      if (replyInput) replyInput.value = "";
      const reply = document.getElementById("composerReply");
      if (reply) reply.hidden = true;
      setBusy(false);
      closeSpecial();
    } catch (fetchError) {
      setBusy(false);
      notify(fetchError.message);
    }
  }

  pollAdd?.addEventListener("click", () => {
    if ((pollOptions?.children.length || 0) < 10) {
      const row = makePollOption();
      row.querySelector("input[type='text']")?.focus();
    }
  });

  pollQuiz?.addEventListener("change", () => {
    const quiz = Boolean(pollQuiz.checked);
    if (pollMultiple) {
      if (quiz) pollMultiple.checked = false;
      pollMultiple.disabled = quiz;
    }
    if (pollExplanationRow) pollExplanationRow.hidden = !quiz;
    refreshPollRows();
  });

  todoAdd?.addEventListener("click", () => {
    if ((todoItems?.children.length || 0) < 30) {
      const row = makeTodoItem();
      row.querySelector("input[type='text']")?.focus();
    }
  });

  locationDetect?.addEventListener("click", () => {
    if (!navigator.geolocation) {
      notify("Браузер не поддерживает геолокацию.");
      return;
    }
    locationDetect.disabled = true;
    locationDetect.textContent = "Определение…";
    if (locationStatus) locationStatus.textContent = "Запрашиваем координаты у браузера…";

    navigator.geolocation.getCurrentPosition(
      (position) => {
        if (locationLatitude) locationLatitude.value = position.coords.latitude.toFixed(6);
        if (locationLongitude) locationLongitude.value = position.coords.longitude.toFixed(6);
        if (locationStatus) {
          const accuracy = Math.round(position.coords.accuracy || 0);
          locationStatus.textContent = accuracy
            ? "Координаты определены · точность около " + accuracy + " м"
            : "Координаты определены.";
        }
        locationDetect.disabled = false;
        locationDetect.textContent = "Обновить местоположение";
      },
      (error) => {
        if (locationStatus) locationStatus.textContent = "Не удалось определить местоположение.";
        locationDetect.disabled = false;
        locationDetect.textContent = "Попробовать снова";
        notify(error.message || "Доступ к геолокации не предоставлен.");
      },
      { enableHighAccuracy: true, timeout: 12000, maximumAge: 60000 }
    );
  });

  document.querySelectorAll("[data-attach-special]").forEach((button) => {
    button.addEventListener("click", () => openSpecial(button.dataset.attachSpecial || ""));
  });

  modalClose?.addEventListener("click", closeSpecial);
  modalSend?.addEventListener("click", sendSpecial);
  modal?.addEventListener("click", (event) => {
    if (event.target === modal) closeSpecial();
  });

  function el(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text != null) node.textContent = text;
    return node;
  }

  function specialMeta(text) {
    return el("small", "message-special__eyebrow", text);
  }

  function buildPollCard(data) {
    const card = el("section", "message-special message-poll");
    card.dataset.specialMessage = "";
    card.dataset.specialType = "poll";
    card.dataset.actionUrl = data.action_url || "";
    card.dataset.multiple = data.multiple ? "true" : "false";
    card.dataset.quiz = data.quiz ? "true" : "false";
    card.dataset.voted = data.selected_indexes?.length ? "true" : "false";

    card.appendChild(el("strong", "message-special__title", data.question || "Опрос"));
    card.appendChild(
      specialMeta(
        (data.quiz ? "Викторина" : "Опрос")
        + (data.anonymous ? " · анонимный" : "")
      )
    );

    const options = el("div", "message-poll__options");
    (data.options || []).forEach((option) => {
      const button = el(
        "button",
        "message-poll__option"
          + (option.selected ? " is-selected" : "")
          + (option.correct ? " is-correct" : "")
      );
      button.type = "button";
      button.dataset.pollOption = String(option.index);
      button.style.setProperty("--poll-percent", (option.percent || 0) + "%");
      button.disabled = Boolean(data.closed);

      button.appendChild(el("span", "message-poll__radio"));
      button.appendChild(el("span", "message-poll__label", option.text || ""));
      button.appendChild(el("span", "message-poll__percent", (option.percent || 0) + "%"));
      if (option.voter_names?.length) {
        button.appendChild(
          el("small", "message-poll__voters", option.voter_names.join(", "))
        );
      }
      button.appendChild(el("span", "message-poll__bar"));
      options.appendChild(button);
    });
    card.appendChild(options);

    if (data.multiple) {
      const submit = el("button", "message-poll__submit", "Голосовать");
      submit.type = "button";
      submit.dataset.pollSubmit = "";
      card.appendChild(submit);
    }

    card.appendChild(
      el(
        "small",
        "message-poll__meta",
        String(data.total_voters || 0)
          + " голосов"
          + (data.closed ? " · завершён" : "")
      )
    );
    if (data.can_close) {
      const close = el("button", "message-poll__close", "Завершить опрос");
      close.type = "button";
      close.dataset.pollClose = "";
      card.appendChild(close);
    }
    if (data.explanation) {
      card.appendChild(el("p", "message-poll__explanation", data.explanation));
    }
    return card;
  }

  function buildTodoCard(data) {
    const card = el("section", "message-special message-todo");
    card.dataset.specialMessage = "";
    card.dataset.specialType = "todo";
    card.dataset.actionUrl = data.action_url || "";
    card.dataset.canAdd = data.can_add ? "true" : "false";
    card.dataset.canToggle = data.can_toggle ? "true" : "false";

    card.appendChild(el("strong", "message-special__title", data.title || "Список задач"));
    card.appendChild(specialMeta("Список задач"));

    const list = el("div", "message-todo__items");
    (data.tasks || []).forEach((task) => {
      const button = el(
        "button",
        "message-todo__item" + (task.done ? " is-done" : "")
      );
      button.type = "button";
      button.dataset.todoToggle = String(task.index);
      button.disabled = !data.can_toggle;
      button.appendChild(el("span", "message-todo__check", "✓"));
      button.appendChild(el("span", "", task.text || ""));
      list.appendChild(button);
    });
    card.appendChild(list);

    if (data.can_add) {
      const add = el("button", "message-todo__add", "+ Добавить задачу");
      add.type = "button";
      add.dataset.todoAdd = "";
      card.appendChild(add);

      const form = el("div", "message-todo__adder");
      form.hidden = true;
      const input = document.createElement("input");
      input.type = "text";
      input.maxLength = 160;
      input.placeholder = "Новая задача";
      input.dataset.todoAddInput = "";
      const send = el("button", "", "Добавить");
      send.type = "button";
      send.dataset.todoAddSubmit = "";
      form.append(input, send);
      card.appendChild(form);
    }

    return card;
  }

  function buildArticleCard(data) {
    const card = el("section", "message-special message-article");
    card.dataset.specialMessage = "";
    card.dataset.specialType = "article";
    card.appendChild(specialMeta("Статья"));
    card.appendChild(el("strong", "message-special__title", data.title || "Статья"));
    card.appendChild(el("div", "message-article__body", data.body || ""));
    return card;
  }

  function buildLocationCard(data) {
    const card = el("a", "message-special message-location");
    card.dataset.specialMessage = "";
    card.dataset.specialType = "location";
    card.target = "_blank";
    card.rel = "noopener noreferrer";
    const lat = Number(data.latitude);
    const lon = Number(data.longitude);
    card.href = "https://www.openstreetmap.org/?mlat="
      + encodeURIComponent(lat)
      + "&mlon="
      + encodeURIComponent(lon)
      + "#map=16/"
      + encodeURIComponent(lat)
      + "/"
      + encodeURIComponent(lon);

    card.appendChild(el("span", "message-location__pin", "⌖"));
    const copy = el("span", "");
    copy.appendChild(specialMeta("Геопозиция"));
    copy.appendChild(el("strong", "message-special__title", data.label || "Геопозиция"));
    copy.appendChild(el("small", "message-location__coords", lat + ", " + lon));
    card.appendChild(copy);
    return card;
  }

  window.buildSovietgramSpecialMessage = (data) => {
    if (!data?.type) return null;
    if (data.type === "poll") return buildPollCard(data);
    if (data.type === "todo") return buildTodoCard(data);
    if (data.type === "article") return buildArticleCard(data);
    if (data.type === "location") return buildLocationCard(data);
    return null;
  };

  async function specialAction(card, values) {
    const url = card?.dataset.actionUrl;
    if (!url) return null;
    const data = new FormData();
    data.append("csrfmiddlewaretoken", csrfToken);
    Object.entries(values || {}).forEach(([key, value]) => {
      data.append(key, typeof value === "string" ? value : JSON.stringify(value));
    });
    const response = await fetch(url, {
      method: "POST",
      credentials: "same-origin",
      headers: { "X-Requested-With": "XMLHttpRequest" },
      body: data,
    });
    const result = await response.json().catch(() => ({}));
    if (!response.ok || !result.ok) {
      throw new Error(result.error || "Не удалось обновить сообщение.");
    }
    if (typeof window.updateSovietgramChatMessage === "function") {
      window.updateSovietgramChatMessage(result.message);
    } else {
      window.location.reload();
    }
    return result;
  }

  function beginMultipleChoice(card) {
    if (card.dataset.choiceEditing === "true") return;
    card.dataset.choiceEditing = "true";
    card.querySelectorAll("[data-poll-option]").forEach((option) => {
      option.classList.toggle("is-pending", option.classList.contains("is-selected"));
    });
  }

  document.addEventListener("click", async (event) => {
    const option = event.target.closest("[data-poll-option]");
    if (option) {
      const card = option.closest("[data-special-type='poll']");
      if (!card || card.classList.contains("is-busy")) return;
      const index = Number(option.dataset.pollOption);
      if (card.dataset.multiple === "true") {
        beginMultipleChoice(card);
        option.classList.toggle("is-pending");
        return;
      }
      card.classList.add("is-busy");
      try {
        await specialAction(card, { action: "vote", options: [index] });
      } catch (error) {
        card.classList.remove("is-busy");
        notify(error.message);
      }
      return;
    }

    const pollSubmit = event.target.closest("[data-poll-submit]");
    if (pollSubmit) {
      const card = pollSubmit.closest("[data-special-type='poll']");
      if (!card || card.classList.contains("is-busy")) return;
      beginMultipleChoice(card);
      const selected = [...card.querySelectorAll("[data-poll-option].is-pending")]
        .map((node) => Number(node.dataset.pollOption))
        .filter(Number.isInteger);
      if (!selected.length) {
        notify("Выберите хотя бы один вариант.");
        return;
      }
      card.classList.add("is-busy");
      try {
        await specialAction(card, { action: "vote", options: selected });
      } catch (error) {
        card.classList.remove("is-busy");
        notify(error.message);
      }
      return;
    }

    const pollClose = event.target.closest("[data-poll-close]");
    if (pollClose) {
      const card = pollClose.closest("[data-special-type='poll']");
      if (!card || card.classList.contains("is-busy")) return;
      if (!window.confirm("Завершить опрос? После этого голосовать будет нельзя.")) return;
      card.classList.add("is-busy");
      try {
        await specialAction(card, { action: "close" });
      } catch (error) {
        card.classList.remove("is-busy");
        notify(error.message);
      }
      return;
    }

    const todoToggle = event.target.closest("[data-todo-toggle]");
    if (todoToggle) {
      const card = todoToggle.closest("[data-special-type='todo']");
      if (!card || card.classList.contains("is-busy")) return;
      card.classList.add("is-busy");
      try {
        await specialAction(card, {
          action: "toggle",
          index: Number(todoToggle.dataset.todoToggle),
        });
      } catch (error) {
        card.classList.remove("is-busy");
        notify(error.message);
      }
      return;
    }

    const todoAdd = event.target.closest("[data-todo-add]");
    if (todoAdd) {
      const card = todoAdd.closest("[data-special-type='todo']");
      const adder = card?.querySelector(".message-todo__adder");
      const input = adder?.querySelector("[data-todo-add-input]");
      if (!adder) return;
      adder.hidden = false;
      todoAdd.hidden = true;
      window.setTimeout(() => input?.focus(), 0);
      return;
    }

    const todoSubmit = event.target.closest("[data-todo-add-submit]");
    if (todoSubmit) {
      const card = todoSubmit.closest("[data-special-type='todo']");
      const input = card?.querySelector("[data-todo-add-input]");
      const value = input?.value.trim() || "";
      if (!value) {
        input?.focus();
        return;
      }
      card.classList.add("is-busy");
      try {
        await specialAction(card, { action: "add", text: value });
      } catch (error) {
        card.classList.remove("is-busy");
        notify(error.message);
      }
    }
  });

  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && modal && !modal.hidden) {
      event.preventDefault();
      closeSpecial();
      return;
    }
    const input = event.target.closest?.("[data-todo-add-input]");
    if (input && event.key === "Enter") {
      event.preventDefault();
      input.closest(".message-todo__adder")
        ?.querySelector("[data-todo-add-submit]")
        ?.click();
    }
  });
})();
