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
const userProfileClose = document.getElementById("userProfileClose");
const userProfileAvatar = document.getElementById("userProfileAvatar");
const userProfileName = document.getElementById("userProfileName");
const userProfileStatus = document.getElementById("userProfileStatus");
const userProfileBioSection = document.getElementById("userProfileBioSection");
const userProfileBio = document.getElementById("userProfileBio");
const userProfileUsername = document.getElementById("userProfileUsername");
const userProfileActions = document.getElementById("userProfileActions");
const userProfileMessage = document.getElementById("userProfileMessage");
const userProfileContact = document.getElementById("userProfileContact");

let openedProfile = null;

function csrfToken() {
  return document.querySelector('input[name="csrfmiddlewaretoken"]')?.value || "";
}

function closeUserProfile() {
  if (!userProfileOverlay) return;
  userProfileOverlay.hidden = true;
  openedProfile = null;
  document.body.classList.remove("has-profile-overlay");
}

function renderUserProfile(profile) {
  if (!userProfileOverlay) return;
  openedProfile = profile;

  if (userProfileAvatar) {
    userProfileAvatar.replaceChildren();
    if (profile.avatar_url) {
      const image = document.createElement("img");
      image.src = profile.avatar_url;
      image.alt = "";
      userProfileAvatar.appendChild(image);
    } else {
      const fallback = document.createElement("span");
      fallback.textContent = profile.initials || "?";
      userProfileAvatar.appendChild(fallback);
    }
  }

  if (userProfileName) userProfileName.textContent = profile.display_name || profile.username || "";
  if (userProfileStatus) userProfileStatus.textContent = profile.status || "";
  if (userProfileUsername) userProfileUsername.textContent = `@${profile.username || ""}`;

  if (userProfileBioSection && userProfileBio) {
    const hasBio = Boolean(profile.bio?.trim());
    userProfileBioSection.hidden = !hasBio;
    userProfileBio.textContent = hasBio ? profile.bio.trim() : "";
  }

  if (userProfileActions) userProfileActions.hidden = Boolean(profile.is_self);
  if (userProfileContact) {
    userProfileContact.textContent = profile.is_contact
      ? "Удалить из контактов"
      : "Добавить в контакты";
    userProfileContact.classList.toggle("is-danger", Boolean(profile.is_contact));
  }

  userProfileOverlay.hidden = false;
  document.body.classList.add("has-profile-overlay");
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
    openUserProfile(link.href);
  });
});

userProfileClose?.addEventListener("click", closeUserProfile);

userProfileOverlay?.addEventListener("click", (event) => {
  if (event.target === userProfileOverlay) closeUserProfile();
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
  if (event.key === "Escape" && userProfileOverlay && !userProfileOverlay.hidden) {
    closeUserProfile();
  }
});
