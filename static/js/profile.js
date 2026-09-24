const profileMenuButton = document.getElementById("profileMenuButton");
const profileMenu = document.getElementById("profileMenu");
const profileMenuBackdrop = document.getElementById("profileMenuBackdrop");
const profileAccountToggle = document.getElementById("profileAccountToggle");
const profileAccountList = document.getElementById("profileAccountList");

function setAccountList(open) {
  if (!profileAccountToggle || !profileAccountList) return;
  profileAccountList.hidden = !open;
  profileAccountToggle.classList.toggle("is-open", open);
  profileAccountToggle.setAttribute("aria-expanded", String(open));
}

function setProfileMenu(open) {
  if (!profileMenu || !profileMenuBackdrop || !profileMenuButton) return;
  if (open) setAccountList(false);
  profileMenu.classList.toggle("is-open", open);
  profileMenuBackdrop.classList.toggle("is-open", open);
  profileMenu.setAttribute("aria-hidden", String(!open));
  profileMenuBackdrop.setAttribute("aria-hidden", String(!open));
  profileMenuButton.setAttribute("aria-expanded", String(open));
}

if (profileAccountToggle && profileAccountList) {
  profileAccountToggle.addEventListener("click", () => {
    setAccountList(profileAccountList.hidden);
  });
}

if (profileMenuButton && profileMenu && profileMenuBackdrop) {
  profileMenuButton.addEventListener("click", () => {
    setProfileMenu(!profileMenu.classList.contains("is-open"));
  });
  profileMenuBackdrop.addEventListener("click", () => setProfileMenu(false));
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") setProfileMenu(false);
  });
}

const avatarInput = document.getElementById("id_avatar");
const avatarPreviewImage = document.getElementById("avatarPreviewImage");
const avatarPreviewFallback = document.getElementById("avatarPreviewFallback");

if (avatarInput && avatarPreviewImage) {
  avatarInput.addEventListener("change", () => {
    const file = avatarInput.files?.[0];
    if (!file) return;
    const reader = new FileReader();
    reader.addEventListener("load", () => {
      avatarPreviewImage.src = reader.result;
      avatarPreviewImage.hidden = false;
      if (avatarPreviewFallback) avatarPreviewFallback.hidden = true;
    });
    reader.readAsDataURL(file);
  });
}

const bioInput = document.getElementById("id_bio");
const bioCounter = document.getElementById("bioCounter");
if (bioInput && bioCounter) {
  const updateBioCounter = () => {
    bioCounter.textContent = String(bioInput.value.length);
  };
  bioInput.addEventListener("input", updateBioCounter);
  updateBioCounter();
}

document.querySelectorAll("[data-copy-profile]").forEach((button) => {
  button.addEventListener("click", async () => {
    const relativeUrl = button.dataset.profileUrl;
    if (!relativeUrl) return;
    const url = new URL(relativeUrl, window.location.origin).href;
    const originalText = button.textContent;

    try {
      await navigator.clipboard.writeText(url);
      button.textContent = "Ссылка скопирована";
    } catch (_error) {
      const input = document.createElement("textarea");
      input.value = url;
      input.style.position = "fixed";
      input.style.opacity = "0";
      document.body.appendChild(input);
      input.select();
      document.execCommand("copy");
      input.remove();
      button.textContent = "Ссылка скопирована";
    }

    window.setTimeout(() => {
      button.textContent = originalText;
    }, 1600);
  });
});

document.querySelectorAll("[data-confirm-form]").forEach((form) => {
  form.addEventListener("submit", (event) => {
    const text = form.dataset.confirmForm || "Продолжить?";
    if (!window.confirm(text)) event.preventDefault();
  });
});



const userProfileOverlay = document.getElementById("userProfileOverlay");
const userProfileView = document.getElementById("userProfileView");
const userProfileClose = document.getElementById("userProfileClose");
const userProfileEditClose = document.getElementById("userProfileEditClose");
const userProfileEdit = document.getElementById("userProfileEdit");
const userProfileAvatar = document.getElementById("userProfileAvatar");
const userProfileName = document.getElementById("userProfileName");
const userProfileStatus = document.getElementById("userProfileStatus");
const userProfileBioSection = document.getElementById("userProfileBioSection");
const userProfileBio = document.getElementById("userProfileBio");
const userProfileUsernameRow = document.getElementById("userProfileUsernameRow");
const userProfileUsername = document.getElementById("userProfileUsername");
const userProfileChannelCard = document.getElementById("userProfileChannelCard");
const userProfileChannelAvatar = document.getElementById("userProfileChannelAvatar");
const userProfileChannelTitle = document.getElementById("userProfileChannelTitle");
const userProfileChannelTime = document.getElementById("userProfileChannelTime");
const userProfileChannelPreview = document.getElementById("userProfileChannelPreview");
const userProfileChannelMeta = document.getElementById("userProfileChannelMeta");
const userProfileBirthdayRow = document.getElementById("userProfileBirthdayRow");
const userProfileBirthday = document.getElementById("userProfileBirthday");
const userProfileActions = document.getElementById("userProfileActions");
const userProfileAccounts = document.getElementById("userProfileAccounts");
const userProfileMessage = document.getElementById("userProfileMessage");
const userProfileContact = document.getElementById("userProfileContact");

