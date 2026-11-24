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
  window.SovietgramSendRetry = { uuid, batch, fileIdentity, fetchSend, textKey, clearText };
})();
