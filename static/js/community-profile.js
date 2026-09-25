(() => {
  const root = document.getElementById("communityProfile");
  const backdrop = document.getElementById("communityProfileBackdrop");
  if (!root || !backdrop) return;

  const $ = (id) => document.getElementById(id);
  const closeButton = $("communityProfileClose");
  const editButton = $("communityProfileEdit");
  const view = $("communityProfileView");
  const editor = $("communityProfileEditor");
  const editorBack = $("communityProfileEditorBack");
  const editorCancel = $("communityProfileEditorCancel");
  const editorSave = $("communityProfileEditorSave");
  const editorTitle = $("communityProfileTitleInput");
  const editorDescription = $("communityProfileDescriptionInput");
  const editorUsername = $("communityProfileUsernameInput");
  const editorUsernameBlock = $("communityProfileUsernameBlock");
  const editorVisibility = $("communityProfileVisibility");
  const editorAvatarInput = $("communityProfileAvatarInput");
  const editorAvatarImage = $("communityProfileEditorAvatarImage");
  const editorAvatarFallback = $("communityProfileEditorAvatarFallback");
  const editorAvatarRemove = $("communityProfileAvatarRemove");
  const editorRemoveInput = $("communityProfileRemoveAvatar");
  const editorError = $("communityProfileEditorError");
  const avatar = $("communityProfileAvatar");
  const avatarImage = $("communityProfileAvatarImage");
  const avatarFallback = $("communityProfileAvatarFallback");
  const name = $("communityProfileName");
  const status = $("communityProfileStatus");
  const descriptionSection = $("communityProfileDescriptionSection");
  const description = $("communityProfileDescription");
  const usernameRow = $("communityProfileUsernameRow");
  const username = $("communityProfileUsername");
  const created = $("communityProfileCreated");
  const role = $("communityProfileRole");
  const muteButton = $("communityProfileMute");
  const muteLabel = $("communityProfileMuteLabel");
  const searchButton = $("communityProfileSearch");
  const archiveButton = $("communityProfileArchive");
  const archiveLabel = $("communityProfileArchiveLabel");
  const leaveButton = $("communityProfileLeave");
  const leaveLabel = $("communityProfileLeaveLabel");
  const mediaGrid = $("communityProfileMediaGrid");
  const fileList = $("communityProfileFileList");
  const membersList = $("communityProfileMembersList");
  const membersHeading = $("communityProfileMembersHeading");
  const addMember = $("communityProfileAddMember");
  const picker = $("communityMemberPicker");
  const pickerClose = $("communityMemberPickerClose");
  const pickerSearch = $("communityMemberPickerSearch");
  const pickerResults = $("communityMemberPickerResults");
  const tabs = Array.from(root.querySelectorAll("[data-community-profile-tab]"));
  const panels = Array.from(root.querySelectorAll("[data-community-profile-panel]"));
  const mediaTab = root.querySelector('[data-community-profile-tab="media"]');
  const filesTab = root.querySelector('[data-community-profile-tab="files"]');
  const membersTab = root.querySelector('[data-community-profile-tab="members"]');

  let opened = null;
  let activeTab = "media";
  let pickerTimer = 0;
  let pickerController = null;
  let avatarPreviewUrl = "";

  function csrf() {
    return document.querySelector('[name="csrfmiddlewaretoken"]')?.value || "";
  }
  function toast(text) {
    if (typeof window.showToast === "function") window.showToast(text);
  }
  function errorText(payload, fallback) {
    if (payload && payload.error) return payload.error;
    const groups = Object.values((payload && payload.errors) || {});
    const first = groups.flat()[0];
    return (first && first.message) || fallback || "Не удалось выполнить действие.";
  }
  async function fetchJson(url, options) {
    const opts = options || {};
    const response = await fetch(url, Object.assign({}, opts, {
      credentials: "same-origin",
      headers: Object.assign({ "X-Requested-With": "XMLHttpRequest" }, opts.headers || {}),
    }));
    const payload = await response.json().catch(() => ({}));
    if (!response.ok || payload.ok === false) {
      const error = new Error(errorText(payload));
      error.payload = payload;
      throw error;
    }
    return payload;
  }
  function postForm(url, values) {
    const data = new FormData();
    data.append("csrfmiddlewaretoken", csrf());
    Object.entries(values).forEach(([key, value]) => data.append(key, value == null ? "" : value));
    return fetchJson(url, { method: "POST", body: data });
  }
  function bytes(value) {
    const size = Number(value) || 0;
    if (size < 1024) return size + " Б";
    if (size < 1024 * 1024) return Math.round(size / 1024) + " КБ";
    return (size / (1024 * 1024)).toFixed(1) + " МБ";
  }
  function setAvatar(image, fallback, url, text) {
    if (url) {
      image.src = url;
      image.hidden = false;
      fallback.hidden = true;
    } else {
      image.removeAttribute("src");
      image.hidden = true;
      fallback.textContent = text || "?";
      fallback.hidden = false;
    }
  }
  function setOpen(open) {
    root.hidden = !open;
    backdrop.hidden = !open;
    root.setAttribute("aria-hidden", String(!open));
    if (!open) {
      closePicker();
      showEditor(false);
    }
  }
  function setTab(tabName) {
    activeTab = tabName;
    tabs.forEach((tab) => {
      const active = tab.dataset.communityProfileTab === tabName;
      tab.classList.toggle("is-active", active);
      tab.setAttribute("aria-selected", String(active));
    });
    panels.forEach((panel) => {
      panel.hidden = panel.dataset.communityProfilePanel !== tabName;
    });
  }
  function empty(text) {
    const node = document.createElement("div");
    node.className = "community-profile__empty";
    node.textContent = text;
    return node;
  }

  function renderAttachments(profile) {
    mediaGrid.replaceChildren();
    fileList.replaceChildren();
    const media = (profile.attachments || []).filter((item) => item.kind === "image" || item.kind === "video");
    const files = (profile.attachments || []).filter((item) => item.kind !== "image" && item.kind !== "video");
    mediaTab.querySelector("b").textContent = String(profile.media_count || 0);
    filesTab.querySelector("b").textContent = String(profile.file_count || 0);

    if (!media.length) mediaGrid.appendChild(empty("Медиа пока нет."));
    media.forEach((item) => {
      const link = document.createElement("a");
      link.className = "community-profile-media community-profile-media--" + item.kind;
      link.href = item.url;
      if (item.kind === "image") {
        link.dataset.lightboxImage = item.url;
        const image = document.createElement("img");
        image.src = item.url;
        image.alt = item.name;
        image.loading = "lazy";
        link.appendChild(image);
      } else {
        const mark = document.createElement("span");
        mark.textContent = "▶";
        const label = document.createElement("small");
        label.textContent = item.name;
        link.append(mark, label);
      }
      mediaGrid.appendChild(link);
    });

    if (!files.length) fileList.appendChild(empty("Файлов пока нет."));
    files.forEach((item) => {
      const link = document.createElement("a");
      link.className = "community-profile-file";
      link.href = item.url;
      const icon = document.createElement("span");
      icon.className = "community-profile-file__icon";
      const nativeIcon = document.createElement("span");
      nativeIcon.className = "tg-native-icon tg-native-icon--file";
      nativeIcon.setAttribute("aria-hidden", "true");
      icon.appendChild(nativeIcon);
      const copy = document.createElement("span");
      const strong = document.createElement("strong");
      strong.textContent = item.name;
      const small = document.createElement("small");
      small.textContent = bytes(item.size) + " · " + item.created_at;
      copy.append(strong, small);
      link.append(icon, copy);
      fileList.appendChild(link);
    });
  }

  async function memberAction(values) {
    if (!opened || !opened.urls || !opened.urls.member_action) return false;
    try {
      const payload = await postForm(opened.urls.member_action, values);
      if (payload.profile) renderProfile(payload.profile);
      return true;
    } catch (error) {
      toast(error.message);
      return false;
    }
  }
  function openMemberProfile(member) {
    if (typeof window.openUserProfile === "function") window.openUserProfile(member.profile_url);
    else window.location.assign(member.profile_url);
  }
  function renderMembers(profile) {
    membersList.replaceChildren();
    membersTab.hidden = !profile.members_visible;
    membersTab.querySelector("b").textContent = String(profile.member_count || 0);
    membersHeading.textContent = profile.type === "channel" ? "Подписчики" : "Участники";
    addMember.hidden = !profile.can_add_members;
    if (!profile.members_visible) {
      if (activeTab === "members") setTab("media");
      return;
    }
    if (!(profile.members || []).length) {
      membersList.appendChild(empty("Список пуст."));
      return;
    }
    profile.members.forEach((member) => {
      const row = document.createElement("div");
      row.className = "community-profile-member";
      const identity = document.createElement("button");
      identity.type = "button";
      identity.className = "community-profile-member__identity";
      identity.addEventListener("click", () => openMemberProfile(member));
      const picture = document.createElement(member.avatar_url ? "img" : "span");
      picture.className = "community-profile-member__avatar";
      if (member.avatar_url) { picture.src = member.avatar_url; picture.alt = ""; }
      else picture.textContent = member.initials;
      const copy = document.createElement("span");
      const strong = document.createElement("strong");
      strong.textContent = member.display_name;
      const small = document.createElement("small");
      small.textContent = member.role === "member" ? member.presence : member.role_label + " · " + member.presence;
      copy.append(strong, small);
      identity.append(picture, copy);
      row.appendChild(identity);

      if (member.can_change_role || member.can_remove) {
        const actions = document.createElement("span");
        actions.className = "community-profile-member__actions";
        if (member.can_change_role) {
          const roleButton = document.createElement("button");
          roleButton.type = "button";
          roleButton.className = "community-profile-member__role";
          roleButton.textContent = member.role === "admin" ? "Снять админа" : "Сделать админом";
          roleButton.addEventListener("click", () => memberAction({ action: "role", username: member.username, role: member.role === "admin" ? "member" : "admin" }));
          actions.appendChild(roleButton);
        }
        if (member.can_remove) {
          const remove = document.createElement("button");
          remove.type = "button";
          remove.className = "community-profile-member__remove";
          remove.textContent = "×";
          remove.setAttribute("aria-label", "Удалить участника");
          remove.addEventListener("click", () => {
            if (window.confirm("Удалить " + member.display_name + "?")) memberAction({ action: "remove", username: member.username });
          });
          actions.appendChild(remove);
        }
        row.appendChild(actions);
      }
      membersList.appendChild(row);
    });
  }

  function syncVisibility() {
    if (!opened || opened.type !== "channel") return;
    const selected = editorVisibility.querySelector('input[name="community_profile_visibility"]:checked')?.value || "private";
    editorUsernameBlock.hidden = selected !== "public";
  }
  function fillEditor(profile) {
    editorTitle.value = profile.title || "";
    editorDescription.value = profile.description || "";
    editorUsername.value = profile.username || "";
    editorVisibility.hidden = profile.type !== "channel";
    editorUsernameBlock.hidden = profile.type !== "channel";
    const visibility = profile.is_public ? "public" : "private";
    editorVisibility.querySelectorAll('input[name="community_profile_visibility"]').forEach((input) => { input.checked = input.value === visibility; });
    editorRemoveInput.value = "";
    editorAvatarInput.value = "";
    setAvatar(editorAvatarImage, editorAvatarFallback, profile.avatar_url, profile.avatar_fallback);
    if (avatarPreviewUrl) URL.revokeObjectURL(avatarPreviewUrl);
    avatarPreviewUrl = "";
    editorError.hidden = true;
    editorError.textContent = "";
    syncVisibility();
  }
  function renderProfile(profile) {
    opened = profile;
    name.textContent = profile.title;
    status.textContent = profile.status;
    created.textContent = "Создано " + profile.created_at;
    role.textContent = profile.viewer_role_label;
    setAvatar(avatarImage, avatarFallback, profile.avatar_url, profile.avatar_fallback);
    avatar.dataset.lightboxImage = profile.avatar_url || "";
    avatar.disabled = !profile.avatar_url;
    descriptionSection.hidden = !profile.description;
    description.textContent = profile.description || "";
    usernameRow.hidden = !profile.username;
    username.textContent = profile.username ? "@" + profile.username : "";
    editButton.hidden = !profile.can_manage;
    muteLabel.textContent = profile.is_muted ? "Включить уведомления" : "Выключить уведомления";
    archiveLabel.textContent = profile.is_archived ? "Вернуть из архива" : "В архив";
    leaveButton.hidden = !profile.can_leave;
    leaveLabel.textContent = profile.type === "channel" ? "Покинуть канал" : "Покинуть группу";
    renderAttachments(profile);
    renderMembers(profile);
    fillEditor(profile);
    setTab(activeTab === "members" && membersTab.hidden ? "media" : activeTab);
  }

  async function refreshProfile() {
    try {
      const payload = await fetchJson(root.dataset.profileUrl);
      renderProfile(payload.profile);
      return payload.profile;
    } catch (error) {
      toast(error.message || "Не удалось открыть информацию.");
      setOpen(false);
      return null;
    }
  }
  async function openCommunityProfile() {
    setOpen(true);
    showEditor(false);
    await refreshProfile();
  }
  window.openCommunityProfile = openCommunityProfile;
  document.querySelectorAll("[data-community-profile-open]").forEach((button) => {
    button.addEventListener("click", (event) => { event.preventDefault(); openCommunityProfile(); });
  });

  function showEditor(open) {
    view.hidden = open;
    editor.hidden = !open;
    editButton.hidden = open || !(opened && opened.can_manage);
    root.classList.toggle("is-editing", open);
    if (open && opened) fillEditor(opened);
  }
  editorVisibility.addEventListener("change", syncVisibility);
  editButton.addEventListener("click", () => showEditor(true));
  editorBack.addEventListener("click", () => showEditor(false));
  editorCancel.addEventListener("click", () => showEditor(false));
  editorAvatarInput.addEventListener("change", () => {
    const file = editorAvatarInput.files && editorAvatarInput.files[0];
    if (!file) return;
    if (avatarPreviewUrl) URL.revokeObjectURL(avatarPreviewUrl);
    avatarPreviewUrl = URL.createObjectURL(file);
    editorRemoveInput.value = "";
    setAvatar(editorAvatarImage, editorAvatarFallback, avatarPreviewUrl, opened ? opened.avatar_fallback : "?");
  });
  editorAvatarRemove.addEventListener("click", () => {
    editorAvatarInput.value = "";
    if (avatarPreviewUrl) URL.revokeObjectURL(avatarPreviewUrl);
    avatarPreviewUrl = "";
    editorRemoveInput.value = "1";
    setAvatar(editorAvatarImage, editorAvatarFallback, "", opened ? opened.avatar_fallback : "?");
  });
  editor.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (!opened || !opened.urls || !opened.urls.update) return;
    editorSave.disabled = true;
    editorError.hidden = true;
    const data = new FormData();
    data.append("csrfmiddlewaretoken", csrf());
    data.append("title", editorTitle.value);
    data.append("description", editorDescription.value);
    const visibility = editorVisibility.querySelector('input[name="community_profile_visibility"]:checked')?.value || "private";
    data.append("visibility", visibility);
    data.append("username", visibility === "public" ? editorUsername.value : "");
    if (editorAvatarInput.files && editorAvatarInput.files[0]) data.append("avatar", editorAvatarInput.files[0]);
    if (editorRemoveInput.value) data.append("remove_avatar", "on");
    try {
      const payload = await fetchJson(opened.urls.update, { method: "POST", body: data });
      renderProfile(payload.profile);
      showEditor(false);
      const headerName = document.querySelector(".conversation-header__identity--community strong");
      if (headerName) headerName.textContent = payload.profile.title;
      toast("Информация обновлена.");
    } catch (error) {
      editorError.textContent = error.message;
      editorError.hidden = false;
    } finally {
      editorSave.disabled = false;
    }
  });

  async function runAction(action) {
    if (!opened || !opened.urls || !opened.urls.action) return;
    try {
      const payload = await postForm(opened.urls.action, { action: action });
      if (payload.left && payload.redirect_url) return window.location.assign(payload.redirect_url);
      if (payload.profile) renderProfile(payload.profile);
    } catch (error) { toast(error.message); }
  }
  muteButton.addEventListener("click", () => runAction("mute"));
  archiveButton.addEventListener("click", () => runAction("archive"));
  leaveButton.addEventListener("click", () => {
    if (!opened) return;
    const noun = opened.type === "channel" ? "канал" : "группу";
    if (window.confirm("Покинуть " + noun + " «" + opened.title + "»?")) runAction("leave");
  });
  searchButton.addEventListener("click", () => {
    setOpen(false);
    $("chatSearchToggle")?.click();
  });
  usernameRow.addEventListener("click", async () => {
    if (!opened || !opened.username) return;
    const value = "@" + opened.username;
    try { await navigator.clipboard.writeText(value); }
    catch (_error) {
      const input = document.createElement("textarea");
      input.value = value;
      input.style.position = "fixed";
      input.style.opacity = "0";
      document.body.appendChild(input);
      input.select();
      document.execCommand("copy");
      input.remove();
    }
    toast("Адрес скопирован.");
  });
  tabs.forEach((tab) => tab.addEventListener("click", () => setTab(tab.dataset.communityProfileTab)));

  function closePicker() {
    if (!picker) return;
    picker.hidden = true;
    pickerSearch.value = "";
    pickerResults.replaceChildren();
    if (pickerController) pickerController.abort();
    pickerController = null;
  }
  function renderCandidates(items) {
    pickerResults.replaceChildren();
    if (!items.length) return pickerResults.appendChild(empty("Никого не найдено."));
    items.forEach((person) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "community-member-candidate";
      const picture = document.createElement(person.avatar_url ? "img" : "span");
      picture.className = "community-member-candidate__avatar";
      if (person.avatar_url) { picture.src = person.avatar_url; picture.alt = ""; }
      else picture.textContent = person.initials;
      const copy = document.createElement("span");
      const strong = document.createElement("strong"); strong.textContent = person.display_name;
      const small = document.createElement("small"); small.textContent = person.presence;
      copy.append(strong, small);
      button.append(picture, copy);
      button.addEventListener("click", async () => {
        button.disabled = true;
        const ok = await memberAction({ action: "add", username: person.username });
        if (ok) closePicker();
        button.disabled = false;
      });
      pickerResults.appendChild(button);
    });
  }
  async function loadCandidates(query) {
    if (!opened || !opened.urls || !opened.urls.member_candidates) return;
    if (pickerController) pickerController.abort();
    pickerController = new AbortController();
    const url = new URL(opened.urls.member_candidates, window.location.origin);
    if (query) url.searchParams.set("q", query);
    try {
      const payload = await fetchJson(url, { signal: pickerController.signal });
      renderCandidates(payload.results || []);
    } catch (error) {
      if (error.name !== "AbortError") toast(error.message);
    }
  }
  addMember.addEventListener("click", () => {
    if (!opened || !opened.can_add_members) return;
    picker.hidden = false;
    loadCandidates("");
    window.setTimeout(() => pickerSearch.focus(), 0);
  });
  pickerClose.addEventListener("click", closePicker);
  picker.addEventListener("click", (event) => { if (event.target === picker) closePicker(); });
  pickerSearch.addEventListener("input", () => {
    window.clearTimeout(pickerTimer);
    pickerTimer = window.setTimeout(() => loadCandidates(pickerSearch.value.trim()), 180);
  });

  closeButton.addEventListener("click", () => setOpen(false));
  backdrop.addEventListener("click", () => setOpen(false));
  document.addEventListener("keydown", (event) => {
    if (event.key !== "Escape") return;
    if (!picker.hidden) return closePicker();
    if (!editor.hidden) return showEditor(false);
    if (!root.hidden) setOpen(false);
  });
})();