const userProfileEditForm = document.getElementById("userProfileEditForm");
const userProfileEditBack = document.getElementById("userProfileEditBack");
const userProfileAvatarInput = document.getElementById("userProfileAvatarInput");
const userProfileEditAvatar = document.getElementById("userProfileEditAvatar");
const userProfileEditAvatarOpen = document.getElementById("userProfileEditAvatarOpen");
const userProfileEditDisplayName = document.getElementById("userProfileEditDisplayName");
const userProfileEditStatus = document.getElementById("userProfileEditStatus");
const userProfileFirstNameInput = document.getElementById("userProfileFirstNameInput");
const userProfileUsernameInput = document.getElementById("userProfileUsernameInput");
const userProfileBirthdayInput = document.getElementById("userProfileBirthdayInput");
const userProfileNameOpen = document.getElementById("userProfileNameOpen");
const userProfileNameChoice = document.getElementById("userProfileNameChoice");
const userProfileUsernameOpen = document.getElementById("userProfileUsernameOpen");
const userProfileUsernameChoice = document.getElementById("userProfileUsernameChoice");
const userProfileBirthdayOpen = document.getElementById("userProfileBirthdayOpen");
const userProfileBirthdayChoice = document.getElementById("userProfileBirthdayChoice");
const userProfileChannelInput = document.getElementById("userProfileChannelInput");
const userProfileChannelOpen = document.getElementById("userProfileChannelOpen");
const userProfileChannelChoice = document.getElementById("userProfileChannelChoice");
const userProfileChannelPicker = document.getElementById("userProfileChannelPicker");
const userProfileChannelList = document.getElementById("userProfileChannelList");
const userProfileChannelRemove = document.getElementById("userProfileChannelRemove");
const userProfileChannelDone = document.getElementById("userProfileChannelDone");
const userProfileBioInput = document.getElementById("userProfileBioInput");
const userProfileBioCount = document.getElementById("userProfileBioCount");
const userProfileEditError = document.getElementById("userProfileEditError");

const userProfileFieldEditor = document.getElementById("userProfileFieldEditor");
const userProfileFieldTitle = document.getElementById("userProfileFieldTitle");
const userProfileFieldLabel = document.getElementById("userProfileFieldLabel");
const userProfileFieldInput = document.getElementById("userProfileFieldInput");
const userProfileFieldError = document.getElementById("userProfileFieldError");
const userProfileFieldClose = document.getElementById("userProfileFieldClose");
const userProfileFieldCancel = document.getElementById("userProfileFieldCancel");
const userProfileFieldSave = document.getElementById("userProfileFieldSave");

const userProfilePhotoViewer = document.getElementById("userProfilePhotoViewer");
const userProfilePhotoImage = document.getElementById("userProfilePhotoImage");
const userProfilePhotoClose = document.getElementById("userProfilePhotoClose");
const userProfilePhotoRemove = document.getElementById("userProfilePhotoRemove");

let openedProfile = null;
let profileAvatarPreviewUrl = "";
let pendingProfileChannelId = "";
let profileFieldKey = "";
let profileBioSaveTimer = 0;
let profileRefreshTimer = 0;

function csrfToken() {
  return document.querySelector('input[name="csrfmiddlewaretoken"]')?.value || "";
}

function showProfileToast(text) {
  if (typeof showToast === "function") showToast(text);
}

async function copyProfileText(text, successText = "Скопировано") {
  if (!text) return;
  try {
    await navigator.clipboard.writeText(text);
  } catch (_error) {
    const input = document.createElement("textarea");
    input.value = text;
    input.style.position = "fixed";
    input.style.opacity = "0";
    document.body.appendChild(input);
    input.select();
    document.execCommand("copy");
    input.remove();
  }
  showProfileToast(successText);
}

