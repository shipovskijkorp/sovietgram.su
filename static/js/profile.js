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
  if (open) {
    const accountToggle = document.getElementById("profileAccountToggleInput");
    if (accountToggle) accountToggle.checked = false;
  }
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

