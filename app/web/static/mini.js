"use strict";
(() => {
  const tg = window.Telegram?.WebApp;
  let token = "";
  let attempted = false;
  // The SDK has already parsed the launch fragment; keep signed data out of navigation.
  history.replaceState(null, "", location.pathname + "#/");
  document.documentElement.classList.add("telegram-mini");
  function safeArea() {
    for (const side of ["top", "bottom", "left", "right"]) {
      const inset = Math.max(Number(tg?.safeAreaInset?.[side]) || 0, Number(tg?.contentSafeAreaInset?.[side]) || 0);
      document.documentElement.style.setProperty(`--mini-safe-${side}`, `${Math.min(200, Math.max(0, inset))}px`);
    }
  }
  function backState() {
    const opened = document.getElementById("dialog")?.open;
    const nested = !["", "#/", "#/overview"].includes(location.hash.split("?")[0]);
    if (opened || nested) tg?.BackButton?.show(); else tg?.BackButton?.hide();
    document.querySelectorAll(".mini-tabs a").forEach((a) => {
      const section = location.hash.split("?")[0].split("/")[1] || "overview";
      if (a.dataset.section === section) a.setAttribute("aria-current", "page");
      else a.removeAttribute("aria-current");
    });
  }
  function back() {
    const dialog = document.getElementById("dialog");
    if (dialog?.open) { dialog.close(); return; }
    const parts = location.hash.slice(2).split("?")[0].split("/").filter(Boolean);
    parts.pop();
    location.hash = "/" + parts.join("/");
  }
  tg?.ready();
  tg?.expand();
  tg?.setHeaderColor?.("#f5f6f3");
  tg?.setBackgroundColor?.("#f5f6f3");
  tg?.BackButton?.onClick(back);
  tg?.onEvent("safeAreaChanged", safeArea);
  tg?.onEvent("contentSafeAreaChanged", safeArea);
  safeArea();
  window.addEventListener("hashchange", backState);
  new MutationObserver(backState).observe(document.getElementById("dialog"), {attributes: true, attributeFilter: ["open"]});
  window.FiinopsMini = {
    headers: () => token ? {Authorization: `Bearer ${token}`} : {},
    clear: () => { token = ""; document.querySelector(".mini-tabs")?.remove(); tg?.BackButton?.hide(); },
    close: () => tg?.close(),
    async authorize() {
      if (attempted) throw new Error("Закройте приложение и откройте его заново из бота.");
      attempted = true;
      if (!tg?.initData) throw new Error("Откройте панель кнопкой «Панель руководителя» в Telegram-боте.");
      const response = await fetch("/api/auth/telegram-mini", {
        method: "POST", credentials: "omit",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({init_data: tg.initData}),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : "Не удалось войти. Откройте приложение заново.");
      token = data.session_token;
      const nav = document.createElement("nav");
      nav.className = "mini-tabs";
      nav.setAttribute("aria-label", "Разделы панели");
      for (const [section, title] of [["overview", "Обзор"], ["money", "Деньги"], ["documents", "Документы"], ["reports", "Отчёты"], ["profile", "Профиль"]]) {
        const link = document.createElement("a");
        link.href = "#/" + section;
        link.dataset.section = section;
        link.textContent = title;
        nav.append(link);
      }
      document.body.append(nav);
      backState();
      return {user: data.user, csrf_token: data.csrf_token};
    },
  };
})();