function updateGlobalSelfIdentity(payload) {
  if (!payload) return;
  document.querySelectorAll(".account-mini__name").forEach((element) => {
    element.textContent = payload.display_name;
  });
  document.querySelectorAll(".profile-account-header__bottom strong").forEach((element) => {
    element.textContent = payload.display_name;
  });
  if (payload.profile_url) {
    document.querySelectorAll("[data-self-profile]").forEach((link) => {
      link.href = payload.profile_url;
    });
  }
}

async function saveSelfProfile(changes = {}, avatarFile = null) {
  if (!openedProfile?.is_self || !openedProfile.edit_url) {
    throw new Error("profile is not editable");
  }

  const currentChannel = openedProfile.personal_channel?.id
    ? String(openedProfile.personal_channel.id)
    : "";
  const values = {
    first_name: openedProfile.first_name || "",
    username: openedProfile.username || "",
    bio: openedProfile.bio || "",
    birthday: openedProfile.birthday || "",
    personal_channel: currentChannel,
    ...changes,
  };

  const body = new FormData();
  body.set("first_name", values.first_name ?? "");
  body.set("username", values.username ?? "");
  body.set("bio", values.bio ?? "");
  body.set("birthday", values.birthday ?? "");
  body.set("personal_channel", values.personal_channel ?? "");
  if (avatarFile) body.set("avatar", avatarFile);

  const response = await fetch(openedProfile.edit_url, {
    method: "POST",
    body,
    headers: { "X-Requested-With": "XMLHttpRequest" },
    credentials: "same-origin",
  });
  const payload = await response.json();
  if (!response.ok || !payload.ok) {
    const error = new Error("profile validation failed");
    error.profileErrors = payload.errors;
    throw error;
  }

  openedProfile = {
    ...openedProfile,
    ...payload,
    is_self: true,
    edit_url: openedProfile.edit_url,
    owned_channels: openedProfile.owned_channels || [],
  };
  updateGlobalSelfIdentity(payload);
  return payload;
}

function renderProfileAvatar(target, profile) {
  if (!target) return;
  target.replaceChildren();
  if (profile.avatar_url) {
    const image = document.createElement("img");
    image.src = profile.avatar_url;
    image.alt = "";
    target.appendChild(image);
    return;
  }
  const fallback = document.createElement("span");
  fallback.textContent = profile.initials || "?";
  target.appendChild(fallback);
}

function setUserProfileMode(mode) {
  const editing = mode === "edit";
  if (userProfileView) userProfileView.hidden = editing;
  if (userProfileEditForm) userProfileEditForm.hidden = !editing;
}

function stopProfileRefresh() {
  if (profileRefreshTimer) window.clearInterval(profileRefreshTimer);
  profileRefreshTimer = 0;
}

function startProfileRefresh() {
  stopProfileRefresh();
  profileRefreshTimer = window.setInterval(async () => {
    if (!openedProfile?.profile_url || userProfileOverlay?.hidden) return;
    try {
      const response = await fetch(openedProfile.profile_url, {
        headers: { "X-Requested-With": "XMLHttpRequest" },
        credentials: "same-origin",
      });
      if (!response.ok) return;
      const fresh = await response.json();
      if (!fresh.ok || !openedProfile) return;
      openedProfile.status = fresh.status;
      openedProfile.is_contact = fresh.is_contact;
      if (userProfileStatus) userProfileStatus.textContent = fresh.status || "";
      if (userProfileEditStatus) userProfileEditStatus.textContent = fresh.status || "";
    } catch (_error) {
      // Presence refresh is best-effort.
    }
  }, 30000);
}

function closeProfilePhotoViewer() {
  if (!userProfilePhotoViewer) return;
  userProfilePhotoViewer.hidden = true;
  if (userProfilePhotoImage) userProfilePhotoImage.removeAttribute("src");
}

function openProfilePhotoViewer() {
  if (!openedProfile?.avatar_url || !userProfilePhotoViewer || !userProfilePhotoImage) return;
  userProfilePhotoImage.src = openedProfile.avatar_url;
  if (userProfilePhotoRemove) {
    userProfilePhotoRemove.hidden = !(openedProfile.is_self && openedProfile.remove_avatar_url);
  }
  userProfilePhotoViewer.hidden = false;
}

function closeProfileFieldEditor() {
  if (!userProfileFieldEditor) return;
  userProfileFieldEditor.hidden = true;
  profileFieldKey = "";
  if (userProfileFieldError) {
    userProfileFieldError.hidden = true;
    userProfileFieldError.textContent = "";
  }
}

