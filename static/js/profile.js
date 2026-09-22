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
const userProfileEditDisplayName = document.getElementById("userProfileEditDisplayName");
const userProfileEditStatus = document.getElementById("userProfileEditStatus");
const userProfileFirstNameInput = document.getElementById("userProfileFirstNameInput");
const userProfileUsernameInput = document.getElementById("userProfileUsernameInput");
const userProfileChannelInput = document.getElementById("userProfileChannelInput");
const userProfileChannelOpen = document.getElementById("userProfileChannelOpen");
const userProfileChannelChoice = document.getElementById("userProfileChannelChoice");
const userProfileChannelPicker = document.getElementById("userProfileChannelPicker");
const userProfileChannelList = document.getElementById("userProfileChannelList");
const userProfileChannelRemove = document.getElementById("userProfileChannelRemove");
const userProfileChannelDone = document.getElementById("userProfileChannelDone");
const userProfileBirthdayInput = document.getElementById("userProfileBirthdayInput");
const userProfileBioInput = document.getElementById("userProfileBioInput");
const userProfileBioCount = document.getElementById("userProfileBioCount");
const userProfileEditError = document.getElementById("userProfileEditError");

let openedProfile = null;
let profileAvatarPreviewUrl = "";
let pendingProfileChannelId = "";

function csrfToken() {
  return document.querySelector('input[name="csrfmiddlewaretoken"]')?.value || "";
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

function closeUserProfile() {
  if (!userProfileOverlay) return;
  if (userProfileChannelPicker) userProfileChannelPicker.hidden = true;
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
    if (userProfileChannelPreview) {
      userProfileChannelPreview.textContent = channel.last_message_preview || "";
    }
    if (userProfileChannelMeta) {
      userProfileChannelMeta.textContent = `Канал · ${channel.subscriber_text || "0 подписчиков"}`;
    }
  }

  const hasBirthday = Boolean(profile.birthday_display);
  if (userProfileBirthdayRow) userProfileBirthdayRow.hidden = !hasBirthday;
  if (userProfileBirthday && hasBirthday) {
    userProfileBirthday.textContent = profile.birthday_display;
  }

  if (userProfileEdit) userProfileEdit.hidden = !profile.is_self;
  if (userProfileActions) userProfileActions.hidden = Boolean(profile.is_self);
  if (userProfileAccounts) userProfileAccounts.hidden = !profile.is_self;

  if (userProfileContact) {
    userProfileContact.textContent = profile.is_contact
      ? "Удалить из контактов"
      : "Добавить в контакты";
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
  pendingProfileChannelId = userProfileChannelInput?.value || "";
  renderProfileChannelPicker(openedProfile, pendingProfileChannelId);
  userProfileChannelPicker.hidden = false;
}

function closeProfileChannelPicker(applySelection = false) {
  if (!userProfileChannelPicker) return;
  if (applySelection) {
    updateProfileChannelChoice(openedProfile, pendingProfileChannelId);
  }
  userProfileChannelPicker.hidden = true;
}

function fillUserProfileEdit() {
  if (!openedProfile?.is_self) return;

  if (userProfileFirstNameInput) userProfileFirstNameInput.value = openedProfile.first_name || "";
  if (userProfileUsernameInput) userProfileUsernameInput.value = openedProfile.username || "";
  if (userProfileBirthdayInput) userProfileBirthdayInput.value = openedProfile.birthday || "";
  if (userProfileBioInput) userProfileBioInput.value = openedProfile.bio || "";
  if (userProfileBioCount) userProfileBioCount.textContent = String((openedProfile.bio || "").length);
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
    renderUserProfile(profile);
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

userProfileClose?.addEventListener("click", closeUserProfile);
userProfileEditClose?.addEventListener("click", closeUserProfile);

userProfileOverlay?.addEventListener("click", (event) => {
  if (event.target === userProfileOverlay) closeUserProfile();
});

userProfileEdit?.addEventListener("click", () => {
  if (!openedProfile?.is_self) return;
  fillUserProfileEdit();
  setUserProfileMode("edit");
});

userProfileEditBack?.addEventListener("click", () => {
  if (!openedProfile) return;
  renderUserProfile(openedProfile);
});

userProfileChannelOpen?.addEventListener("click", openProfileChannelPicker);

userProfileChannelDone?.addEventListener("click", () => {
  closeProfileChannelPicker(true);
});

userProfileChannelRemove?.addEventListener("click", () => {
  pendingProfileChannelId = "";
  closeProfileChannelPicker(true);
});

userProfileChannelPicker?.addEventListener("click", (event) => {
  if (event.target === userProfileChannelPicker) {
    closeProfileChannelPicker(false);
  }
});

userProfileBioInput?.addEventListener("input", () => {
  if (userProfileBioCount) {
    userProfileBioCount.textContent = String(userProfileBioInput.value.length);
  }
});

userProfileAvatarInput?.addEventListener("change", () => {
  const file = userProfileAvatarInput.files?.[0];
  if (!file || !userProfileEditAvatar) return;

  if (profileAvatarPreviewUrl) URL.revokeObjectURL(profileAvatarPreviewUrl);
  profileAvatarPreviewUrl = URL.createObjectURL(file);

  userProfileEditAvatar.replaceChildren();
  const image = document.createElement("img");
  image.src = profileAvatarPreviewUrl;
  image.alt = "";
  userProfileEditAvatar.appendChild(image);
});

userProfileEditForm?.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (!openedProfile?.is_self || !openedProfile.edit_url) return;

  const submit = document.getElementById("userProfileEditSave");
  if (submit) submit.disabled = true;
  if (userProfileEditError) {
    userProfileEditError.hidden = true;
    userProfileEditError.textContent = "";
  }

  try {
    const response = await fetch(openedProfile.edit_url, {
      method: "POST",
      body: new FormData(userProfileEditForm),
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

    renderUserProfile(openedProfile);

    document.querySelectorAll(".account-mini__name").forEach((element) => {
      element.textContent = payload.display_name;
    });
    document.querySelectorAll(".profile-account-header__bottom strong").forEach((element) => {
      element.textContent = payload.display_name;
    });
  } catch (error) {
    if (userProfileEditError) {
      userProfileEditError.textContent = profileErrorsToText(error?.profileErrors);
      userProfileEditError.hidden = false;
    }
  } finally {
    if (submit) submit.disabled = false;
  }
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

  const url = openedProfile.is_contact
    ? openedProfile.remove_contact_url
    : openedProfile.add_contact_url;
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

    openedProfile.is_contact = !openedProfile.is_contact;
    userProfileContact.textContent = openedProfile.is_contact
      ? "Удалить из контактов"
      : "Добавить в контакты";
    userProfileContact.classList.toggle("is-danger", openedProfile.is_contact);
  } catch (_error) {
    if (typeof showToast === "function") showToast("Не удалось изменить контакт.");
  } finally {
    userProfileContact.disabled = false;
  }
});

document.addEventListener("keydown", (event) => {
  if (event.key !== "Escape") return;
  if (userProfileChannelPicker && !userProfileChannelPicker.hidden) {
    closeProfileChannelPicker(false);
    return;
  }
  if (userProfileOverlay && !userProfileOverlay.hidden) {
    closeUserProfile();
  }
});
