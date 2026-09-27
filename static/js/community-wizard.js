(() => {
  const root = document.getElementById("communityWizard");
  const form = document.getElementById("communityWizardForm");
  if (!root || !form) return;

  const typeInput = document.getElementById("communityWizardType");
  const membersInput = document.getElementById("communityWizardMembers");
  const visibilityInput = document.getElementById("communityWizardVisibility");
  const titleInput = document.getElementById("communityTitleInput");
  const titleLabel = document.getElementById("communityTitleLabel");
  const descriptionInput = document.getElementById("communityDescriptionInput");
  const avatarInput = document.getElementById("communityAvatarInput");
  const avatarPreview = document.getElementById("communityAvatarPreview");
  const memberSearch = document.getElementById("communityMemberSearch");
  const selectedCount = document.getElementById("communitySelectedCount");
  const usernameField = document.getElementById("communityUsernameField");
  const usernameInput = document.getElementById("communityUsernameInput");
  const privateNote = document.getElementById("communityPrivateNote");
  const detailError = document.getElementById("communityDetailsError");
  const membersError = document.getElementById("communityMembersError");
  const privacyError = document.getElementById("communityPrivacyError");
  const steps = [...root.querySelectorAll("[data-community-step]")];
  const memberRows = [...root.querySelectorAll("[data-member-row]")];
  const visibilityRadios = [...root.querySelectorAll('input[name="wizard_visibility"]')];

  let mode = "group";
  let avatarObjectUrl = "";
  let submitting = false;

  function errorBox(step) {
    if (step === "members") return membersError;
    if (step === "privacy") return privacyError;
    return detailError;
  }

  function setError(step, message = "") {
    const box = errorBox(step);
    if (!box) return;
    box.textContent = message;
    box.hidden = !message;
  }

  function showStep(step) {
    steps.forEach((item) => {
      item.hidden = item.dataset.communityStep !== step;
    });
    setError("details");
    setError("members");
    setError("privacy");

    window.setTimeout(() => {
      if (step === "details") titleInput?.focus();
      if (step === "members") memberSearch?.focus();
      if (
        step === "privacy"
        && visibilityRadios.find((radio) => radio.checked)?.value === "public"
      ) usernameInput?.focus();
    }, 0);
  }

  function selectedMembers() {
    return memberRows
      .map((row) => row.querySelector('input[type="checkbox"]'))
      .filter((input) => input?.checked)
      .map((input) => input.value);
  }

  function syncMemberCount() {
    const selected = selectedMembers();
    if (selectedCount) {
      selectedCount.textContent = selected.length
        ? `${selected.length} выбрано`
        : "Никто не выбран";
    }
    if (membersInput) membersInput.value = selected.join(",");
  }

  function resetAvatar() {
    if (avatarObjectUrl) URL.revokeObjectURL(avatarObjectUrl);
    avatarObjectUrl = "";
    if (avatarInput) avatarInput.value = "";
    if (avatarPreview) {
      avatarPreview.innerHTML = `
        <svg viewBox="0 0 24 24" aria-hidden="true">
          <path d="M8.5 6.5 10 4h4l1.5 2.5H18a3 3 0 0 1 3 3V17a3 3 0 0 1-3 3H6a3 3 0 0 1-3-3V9.5a3 3 0 0 1 3-3h2.5Z"></path>
          <circle cx="12" cy="13" r="4"></circle>
        </svg>
      `;
    }
  }

  function syncPrivacy() {
    const visibility = visibilityRadios.find((radio) => radio.checked)?.value || "public";
    if (visibilityInput) visibilityInput.value = visibility;
    const isPrivate = visibility === "private";
    if (usernameField) usernameField.hidden = isPrivate;
    if (privateNote) privateNote.hidden = !isPrivate;
  }

  function reset(nextMode) {
    mode = nextMode === "channel" ? "channel" : "group";
    if (typeInput) typeInput.value = mode;
    if (titleLabel) titleLabel.textContent = mode === "channel" ? "Название канала" : "Название группы";
    if (titleInput) titleInput.value = "";
    if (descriptionInput) descriptionInput.value = "";
    if (usernameInput) usernameInput.value = "";
    if (memberSearch) memberSearch.value = "";
    if (visibilityInput) visibilityInput.value = "public";

    visibilityRadios.forEach((radio) => {
      radio.checked = radio.value === "public";
    });
    memberRows.forEach((row) => {
      const checkbox = row.querySelector('input[type="checkbox"]');
      if (checkbox) checkbox.checked = false;
      row.hidden = false;
    });

    resetAvatar();
    syncMemberCount();
    syncPrivacy();
    showStep("details");
  }

  function open(nextMode) {
    reset(nextMode);
    root.hidden = false;
    document.body.classList.add("has-modal");
  }

  function close() {
    if (submitting) return;
    root.hidden = true;
    document.body.classList.remove("has-modal");
    resetAvatar();
  }

  function validateDetails() {
    if (titleInput?.value.trim()) return true;
    setError(
      "details",
      mode === "channel" ? "Введите название канала." : "Введите название группы.",
    );
    titleInput?.focus();
    return false;
  }

  function errorsToText(errors) {
    if (!errors || typeof errors !== "object") return "Не удалось создать чат.";
    const order = ["title", "avatar", "username", "members", "__all__"];
    const seen = new Set();
    const messages = [];
    [...order, ...Object.keys(errors)].forEach((key) => {
      if (seen.has(key) || !errors[key]) return;
      seen.add(key);
      const message = errors[key]
        .map((item) => item?.message || "")
        .filter(Boolean)
        .join(" ");
      if (message) messages.push(message);
    });
    return messages.join(" ") || "Проверьте введённые данные.";
  }

  async function submit(step) {
    if (submitting) return;
    if (!validateDetails()) {
      showStep("details");
      return;
    }

    if (mode === "channel") {
      const visibility = visibilityRadios.find((radio) => radio.checked)?.value || "public";
      if (visibility === "public" && !usernameInput?.value.trim()) {
        setError("privacy", "Укажите публичный @адрес канала.");
        usernameInput?.focus();
        return;
      }
    }

    syncMemberCount();
    syncPrivacy();
    submitting = true;
    root.querySelectorAll("button").forEach((button) => {
      button.disabled = true;
    });

    try {
      const response = await fetch(root.dataset.createUrl, {
        method: "POST",
        body: new FormData(form),
        credentials: "same-origin",
        headers: { "X-Requested-With": "XMLHttpRequest" },
      });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok || !payload.ok) {
        const target = payload.errors?.username ? "privacy" : step;
        if (target !== step) showStep(target);
        setError(target, errorsToText(payload.errors));
        return;
      }
      window.location.assign(payload.redirect_url);
    } catch (_error) {
      setError(step, "Не удалось связаться с сервером. Попробуйте ещё раз.");
    } finally {
      submitting = false;
      root.querySelectorAll("button").forEach((button) => {
        button.disabled = false;
      });
    }
  }

  document.querySelectorAll("[data-community-open]").forEach((control) => {
    control.addEventListener("click", (event) => {
      event.preventDefault();
      if (typeof setProfileMenu === "function") setProfileMenu(false);
      open(control.dataset.communityOpen || "group");
    });
  });

  root.querySelectorAll("[data-community-close]").forEach((button) => {
    button.addEventListener("click", close);
  });
  root.querySelectorAll("[data-community-back]").forEach((button) => {
    button.addEventListener("click", () => showStep("details"));
  });

  document.getElementById("communityDetailsNext")?.addEventListener("click", () => {
    if (!validateDetails()) return;
    showStep(mode === "channel" ? "privacy" : "members");
  });
  document.getElementById("communityCreateGroup")?.addEventListener("click", () => {
    if (!selectedMembers().length) {
      setError("members", "Выберите хотя бы одного участника.");
      return;
    }
    submit("members");
  });
  document.getElementById("communityCreateChannel")?.addEventListener("click", () => {
    submit("privacy");
  });

  avatarInput?.addEventListener("change", () => {
    const file = avatarInput.files?.[0];
    if (!file || !avatarPreview) return;
    if (avatarObjectUrl) URL.revokeObjectURL(avatarObjectUrl);
    avatarObjectUrl = URL.createObjectURL(file);
    const image = document.createElement("img");
    image.src = avatarObjectUrl;
    image.alt = "";
    avatarPreview.replaceChildren(image);
  });

  memberRows.forEach((row) => {
    row.querySelector('input[type="checkbox"]')?.addEventListener("change", syncMemberCount);
  });
  memberSearch?.addEventListener("input", () => {
    const query = memberSearch.value.trim().toLowerCase().replace(/^@/, "");
    memberRows.forEach((row) => {
      row.hidden = Boolean(query) && !(row.dataset.memberSearch || "").includes(query);
    });
  });
  visibilityRadios.forEach((radio) => radio.addEventListener("change", syncPrivacy));

  root.addEventListener("click", (event) => {
    if (event.target === root) close();
  });
  form.addEventListener("submit", (event) => event.preventDefault());
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && !root.hidden) close();
  });

  if (root.dataset.autoOpen === "group" || root.dataset.autoOpen === "channel") {
    open(root.dataset.autoOpen);
  }

  window.SovietgramCommunityWizard = { open, close };
})();