async function flushBioSave() {
  if (profileBioSaveTimer) {
    window.clearTimeout(profileBioSaveTimer);
    profileBioSaveTimer = 0;
  }
  if (!openedProfile?.is_self || !userProfileBioInput) return;
  const bio = userProfileBioInput.value;
  if (bio === (openedProfile.bio || "")) return;
  try {
    await saveSelfProfile({ bio });
    if (userProfileEditError) userProfileEditError.hidden = true;
  } catch (error) {
    if (userProfileEditError) {
      userProfileEditError.textContent = profileErrorsToText(error?.profileErrors);
      userProfileEditError.hidden = false;
    }
    throw error;
  }
}

async function closeUserProfile() {
  if (!userProfileOverlay) return;
  if (userProfileEditForm && !userProfileEditForm.hidden) {
    try {
      await flushBioSave();
    } catch (_error) {
      return;
    }
  }
  closeProfileFieldEditor();
  closeProfilePhotoViewer();
  if (userProfileChannelPicker) userProfileChannelPicker.hidden = true;
  stopProfileRefresh();
  userProfileOverlay.hidden = true;
  setUserProfileMode("view");
  openedProfile = null;
  if (profileAvatarPreviewUrl) URL.revokeObjectURL(profileAvatarPreviewUrl);
  profileAvatarPreviewUrl = "";
  document.body.classList.remove("has-profile-overlay");
}

function renderUserProfile(profile) {
  if (!userProfileOverlay) return;
  openedProfile = profile;

  renderProfileAvatar(userProfileAvatar, profile);
  if (userProfileAvatar) {
    userProfileAvatar.disabled = !profile.avatar_url;
    userProfileAvatar.classList.toggle("is-clickable", Boolean(profile.avatar_url));
  }
  if (userProfileName) userProfileName.textContent = profile.display_name || profile.username || "";
  if (userProfileStatus) userProfileStatus.textContent = profile.status || "";
  if (userProfileUsername) userProfileUsername.textContent = `@${profile.username || ""}`;

  if (userProfileBioSection && userProfileBio) {
    const hasBio = Boolean(profile.bio?.trim());
    userProfileBioSection.hidden = !hasBio;
    userProfileBio.textContent = hasBio ? profile.bio.trim() : "";
  }

  const hasChannel = Boolean(profile.personal_channel);
  if (userProfileChannelCard) userProfileChannelCard.hidden = !hasChannel;
  if (hasChannel) {
    const channel = profile.personal_channel;
    if (userProfileChannelAvatar) {
      userProfileChannelAvatar.replaceChildren();
      if (channel.avatar_url) {
        const image = document.createElement("img");
        image.src = channel.avatar_url;
        image.alt = "";
        userProfileChannelAvatar.appendChild(image);
      } else {
        const fallback = document.createElement("span");
        fallback.textContent = (channel.title || channel.username || "К").trim().slice(0, 2).toUpperCase();
        userProfileChannelAvatar.appendChild(fallback);
      }
    }
    if (userProfileChannelTitle) {
      userProfileChannelTitle.textContent = channel.title || (channel.username ? `@${channel.username}` : "Канал");
    }
    if (userProfileChannelTime) {
      userProfileChannelTime.textContent = channel.last_message_time || "";
      userProfileChannelTime.hidden = !channel.last_message_time;
    }
    if (userProfileChannelPreview) userProfileChannelPreview.textContent = channel.last_message_preview || "";
    if (userProfileChannelMeta) {
      userProfileChannelMeta.textContent = `Канал · ${channel.subscriber_text || "0 подписчиков"}`;
    }
    if (userProfileChannelCard) {
      userProfileChannelCard.disabled = !channel.open_url;
      userProfileChannelCard.classList.toggle("is-clickable", Boolean(channel.open_url));
    }
  }

  const hasBirthday = Boolean(profile.birthday_display);
  if (userProfileBirthdayRow) userProfileBirthdayRow.hidden = !hasBirthday;
  if (userProfileBirthday && hasBirthday) userProfileBirthday.textContent = profile.birthday_display;

  if (userProfileEdit) userProfileEdit.hidden = !profile.is_self;
  if (userProfileActions) userProfileActions.hidden = Boolean(profile.is_self);
  if (userProfileAccounts) userProfileAccounts.hidden = !profile.is_self;

  if (userProfileContact) {
    userProfileContact.textContent = profile.is_contact ? "Удалить контакт" : "Добавить в контакты";
    userProfileContact.classList.toggle("is-danger", Boolean(profile.is_contact));
  }

  setUserProfileMode("view");
  userProfileOverlay.hidden = false;
  document.body.classList.add("has-profile-overlay");
}
function channelTitleById(profile, channelId) {
  if (!channelId) return "Не выбран";
  const channel = (profile?.owned_channels || []).find(
    (item) => String(item.id) === String(channelId)
  );
  return channel?.title || (channel?.username ? `@${channel.username}` : "Не выбран");
}

