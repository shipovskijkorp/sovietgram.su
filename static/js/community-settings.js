(() => {
  const profileRoot = document.getElementById("communityProfile");
  const profileBackdrop = document.getElementById("communityProfileBackdrop");
  const panel = document.getElementById("communitySettings");
  const openButton = document.getElementById("communityProfileSettingsOpen");
  if (!profileRoot || !panel || !openButton) return;

  const $ = (id) => document.getElementById(id);
  const overview = $("communitySettingsOverview");
  const closeButton = $("communitySettingsClose");
  const communityName = $("communitySettingsCommunityName");
  const communityMeta = $("communitySettingsCommunityMeta");
  const typeSummary = $("communitySettingsTypeSummary");
  const permissionsSummary = $("communitySettingsPermissionsSummary");
  const inviteSummary = $("communitySettingsInviteSummary");
  const adminSummary = $("communitySettingsAdminSummary");
  const memberSummary = $("communitySettingsMemberSummary");
  const signatures = $("communitySettingsSignatures");
  const deleteButton = $("communitySettingsDelete");
  const typeForm = $("communitySettingsTypeForm");
  const typeUsername = $("communitySettingsUsername");
  const typeUsernameField = $("communitySettingsUsernameField");
  const typeError = $("communitySettingsTypeError");
  const permissionsForm = $("communitySettingsPermissionsForm");
  const permissionsError = $("communitySettingsPermissionsError");
  const slowMode = $("communitySettingsSlowMode");
  const inviteCreateOpen = $("communitySettingsInviteCreateOpen");
  const inviteForm = $("communitySettingsInviteForm");
  const inviteCancel = $("communitySettingsInviteCancel");
  const inviteList = $("communitySettingsInviteList");
  const adminList = $("communitySettingsAdminList");
  const memberList = $("communitySettingsMemberList");
  const addMember = $("communitySettingsAddMember");
  const memberSearchWrap = $("communitySettingsMemberSearchWrap");
  const memberSearch = $("communitySettingsMemberSearch");
  const candidateList = $("communitySettingsCandidateList");
  const logList = $("communitySettingsLogList");
  const subviews = Array.from(panel.querySelectorAll("[data-community-settings-view]"));
  const openRows = Array.from(panel.querySelectorAll("[data-community-settings-open]"));
  const backButtons = Array.from(panel.querySelectorAll("[data-community-settings-back]"));

  let settings = null;
  let activeView = "overview";
  let searchTimer = 0;
  let searchController = null;
  let signatureBusy = false;

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
    const response = await fetch(url, {
      ...opts,
      credentials: "same-origin",
      headers: {
        "X-Requested-With": "XMLHttpRequest",
        ...(opts.headers || {}),
      },
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok || payload.ok === false) throw new Error(errorText(payload));
    return payload;
  }

  async function post(url, values) {
    const body = new FormData();
    body.append("csrfmiddlewaretoken", csrf());
    Object.entries(values || {}).forEach(([key, value]) => {
      if (value !== undefined && value !== null) body.append(key, String(value));
    });
    return fetchJson(url, { method: "POST", body });
  }

  function empty(text) {
    const node = document.createElement("div");
    node.className = "community-settings-empty";
    node.textContent = text;
    return node;
  }

  function setView(name) {
    activeView = name;
    overview.hidden = name !== "overview";
    subviews.forEach((view) => {
      view.hidden = view.dataset.communitySettingsView !== name;
    });
    if (name === "members") {
      closeMemberSearch();
      renderMembers();
    }
  }

  function closeSettings() {
    panel.hidden = true;
    panel.setAttribute("aria-hidden", "true");
    setView("overview");
    closeMemberSearch();
    if (inviteForm) inviteForm.hidden = true;
  }

  async function openSettings() {
    panel.hidden = false;
    panel.setAttribute("aria-hidden", "false");
    setView("overview");
    try {
      const payload = await fetchJson(profileRoot.dataset.settingsUrl);
      settings = payload.settings;
      render();
    } catch (error) {
      toast(error.message);
      closeSettings();
    }
  }

  function visibilityValue() {
    return typeForm?.querySelector('input[name="community_settings_visibility"]:checked')?.value || "private";
  }

  function syncTypeField() {
    if (typeUsernameField) typeUsernameField.hidden = visibilityValue() !== "public";
  }

  function slowModeText(value) {
    const seconds = Number(value) || 0;
    if (!seconds) return "выкл.";
    if (seconds < 60) return String(seconds) + " сек.";
    if (seconds === 60) return "1 мин.";
    if (seconds < 3600) return String(seconds / 60) + " мин.";
    return "1 ч.";
  }

  function renderOverview() {
    if (!settings) return;
    communityName.textContent = settings.title || "";
    communityMeta.textContent = String(settings.member_count) + " " + (settings.type === "channel" ? "подписчик(ов)" : "участник(ов)");
    typeSummary.textContent = settings.is_public ? "Публичное · @" + settings.username : "Частное";
    if (permissionsSummary && settings.permissions) {
      const denied = settings.permissions.restriction_count || 0;
      const total = settings.permissions.restriction_total || 5;
      const slow = Number(settings.permissions.slow_mode_seconds) || 0;
      permissionsSummary.textContent = String(denied) + "/" + String(total) + " запрещено" + (slow ? " · медленный режим " + slowModeText(slow) : "");
    }
    inviteSummary.textContent = String(settings.active_invite_count || 0) + " активн.";
    adminSummary.textContent = String(settings.admin_count || 0);
    memberSummary.textContent = String(settings.member_count || 0);
    if (signatures) signatures.checked = Boolean(settings.signatures_enabled);
  }

  function renderTypeForm() {
    if (!settings || !typeForm) return;
    typeForm.querySelectorAll('input[name="community_settings_visibility"]').forEach((input) => {
      input.checked = input.value === (settings.is_public ? "public" : "private");
    });
    typeUsername.value = settings.username || "";
    syncTypeField();
    typeError.hidden = true;
  }

  function renderPermissionsForm() {
    if (!settings?.permissions || !permissionsForm) return;
    const p = settings.permissions;
    const fields = {
      send_messages: p.send_messages,
      send_media: p.send_media,
      send_links: p.send_links,
      add_members: p.add_members,
      pin_messages: p.pin_messages,
      history_visible: settings.history_visible_to_new_members,
    };
    Object.entries(fields).forEach(([name, value]) => {
      const input = permissionsForm.elements[name];
      if (input) input.checked = Boolean(value);
    });
    if (slowMode) slowMode.value = String(p.slow_mode_seconds || 0);
    permissionsError.hidden = true;
  }

  function memberAvatar(member) {
    const avatar = document.createElement(member.avatar_url ? "img" : "span");
    avatar.className = "community-settings-person__avatar";
    if (member.avatar_url) {
      avatar.src = member.avatar_url;
      avatar.alt = "";
    } else {
      avatar.textContent = member.initials || "?";
    }
    return avatar;
  }

  function openProfile(member) {
    if (typeof window.openUserProfile === "function") window.openUserProfile(member.profile_url);
    else window.location.assign(member.profile_url);
  }

  function personRow(member, mode) {
    const row = document.createElement("div");
    row.className = "community-settings-person";

    const identity = document.createElement("button");
    identity.type = "button";
    identity.className = "community-settings-person__identity";
    identity.appendChild(memberAvatar(member));

    const copy = document.createElement("span");
    const personName = document.createElement("strong");
    personName.textContent = member.display_name;
    const meta = document.createElement("small");
    meta.textContent = member.role === "member"
      ? "@" + member.username
      : member.role_label + " · @" + member.username;
    copy.append(personName, meta);
    identity.appendChild(copy);
    identity.addEventListener("click", () => openProfile(member));
    row.appendChild(identity);

    const actions = document.createElement("span");
    actions.className = "community-settings-person__actions";

    if (member.can_change_role) {
      const roleButton = document.createElement("button");
      roleButton.type = "button";
      roleButton.className = "community-settings-person__role";
      roleButton.textContent = member.role === "admin" ? "Снять" : "Админ";
      roleButton.title = member.role === "admin" ? "Снять администратора" : "Назначить администратором";
      roleButton.addEventListener("click", () => changeMemberRole(member));
      actions.appendChild(roleButton);
    }

    if (mode === "members" && member.can_remove) {
      const remove = document.createElement("button");
      remove.type = "button";
      remove.className = "community-settings-person__remove";
      remove.textContent = "×";
      remove.title = "Удалить";
      remove.addEventListener("click", () => removeMember(member));
      actions.appendChild(remove);
    }

    if (actions.childNodes.length) row.appendChild(actions);
    return row;
  }

  function renderAdmins() {
    if (!adminList) return;
    adminList.replaceChildren();
    const admins = settings?.admins || [];
    if (!admins.length) return adminList.appendChild(empty("Администраторов нет."));
    admins.forEach((member) => adminList.appendChild(personRow(member, "admins")));
  }

  function renderMembers() {
    if (!memberList) return;
    memberList.replaceChildren();
    const members = settings?.members || [];
    if (!members.length) return memberList.appendChild(empty("Список пуст."));
    members.forEach((member) => memberList.appendChild(personRow(member, "members")));
  }

  function absoluteUrl(relative) {
    return new URL(relative, window.location.origin).href;
  }

  async function copyText(value, confirmation) {
    try {
      await navigator.clipboard.writeText(value);
    } catch (_error) {
      const area = document.createElement("textarea");
      area.value = value;
      area.style.position = "fixed";
      area.style.opacity = "0";
      document.body.appendChild(area);
      area.select();
      document.execCommand("copy");
      area.remove();
    }
    toast(confirmation);
  }

  function renderInvites() {
    if (!inviteList) return;
    inviteList.replaceChildren();
    const links = settings?.invite_links || [];
    if (!links.length) return inviteList.appendChild(empty("Ссылок пока нет."));

    links.forEach((invite) => {
      const row = document.createElement("div");
      row.className = "community-settings-invite" + (invite.is_active ? "" : " is-inactive");

      const icon = document.createElement("span");
      icon.className = "community-settings-invite__icon";
      const nativeIcon = document.createElement("span");
      nativeIcon.className = "tg-native-icon tg-native-icon--copy";
      nativeIcon.setAttribute("aria-hidden", "true");
      icon.appendChild(nativeIcon);

      const copy = document.createElement("span");
      copy.className = "community-settings-invite__copy";
      const titleNode = document.createElement("strong");
      titleNode.textContent = invite.name;
      const meta = document.createElement("small");
      const parts = [
        invite.is_active ? "активна" : "недействительна",
        String(invite.usage_count) + (invite.usage_limit ? "/" + String(invite.usage_limit) : "") + " вступл.",
      ];
      if (invite.expires_at) parts.push("до " + invite.expires_at);
      meta.textContent = parts.join(" · ");
      copy.append(titleNode, meta);

      const actions = document.createElement("span");
      actions.className = "community-settings-invite__actions";
      if (invite.is_active) {
        const copyButton = document.createElement("button");
        copyButton.type = "button";
        copyButton.textContent = "Копировать";
        copyButton.addEventListener("click", () => copyText(absoluteUrl(invite.url), "Ссылка скопирована."));
        const revokeButton = document.createElement("button");
        revokeButton.type = "button";
        revokeButton.className = "is-danger";
        revokeButton.textContent = "Отозвать";
        revokeButton.addEventListener("click", () => revokeInvite(invite));
        actions.append(copyButton, revokeButton);
      }
      row.append(icon, copy, actions);
      inviteList.appendChild(row);
    });
  }

  function renderLog() {
    if (!logList) return;
    logList.replaceChildren();
    const logs = settings?.recent_actions || [];
    if (!logs.length) return logList.appendChild(empty("Недавних действий пока нет."));
    logs.forEach((item) => {
      const row = document.createElement("div");
      row.className = "community-settings-log";
      const marker = document.createElement("span");
      marker.className = "community-settings-log__marker";
      marker.textContent = "•";
      const copy = document.createElement("span");
      const description = document.createElement("strong");
      description.textContent = item.description;
      const meta = document.createElement("small");
      meta.textContent = item.actor_name + " · " + item.time;
      copy.append(description, meta);
      row.append(marker, copy);
      logList.appendChild(row);
    });
  }

  function render() {
    renderOverview();
    renderTypeForm();
    renderPermissionsForm();
    renderInvites();
    renderAdmins();
    renderMembers();
    renderLog();
    const conversation = document.querySelector(".conversation--chat");
    if (conversation && settings?.type === "channel") {
      conversation.dataset.channelSignatures = settings.signatures_enabled ? "true" : "false";
      document.querySelectorAll(".message").forEach((article) => {
        const footer = article.querySelector("footer");
        if (!footer) return;
        let signature = footer.querySelector(".message-channel-signature");
        if (settings.signatures_enabled) {
          if (!signature) {
            signature = document.createElement("span");
            signature.className = "message-channel-signature";
            footer.insertBefore(signature, footer.firstChild);
          }
          signature.textContent = article.dataset.messageSender || "";
        } else {
          signature?.remove();
        }
      });
    }
  }

  async function applySettings(values) {
    if (!settings?.urls?.settings) return null;
    const payload = await post(settings.urls.settings, values);
    if (payload.settings) settings = payload.settings;
    render();
    return payload;
  }

  async function memberAction(values) {
    if (!settings?.urls?.member_action) return;
    try {
      const payload = await post(settings.urls.member_action, values);
      if (payload.settings) settings = payload.settings;
      else {
        const refreshed = await fetchJson(profileRoot.dataset.settingsUrl);
        settings = refreshed.settings;
      }
      render();
    } catch (error) {
      toast(error.message);
    }
  }

  async function changeMemberRole(member) {
    const next = member.role === "admin" ? "member" : "admin";
    await memberAction({ action: "role", username: member.username, role: next });
  }

  async function removeMember(member) {
    if (!window.confirm("Удалить " + member.display_name + "?")) return;
    await memberAction({ action: "remove", username: member.username });
  }

  async function revokeInvite(invite) {
    if (!window.confirm("Отозвать ссылку «" + invite.name + "»?")) return;
    try {
      const payload = await post(settings.urls.invite_action, {
        action: "revoke",
        invite_id: invite.id,
      });
      settings = payload.settings;
      render();
    } catch (error) {
      toast(error.message);
    }
  }

  function closeMemberSearch() {
    if (!memberSearchWrap || !candidateList) return;
    memberSearchWrap.hidden = true;
    candidateList.hidden = true;
    candidateList.replaceChildren();
    if (memberSearch) memberSearch.value = "";
    if (searchController) searchController.abort();
    searchController = null;
  }

  async function loadCandidates(query) {
    if (!settings?.urls?.member_candidates || !candidateList) return;
    if (searchController) searchController.abort();
    searchController = new AbortController();
    const url = new URL(settings.urls.member_candidates, window.location.origin);
    if (query) url.searchParams.set("q", query);
    try {
      const response = await fetch(url, {
        credentials: "same-origin",
        headers: { "X-Requested-With": "XMLHttpRequest" },
        signal: searchController.signal,
      });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok || payload.ok === false) throw new Error(errorText(payload));
      candidateList.replaceChildren();
      const people = payload.results || [];
      if (!people.length) return candidateList.appendChild(empty("Никого не найдено."));

      people.forEach((person) => {
        const button = document.createElement("button");
        button.type = "button";
        button.className = "community-settings-candidate";
        button.appendChild(memberAvatar(person));
        const copy = document.createElement("span");
        const strong = document.createElement("strong");
        strong.textContent = person.display_name;
        const small = document.createElement("small");
        small.textContent = "@" + person.username + " · " + person.presence;
        copy.append(strong, small);
        button.appendChild(copy);
        button.addEventListener("click", async () => {
          button.disabled = true;
          await memberAction({ action: "add", username: person.username });
          closeMemberSearch();
          button.disabled = false;
        });
        candidateList.appendChild(button);
      });
    } catch (error) {
      if (error.name !== "AbortError") toast(error.message);
    }
  }

  openRows.forEach((button) => {
    button.addEventListener("click", () => {
      const next = button.dataset.communitySettingsOpen;
      setView(next);
      if (next === "type") renderTypeForm();
      if (next === "permissions") renderPermissionsForm();
      if (next === "invites") renderInvites();
      if (next === "admins") renderAdmins();
      if (next === "members") renderMembers();
      if (next === "log") renderLog();
    });
  });

  backButtons.forEach((button) => button.addEventListener("click", () => setView("overview")));
  openButton.addEventListener("click", openSettings);
  closeButton?.addEventListener("click", closeSettings);
  profileBackdrop?.addEventListener("click", closeSettings);

  typeForm?.addEventListener("change", syncTypeField);
  typeForm?.addEventListener("submit", async (event) => {
    event.preventDefault();
    typeError.hidden = true;
    try {
      await applySettings({
        section: "type",
        visibility: visibilityValue(),
        username: typeUsername.value,
      });
      setView("overview");
      toast("Тип сообщества обновлён.");
    } catch (error) {
      typeError.textContent = error.message;
      typeError.hidden = false;
    }
  });

  permissionsForm?.addEventListener("submit", async (event) => {
    event.preventDefault();
    permissionsError.hidden = true;
    const values = {
      section: "permissions",
      slow_mode_seconds: slowMode?.value || "0",
    };
    ["send_messages", "send_media", "send_links", "add_members", "pin_messages", "history_visible"].forEach((name) => {
      values[name] = permissionsForm.elements[name]?.checked ? "1" : "0";
    });
    try {
      await applySettings(values);
      setView("overview");
      toast("Разрешения сохранены.");
    } catch (error) {
      permissionsError.textContent = error.message;
      permissionsError.hidden = false;
    }
  });

  signatures?.addEventListener("change", async () => {
    if (signatureBusy || !settings) return;
    signatureBusy = true;
    signatures.disabled = true;
    try {
      await applySettings({
        section: "signatures",
        enabled: signatures.checked ? "1" : "0",
      });
      toast(signatures.checked ? "Подписи включены." : "Подписи выключены.");
    } catch (error) {
      signatures.checked = !signatures.checked;
      toast(error.message);
    } finally {
      signatures.disabled = false;
      signatureBusy = false;
    }
  });

  inviteCreateOpen?.addEventListener("click", () => {
    inviteForm.hidden = false;
    inviteForm.querySelector('input[name="name"]')?.focus();
  });
  inviteCancel?.addEventListener("click", () => {
    inviteForm.reset();
    inviteForm.hidden = true;
  });
  inviteForm?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const data = new FormData(inviteForm);
    try {
      const payload = await post(settings.urls.invite_action, {
        action: "create",
        name: data.get("name") || "",
        expires_hours: data.get("expires_hours") || "0",
        usage_limit: data.get("usage_limit") || "0",
      });
      settings = payload.settings;
      inviteForm.reset();
      inviteForm.hidden = true;
      render();
      toast("Ссылка-приглашение создана.");
    } catch (error) {
      toast(error.message);
    }
  });

  addMember?.addEventListener("click", () => {
    const shouldOpen = memberSearchWrap.hidden;
    if (!shouldOpen) return closeMemberSearch();
    memberSearchWrap.hidden = false;
    candidateList.hidden = false;
    loadCandidates("");
    window.setTimeout(() => memberSearch?.focus(), 0);
  });

  memberSearch?.addEventListener("input", () => {
    window.clearTimeout(searchTimer);
    searchTimer = window.setTimeout(() => loadCandidates(memberSearch.value.trim()), 180);
  });

  deleteButton?.addEventListener("click", async () => {
    if (!settings) return;
    const noun = settings.type === "channel" ? "канал" : "группу";
    if (!window.confirm("Удалить " + noun + " «" + settings.title + "» для всех? Это действие нельзя отменить.")) return;
    try {
      const payload = await post(settings.urls.action, { action: "delete" });
      if (payload.redirect_url) window.location.assign(payload.redirect_url);
    } catch (error) {
      toast(error.message);
    }
  });

  document.addEventListener("keydown", (event) => {
    if (event.key !== "Escape" || panel.hidden) return;
    event.stopImmediatePropagation();
    if (activeView !== "overview") {
      setView("overview");
      return;
    }
    closeSettings();
  }, true);

  window.communitySettingsVisible = () => !panel.hidden;
})();
