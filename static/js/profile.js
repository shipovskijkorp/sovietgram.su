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
const userProfileChannelContext = document.getElementById("userProfileChannelContext");
const userProfileChannelContextRemove = document.getElementById("userProfileChannelContextRemove");
const userProfileBirthdayRow = document.getElementById("userProfileBirthdayRow");
const userProfileBirthday = document.getElementById("userProfileBirthday");
const userProfileActions = document.getElementById("userProfileActions");
const userProfileAccounts = document.getElementById("userProfileAccounts");
const userProfileMessage = document.getElementById("userProfileMessage");
const userProfileContact = document.getElementById("userProfileContact");
const peerProfileElements = Object.fromEntries([
  "Mute", "MuteLabel", "MuteMenu", "Unmute", "More", "MoreMenu", "AutoDelete",
  "AutoDeleteLabel", "TimerOptions", "MenuContact", "MenuContactLabel", "ContactLabel",
  "RenameContact", "AliasEditor", "AliasInput", "AliasSave", "AliasReset", "OriginalNameRow", "OriginalName",
  "Protection", "ProtectionLabel", "CopyLink", "Report", "Block", "BlockSection",
  "BlockLabel", "MenuBlock", "MenuBlockLabel", "CommonGroups", "CommonGroupsLabel", "CommonGroupsList",
].map(key => [key, document.getElementById("userProfile" + key)]));
let peerProfileActionBusy = false;
let peerProfileActionVersion = 0;

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
let profilePhotoId = null, profileEmojiTimer = 0;
let profileAvatarPreviewUrl = "";
let pendingProfileChannelId = "";
let profileFieldKey = "";
let profileBioSaveTimer = 0;
let profileBioSaveInFlight = null;
let profileRefreshTimer = 0;
let profileRefreshBusy = false;

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
    let copied = false;
    try { copied = document.execCommand("copy"); }
    catch (_error) { /* Clipboard access can be denied. */ }
    finally { input.remove(); }
    if (!copied) {
      showProfileToast("Не удалось скопировать. Скопируйте ссылку вручную.");
      return;
    }
  }
  showProfileToast(successText);
}

