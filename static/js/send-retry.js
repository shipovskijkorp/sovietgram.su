/* Stable IDs for logical sends. Never retry a write with a newly generated ID. */
(() => {
  function uuid() {
    if (window.crypto.randomUUID) return window.crypto.randomUUID();
    const bytes = window.crypto.getRandomValues(new Uint8Array(16));
    bytes[6] = (bytes[6] & 15) | 64;
    bytes[8] = (bytes[8] & 63) | 128;
    const hex = Array.from(bytes, value => value.toString(16).padStart(2, "0")).join("");
    return hex.slice(0, 8) + "-" + hex.slice(8, 12) + "-" + hex.slice(12, 16) + "-" +
      hex.slice(16, 20) + "-" + hex.slice(20);
  }
  const objects = new WeakMap();
  function fileIdentity(file) {
    if (!objects.has(file)) objects.set(file, uuid());
    return objects.get(file);
  }
  function batch() {
    const keys = new Map();
    return {
      key(slot, signature) {
        const value = JSON.stringify(signature);
        const prior = keys.get(slot);
        if (prior?.signature === value) return prior.id;
        const id = uuid();
        keys.set(slot, { signature: value, id });
        return id;
      },
      clear() { keys.clear(); },
    };
  }
  async function fetchSend(url, options) {
    // One automatic retry for uncertain transport failures. FormData remains
    // reusable; the same client_message_id is present in both requests.
    for (let attempt = 0; attempt < 2; attempt += 1) {
      try {
        const response = await fetch(url, options);
        if (attempt === 0 && [502, 503, 504].includes(response.status)) continue;
        return response;
      } catch (error) {
        if (attempt) throw error;
      }
    }
    throw new Error("Не удалось получить ответ сервера.");
  }

  async function textKey(scope, signature, memory) {
    // Preserve an unacknowledged text send across a reload without storing
    // message text in browser storage. Each tab has its own pending key.
    if (!window.crypto.subtle) return memory.key("text", signature);
    try {
      const bytes = new TextEncoder().encode(JSON.stringify(signature));
      const digest = await window.crypto.subtle.digest("SHA-256", bytes);
      const hash = Array.from(new Uint8Array(digest), b => b.toString(16).padStart(2, "0")).join("");
      const prior = JSON.parse(sessionStorage.getItem(scope) || "null");
      if (prior?.hash === hash && prior.id) return prior.id;
      const id = memory.key("text", signature);
      sessionStorage.setItem(scope, JSON.stringify({ hash, id }));
      return id;
    } catch (_error) {
      return memory.key("text", signature);
    }
  }
  function clearText(scope, memory) {
    memory.clear();
    try { sessionStorage.removeItem(scope); } catch (_error) {}
  }
  // Text outbox is tab/account/chat scoped. Persist the same UUID before
  // the first request, including after an uncertain response or reload.
  function createOutbox({ storage, key, send, changed = () => {}, delivered = () => {}, now = Date.now }) {
    const valid = item => item && typeof item.id === "string" &&
      /^[a-f0-9-]{36}$/i.test(item.id) && typeof item.text === "string" &&
      item.text.trim() && item.text.length <= 4096 &&
      typeof item.reply === "string" && /^\d*$/.test(item.reply);
    let items = [], busy = false, saved = true;
    try {
      const stored = JSON.parse(storage.getItem(key) || "[]");
      if (Array.isArray(stored)) {
        items = stored.filter(valid).slice(0, 20).map(item => ({
          id: item.id, text: item.text, reply: item.reply, silent: !!item.silent,
          createdAt: Number(item.createdAt) || now(), attempts: Math.max(0, Number(item.attempts) || 0),
          state: item.state === "failed" ? "failed" : "waiting",
          error: typeof item.error === "string" ? item.error : "",
          nextAttempt: Number(item.nextAttempt) || 0,
        }));
      }
    } catch (_) { saved = false; }
    function snapshot() { return items.map(item => ({...item})); }
    function persist() {
      try {
        if (items.length) storage.setItem(key, JSON.stringify(items));
        else storage.removeItem(key);
        saved = true;
      } catch (_) { saved = false; }
      changed(snapshot(), saved);
    }
    function enqueue(text, reply = "", silent = false) {
      if (items.length >= 20) return false;
      const item = {id: uuid(), text, reply: String(reply || ""), silent: !!silent,
                    createdAt: now(), attempts: 0, state: "waiting", error: "", nextAttempt: 0};
      if (!valid(item)) return false;
      items.push(item); persist(); return true;
    }
    function discard(id) {
      const item = items.find(entry => entry.id === id);
      if (!item || item.state === "sending") return false;
      items = items.filter(entry => entry.id !== id); persist(); return true;
    }
    function retryItem(id) {
      const item = items.find(entry => entry.id === id);
      if (!item || item.state === "sending") return false;
      item.state = "waiting"; item.error = ""; item.nextAttempt = 0;
      persist(); return true;
    }
    async function flush() {
      const item = items[0];
      if (busy || !item || item.state === "failed" || item.nextAttempt > now()) return false;
      busy = true; item.state = "sending"; item.attempts += 1; persist();
      let result;
      try { result = await send({...item}); }
      catch (_) { result = {retry: true, error: "Нет ответа сервера"}; }
      if (result?.ok) {
        items = items.filter(entry => entry.id !== item.id);
        busy = false; persist();
        try { delivered(result, {...item}); } catch (_) {}
        return true;
      }
      item.error = result?.error || "Не удалось отправить сообщение";
      if (result?.retry) {
        item.state = "waiting";
        const delay = Math.min(30000, 1000 * 2 ** Math.min(item.attempts, 5));
        item.nextAttempt = now() + Math.max(delay, Number(result.delay) || 0);
      } else {
        item.state = "failed"; item.nextAttempt = 0;
      }
      busy = false; persist(); return false;
    }
    return {enqueue, discard, retryItem, flush, snapshot, get saved() { return saved; }};
  }
  window.SovietgramSendRetry = { uuid, batch, fileIdentity, fetchSend, textKey, clearText, createOutbox };
})();
