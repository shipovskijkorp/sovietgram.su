(() => {
  if (!window.isSecureContext || !("serviceWorker" in navigator)) return;
  let promptEvent = null;
  const standalone = window.matchMedia("(display-mode: standalone)");
  const links = Array.from(document.querySelectorAll("[data-pwa-install]"));
  const help = document.getElementById("pwaInstallHelp");
  function refresh() {
    const installed = standalone.matches || navigator.standalone === true;
    for (const link of links) link.hidden = installed;
  }
  // Listen synchronously; the install prompt may arrive before registration finishes.
  window.addEventListener("beforeinstallprompt", event => {
    event.preventDefault();
    promptEvent = event;
    refresh();
  });
  window.addEventListener("appinstalled", () => {
    promptEvent = null;
    for (const link of links) link.hidden = true;
  });
  standalone.addEventListener?.("change", refresh);
  for (const link of links) {
    link.addEventListener("click", async event => {
      event.preventDefault();
      if (promptEvent) {
        const current = promptEvent;
        promptEvent = null;
        try { await current.prompt(); await current.userChoice; } catch (_) { help?.showModal(); }
      } else if (help && !help.open) help.showModal();
    });
  }
  navigator.serviceWorker.register("/sw.js", {scope:"/", updateViaCache:"none"})
    .then(refresh)
    .catch(() => { /* Do not advertise installation if registration failed. */ });
})();