function updateGlobalSelfIdentity(payload) {
  if (!payload) return;
  if (payload.display_name) {
    document.querySelectorAll(".account-mini__name").forEach((element) => {
      element.textContent = payload.display_name;
    });
    document.querySelectorAll(".profile-account-header__bottom strong").forEach((element) => {
      element.textContent = payload.display_name;
    });
  }
  if (payload.profile_url) {
    document.querySelectorAll("[data-self-profile]").forEach((link) => {
      link.href = payload.profile_url;
    });
  }
  if (
    payload.user_id != null
    && Object.prototype.hasOwnProperty.call(payload, "avatar_url")
  ) {
    window.SovietgramAvatarSync?.updateUser(
      payload.user_id, payload.avatar_url || "", payload.initials || "?",
    );
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
  // Django rejects overlay saves without CSRF protection, including birthdays and bios.
  const token = userProfileEditForm?.querySelector("[name='csrfmiddlewaretoken']")?.value || csrfToken();
  body.set("csrfmiddlewaretoken", token);
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
  const payload = await response.json().catch(() => null);
  if (!response.ok || !payload?.ok) {
    const error = new Error("Не удалось сохранить профиль.");
    error.profileErrors = payload?.errors;
    throw error;
  }

  openedProfile = {
    ...openedProfile,
    ...payload,
    is_self: true,
    edit_url: openedProfile.edit_url,
    owned_channels: openedProfile.owned_channels || [],
  };
  renderProfileAvatar(userProfileAvatar, openedProfile);
  renderProfileAvatar(userProfileEditAvatar, openedProfile);
  refreshProfileExtras(openedProfile);
  updateGlobalSelfIdentity(payload);
  updateProfileHistory(openedProfile.username || "");
  return payload;
}

function renderProfileAvatar(target, profile) {
  if (!target) return;
  target.replaceChildren();
  if (profile.avatar_url) {
    const image = document.createElement("img");
    image.src = profile.avatar_url;
    image.alt = "";
    if (profile.id != null) image.dataset.avatarUserId = String(profile.id);
    target.appendChild(image);
    return;
  }
  const fallback = document.createElement("span");
  if (profile.id != null) fallback.dataset.avatarUserId = String(profile.id);
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

function formatProfileLastSeen(profile, now = new Date()) {
  // Privacy-restricted profiles only expose approximate text from Django.
  if (!profile?.last_seen_exact) return profile?.status || "был(а) давно";
  if (profile.is_online) return "в сети";
  if (!profile.last_seen_at) return profile.status || "был(а) давно";

  const seen = new Date(profile.last_seen_at);
  if (!Number.isFinite(seen.getTime())) return profile.status || "был(а) давно";
  const startToday = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const startYesterday = new Date(startToday);
  startYesterday.setDate(startYesterday.getDate() - 1);
  const time = new Intl.DateTimeFormat("ru-RU", {
    hour: "2-digit", minute: "2-digit", hour12: false,
  }).format(seen);
  if (seen >= startToday) return `был(а) сегодня в ${time}`;
  if (seen >= startYesterday) return `был(а) вчера в ${time}`;
  const date = new Intl.DateTimeFormat("ru-RU", {
    day: "2-digit", month: "2-digit", year: "numeric",
  }).format(seen);
  return `был(а) ${date} в ${time}`;
}

function updateProfilePresence(profile) {
  const status = formatProfileLastSeen(profile);
  if (userProfileStatus) {
    userProfileStatus.textContent = status;
    userProfileStatus.classList.toggle("is-online", Boolean(profile?.is_online && profile?.last_seen_exact));
  }
  if (userProfileEditStatus) userProfileEditStatus.textContent = status;
}

async function refreshProfilePresence() {
  const profileUrl = openedProfile?.profile_url;
  if (!profileUrl || userProfileOverlay?.hidden || document.hidden || profileRefreshBusy || peerProfileActionBusy) return;
  profileRefreshBusy = true;
  const target = openedProfile;
  const actionVersion = peerProfileActionVersion;
  try {
    const response = await fetch(profileUrl, {
      headers: { "X-Requested-With": "XMLHttpRequest" },
      credentials: "same-origin",
      cache: "no-store",
    });
    if (!response.ok) return;
    const fresh = await response.json();
    if (!fresh.ok || openedProfile !== target || userProfileOverlay.hidden || peerProfileActionBusy
        || peerProfileActionVersion !== actionVersion || openedProfile.profile_url !== profileUrl) return;
    if (fresh.viewer_id != null && document.body?.dataset?.accountId &&
        String(fresh.viewer_id) !== document.body.dataset.accountId) {
      await closeUserProfile();
      showProfileToast("Аккаунт изменился. Обновите страницу.");
      return;
    }

    openedProfile.status = fresh.status;
    openedProfile.is_online = fresh.is_online;
    openedProfile.last_seen_exact = fresh.last_seen_exact;
    openedProfile.last_seen_at = fresh.last_seen_at;
    openedProfile.is_contact = fresh.is_contact;
    if (!openedProfile.is_self) {
      for (const key of ["bio", "birthday", "birthday_display", "start_chat_url", "is_blocked",
        "blocked_by_me", "direct_chat", "common_groups", "report_url", "block_url",
        "contact_alias", "contact_name", "rename_contact_url", "display_name"]) {
        if (Object.prototype.hasOwnProperty.call(fresh, key)) openedProfile[key] = fresh[key];
      }
      renderPeerProfileDetails(openedProfile);
      renderPeerProfileActions(openedProfile);
    }

    if (Object.prototype.hasOwnProperty.call(fresh, "avatar_url")) {
      const avatarChanged = (openedProfile.avatar_url || "") !== (fresh.avatar_url || "");
      openedProfile.avatar_url = fresh.avatar_url || "";
      openedProfile.initials = fresh.initials || openedProfile.initials;
      openedProfile.display_name = fresh.display_name || openedProfile.display_name;
      if (avatarChanged) {
        renderProfileAvatar(userProfileAvatar, openedProfile);
        renderProfileAvatar(userProfileEditAvatar, openedProfile);
        if (userProfileAvatar) {
          userProfileAvatar.disabled = !openedProfile.avatar_url;
          userProfileAvatar.classList.toggle("is-clickable", Boolean(openedProfile.avatar_url));
        }
        if (userProfileEditAvatarOpen) {
          userProfileEditAvatarOpen.disabled = !openedProfile.avatar_url;
        }
        // The gallery refresh below preserves the selected archived photo.
      }
      if (fresh.id != null) {
        window.SovietgramAvatarSync?.updateUser(
          fresh.id, openedProfile.avatar_url, openedProfile.initials,
        );
      }
      if (openedProfile.is_self) {
        updateGlobalSelfIdentity({
          user_id: fresh.id,
          display_name: openedProfile.display_name,
          avatar_url: openedProfile.avatar_url,
          initials: openedProfile.initials,
          profile_url: fresh.profile_url,
        });
      }
    }
    openedProfile.profile_photos = fresh.profile_photos || [];
    openedProfile.emoji_status = fresh.emoji_status || {emoji:"",until:""};
    refreshProfileExtras(openedProfile);
    if (Object.prototype.hasOwnProperty.call(fresh, "personal_channel")) {
      const previousChannel = openedProfile.personal_channel;
      const nextChannel = fresh.personal_channel;
      const channelChanged = (
        previousChannel?.id !== nextChannel?.id
        || previousChannel?.avatar_url !== nextChannel?.avatar_url
        || previousChannel?.title !== nextChannel?.title
        || previousChannel?.username !== nextChannel?.username
        || previousChannel?.last_message_time !== nextChannel?.last_message_time
        || previousChannel?.last_message_preview !== nextChannel?.last_message_preview
        || previousChannel?.subscriber_text !== nextChannel?.subscriber_text
      );
      openedProfile.personal_channel = nextChannel;
      if (channelChanged) renderProfilePersonalChannel(nextChannel);
      if (nextChannel?.id != null) {
        window.SovietgramAvatarSync?.updateChat(
          nextChannel.id,
          nextChannel.avatar_url || "",
          (nextChannel.title || nextChannel.username || "К").trim().slice(0, 2).toUpperCase(),
        );
      }
    }
    updateProfilePresence(openedProfile);
  } catch (_error) {
    // The next refresh retries automatically.
  } finally {
    profileRefreshBusy = false;
  }
}

function startProfileRefresh() {
  stopProfileRefresh();
  profileRefreshTimer = window.setInterval(() => { void refreshProfilePresence(); }, 10000);
}

document.addEventListener("visibilitychange", () => {
  if (!document.hidden) void refreshProfilePresence();
});
window.addEventListener?.("focus", () => { void refreshProfilePresence(); });

function closeProfileChannelContext() {
  if (userProfileChannelContext) userProfileChannelContext.hidden = true;
}

function openProfileChannelContext(event) {
  if (!openedProfile?.is_self || !openedProfile.personal_channel || !userProfileChannelContext) return;
  event.preventDefault();
  userProfileChannelContext.hidden = false;

  const width = 170;
  const height = 44;
  const left = Math.min(event.clientX, window.innerWidth - width - 8);
  const top = Math.min(event.clientY, window.innerHeight - height - 8);
  userProfileChannelContext.style.left = `${Math.max(8, left)}px`;
  userProfileChannelContext.style.top = `${Math.max(8, top)}px`;
}

function profilePhotos(profile=openedProfile){
  if(!profile)return [];
  if(Array.isArray(profile.profile_photos))return profile.profile_photos;
  return profile.avatar_url?[{id:"current",url:profile.avatar_url,current:true}]:[];
}
function currentProfileEmoji(profile){
  const status=profile?.emoji_status;
  if(!status?.emoji||status.until&&Date.parse(status.until)<=Date.now())return "";
  return status.emoji;
}
function refreshProfileExtras(profile){
  const photos=profilePhotos(profile);
  const gallery=document.getElementById("userProfileGalleryOpen");
  const count=document.getElementById("userProfileGalleryCount");
  const manage=document.getElementById("userProfileGalleryManage");
  const emojiEdit=document.getElementById("userProfileEmojiEdit");
  if(gallery)gallery.hidden=!photos.length;
  if(count)count.textContent=String(photos.length);
  if(manage){
    manage.hidden=!profile.is_self||!profile.gallery_manage_url;
    if(manage.hidden)manage.removeAttribute("href");else manage.href=profile.gallery_manage_url;
  }
  if(emojiEdit){
    emojiEdit.hidden=!profile.is_self||!profile.emoji_status_url;
    if(emojiEdit.hidden)emojiEdit.removeAttribute("href");else emojiEdit.href=profile.emoji_status_url;
  }
  const emoji=currentProfileEmoji(profile);
  const badge=document.getElementById("userProfileEmojiStatus");
  if(badge){badge.textContent=emoji;badge.hidden=!emoji;badge.title=emoji?"Emoji-статус":"";}
  const label=document.getElementById("userProfileEmojiEditLabel");
  if(label)label.textContent=emoji?emoji+" · Изменить emoji-статус":"Установить emoji-статус";
  window.clearTimeout(profileEmojiTimer);
  const until=Date.parse(profile.emoji_status?.until||"");
  if(emoji&&Number.isFinite(until)&&until>Date.now()){
    profileEmojiTimer=window.setTimeout(()=>{if(openedProfile===profile)refreshProfileExtras(profile);},Math.min(2147483647,until-Date.now()+100));
  }
  if(userProfileAvatar){userProfileAvatar.disabled=!photos.length;userProfileAvatar.classList.toggle("is-clickable",Boolean(photos.length));}
  if(userProfileEditAvatarOpen)userProfileEditAvatarOpen.disabled=!photos.length;
  if(userProfilePhotoViewer&&!userProfilePhotoViewer.hidden){
    if(photos.some(photo=>photo.id===profilePhotoId))renderProfilePhoto(profilePhotoId);
    else closeProfilePhotoViewer(); // Recheck permission / publication on every refresh.
  }
}
function closeProfilePhotoViewer() {
  if (!userProfilePhotoViewer) return;
  userProfilePhotoViewer.hidden = true;
  profilePhotoId=null;
  if (userProfilePhotoImage) userProfilePhotoImage.removeAttribute("src");
}
function renderProfilePhoto(id){
  const photos=profilePhotos();
  const index=photos.findIndex(photo=>photo.id===id);
  if(index<0||!userProfilePhotoViewer||!userProfilePhotoImage)return;
  const photo=photos[index];
  profilePhotoId=photo.id;
  if(userProfilePhotoImage.getAttribute("src")!==photo.url)userProfilePhotoImage.src=photo.url;
  userProfilePhotoImage.alt=photo.current?"Текущая фотография профиля":"Фотография профиля";
  const controls=document.getElementById("userProfilePhotoControls");
  if(controls){
    controls.hidden=photos.length<2;
    document.getElementById("userProfilePhotoPrev").disabled=index===0;
    document.getElementById("userProfilePhotoNext").disabled=index===photos.length-1;
    document.getElementById("userProfilePhotoPosition").textContent=(index+1)+" / "+photos.length;
  }
  if(userProfilePhotoRemove)userProfilePhotoRemove.hidden=!(photo.current&&openedProfile.is_self&&openedProfile.remove_avatar_url);
}
function openProfilePhotoViewer(){
  const photo=profilePhotos()[0];
  if(!photo||!userProfilePhotoViewer)return;
  renderProfilePhoto(photo.id);
  userProfilePhotoViewer.hidden=false;
}
function stepProfilePhoto(offset){
  const photos=profilePhotos(),index=photos.findIndex(photo=>photo.id===profilePhotoId);
  if(index<0)return;
  if(photos[index+offset])renderProfilePhoto(photos[index+offset].id);
}
document.getElementById("userProfilePhotoPrev")?.addEventListener("click",()=>stepProfilePhoto(-1));
document.getElementById("userProfilePhotoNext")?.addEventListener("click",()=>stepProfilePhoto(1));
document.getElementById("userProfileGalleryOpen")?.addEventListener("click",openProfilePhotoViewer);
userProfilePhotoViewer?.addEventListener("keydown",event=>{
  if(event.key==="ArrowLeft"||event.key==="ArrowRight"){
    event.preventDefault();event.stopPropagation();stepProfilePhoto(event.key==="ArrowLeft"?-1:1);
  }
});
userProfilePhotoImage?.addEventListener("error",()=>{
  if(!userProfilePhotoViewer?.hidden){closeProfilePhotoViewer();showProfileToast("Фотография больше недоступна.");}
});

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

  // Blur, debounce and the close button can trigger the same save at once.
  // Share the pending request and save any text typed while it was in flight.
  if (profileBioSaveInFlight) {
    if (!await profileBioSaveInFlight) return false;
  }
  if (!openedProfile?.is_self || !userProfileBioInput) return true;

  const bio = userProfileBioInput.value;
  if (bio === (openedProfile.bio || "")) return true;

  const saving = (async () => {
    try {
      await saveSelfProfile({ bio });
      if (userProfileEditError) userProfileEditError.hidden = true;
      return true;
    } catch (error) {
      if (userProfileEditError) {
        userProfileEditError.textContent = profileErrorsToText(error?.profileErrors);
        userProfileEditError.hidden = false;
      }
      return false;
    }
  })();
  profileBioSaveInFlight = saving;
  try {
    return await saving;
  } finally {
    if (profileBioSaveInFlight === saving) profileBioSaveInFlight = null;
  }
}

async function closeUserProfile() {
  if (!userProfileOverlay) return;
  if (userProfileEditForm && !userProfileEditForm.hidden) {
    if (!await flushBioSave()) {
      showProfileToast("Не удалось сохранить «О себе». Изменения не сохранены.");
    }
  }
  closeProfileFieldEditor();
  closeProfilePhotoViewer();
  window.clearTimeout(profileEmojiTimer);
  closeProfileChannelContext();
  closePeerProfileMenus();
  if (peerProfileElements.CommonGroups) peerProfileElements.CommonGroups.open = false;
  if (userProfileChannelPicker) userProfileChannelPicker.hidden = true;
  stopProfileRefresh();
  userProfileOverlay.hidden = true;
  setUserProfileMode("view");
  updateProfileHistory("");
  openedProfile = null;
  if (profileAvatarPreviewUrl) URL.revokeObjectURL(profileAvatarPreviewUrl);
  profileAvatarPreviewUrl = "";
  document.body.classList.remove("has-profile-overlay");
}

function renderProfilePersonalChannel(channel) {
  const hasChannel = Boolean(channel);
  if (userProfileChannelCard) userProfileChannelCard.hidden = !hasChannel;
  if (!hasChannel) {
    userProfileChannelAvatar?.replaceChildren();
    return;
  }
  if (userProfileChannelAvatar) {
    userProfileChannelAvatar.replaceChildren();
    if (channel.avatar_url) {
      const image = document.createElement("img");
      image.src = channel.avatar_url;
      image.alt = "";
      image.dataset.avatarChatId = String(channel.id);
      userProfileChannelAvatar.appendChild(image);
    } else {
      const fallback = document.createElement("span");
      fallback.textContent = (channel.title || channel.username || "К").trim().slice(0, 2).toUpperCase();
      fallback.dataset.avatarChatId = String(channel.id);
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

function renderPeerProfileDetails(profile) {
  if (userProfileBioSection && userProfileBio) {
    const hasBio = Boolean(profile.bio?.trim());
    userProfileBioSection.hidden = !hasBio;
    userProfileBio.textContent = hasBio ? profile.bio.trim() : "";
  }
  const hasBirthday = Boolean(profile.birthday_display);
  if (userProfileBirthdayRow) userProfileBirthdayRow.hidden = !hasBirthday;
  if (userProfileBirthday) {
    let label = profile.birthday_display || "";
    if (!profile.is_self && profile.birthday && /^\d{4}-\d{2}-\d{2}$/.test(profile.birthday)) {
      const [year, month, day] = profile.birthday.split("-").map(Number);
      const birthday = new Date(year, month - 1, day);
      const now = new Date();
      let age = now.getFullYear() - year;
      if (now.getMonth() < month - 1 || (now.getMonth() === month - 1 && now.getDate() < day)) age--;
      const ending = age % 100 >= 11 && age % 100 <= 14 ? "лет"
        : age % 10 === 1 ? "год" : age % 10 >= 2 && age % 10 <= 4 ? "года" : "лет";
      if (age >= 0) label = birthday.toLocaleDateString("ru-RU", {day:"numeric", month:"long", year:"numeric"}).replace(/ г\.$/, "") + " (" + age + " " + ending + ")";
    }
    userProfileBirthday.textContent = label;
  }
}

function closePeerProfileMenus() {
  const e = peerProfileElements;
  for (const key of ["MuteMenu", "MoreMenu", "TimerOptions", "AliasEditor"]) {
    if (e[key]) e[key].hidden = true;
  }
  for (const key of ["Mute", "More"]) e[key]?.setAttribute("aria-expanded", "false");
}

function togglePeerProfileMenu(key) {
  const e = peerProfileElements;
  const opening = e[key + "Menu"]?.hidden;
  closePeerProfileMenus();
  if (opening) {
    e[key + "Menu"].hidden = false;
    e[key]?.setAttribute("aria-expanded", "true");
  }
}

function renderPeerProfileActions(profile) {
  const e = peerProfileElements;
  const foreign = !profile.is_self;
  const direct = foreign ? profile.direct_chat : null;
  const showContact = foreign && Boolean(profile.is_contact ? profile.remove_contact_url : profile.add_contact_url);
  if (foreign && userProfileName) userProfileName.textContent = profile.contact_alias || profile.display_name || profile.username || "";
  if (e.OriginalNameRow) e.OriginalNameRow.hidden = !foreign || !profile.contact_alias || profile.contact_alias === profile.display_name;
  if (e.OriginalName) e.OriginalName.textContent = foreign ? profile.display_name || "" : "";
  if (e.RenameContact) e.RenameContact.hidden = !foreign || !profile.is_contact || !profile.rename_contact_url;
  if (!profile.is_contact && e.AliasEditor) e.AliasEditor.hidden = true;
  const contactText = profile.is_contact ? "Удалить контакт" : "Добавить в контакты";
  const blockText = profile.blocked_by_me ? "Разблокировать" : "Заблокировать";
  if (userProfileActions) userProfileActions.hidden = !foreign;
  if (userProfileMessage) userProfileMessage.hidden = !foreign || !(direct?.url || profile.start_chat_url);
  if (userProfileContact) userProfileContact.hidden = !showContact;
  if (e.ContactLabel) e.ContactLabel.textContent = contactText;
  if (e.MenuContact) e.MenuContact.hidden = !showContact;
  if (e.MenuContactLabel) e.MenuContactLabel.textContent = contactText;
  if (!direct?.action_url && e.MuteMenu && !e.MuteMenu.hidden) closePeerProfileMenus();
  if (!direct?.action_url && e.TimerOptions) e.TimerOptions.hidden = true;
  if (e.Mute) {
    e.Mute.hidden = !direct?.action_url;
    e.Mute.classList.toggle("is-muted", Boolean(direct?.is_muted));
    e.Mute.title = direct?.is_muted ? "Уведомления выключены" : "Уведомления включены";
  }
  if (e.MuteLabel) e.MuteLabel.textContent = direct?.is_muted ? "Без звука" : "Звук";
  if (e.Unmute) e.Unmute.hidden = !direct?.is_muted;
  if (e.Protection) e.Protection.hidden = !direct?.action_url;
  if (e.ProtectionLabel) e.ProtectionLabel.textContent = direct?.protect_content ? "Разрешить копирование" : "Запретить копирование";
  if (e.AutoDelete) e.AutoDelete.hidden = !direct?.action_url;
  const timerNames = {0:"Выкл.",86400:"1 день",604800:"1 неделя",2592000:"1 месяц"};
  if (e.AutoDeleteLabel) e.AutoDeleteLabel.textContent = "Автоудаление · " + (timerNames[direct?.auto_delete_seconds || 0] || "Настроено");
  e.TimerOptions?.querySelectorAll("[data-peer-timer]").forEach(button => {
    button.setAttribute("aria-pressed", String(Number(button.dataset.peerTimer) === Number(direct?.auto_delete_seconds || 0)));
  });
  if (e.Report) {
    e.Report.hidden = !foreign || !profile.report_url;
    if (profile.report_url) e.Report.href = profile.report_url;
    else e.Report.removeAttribute("href");
  }
  if (e.BlockSection) e.BlockSection.hidden = !foreign || !profile.block_url;
  if (e.MenuBlock) e.MenuBlock.hidden = !foreign || !profile.block_url;
  if (e.BlockLabel) e.BlockLabel.textContent = blockText;
  if (e.MenuBlockLabel) e.MenuBlockLabel.textContent = blockText;
  const groups = foreign ? profile.common_groups || [] : [];
  if (e.CommonGroups) {
    e.CommonGroups.hidden = !groups.length;
    if (!groups.length) e.CommonGroups.open = false;
  }
  if (e.CommonGroupsLabel) {
    const n = groups.length, mod = n % 100;
    e.CommonGroupsLabel.textContent = n + (mod >= 11 && mod <= 14 ? " общих групп" :
      n % 10 === 1 ? " общая группа" : n % 10 >= 2 && n % 10 <= 4 ? " общие группы" : " общих групп");
  }
  if (e.CommonGroupsList) {
    const signature = JSON.stringify(groups);
    if (e.CommonGroupsList.dataset.signature !== signature) {
      e.CommonGroupsList.dataset.signature = signature;
      e.CommonGroupsList.replaceChildren();
      for (const group of groups) {
        const link = document.createElement("a");
        link.href = group.url;
        link.textContent = group.title || "Группа";
        e.CommonGroupsList.appendChild(link);
      }
    }
  }
}

function renderUserProfile(profile) {
  if (!userProfileOverlay) return;
  openedProfile = profile;

  renderProfileAvatar(userProfileAvatar, profile);
  if (userProfileAvatar) {
    userProfileAvatar.disabled = !profile.avatar_url;
    userProfileAvatar.classList.toggle("is-clickable", Boolean(profile.avatar_url));
  }
  if (userProfileName) userProfileName.textContent = profile.contact_alias || profile.display_name || profile.username || "";
  refreshProfileExtras(profile);
  updateProfilePresence(profile);
  if (userProfileUsername) userProfileUsername.textContent = `@${profile.username || ""}`;

  userProfileView?.classList.toggle("is-foreign", !profile.is_self);
  renderPeerProfileDetails(profile);
  renderProfilePersonalChannel(profile.personal_channel);

  if (userProfileEdit) userProfileEdit.hidden = !profile.is_self;
  if (userProfileAccounts) userProfileAccounts.hidden = !profile.is_self;
  closePeerProfileMenus();
  if (peerProfileElements.CommonGroups) peerProfileElements.CommonGroups.open = false;
  renderPeerProfileActions(profile);

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
      image.dataset.avatarChatId = String(channel.id);
      avatar.appendChild(image);
    } else {
      const fallback = document.createElement("span");
      fallback.textContent = (channel.title || channel.username || "К").trim().slice(0, 2).toUpperCase();
      fallback.dataset.avatarChatId = String(channel.id);
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
  updateProfilePresence(openedProfile);

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
    if (!await flushBioSave()) {
      throw new Error("Не удалось сохранить «О себе» перед изменением поля.");
    }
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

function updateProfileHistory(username) {
  const url = new URL(window.location.href);
  if (username) url.searchParams.set("profile", username);
  else url.searchParams.delete("profile");
  window.history.replaceState({}, "", url);
}

let selfAvatarRefreshBusy = false;
async function refreshSelfAvatar() {
  const url = document.body?.dataset.selfProfileUrl;
  if (!url || document.hidden || selfAvatarRefreshBusy) return;
  selfAvatarRefreshBusy = true;
  try {
    const response = await fetch(url, {
      headers: { "X-Requested-With": "XMLHttpRequest" },
      credentials: "same-origin",
      cache: "no-store",
    });
    if (!response.ok) return;
    const fresh = await response.json();
    if (!fresh.ok || fresh.id == null) return;
    updateGlobalSelfIdentity({
      user_id: fresh.id,
      display_name: fresh.display_name,
      profile_url: fresh.profile_url,
      avatar_url: fresh.avatar_url || "",
      initials: fresh.initials || "?",
    });
  } catch (_error) {
    // Retry on the next interval or when the tab becomes visible.
  } finally {
    selfAvatarRefreshBusy = false;
  }
}

window.setInterval(refreshSelfAvatar, 15000);
document.addEventListener("visibilitychange", () => {
  if (!document.hidden) void refreshSelfAvatar();
});
window.addEventListener?.("focus", () => { void refreshSelfAvatar(); });

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
    if (profile.viewer_id != null && document.body?.dataset?.accountId &&
        String(profile.viewer_id) !== document.body.dataset.accountId) {
      throw new Error("Аккаунт изменился. Обновите страницу.");
    }
    if (!profile.profile_url) profile.profile_url = url;
    renderUserProfile(profile);
    updateProfileHistory(profile.username || "");
    startProfileRefresh();
  } catch (_error) {
    updateProfileHistory("");
    showProfileToast(_error?.message === "Аккаунт изменился. Обновите страницу."
      ? _error.message : "Не удалось открыть профиль.");
  }
}

const profileFromUrl = new URL(window.location.href).searchParams.get("profile");
if (profileFromUrl && profileFromUrl.length <= 150) {
  void openUserProfile(`/u/${encodeURIComponent(profileFromUrl)}/`);
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
  if (userProfileActions && !userProfileActions.contains(event.target)) closePeerProfileMenus();
  if (!userProfileChannelContext?.hidden && !userProfileChannelContext.contains(event.target)) {
    closeProfileChannelContext();
  }
});

userProfileAvatar?.addEventListener("click", openProfilePhotoViewer);
userProfileEditAvatarOpen?.addEventListener("click", openProfilePhotoViewer);
userProfilePhotoClose?.addEventListener("click", closeProfilePhotoViewer);
userProfilePhotoViewer?.addEventListener("click", (event) => {
  if (event.target === userProfilePhotoViewer) closeProfilePhotoViewer();
});

userProfilePhotoRemove?.addEventListener("click", async () => {
  if (!openedProfile?.is_self || !openedProfile.remove_avatar_url || profilePhotoId!=="current") return;
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
    openedProfile.profile_photos=profilePhotos().filter(photo=>!photo.current);
    openedProfile.initials = payload.initials || openedProfile.initials;
    updateGlobalSelfIdentity(payload);
    renderProfileAvatar(userProfileAvatar, openedProfile);
    renderProfileAvatar(userProfileEditAvatar, openedProfile);
    if (userProfileAvatar) {
      userProfileAvatar.disabled = true;
      userProfileAvatar.classList.remove("is-clickable");
    }
    if (userProfileEditAvatarOpen) userProfileEditAvatarOpen.disabled = true;
    closeProfilePhotoViewer();refreshProfileExtras(openedProfile);
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

document.getElementById("userProfileQr")?.addEventListener("click", () => {
  if (!openedProfile?.username) return;
  window.open(`/u/${encodeURIComponent(openedProfile.username)}/qr/`, "_blank", "noopener,noreferrer");
});

userProfileChannelCard?.addEventListener("contextmenu", openProfileChannelContext);
userProfileChannelContextRemove?.addEventListener("click", async () => {
  closeProfileChannelContext();
  if (!openedProfile?.is_self || !openedProfile.personal_channel) return;
  try {
    await saveSelfProfile({ personal_channel: "" });
    renderUserProfile(openedProfile);
  } catch (error) {
    showProfileToast(profileErrorsToText(error?.profileErrors));
  }
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
  if (!await flushBioSave()) {
    showProfileToast("Не удалось сохранить «О себе». Изменения не сохранены.");
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
  if (!openedProfile) return;
  if (openedProfile.direct_chat?.url) {
    window.location.assign(openedProfile.direct_chat.url);
    return;
  }
  if (!openedProfile.start_chat_url) return;
  const form = document.createElement("form");
  form.method = "post";
  form.action = openedProfile.start_chat_url;
  for (const [name, value] of Object.entries({
    csrfmiddlewaretoken: csrfToken(), account_id: document.body.dataset.accountId,
  })) {
    const input = document.createElement("input");
    input.type = "hidden";
    input.name = name;
    input.value = value;
    form.appendChild(input);
  }
  document.body.appendChild(form);
  form.submit();
});

async function postPeerProfileAction(url, values) {
  const body = new URLSearchParams();
  body.set("csrfmiddlewaretoken", csrfToken());
  if (document.body.dataset.accountId) body.set("account_id", document.body.dataset.accountId);
  for (const [key, value] of Object.entries(values)) body.set(key, String(value));
  const response = await fetch(url, {
    method: "POST",
    headers: {"X-Requested-With": "XMLHttpRequest", "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8"},
    body, credentials: "same-origin",
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok || response.redirected || payload.ok !== true) {
    throw new Error(payload.error || "Не удалось выполнить действие. Обновите страницу и повторите попытку.");
  }
  return payload;
}

async function runPeerProfileAction(url, values, onSuccess) {
  if (!openedProfile || !url || peerProfileActionBusy) return;
  const target = openedProfile;
  peerProfileActionBusy = true;
  peerProfileActionVersion++;
  closePeerProfileMenus();
  try {
    const payload = await postPeerProfileAction(url, values);
    if (openedProfile === target) {
      onSuccess(payload, target);
      renderPeerProfileActions(target);
    }
    showProfileToast(payload.message || "Готово.");
  } catch (error) {
    showProfileToast(error.message);
  } finally {
    peerProfileActionBusy = false;
    void refreshProfilePresence();
  }
}

function changePeerProfileContact() {
  if (!openedProfile) return;
  const removing = Boolean(openedProfile.is_contact);
  if (removing && !window.confirm("Удалить пользователя из контактов?")) return;
  void runPeerProfileAction(removing ? openedProfile.remove_contact_url : openedProfile.add_contact_url,
    {}, (payload, target) => {
      target.is_contact = Boolean(payload.is_contact);
      if (!target.is_contact) target.contact_alias = "";
      void window.SovietgramSidebar?.refresh?.();
    });
}

function renamePeerContact(reset = false) {
  const profile = openedProfile;
  if (!profile?.is_contact || !profile.rename_contact_url) return;
  const alias = reset ? "" : peerProfileElements.AliasInput?.value || "";
  void runPeerProfileAction(profile.rename_contact_url, {alias}, (payload, target) => {
    target.contact_alias = payload.contact_alias || "";
    target.contact_name = payload.contact_name;
    void window.SovietgramSidebar?.refresh?.();
  });
}

function changePeerProfileBlock() {
  if (!openedProfile?.block_url) return;
  const blocking = !openedProfile.blocked_by_me;
  if (!window.confirm(blocking ? "Заблокировать пользователя?" : "Разблокировать пользователя?")) return;
  void runPeerProfileAction(openedProfile.block_url, {
    action: blocking ? "block" : "unblock", username: openedProfile.username,
  }, (_payload, target) => {
    target.blocked_by_me = blocking;
    if (blocking) target.start_chat_url = "";
    const conversation = document.querySelector(".conversation--chat");
    if (String(target.direct_chat?.id) === conversation?.dataset.chatId) window.location.reload();
  });
}

function changePeerChatSetting(values) {
  const direct = openedProfile?.direct_chat;
  if (!direct?.action_url) return;
  void runPeerProfileAction(direct.action_url, values, (payload, target) => {
    const chat = target.direct_chat;
    if (!chat || chat.id !== direct.id) return;
    const conversation = document.querySelector(".conversation--chat");
    const active = String(chat.id) === conversation?.dataset.chatId;
    if (values.action === "mute") {
      chat.is_muted = Boolean(payload.is_muted);
      chat.muted_until = payload.muted_until || "";
      if (active) document.dispatchEvent(new CustomEvent("sovietgram:chat-mute-state", {
        detail: {isMuted: chat.is_muted, mutedUntil: chat.muted_until},
      }));
      void window.SovietgramSidebar?.refresh?.();
    } else if (values.action === "toggle_protection") {
      chat.protect_content = Boolean(payload.protect_content);
      if (active) document.dispatchEvent(new CustomEvent("sovietgram:chat-protection", {
        detail: {enabled: chat.protect_content},
      }));
    } else if (values.action === "auto_delete") {
      chat.auto_delete_seconds = Number(payload.auto_delete_seconds);
    }
  });
}

userProfileContact?.addEventListener("click", changePeerProfileContact);
peerProfileElements.MenuContact?.addEventListener("click", changePeerProfileContact);
peerProfileElements.RenameContact?.addEventListener("click", () => {
  if (!openedProfile?.is_contact) return;
  const {AliasEditor, AliasInput} = peerProfileElements;
  if (!AliasEditor || !AliasInput) return;
  AliasEditor.hidden = !AliasEditor.hidden;
  if (!AliasEditor.hidden) {
    AliasInput.value = openedProfile.contact_alias || openedProfile.display_name || "";
    AliasInput.focus();
    AliasInput.select();
  }
});
peerProfileElements.AliasSave?.addEventListener("click", () => renamePeerContact());
peerProfileElements.AliasReset?.addEventListener("click", () => renamePeerContact(true));
peerProfileElements.AliasInput?.addEventListener("keydown", event => {
  if (event.key === "Enter") { event.preventDefault(); renamePeerContact(); }
});
peerProfileElements.Block?.addEventListener("click", changePeerProfileBlock);
peerProfileElements.MenuBlock?.addEventListener("click", changePeerProfileBlock);
peerProfileElements.More?.addEventListener("click", () => togglePeerProfileMenu("More"));
peerProfileElements.Mute?.addEventListener("click", () => togglePeerProfileMenu("Mute"));
peerProfileElements.CopyLink?.addEventListener("click", () => {
  closePeerProfileMenus();
  userProfileUsernameRow?.click();
});
peerProfileElements.AutoDelete?.addEventListener("click", () => {
  const options = peerProfileElements.TimerOptions;
  if (options) options.hidden = !options.hidden;
});
peerProfileElements.Protection?.addEventListener("click", () => {
  const direct = openedProfile?.direct_chat;
  if (direct) changePeerChatSetting({action:"toggle_protection", enabled:direct.protect_content ? "0" : "1"});
});
peerProfileElements.MuteMenu?.querySelectorAll("[data-peer-mute]").forEach(button => {
  button.addEventListener("click", () => changePeerChatSetting({action:"mute", duration:button.dataset.peerMute}));
});
peerProfileElements.TimerOptions?.querySelectorAll("[data-peer-timer]").forEach(button => {
  button.addEventListener("click", () => changePeerChatSetting({action:"auto_delete", seconds:button.dataset.peerTimer}));
});

document.addEventListener("keydown", (event) => {
  if (event.key !== "Escape") return;

  if ([peerProfileElements.MoreMenu, peerProfileElements.MuteMenu].some(menu => menu && !menu.hidden)) {
    closePeerProfileMenus();
    return;
  }
  if (userProfileChannelContext && !userProfileChannelContext.hidden) {
    closeProfileChannelContext();
    return;
  }
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
      if (!await flushBioSave()) {
        showProfileToast("Не удалось сохранить «О себе». Изменения не сохранены.");
      }
      if (openedProfile) renderUserProfile(openedProfile);
    })();
    return;
  }
  if (userProfileOverlay && !userProfileOverlay.hidden) {
    void closeUserProfile();
  }
});
