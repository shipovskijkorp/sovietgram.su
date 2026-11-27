(() => {
  const profileRoot = document.getElementById("communityProfile");
  const profileBackdrop = document.getElementById("communityProfileBackdrop");
  const panel = document.getElementById("communitySettings");
  const openButton = document.getElementById("communityProfileSettingsOpen");
  if (!profileRoot || !panel) return;

  const $ = (id) => document.getElementById(id);
  const overview = $("communitySettingsOverview");
  const closeButton = $("communitySettingsClose");
  const loadState = $("communitySettingsLoadState");
  const loadMessage = $("communitySettingsLoadMessage");
  const retryButton = $("communitySettingsRetry");
  let loadGeneration = 0;
  const communityName = $("communitySettingsCommunityName");
  const communityMeta = $("communitySettingsCommunityMeta");
  const typeSummary = $("communitySettingsTypeSummary");
  const permissionsSummary = $("communitySettingsPermissionsSummary");
  const inviteSummary = $("communitySettingsInviteSummary");
  const adminSummary = $("communitySettingsAdminSummary");
  const memberSummary = $("communitySettingsMemberSummary");
  const signatures = $("communitySettingsSignatures");
  const comments = $("communitySettingsComments");
  let commentsBusy = false;
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
  let statsDays = 7, statsGeneration = 0, statsController = null;

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
    if (!response.ok || response.redirected || payload.ok !== true)
      throw new Error(errorText(payload, response.redirected ? "Сессия истекла. Обновите страницу." : "Не удалось выполнить действие (" + response.status + ")."));
    return payload;
  }

  async function post(url, values) {
    const body = new FormData();
    body.append("csrfmiddlewaretoken", csrf());
    if (!Object.hasOwn(values || {}, "account_id") && document.body.dataset.accountId)
      body.append("account_id", document.body.dataset.accountId);
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
    if (name !== "statistics") { statsGeneration++; statsController?.abort(); }
    activeView = name;
    overview.hidden = !settings || name !== "overview";
    subviews.forEach((view) => {
      view.hidden = !settings || view.dataset.communitySettingsView !== name;
    });
    if (name === "members") {
      closeMemberSearch();
      renderMembers();
    }
    if (name === "statistics") void loadStatistics();
  }

  function renderStatsChart(target, rows, key) {
    const max = Math.max(1, ...rows.map(row => Number(row[key]) || 0));
    target.replaceChildren(...rows.map(row => {
      const line = document.createElement("div");
      line.className = "community-stats-chart-row";
      const date = document.createElement("span");
      date.textContent = row.date.slice(8,10) + "." + row.date.slice(5,7);
      const track = document.createElement("span");
      track.className = "community-stats-bar-track";
      const bar = document.createElement("span");
      bar.style.width = (Math.max(0,Number(row[key]) || 0) / max * 100) + "%";
      track.append(bar);
      const value = document.createElement("strong");
      value.textContent = String(row[key] || 0);
      line.append(date, track, value);
      return line;
    }));
  }

  async function loadStatistics() {
    if (activeView !== "statistics" || !settings?.urls?.statistics) return;
    const mine = ++statsGeneration;
    statsController?.abort();
    statsController = new AbortController();
    const status = $("communityStatsStatus"), content = $("communityStatsContent");
    const refresh = $("communityStatsRefresh");
    const requestedDays = statsDays;
    content.hidden = true;
    status.textContent = "Загрузка…";
    refresh.disabled = true;
    panel.querySelectorAll("[data-stats-days]").forEach(button => {
      button.setAttribute("aria-pressed", String(Number(button.dataset.statsDays) === requestedDays));
    });
    try {
      const url = new URL(settings.urls.statistics, location.origin);
      url.searchParams.set("days", String(requestedDays));
      url.searchParams.set("account_id", document.body.dataset.accountId || "");
      const data = await fetchJson(url, {cache:"no-store",signal:statsController.signal});
      if (mine !== statsGeneration || activeView !== "statistics" || panel.hidden) return;
      for (const element of content.querySelectorAll("[data-stats-value]")) {
        element.textContent = Number(data[element.dataset.statsValue] || 0).toLocaleString("ru-RU");
      }
      renderStatsChart($("communityStatsMessages"), data.series || [], "messages");
      renderStatsChart($("communityStatsMembers"), data.series || [], "new_members");
      const channel = $("communityStatsChannel");
      if (channel) {
        channel.hidden = !data.channel_stats;
        if (data.channel_stats) {
          for (const element of channel.querySelectorAll("[data-channel-stat]")) {
            element.textContent = Number(data.channel_stats[element.dataset.channelStat] || 0)
              .toLocaleString("ru-RU", {maximumFractionDigits: 1});
          }
          renderStatsChart($("communityStatsViews"), data.series || [], "views");
        }
      }
      status.textContent = "Часовой пояс: " + data.timezone;
      content.hidden = false;
    } catch (error) {
      if (mine !== statsGeneration || error.name === "AbortError") return;
      status.textContent = error.message;
    } finally {
      if (mine === statsGeneration) refresh.disabled = false;
    }
  }
  panel.querySelectorAll("[data-stats-days]").forEach(button => button.addEventListener("click", () => {
    statsDays = Number(button.dataset.statsDays) === 30 ? 30 : 7;
    void loadStatistics();
  }));
  $("communityStatsRefresh")?.addEventListener("click", () => { void loadStatistics(); });

  function closeSettings() {
    loadGeneration++;
    panel.hidden = true;
    panel.setAttribute("aria-hidden", "true");
    loadState.hidden = true;
    retryButton.hidden = true;
    setView("overview");
    closeMemberSearch();
    if (inviteForm) inviteForm.hidden = true;
  }

  async function openSettings() {
    const generation = ++loadGeneration;
    const menu = $("chatMenu");
    if (menu) menu.hidden = true;
    $("chatMenuButton")?.setAttribute("aria-expanded", "false");
    // The separate profile request must never prevent management from opening.
    const wasHidden = profileRoot.hidden;
    profileRoot.hidden = false;
    profileRoot.setAttribute("aria-hidden", "false");
    if (profileBackdrop) profileBackdrop.hidden = false;
    panel.hidden = false;
    panel.setAttribute("aria-hidden", "false");
    settings = null;
    setView("overview");
    loadState.hidden = false;
    loadMessage.textContent = "Загрузка управления…";
    retryButton.hidden = true;
    if (wasHidden && typeof window.openCommunityProfile === "function") {
      Promise.resolve(window.openCommunityProfile()).catch(() => {});
    }
    try {
      const payload = await fetchJson(profileRoot.dataset.settingsUrl, {cache: "no-store"});
      if (generation !== loadGeneration || panel.hidden) return;
      if (!payload.settings || typeof payload.settings !== "object") throw new Error("Управление недоступно для текущего аккаунта.");
      settings = payload.settings;
      render();
      setView("overview");
      loadState.hidden = true;
    } catch (error) {
      if (generation !== loadGeneration || panel.hidden) return;
      settings = null;
      setView("overview");
      loadMessage.textContent = error.message || "Не удалось загрузить управление.";
      retryButton.hidden = false;
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
    $("communitySettingsReactionsSummary").textContent = settings.allowed_reactions?.length
      ? settings.allowed_reactions.length + " доступно" : "Отключены";
    inviteSummary.textContent = String(settings.active_invite_count || 0) + " активн.";
    const joinSummary=$("communitySettingsJoinSummary");
    if(joinSummary)joinSummary.textContent = String(settings.pending_join_count || 0) + " ожидают";
    adminSummary.textContent = String(settings.admin_count || 0);
    memberSummary.textContent = String(settings.member_count || 0);
    const rights=new Set(settings.admin_rights||[]);
    const required={type:"change_info",permissions:"manage_permissions",reactions:"manage_permissions",statistics:"manage_permissions",invites:"invite_users","join-requests":"invite_users",moderation:"moderate_members"};
    for(const [view,right] of Object.entries(required)){
      const control=panel.querySelector('[data-community-settings-open="'+view+'"]');
      if(control)control.hidden=!rights.has(right);
      if(activeView===view&&!rights.has(right))setView("overview");
    }
    if(signatures){signatures.checked=Boolean(settings.signatures_enabled);signatures.closest("label").hidden=!rights.has("change_info");}
    if(comments){comments.checked=Boolean(settings.comments_enabled);comments.closest("label").hidden=!rights.has("manage_permissions");}
    if(addMember)addMember.hidden=!settings.can_add_members;
    if(deleteButton)deleteButton.hidden=!settings.can_delete;
    $("communitySettingsModerationSummary").textContent=String(settings.moderation_count||0)+" активных";
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
    permissionsForm.querySelectorAll("[data-media-kind]").forEach(input => {
      input.checked = (p.media_kinds || ["image","video","audio","voice","sticker","file"]).includes(input.dataset.mediaKind);
      input.disabled = !permissionsForm.elements.send_media.checked;
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

    if(member.can_edit_admin_rights){
      const rights=document.createElement("button");rights.type="button";rights.className="community-settings-person__role";
      rights.textContent="Права";rights.addEventListener("click",()=>openModerationEditor(member,"admin_rights"));actions.appendChild(rights);
    }
    if(mode==="members"&&member.can_restrict){
      const restrict=document.createElement("button");restrict.type="button";restrict.className="community-settings-person__role";
      restrict.textContent="Ограничить";restrict.addEventListener("click",()=>openModerationEditor(member,"restrict"));actions.appendChild(restrict);
    }
    if(mode==="members"&&member.can_ban){
      const ban=document.createElement("button");ban.type="button";ban.className="community-settings-person__role is-danger";
      ban.textContent="Бан";ban.addEventListener("click",()=>openModerationEditor(member,"ban"));actions.appendChild(ban);
    }

    if (member.can_transfer_owner) {
      const transfer = document.createElement("button");
      transfer.type = "button";
      transfer.className = "community-settings-person__role";
      transfer.textContent = "Передать";
      transfer.title = "Передать права владельца";
      transfer.addEventListener("click", () => transferOwnership(member));
      actions.appendChild(transfer);
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
      let copied = false;
      try { copied = document.execCommand("copy"); } catch (_) {}
      finally { area.remove(); }
      if (!copied) { toast("Не удалось скопировать ссылку."); return; }
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
      if (invite.requires_approval) parts.push("с одобрением");
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

  let joinBusy=false;
  function renderJoinRequests() {
    const list=$("communitySettingsJoinList");
    if(!list)return;
    list.replaceChildren();
    const requests=settings?.join_requests||[];
    if(!requests.length)list.appendChild(empty("Нет заявок на вступление."));
    for(const item of requests){
      const row=document.createElement("div");row.className="community-settings-join-row";
      const copy=document.createElement("div");copy.className="community-settings-invite__copy";
      const title=document.createElement("strong");title.textContent=item.name+" · @"+item.username;
      const detail=document.createElement("small");detail.textContent=item.invite_name+" · "+item.created_at+(item.invite_active?"":" · ссылка недействительна");
      copy.append(title,detail);
      const actions=document.createElement("div");actions.className="community-settings-invite__actions";
      for(const [action,label] of [["approve","Принять"],["reject","Отклонить"]]){
        const node=document.createElement("button");node.type="button";node.textContent=label;
        node.disabled=joinBusy||(action==="approve"&&!item.invite_active);
        if(action==="reject")node.className="is-danger";
        node.addEventListener("click",()=>void decideJoinRequest(item,action));actions.appendChild(node);
      }
      row.append(copy,actions);list.appendChild(row);
    }
    if((settings?.pending_join_count||0)>requests.length)list.appendChild(empty("Показаны первые 100 заявок. Остальные появятся после обработки."));
  }
  async function refreshJoinRequests() {
    if(joinBusy)return;
    joinBusy=true;renderJoinRequests();
    try{
      const payload=await fetchJson(profileRoot.dataset.settingsUrl,{cache:"no-store"});
      settings=payload.settings;render();
    }catch(error){toast(error.message);}
    finally{joinBusy=false;renderJoinRequests();}
  }
  async function decideJoinRequest(item,action) {
    if(joinBusy)return;
    if(!window.confirm((action==="approve"?"Принять":"Отклонить")+" заявку @"+item.username+"?"))return;
    joinBusy=true;renderJoinRequests();
    try{
      const payload=await post(settings.urls.join_request_action,{
        account_id:document.getElementById("messageStage")?.dataset.accountId,
        action,request_id:item.id,revision:item.revision,
      });
      settings=payload.settings;render();toast(action==="approve"?"Заявка одобрена.":"Заявка отклонена.");
      void window.SovietgramSidebar?.refresh();
    }catch(error){toast(error.message);}
    finally{joinBusy=false;renderJoinRequests();}
  }
  $("communitySettingsJoinRefresh")?.addEventListener("click",refreshJoinRequests);

  const modDialog=$("communityModerationDialog");
  const modForm=$("communityModerationForm");
  let moderationTarget=null, moderationAction="", moderationBusy=false;
  function sanctionLabel(row){
    if(row.banned)return "Заблокирован";
    const labels=settings?.member_denial_labels||{};
    return (row.permissions||[]).map(key=>labels[key]||key).join(" · ");
  }
  function renderModeration(){
    const list=$("communityModerationList");if(!list)return;
    const query=($("communityModerationSearch").value||"").trim().toLowerCase().replace(/^@/,"");
    const filter=$("communityModerationFilter").value;
    const rows=(settings?.moderation||[]).filter(row=>
      (filter==="all"||(filter==="ban")===row.banned)&&
      (!query||(row.name+" "+row.username).toLowerCase().includes(query)));
    list.replaceChildren();
    if(!rows.length){list.appendChild(empty("Активных ограничений не найдено."));return;}
    for(const row of rows){
      const item=document.createElement("article");item.className="community-moderation-row";
      const name=document.createElement("strong");name.textContent=row.name+" · @"+row.username;
      const detail=document.createElement("small");
      detail.textContent=sanctionLabel(row)+" · "+(row.expires_at?"До "+new Date(row.expires_at).toLocaleString():"Навсегда");
      const reason=document.createElement("small");reason.textContent=row.reason||"";reason.hidden=!row.reason;
      const actions=document.createElement("div");actions.className="community-settings-invite__actions";
      const lift=document.createElement("button");lift.type="button";lift.textContent=row.banned?"Разблокировать":"Снять ограничения";lift.disabled=moderationBusy;
      lift.addEventListener("click",()=>{if(window.confirm("Снять ограничения с @"+row.username+"?"))void applyModeration("lift",row.user_id);});
      actions.appendChild(lift);
      const member=(settings?.members||[]).find(person=>person.user_id===row.user_id);
      if(row.banned||member?.can_restrict){
        const edit=document.createElement("button");edit.type="button";edit.textContent="Изменить";edit.disabled=moderationBusy;
        edit.addEventListener("click",()=>openModerationEditor(member||row,row.banned?"ban":"restrict",row));actions.appendChild(edit);
      }
      item.append(name,detail,reason,actions);list.appendChild(item);
    }
    // Every active sanction is available in this list, including former members.
  }
  function openModerationEditor(member,action,existing=null){
    if(moderationBusy)return;
    moderationTarget=member;moderationAction=action;
    $("communityModerationTitle").textContent=action==="admin_rights"?"Права администратора":action==="ban"?"Заблокировать участника":"Ограничить участника";
    $("communityModerationTarget").textContent=(member.display_name||member.name)+" · @"+member.username;
    $("communityModerationError").hidden=true;
    const rights=$("communityModerationRights");rights.replaceChildren();
    const labels=action==="admin_rights"?settings.admin_right_labels:action==="restrict"?settings.member_denial_labels:{};
    const current=action==="admin_rights"?member.admin_rights:existing?.permissions||[];
    for(const [key,label] of Object.entries(labels||{})){
      const field=document.createElement("label");field.className="moderation-right";
      const input=document.createElement("input");input.type="checkbox";input.value=key;input.checked=(current||[]).includes(key);
      const copy=document.createElement("span");copy.textContent=label;field.append(input,copy);rights.appendChild(field);
    }
    $("communityModerationDurationRow").hidden=action==="admin_rights";
    $("communityModerationReasonRow").hidden=action==="admin_rights";
    $("communityModerationDuration").value=action==="ban"?"forever":"1d";
    $("communityModerationReason").value=existing?.reason||"";
    if(action==="ban"){
      const info=document.createElement("p");info.textContent="Участник потеряет доступ к сообществу. До окончания бана он не сможет вступить снова.";rights.appendChild(info);
    }
    if(!modDialog.open)modDialog.showModal();
  }
  async function applyModeration(action,userId,fields={}){
    if(moderationBusy||!settings?.urls?.moderation)return;
    moderationBusy=true;
    $("communityModerationSubmit").disabled=true;renderModeration();
    try{
      const result=await post(settings.urls.moderation,{
        account_id:document.getElementById("messageStage")?.dataset.accountId,
        action,user_id:userId,...fields
      });
      settings=result.settings;render();if(modDialog.open)modDialog.close();
      toast("Изменения сохранены.");void window.SovietgramSidebar?.refresh();
    }catch(error){
      if(modDialog.open){const node=$("communityModerationError");node.textContent=error.message;node.hidden=false;}
      else toast(error.message);
    }finally{moderationBusy=false;$("communityModerationSubmit").disabled=false;renderModeration();}
  }
  modForm?.addEventListener("submit",event=>{
    event.preventDefault();if(!moderationTarget)return;
    const permissions=Array.from($("communityModerationRights").querySelectorAll("input:checked")).map(input=>input.value);
    void applyModeration(moderationAction,moderationTarget.user_id,{
      permissions:JSON.stringify(permissions),duration:$("communityModerationDuration").value,reason:$("communityModerationReason").value,
    });
  });
  for(const id of ["communityModerationClose","communityModerationCancel"])$(id)?.addEventListener("click",()=>{if(!moderationBusy)modDialog.close();});
  modDialog?.addEventListener("cancel",event=>{if(moderationBusy)event.preventDefault();});
  $("communityModerationSearch")?.addEventListener("input",renderModeration);
  $("communityModerationFilter")?.addEventListener("change",renderModeration);
  async function refreshModeration(){
    if(moderationBusy)return;
    try{const payload=await fetchJson(profileRoot.dataset.settingsUrl,{cache:"no-store"});settings=payload.settings;render();}
    catch(error){toast(error.message);}
  }
  $("communityModerationRefresh")?.addEventListener("click",refreshModeration);

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

  function renderReactionSettings() {
    const choices = $("communitySettingsReactionChoices");
    if (!choices || !settings) return;
    const allowed = new Set(settings.allowed_reactions || []);
    choices.replaceChildren(...(settings.reaction_choices || []).map(choice => {
      const label = document.createElement("label");
      label.className = "community-settings-toggle-row";
      const title = document.createElement("strong");
      title.textContent = choice.emoji + " " + choice.label;
      const toggle = document.createElement("span");
      toggle.className = "community-settings-switch";
      const input = document.createElement("input");
      input.type = "checkbox"; input.name = "reaction"; input.value = choice.emoji;
      input.checked = allowed.has(choice.emoji);
      const track = document.createElement("span");
      track.append(document.createElement("i"));
      toggle.append(input, track);
      label.append(title, toggle);
      return label;
    }));
  }

  function render() {
    renderOverview();
    renderReactionSettings();
    renderTypeForm();
    renderPermissionsForm();
    renderInvites();
    renderJoinRequests();
    renderAdmins();
    renderMembers();
    renderModeration();
    renderLog();
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
      void window.SovietgramSidebar?.refresh?.();
      return true;
    } catch (error) {
      toast(error.message);
      return false;
    }
  }

  async function changeMemberRole(member) {
    const next = member.role === "admin" ? "member" : "admin";
    await memberAction({ action: "role", username: member.username, role: next });
  }

  async function transferOwnership(member) {
    const accepted = window.confirm(
      "Передать права владельца " + member.display_name + "? После передачи вы останетесь администратором.",
    );
    if (!accepted) return;
    await memberAction({ action: "transfer_owner", username: member.username });
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
      if (!response.ok || response.redirected || payload.ok !== true)
      throw new Error(errorText(payload, response.redirected ? "Сессия истекла. Обновите страницу." : "Не удалось выполнить действие (" + response.status + ")."));
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
          if (await memberAction({ action: "add", username: person.username })) closeMemberSearch();
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
      if (next === "join-requests") void refreshJoinRequests();
      if (next === "moderation") void refreshModeration();
      if (next === "admins") renderAdmins();
      if (next === "members") renderMembers();
      if (next === "log") renderLog();
    });
  });

  backButtons.forEach((button) => button.addEventListener("click", () => setView("overview")));
  // A single handler for both entry points, independent of chat.js.
  document.addEventListener("click", event => {
    const trigger = event.target.closest?.("[data-open-community-settings], #communityProfileSettingsOpen");
    if (!trigger) return;
    event.preventDefault();
    void openSettings();
  });
  retryButton?.addEventListener("click", () => { void openSettings(); });
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

  permissionsForm?.elements.send_media?.addEventListener("change", () => {
    permissionsForm.querySelectorAll("[data-media-kind]").forEach(input => {
      input.disabled = !permissionsForm.elements.send_media.checked;
    });
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
    values.media_kinds = JSON.stringify(Array.from(permissionsForm.querySelectorAll("[data-media-kind]:checked"),
      input => input.dataset.mediaKind));
    try {
      await applySettings(values);
      setView("overview");
      toast("Разрешения сохранены.");
    } catch (error) {
      permissionsError.textContent = error.message;
      permissionsError.hidden = false;
    }
  });

  $("communitySettingsReactionsForm")?.addEventListener("submit", async event => {
    event.preventDefault();
    const form = event.currentTarget;
    const submit = form.querySelector('button[type="submit"]');
    const errorNode = $("communitySettingsReactionsError");
    if (submit.disabled || !settings) return;
    errorNode.hidden = true;
    submit.disabled = true;
    try {
      const values = [...form.querySelectorAll('input[name="reaction"]:checked')].map(input => input.value);
      await applySettings({section:"reactions", reactions:JSON.stringify(values)});
      window.SovietgramSocial?.setAllowedReactions(settings.allowed_reactions);
      setView("overview");
      toast("Реакции сохранены.");
    } catch (error) {
      errorNode.textContent = error.message;
      errorNode.hidden = false;
    } finally { submit.disabled = false; }
  });

  comments?.addEventListener("change", async () => {
    if (commentsBusy || !settings) return;
    commentsBusy = true;
    const desired = comments.checked;
    comments.disabled = true;
    try {
      await applySettings({section:"comments",enabled:desired?"1":"0"});
      window.SovietgramDiscussions?.sync(Boolean(settings.comments_enabled), {});
      toast(desired ? "Комментарии включены." : "Комментарии отключены.");
    } catch (error) {
      comments.checked = !desired; toast(error.message);
    } finally { comments.disabled = false; commentsBusy = false; }
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
        requires_approval: data.get("requires_approval") || "0",
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
    if (event.key !== "Escape" || panel.hidden || profileRoot.hidden || document.querySelector("dialog[open], #userProfileOverlay:not([hidden]), #imageViewer:not([hidden])")) return;
    event.preventDefault();
    event.stopImmediatePropagation();
    if (activeView !== "overview") {
      setView("overview");
      return;
    }
    closeSettings();
  }, true);

  window.openCommunitySettings = openSettings;
  window.closeCommunitySettings = closeSettings;
  window.communitySettingsVisible = () => !profileRoot.hidden && !panel.hidden;
})();