function updateProfileChannelChoice(profile, channelId) {
  if (userProfileChannelInput) userProfileChannelInput.value = channelId || "";
  if (userProfileChannelChoice) {
    userProfileChannelChoice.textContent = channelTitleById(profile, channelId);
  }
}

function renderProfileChannelPicker(profile, selectedId) {
  if (!userProfileChannelList) return;
  userProfileChannelList.replaceChildren();

  const channels = profile?.owned_channels || [];
  channels.forEach((channel) => {
    const row = document.createElement("button");
    row.type = "button";
    row.className = "tg-profile-channel-option";
    row.dataset.channelId = String(channel.id);

    const avatar = document.createElement("span");
    avatar.className = "tg-profile-channel-option__avatar";
    if (channel.avatar_url) {
      const image = document.createElement("img");
      image.src = channel.avatar_url;
      image.alt = "";
      avatar.appendChild(image);
    } else {
      const fallback = document.createElement("span");
      fallback.textContent = (channel.title || channel.username || "К").trim().slice(0, 2).toUpperCase();
      avatar.appendChild(fallback);
    }

    const copy = document.createElement("span");
    copy.className = "tg-profile-channel-option__copy";
    const title = document.createElement("strong");
    title.textContent = channel.title || (channel.username ? `@${channel.username}` : `Канал #${channel.id}`);
    const username = document.createElement("small");
    username.textContent = channel.username ? `@${channel.username}` : "Канал";
    copy.append(title, username);

    const check = document.createElement("span");
    check.className = "tg-profile-channel-option__check";
    check.textContent = "✓";

    row.classList.toggle("is-selected", String(channel.id) === String(selectedId || ""));
    row.append(avatar, copy, check);
    row.addEventListener("click", () => {
      pendingProfileChannelId = String(channel.id);
      userProfileChannelList.querySelectorAll(".tg-profile-channel-option").forEach((item) => {
        item.classList.toggle("is-selected", item === row);
      });
    });

    userProfileChannelList.appendChild(row);
  });

  if (!channels.length) {
    const empty = document.createElement("div");
    empty.className = "tg-profile-channel-picker__empty";
    empty.textContent = "У вас пока нет каналов.";
    userProfileChannelList.appendChild(empty);
  }
}

function openProfileChannelPicker() {
  if (!openedProfile?.is_self || !userProfileChannelPicker) return;
  pendingProfileChannelId = openedProfile.personal_channel?.id
    ? String(openedProfile.personal_channel.id)
    : "";
  renderProfileChannelPicker(openedProfile, pendingProfileChannelId);
  userProfileChannelPicker.hidden = false;
}

function closeProfileChannelPicker() {
  if (userProfileChannelPicker) userProfileChannelPicker.hidden = true;
}

async function applyProfileChannelSelection(channelId) {
  if (!openedProfile?.is_self) return;
  const current = openedProfile.personal_channel?.id
    ? String(openedProfile.personal_channel.id)
    : "";
  if (String(channelId || "") === current) {
    closeProfileChannelPicker();
    return;
  }

  if (userProfileChannelDone) userProfileChannelDone.disabled = true;
  if (userProfileChannelRemove) userProfileChannelRemove.disabled = true;
  try {
    await saveSelfProfile({ personal_channel: channelId || "" });
    fillUserProfileEdit();
    closeProfileChannelPicker();
  } catch (error) {
    showProfileToast(profileErrorsToText(error?.profileErrors));
  } finally {
    if (userProfileChannelDone) userProfileChannelDone.disabled = false;
    if (userProfileChannelRemove) userProfileChannelRemove.disabled = false;
  }
}

