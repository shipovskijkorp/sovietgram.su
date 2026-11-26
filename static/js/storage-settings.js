(() => {
  const root = document.getElementById("storageLocal");
  if (!root) return;
  const cacheValue = document.getElementById("storagePublicCache");
  const estimate = document.getElementById("storageEstimate");
  const clear = document.getElementById("storageClearCache");
  const status = document.getElementById("storageCacheStatus");
  const prefix = "sovietgram-public-shell-";
  const format = bytes => {
    if (!Number.isFinite(bytes) || bytes < 0) return "Нет данных";
    const units = ["Б", "КиБ", "МиБ", "ГиБ", "ТиБ"];
    let n = bytes, unit = 0;
    while (n >= 1024 && unit < units.length - 1) { n /= 1024; unit++; }
    return new Intl.NumberFormat("ru-RU", {maximumFractionDigits: unit ? 1 : 0}).format(n) + " " + units[unit];
  };
  async function refresh() {
    try {
      const info = await navigator.storage?.estimate?.();
      estimate.textContent = format(info?.usage);
    } catch (_) { estimate.textContent = "Нет данных"; }
    try {
      if (!("caches" in window)) throw Error("Cache Storage unavailable");
      const names = (await caches.keys()).filter(name => name.startsWith(prefix));
      let size = 0;
      for (const name of names) {
        const cache = await caches.open(name);
        for (const request of await cache.keys()) {
          const response = await cache.match(request);
          if (response) size += (await response.blob()).size;
        }
      }
      cacheValue.textContent = format(size);
      clear.hidden = false;
      clear.disabled = !names.length;
    } catch (_) {
      cacheValue.textContent = "Недоступно в этом браузере";
      clear.hidden = true;
    }
  }
  clear.addEventListener("click", async () => {
    clear.disabled = true;
    status.textContent = "";
    try {
      const names = (await caches.keys()).filter(name => name.startsWith(prefix));
      await Promise.all(names.map(name => caches.delete(name)));
      status.textContent = "Публичный кэш очищен. Переписки и очередь отправки сохранены.";
    } catch (_) {
      status.textContent = "Не удалось очистить кэш.";
    } finally { await refresh(); }
  });
  void refresh();
})();