function fillUserProfileEdit() {
  if (!openedProfile?.is_self) return;

  if (userProfileFirstNameInput) userProfileFirstNameInput.value = openedProfile.first_name || "";
  if (userProfileUsernameInput) userProfileUsernameInput.value = openedProfile.username || "";
  if (userProfileBirthdayInput) userProfileBirthdayInput.value = openedProfile.birthday || "";
  if (userProfileBioInput) userProfileBioInput.value = openedProfile.bio || "";
  if (userProfileBioCount) userProfileBioCount.textContent = String((openedProfile.bio || "").length);
  if (userProfileNameChoice) {
    userProfileNameChoice.textContent = openedProfile.first_name || openedProfile.display_name || "Не указано";
  }
  if (userProfileUsernameChoice) {
    userProfileUsernameChoice.textContent = openedProfile.username ? `@${openedProfile.username}` : "Не указано";
  }
  if (userProfileBirthdayChoice) {
    userProfileBirthdayChoice.textContent = openedProfile.birthday_display || "Не указан";
  }
  if (userProfileEditDisplayName) {
    userProfileEditDisplayName.textContent = openedProfile.display_name || openedProfile.username || "";
  }
  if (userProfileEditStatus) userProfileEditStatus.textContent = openedProfile.status || "";

  updateProfileChannelChoice(
    openedProfile,
    openedProfile.personal_channel?.id ? String(openedProfile.personal_channel.id) : ""
  );

  if (userProfileEditError) {
    userProfileEditError.hidden = true;
    userProfileEditError.textContent = "";
  }
  if (userProfileAvatarInput) userProfileAvatarInput.value = "";
  renderProfileAvatar(userProfileEditAvatar, openedProfile);
  if (userProfileEditAvatarOpen) userProfileEditAvatarOpen.disabled = !openedProfile.avatar_url;
}

function openProfileFieldEditor(key) {
  if (!openedProfile?.is_self || !userProfileFieldEditor || !userProfileFieldInput) return;
  profileFieldKey = key;

  const configs = {
    first_name: { title: "Имя", label: "Имя", type: "text", maxLength: 150, value: openedProfile.first_name || "" },
    username: { title: "Имя пользователя", label: "Имя пользователя", type: "text", maxLength: 150, value: openedProfile.username || "" },
    birthday: { title: "День рождения", label: "День рождения", type: "date", maxLength: 0, value: openedProfile.birthday || "" },
  };
  const config = configs[key];
  if (!config) return;

  if (userProfileFieldTitle) userProfileFieldTitle.textContent = config.title;
  if (userProfileFieldLabel) userProfileFieldLabel.textContent = config.label;
  userProfileFieldInput.type = config.type;
  userProfileFieldInput.value = config.value;
  if (config.maxLength) userProfileFieldInput.maxLength = config.maxLength;
  else userProfileFieldInput.removeAttribute("maxlength");
  if (userProfileFieldError) {
    userProfileFieldError.hidden = true;
    userProfileFieldError.textContent = "";
  }
  userProfileFieldEditor.hidden = false;
  window.setTimeout(() => {
    userProfileFieldInput.focus();
    if (config.type === "text") userProfileFieldInput.select();
  }, 0);
}

async function saveProfileFieldEditor() {
  if (!profileFieldKey || !userProfileFieldInput || !userProfileFieldSave) return;
  let value = userProfileFieldInput.value;
  if (profileFieldKey === "username") value = value.trim().replace(/^@+/, "");
  if (profileFieldKey === "first_name") value = value.trim();

  userProfileFieldSave.disabled = true;
  if (userProfileFieldError) userProfileFieldError.hidden = true;
  try {
    await saveSelfProfile({ [profileFieldKey]: value });
    fillUserProfileEdit();
    closeProfileFieldEditor();
  } catch (error) {
    if (userProfileFieldError) {
      userProfileFieldError.textContent = profileErrorsToText(error?.profileErrors);
      userProfileFieldError.hidden = false;
    }
  } finally {
    userProfileFieldSave.disabled = false;
  }
}
function profileErrorsToText(errors) {
  if (!errors || typeof errors !== "object") return "Не удалось сохранить профиль.";
  const order = [
    "avatar",
    "first_name",
    "username",
    "bio",
    "personal_channel",
    "birthday",
    "__all__",
  ];
  const used = new Set();
  const messages = [];
  [...order, ...Object.keys(errors)].forEach((key) => {
    if (used.has(key) || !errors[key]) return;
    used.add(key);
    errors[key].forEach((item) => {
      if (item?.message) messages.push(item.message);
    });
  });
  return messages.join(" ") || "Проверьте введённые данные.";
}

async function openUserProfile(url) {
  if (!userProfileOverlay || !url) {
    window.location.assign(url);
    return;
  }

  try {
    const response = await fetch(url, {
      headers: { "X-Requested-With": "XMLHttpRequest" },
      credentials: "same-origin",
    });
    if (!response.ok) throw new Error("profile fetch failed");
    const profile = await response.json();
    if (!profile.ok) throw new Error("invalid profile payload");
    if (!profile.profile_url) profile.profile_url = url;
    renderUserProfile(profile);
    startProfileRefresh();
  } catch (_error) {
    window.location.assign(url);
  }
}

document.querySelectorAll("[data-user-profile]").forEach((link) => {
  link.addEventListener("click", (event) => {
    if (event.button !== 0 || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
    event.preventDefault();
    if (typeof setProfileMenu === "function") setProfileMenu(false);
    openUserProfile(link.href);
  });
});

userProfileClose?.addEventListener("click", () => {
  void closeUserProfile();
});
userProfileEditClose?.addEventListener("click", () => {
  void closeUserProfile();
});

userProfileOverlay?.addEventListener("click", (event) => {
  if (event.target === userProfileOverlay) void closeUserProfile();
});

userProfileAvatar?.addEventListener("click", openProfilePhotoViewer);
userProfileEditAvatarOpen?.addEventListener("click", openProfilePhotoViewer);
userProfilePhotoClose?.addEventListener("click", closeProfilePhotoViewer);
userProfilePhotoViewer?.addEventListener("click", (event) => {
  if (event.target === userProfilePhotoViewer) closeProfilePhotoViewer();
});

userProfilePhotoRemove?.addEventListener("click", async () => {
  if (!openedProfile?.is_self || !openedProfile.remove_avatar_url) return;
  if (!window.confirm("Удалить фотографию профиля?")) return;

  userProfilePhotoRemove.disabled = true;
  try {
    const body = new URLSearchParams();
    body.set("csrfmiddlewaretoken", csrfToken());
    const response = await fetch(openedProfile.remove_avatar_url, {
      method: "POST",
      headers: {
        "X-Requested-With": "XMLHttpRequest",
        "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8",
      },
      body,
      credentials: "same-origin",
    });
    const payload = await response.json();
    if (!response.ok || !payload.ok) throw new Error("avatar remove failed");

    openedProfile.avatar_url = "";
    openedProfile.initials = payload.initials || openedProfile.initials;
    renderProfileAvatar(userProfileAvatar, openedProfile);
    renderProfileAvatar(userProfileEditAvatar, openedProfile);
    if (userProfileAvatar) {
      userProfileAvatar.disabled = true;
      userProfileAvatar.classList.remove("is-clickable");
    }
    if (userProfileEditAvatarOpen) userProfileEditAvatarOpen.disabled = true;
    closeProfilePhotoViewer();
  } catch (_error) {
    showProfileToast("Не удалось удалить фото.");
  } finally {
    userProfilePhotoRemove.disabled = false;
  }
});

userProfileUsernameRow?.addEventListener("click", () => {
  if (!openedProfile?.username) return;
  const relative = openedProfile.profile_url || `/u/${encodeURIComponent(openedProfile.username)}/`;
  const absolute = new URL(relative, window.location.origin).href;
  void copyProfileText(absolute, "Ссылка на профиль скопирована");
});

userProfileChannelCard?.addEventListener("click", () => {
  const channel = openedProfile?.personal_channel;
  if (!channel?.open_url) return;

  if (channel.open_method === "post") {
    const form = document.createElement("form");
    form.method = "post";
    form.action = channel.open_url;

    const token = document.createElement("input");
    token.type = "hidden";
    token.name = "csrfmiddlewaretoken";
    token.value = csrfToken();

    form.appendChild(token);
    document.body.appendChild(form);
    form.submit();
    return;
  }

  window.location.assign(channel.open_url);
});

userProfileEdit?.addEventListener("click", () => {
  if (!openedProfile?.is_self) return;
  fillUserProfileEdit();
  setUserProfileMode("edit");
});

userProfileEditBack?.addEventListener("click", async () => {
  if (!openedProfile) return;
  try {
    await flushBioSave();
  } catch (_error) {
    return;
  }
  renderUserProfile(openedProfile);
});

userProfileNameOpen?.addEventListener("click", () => openProfileFieldEditor("first_name"));
userProfileUsernameOpen?.addEventListener("click", () => openProfileFieldEditor("username"));
userProfileBirthdayOpen?.addEventListener("click", () => openProfileFieldEditor("birthday"));

userProfileFieldClose?.addEventListener("click", closeProfileFieldEditor);
userProfileFieldCancel?.addEventListener("click", closeProfileFieldEditor);
userProfileFieldSave?.addEventListener("click", () => {
  void saveProfileFieldEditor();
});
userProfileFieldEditor?.addEventListener("click", (event) => {
  if (event.target === userProfileFieldEditor) closeProfileFieldEditor();
});
userProfileFieldInput?.addEventListener("keydown", (event) => {
  if (event.key === "Enter") {
    event.preventDefault();
    void saveProfileFieldEditor();
  }
});

userProfileChannelOpen?.addEventListener("click", openProfileChannelPicker);
userProfileChannelDone?.addEventListener("click", () => {
  void applyProfileChannelSelection(pendingProfileChannelId);
});
userProfileChannelRemove?.addEventListener("click", () => {
  void applyProfileChannelSelection("");
});
userProfileChannelPicker?.addEventListener("click", (event) => {
  if (event.target === userProfileChannelPicker) closeProfileChannelPicker();
});

userProfileBioInput?.addEventListener("input", () => {
  if (userProfileBioCount) {
    userProfileBioCount.textContent = String(userProfileBioInput.value.length);
  }
  if (profileBioSaveTimer) window.clearTimeout(profileBioSaveTimer);
  profileBioSaveTimer = window.setTimeout(() => {
    profileBioSaveTimer = 0;
    void flushBioSave();
  }, 1000);
});
userProfileBioInput?.addEventListener("blur", () => {
  void flushBioSave();
});

userProfileAvatarInput?.addEventListener("change", async () => {
  const file = userProfileAvatarInput.files?.[0];
  if (!file || !userProfileEditAvatar) return;

  if (profileAvatarPreviewUrl) URL.revokeObjectURL(profileAvatarPreviewUrl);
  profileAvatarPreviewUrl = URL.createObjectURL(file);

  userProfileEditAvatar.replaceChildren();
  const image = document.createElement("img");
  image.src = profileAvatarPreviewUrl;
  image.alt = "";
  userProfileEditAvatar.appendChild(image);

  try {
    await saveSelfProfile({}, file);
    if (profileAvatarPreviewUrl) URL.revokeObjectURL(profileAvatarPreviewUrl);
    profileAvatarPreviewUrl = "";
    fillUserProfileEdit();
  } catch (error) {
    showProfileToast(profileErrorsToText(error?.profileErrors));
    renderProfileAvatar(userProfileEditAvatar, openedProfile);
  } finally {
    if (userProfileAvatarInput) userProfileAvatarInput.value = "";
  }
});

userProfileEditForm?.addEventListener("submit", (event) => {
  event.preventDefault();
  void flushBioSave();
});

userProfileMessage?.addEventListener("click", () => {
  if (!openedProfile?.start_chat_url) return;

  const form = document.createElement("form");
  form.method = "post";
  form.action = openedProfile.start_chat_url;

  const token = document.createElement("input");
  token.type = "hidden";
  token.name = "csrfmiddlewaretoken";
  token.value = csrfToken();

  form.appendChild(token);
  document.body.appendChild(form);
  form.submit();
});

userProfileContact?.addEventListener("click", async () => {
  if (!openedProfile) return;

  const removing = Boolean(openedProfile.is_contact);
  if (removing && !window.confirm("Удалить пользователя из контактов?")) return;
  const url = removing ? openedProfile.remove_contact_url : openedProfile.add_contact_url;
  if (!url) return;

  userProfileContact.disabled = true;
  try {
    const body = new URLSearchParams();
    body.set("csrfmiddlewaretoken", csrfToken());
    const response = await fetch(url, {
      method: "POST",
      headers: {
        "X-Requested-With": "XMLHttpRequest",
        "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8",
      },
      body,
      credentials: "same-origin",
    });
    if (!response.ok) throw new Error("contact action failed");

    openedProfile.is_contact = !removing;
    userProfileContact.textContent = openedProfile.is_contact ? "Удалить контакт" : "Добавить в контакты";
    userProfileContact.classList.toggle("is-danger", openedProfile.is_contact);
  } catch (_error) {
    showProfileToast("Не удалось изменить контакт.");
  } finally {
    userProfileContact.disabled = false;
  }
});

document.addEventListener("keydown", (event) => {
  if (event.key !== "Escape") return;

  if (userProfilePhotoViewer && !userProfilePhotoViewer.hidden) {
    closeProfilePhotoViewer();
    return;
  }
  if (userProfileFieldEditor && !userProfileFieldEditor.hidden) {
    closeProfileFieldEditor();
    return;
  }
  if (userProfileChannelPicker && !userProfileChannelPicker.hidden) {
    closeProfileChannelPicker();
    return;
  }
  if (userProfileEditForm && !userProfileEditForm.hidden) {
    event.preventDefault();
    void (async () => {
      try {
        await flushBioSave();
      } catch (_error) {
        return;
      }
      if (openedProfile) renderUserProfile(openedProfile);
    })();
    return;
  }
  if (userProfileOverlay && !userProfileOverlay.hidden) {
    void closeUserProfile();
  }
});
