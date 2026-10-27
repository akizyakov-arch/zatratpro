"use strict";
(() => {
  const app = document.getElementById("app");
  const dialog = document.getElementById("dialog");
  const mini = window.FiinopsMini;
  const state = {
    user: null,
    csrf: "",
    poll: null,
    request: 0,
    refs: null,
    refsAt: 0,
    listRoutes: {},
  };
  const svgPaths = {
    grid: "M3 3h7v7H3z M14 3h7v7h-7z M3 14h7v7H3z M14 14h7v7h-7z",
    wallet:
      "M3 7V5a2 2 0 0 1 2-2h13v4 M3 7h16a2 2 0 0 1 2 2v10a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V7z M21 11h-6v6h6 M17 14h.01",
    file: "M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z M14 2v6h6 M8 13h8 M8 17h5",
    folder:
      "M3 7V5a2 2 0 0 1 2-2h5l2 3h7a2 2 0 0 1 2 2v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z",
    users:
      "M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2 M16 3a4 4 0 0 1 0 8 M22 21v-2a4 4 0 0 0-3-3.87 M9 3a4 4 0 1 0 0 8 4 4 0 0 0 0-8",
    chart: "M4 3v18h17 M8 16v-4 M13 16V8 M18 16V5",
    building:
      "M4 21V3h12v18 M16 9h4v12 M2 21h20 M8 7h4 M8 11h4 M8 15h4 M8 21v-3h4v3",
    user: "M20 21v-2a7 7 0 0 0-14 0v2 M12 3a4 4 0 1 0 0 8 4 4 0 0 0 0-8",
    plus: "M12 5v14 M5 12h14",
    arrow: "M5 12h14 M13 6l6 6-6 6",
    back: "M19 12H5 M11 6l-6 6 6 6",
    down: "M12 3v12 M7 10l5 5 5-5 M4 16v5h16v-5",
    check: "M5 12l4 4L19 6",
    close: "M6 6l12 12 M18 6L6 18",
    search: "M21 21l-5-5 M11 3a8 8 0 1 0 0 16 8 8 0 0 0 0-16",
    shield: "M12 2l9 4v6c0 5-9 10-9 10S3 17 3 12V6z M8 12l3 3 5-6",
    telegram: "M22 3L9 15 M22 3l-4 18-7-6-4 5v-7L2 10z",
    clock: "M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18 M12 7v5l3 2",
    card: "M2 6h20v13H2z M2 10h20 M6 15h3",
    copy: "M9 9h12v12H9z M15 9V3H3v12h6",
    menu: "M3 6h18 M3 12h18 M3 18h18",
    logout: "M9 21H4V3h5 M14 8l5 4-5 4 M8 12h11",
    refresh:
      "M21 8V3l-4 4 M3 16v5l4-4 M20 9A8 8 0 0 0 6 5 M4 15a8 8 0 0 0 14 4",
    empty: "M4 7l3-4h10l3 4v14H4z M4 7h16 M9 11v4h6v-4",
    external: "M14 3h7v7 M10 14L21 3 M21 14v7H3V3h7",
    info: "M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18 M12 11v6 M12 7h.01",
  };
  function icon(name) {
    const node = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    node.setAttribute("viewBox", "0 0 24 24");
    node.setAttribute("aria-hidden", "true");
    const p = document.createElementNS("http://www.w3.org/2000/svg", "path");
    p.setAttribute("d", svgPaths[name] || svgPaths.file);
    node.append(p);
    return node;
  }
  function h(tag, attrs = {}, ...children) {
    const n = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs)) {
      if (v === null || v === undefined || v === false) continue;
      if (k === "class") n.className = v;
      else if (k === "text") n.textContent = v;
      else if (k.startsWith("on")) n.addEventListener(k.slice(2), v);
      else if (k === "value") n.value = v;
      else if (k === "checked") n.checked = v;
      else if (k === "disabled") n.disabled = v;
      else n.setAttribute(k, v === true ? "" : String(v));
    }
    children.flat(Infinity).forEach((c) => {
      if (c !== null && c !== undefined && c !== false)
        n.append(c instanceof Node ? c : document.createTextNode(String(c)));
    });
    return n;
  }
  const text = (value, fallback = "—") =>
    value === null || value === undefined || value === ""
      ? fallback
      : String(value);
  const initials = (name) =>
    String(name || "F")
      .trim()
      .split(/\s+/)
      .slice(0, 2)
      .map((x) => x[0])
      .join("")
      .toUpperCase();
  const money = (value, currency = "RUB") => {
    if (value === null || value === undefined) return "—";
    const exact = String(value).match(/^(-?)(\d+)(?:\.(\d{1,2}))?$/);
    if (exact) {
      const integer = new Intl.NumberFormat("ru-RU").format(BigInt(exact[2]));
      const fraction = (exact[3] || "").padEnd(2, "0");
      const symbol = { RUB: "₽", USD: "$", EUR: "€" }[currency] || currency;
      return `${exact[1]}${integer}${fraction === "00" ? "" : "," + fraction} ${symbol}`;
    }
    const n = Number(value);
    if (!Number.isFinite(n)) return "—";
    try {
      return new Intl.NumberFormat("ru-RU", {
        style: "currency",
        currency,
        maximumFractionDigits: 2,
        minimumFractionDigits: n % 1 ? 2 : 0,
      }).format(n);
    } catch {
      return `${n.toLocaleString("ru-RU")} ${currency}`;
    }
  };
  const date = (value) => {
    if (!value) return "—";
    const d = new Date(value);
    return Number.isNaN(d.valueOf())
      ? text(value)
      : new Intl.DateTimeFormat("ru-RU", {
          day: "2-digit",
          month: "short",
          year: "numeric",
          timeZone: "UTC",
        }).format(d);
  };
  const datetime = (value) => {
    if (!value) return "—";
    const d = new Date(value);
    return Number.isNaN(d.valueOf())
      ? text(value)
      : new Intl.DateTimeFormat("ru-RU", {
          day: "2-digit",
          month: "short",
          year: "numeric",
          hour: "2-digit",
          minute: "2-digit",
          timeZone: "UTC",
        }).format(d) + " UTC";
  };
  const who = (row) =>
    row.employee_name ||
    row.uploaded_by_name ||
    row.name ||
    [row.first_name, row.last_name].filter(Boolean).join(" ") ||
    row.username ||
    `Пользователь №${row.user_id || row.employee_id || row.id}`;
  const items = (data) => (Array.isArray(data) ? data : data?.items || []);
  const badge = (label, tone = "") =>
    h("span", { class: `badge ${tone}` }, label);
  const status = (row) =>
    row.canceled_at
      ? badge("Отменена", "danger")
      : row.rejected_at
        ? badge("Отклонено", "danger")
        : row.approved_at
          ? badge("Учтено", "success")
          : row.received_at
            ? badge("Получено", "success")
            : badge("Ожидает подтверждения", "warning");
  function button(label, action, kind = "", image) {
    return h(
      "button",
      { type: "button", class: `button ${kind}`, onclick: action },
      image && icon(image),
      label,
    );
  }
  function link(label, to, kind = "", image) {
    return h(
      "a",
      { href: to, class: `button ${kind}` },
      image && icon(image),
      label,
    );
  }
  function toast(message, error = false) {
    const n = h(
      "div",
      { class: `toast${error ? " error" : ""}` },
      h(
        "button",
        { "aria-label": "Закрыть уведомление", onclick: () => n.remove() },
        "×",
      ),
      message,
    );
    document.getElementById("toast-region").append(n);
    setTimeout(() => n.remove(), 7000);
  }
  async function api(path, options = {}) {
    const userAtRequest = state.user;
    const opts = {
      credentials: mini ? "omit" : "same-origin",
      ...options,
      headers: { Accept: "application/json", ...(options.headers || {}), ...(mini?.headers() || {}) },
    };
    if (opts.body && typeof opts.body !== "string") {
      opts.body = JSON.stringify(opts.body);
      opts.headers["Content-Type"] = "application/json";
    }
    if (opts.method && opts.method !== "GET")
      opts.headers["X-CSRF-Token"] = state.csrf;
    const res = await fetch(path, opts);
    let data = null;
    const ct = res.headers.get("content-type") || "";
    if (ct.includes("json")) data = await res.json();
    if (!res.ok) {
      const detail = data?.detail;
      const message =
        typeof detail === "string"
          ? detail
          : Array.isArray(detail)
            ? detail.map((x) => x.msg).join("; ")
            : data?.message || `Не удалось выполнить запрос (${res.status}).`;
      const e = new Error(message);
      e.status = res.status;
      if (res.status === 401 && state.user && state.user === userAtRequest) {
        state.user = null;
        state.csrf = "";
        dialog.close();
        login("Сессия завершена. Подтвердите вход ещё раз.");
      }
      throw e;
    }
    return data;
  }
  function query(values) {
    const p = new URLSearchParams();
    Object.entries(values || {}).forEach(([k, v]) => {
      if (v !== "" && v !== null && v !== undefined) p.set(k, v);
    });
    return p.toString();
  }
  function route() {
    const [path, qs = ""] = (location.hash.slice(1) || "/").split("?");
    return {
      parts: path.split("/").filter(Boolean),
      params: Object.fromEntries(new URLSearchParams(qs)),
    };
  }
  function go(path, params = {}) {
    location.hash = `/${path}${query(params) ? "?" + query(params) : ""}`;
  }
  function pageTitle() {
    const p = route().parts[0];
    return (
      {
        overview: "Обзор",
        money: "Деньги",
        documents: "Документы",
        projects: "Проекты",
        employees: "Сотрудники",
        reports: "Отчёты",
        company: "Моя компания",
        profile: "Профиль",
        companies: "Компании",
        users: "Пользователи",
        stats: "Статистика",
      }[p] || "Обзор"
    );
  }
  const managerNav = [
    ["overview", "Обзор", "grid"],
    ["money", "Деньги", "wallet"],
    ["documents", "Документы", "file"],
    ["projects", "Проекты", "folder"],
    ["employees", "Сотрудники", "users"],
    ["reports", "Отчёты", "chart"],
    ["company", "Моя компания", "building"],
  ];
  const ownerNav = [
    ["companies", "Компании", "building"],
    ["users", "Пользователи", "users"],
    ["stats", "Статистика", "chart"],
  ];
  function shell() {
    const nav = state.user.role === "owner" ? ownerNav : managerNav;
    const active = route().parts[0] || nav[0][0];
    const company = state.user.company_name || "Управление системой";
    const sidebar = h(
      "aside",
      {
        class: "sidebar",
        id: "app-navigation",
        "aria-label": "Главная навигация",
      },
      brand(),
      h(
        "div",
        { class: "workspace-chip" },
        h("span", { class: "company-avatar" }, initials(company)),
        h(
          "div",
          { class: "workspace-name" },
          company,
          h(
            "small",
            {},
            state.user.role === "owner"
              ? "Кабинет владельца"
              : "Рабочее пространство",
          ),
        ),
      ),
      h(
        "p",
        { class: "nav-caption" },
        state.user.role === "owner" ? "СИСТЕМА" : "УПРАВЛЕНИЕ",
      ),
      h(
        "nav",
        { class: "nav-list" },
        nav.map(([id, label, img]) =>
          h(
            "a",
            {
              href: `#/${id}`,
              class: `nav-link ${active === id ? "active" : ""}`,
              "aria-current": active === id ? "page" : null,
            },
            icon(img),
            label,
          ),
        ),
      ),
      h(
        "div",
        { class: "sidebar-foot" },
        h(
          "div",
          { class: "sidebar-note" },
          h("span", { class: "live-dot" }),
          h(
            "span",
            {},
            "Бот и панель",
            h("br"),
            "в одном рабочем пространстве",
          ),
        ),
        h(
          "a",
          { class: "user-menu", href: "#/profile" },
          h("span", { class: "avatar" }, initials(state.user.name)),
          h(
            "span",
            {},
            h("span", { class: "user-name" }, text(state.user.name)),
            h(
              "span",
              { class: "user-role" },
              state.user.role === "owner" ? "Владелец системы" : "Руководитель",
            ),
          ),
        ),
      ),
    );
    const main = h(
      "main",
      { id: "main-content", class: "main-content", tabindex: "-1" },
      loading(),
    );
    const frame = h(
      "div",
      { class: "app-shell" },
      sidebar,
      h("button", {
        class: "mobile-overlay",
        "aria-label": "Закрыть меню",
        onclick: () => {
          frame.classList.remove("menu-open");
          frame
            .querySelector(".menu-button")
            .setAttribute("aria-expanded", "false");
        },
      }),
      h(
        "div",
        { class: "main-shell" },
        h(
          "header",
          { class: "topbar" },
          h(
            "button",
            {
              class: "menu-button",
              "aria-label": "Открыть меню",
              "aria-controls": "app-navigation",
              "aria-expanded": "false",
              onclick: (event) => {
                const expanded = frame.classList.toggle("menu-open");
                event.currentTarget.setAttribute(
                  "aria-expanded",
                  String(expanded),
                );
              },
            },
            icon("menu"),
          ),
          h(
            "div",
            { class: "breadcrumb" },
            h("span", {}, "Рабочее пространство"),
            h("span", { class: "separator" }, "/"),
            h("strong", {}, pageTitle()),
          ),
          h(
            "div",
            { class: "topbar-end" },
            h(
              "span",
              { class: "topbar-clock" },
              date(new Date().toISOString()),
            ),
            h(
              "span",
              { class: "secure-tag" },
              icon("shield"),
              h("span", {}, "Защищённый доступ"),
            ),
            h(
              "a",
              {
                href: "#/profile",
                "aria-label": "Мой профиль",
                class: "avatar",
              },
              initials(state.user.name),
            ),
          ),
        ),
        main,
      ),
    );
    app.replaceChildren(frame);
    app.setAttribute("aria-busy", "false");
    return main;
  }
  function brand() {
    return h(
      "div",
      { class: "brand" },
      h("span", { class: "brand-mark" }, "F"),
      h(
        "span",
        { class: "brand-text" },
        "FIINOPS",
        h("small", {}, "ФИНАНСЫ ПОД КОНТРОЛЕМ"),
      ),
    );
  }
  function loading(message = "Загружаем данные…") {
    return h(
      "div",
      { class: "loading-state", role: "status" },
      h("span", { class: "spinner" }),
      message,
    );
  }
  function header(title, description = "", actions = []) {
    return h(
      "div",
      { class: "page-header" },
      h(
        "div",
        {},
        h(
          "p",
          { class: "eyebrow" },
          state.user.role === "owner"
            ? "FIINOPS / СИСТЕМА"
            : "FIINOPS / РАБОЧЕЕ ПРОСТРАНСТВО",
        ),
        h("h1", {}, title),
        description && h("p", { class: "page-description" }, description),
      ),
      h("div", { class: "page-actions" }, actions),
    );
  }
  function panel(title, body, sub = "", action) {
    return h(
      "section",
      { class: "panel" },
      title &&
        h(
          "div",
          { class: "panel-heading" },
          h("h2", {}, title),
          action || h("small", {}, sub),
        ),
      body,
    );
  }
  function empty(
    title = "Здесь пока нет записей",
    description = "Измените фильтры или добавьте первую запись.",
    action,
  ) {
    return h(
      "div",
      { class: "empty-state" },
      h("div", { class: "empty-icon" }, icon("empty")),
      h("h3", {}, title),
      h("p", {}, description),
      action,
    );
  }
  function info(message) {
    return h("div", { class: "notice" }, h("p", {}, message));
  }
  function metric(
    label,
    value,
    note = "",
    img = "wallet",
    href,
    highlight = false,
  ) {
    return h(
      href ? "a" : "div",
      { class: `metric ${highlight ? "highlight" : ""}`, href },
      h("span", { class: "metric-label" }, label),
      h("span", { class: "metric-icon" }, icon(img)),
      h("strong", { class: "metric-value" }, value),
      h("span", { class: "metric-note" }, note),
    );
  }
  function table(columns, rows, { emptyTitle, emptyDescription } = {}) {
    if (!rows?.length) return empty(emptyTitle, emptyDescription);
    return h(
      "div",
      { class: "table-wrap" },
      h(
        "table",
        { class: "data-table" },
        h(
          "thead",
          {},
          h(
            "tr",
            {},
            columns.map((c) =>
              h(
                "th",
                { scope: "col", class: c.numeric ? "numeric" : "" },
                c.label,
              ),
            ),
          ),
        ),
        h(
          "tbody",
          {},
          rows.map((row) =>
            h(
              "tr",
              {},
              columns.map((c) =>
                h(
                  "td",
                  { class: c.numeric ? "numeric" : "" },
                  c.render ? c.render(row) : text(row[c.key]),
                ),
              ),
            ),
          ),
        ),
      ),
    );
  }
  function pagination(data, path, params) {
    const total = Number(data?.total ?? items(data).length);
    const page = Number(data?.page || params.page || 1),
      size = Number(data?.per_page || 25),
      pages = Math.max(1, Math.ceil(total / size));
    return h(
      "div",
      { class: "pagination" },
      h(
        "span",
        {},
        total
          ? `${(page - 1) * size + 1}–${Math.min(page * size, total)} из ${total}`
          : "0 записей",
      ),
      h(
        "div",
        { class: "pagination-buttons" },
        h("span", { class: "muted pagination-position" }, `${page} / ${pages}`),
        button(
          "Назад",
          () => go(path, { ...params, page: page - 1 }),
          "small",
          "back",
        ),
        button(
          "Далее",
          () => go(path, { ...params, page: page + 1 }),
          "small",
          "arrow",
        ),
      ),
    );
  }
  function paginatedTable(columns, data, path, params, options = {}) {
    const wrap = h("div", {}, table(columns, items(data), options));
    if (items(data).length) {
      const p = pagination(data, path, params);
      const buttons = p.querySelectorAll("button");
      buttons[0].disabled = Number(data.page || params.page || 1) <= 1;
      buttons[1].disabled =
        Number(data.page || params.page || 1) * Number(data.per_page || 25) >=
        Number(data.total ?? items(data).length);
      wrap.append(p);
    }
    return wrap;
  }
  function mainCell(label, sub, to) {
    return h(
      "div",
      {},
      h(to ? "a" : "span", { class: "cell-main", href: to }, text(label)),
      sub && h("div", { class: "cell-sub" }, sub),
    );
  }
  function field(
    label,
    name,
    {
      type = "text",
      value = "",
      placeholder = "",
      required = false,
      options,
      help,
      min,
      max,
      step,
      pattern,
    } = {},
  ) {
    const id = `field-${name}-${Math.random().toString(36).slice(2, 7)}`;
    const control = options
      ? h(
          "select",
          { id, name, required },
          options.map((o) => h("option", { value: o.value }, o.label)),
        )
      : type === "textarea"
        ? h("textarea", { id, name, required, placeholder }, value)
        : h("input", {
            id,
            name,
            type,
            required,
            value,
            placeholder,
            min,
            max,
            step,
            pattern,
          });
    if (options) control.value = value;
    return h(
      "div",
      { class: `field ${name === "q" ? "search-field" : ""}` },
      h("label", { for: id }, label),
      control,
      help && h("small", {}, help),
    );
  }
  function filterForm(
    path,
    params,
    specs,
    { search = true, dates = false } = {},
  ) {
    const form = h(
      "form",
      {
        class: "filters",
        onsubmit: (event) => {
          event.preventDefault();
          const v = Object.fromEntries(new FormData(form));
          if (dates && v.period !== "custom") {
            delete v.start;
            delete v.end;
          }
          go(path, { ...v, page: 1 });
        },
      },
      search &&
        field("Поиск", "q", {
          value: params.q || "",
          placeholder: "Найти запись…",
        }),
      specs.map((s) =>
        field(s.label, s.name, {
          value: params[s.name] ?? s.options[0]?.value ?? "",
          options: s.options,
        }),
      ),
    );
    const moneySort = ["money", "money/cards", "documents"].includes(path);
    const nameSort = ["projects", "employees", "companies", "users"].includes(
      path,
    );
    if (moneySort || nameSort) {
      const order = [
        { value: "newest", label: "Сначала новые" },
        { value: "oldest", label: "Сначала старые" },
        ...(moneySort
          ? [
              { value: "amount_desc", label: "Сначала крупные суммы" },
              { value: "amount_asc", label: "Сначала меньшие суммы" },
            ]
          : [{ value: "name", label: "По алфавиту" }]),
      ];
      form.append(
        field("Сортировка", "sort", {
          value: params.sort || "newest",
          options: order,
        }),
      );
    }
    if (dates) {
      const period = field("Период", "period", {
        value: params.period || (params.start ? "custom" : "month"),
        options: [
          ["month", "Этот месяц"],
          ["week", "Эта неделя"],
          ["quarter", "Этот квартал"],
          ["half_year", "Это полугодие"],
          ["year", "Этот год"],
          ["all_time", "Всё время"],
          ["custom", "Выбрать даты"],
        ].map(([value, label]) => ({ value, label })),
      });
      const start = field("С даты · UTC", "start", {
        type: "date",
        value: params.start || "",
      });
      const end = field("По дату · UTC", "end", {
        type: "date",
        value: params.end || "",
      });
      start.classList.add("date-field");
      end.classList.add("date-field");
      const toggle = () => {
        const custom = period.querySelector("select").value === "custom";
        start.hidden = !custom;
        end.hidden = !custom;
        start.querySelector("input").required = custom;
        end.querySelector("input").required = custom;
      };
      period.querySelector("select").addEventListener("change", toggle);
      toggle();
      form.append(period, start, end);
    }
    form.append(
      h(
        "button",
        { class: "button", type: "submit" },
        icon("search"),
        "Применить",
      ),
    );
    if (Object.keys(params).some((k) => k !== "page"))
      form.append(button("Сбросить", () => go(path), "ghost small"));
    return form;
  }
  const opts = (rows, label = "Все") => [
    { value: "", label },
    ...rows.map((r) => ({
      value: r.id ?? r.user_id,
      label: (r.name || who(r)) + (r.status === "archived" ? " · архив" : ""),
    })),
  ];
  async function allRows(path) {
    let page = 1,
      rows = [];
    for (;;) {
      const data = await api(
        `${path}${path.includes("?") ? "&" : "?"}page=${page}&per_page=100`,
      );
      rows.push(...items(data));
      if (
        !data?.total ||
        rows.length >= Number(data.total) ||
        !items(data).length
      )
        break;
      page++;
      if (page > 500)
        throw new Error("Слишком большой справочник. Уточните условия поиска.");
    }
    return rows;
  }
  async function refs() {
    if (!state.refs || Date.now() - state.refsAt > 30000) {
      const userAtRequest = state.user;
      const [employees, active, archived] = await Promise.all([
        allRows("/api/employees"),
        allRows("/api/projects"),
        allRows("/api/projects?archived=true"),
      ]);
      if (state.user !== userAtRequest)
        throw new Error("Аккаунт изменился. Обновите страницу.");
      state.refs = { employees, projects: [...active, ...archived] };
      state.refsAt = Date.now();
    }
    return state.refs;
  }
  function detail(entries) {
    return h(
      "dl",
      { class: "detail-grid" },
      entries
        .filter((x) => x[1] !== undefined)
        .map(([label, value, className = ""]) =>
          h(
            "div",
            { class: `detail-item ${className}` },
            h("dt", {}, label),
            h(
              "dd",
              { class: className.includes("amount") ? "amount" : "" },
              value instanceof Node ? value : text(value),
            ),
          ),
        ),
    );
  }
  function back(label, path) {
    return h(
      "a",
      { class: "back-link", href: state.listRoutes[path] || `#/${path}` },
      icon("back"),
      label,
    );
  }
  function openDialog(
    title,
    body,
    submit,
    label = "Сохранить",
    { danger = false, description = "" } = {},
  ) {
    const dialogUser = state.user;
    dialog.replaceChildren(
      h(
        "div",
        { class: "dialog-header" },
        h("h2", { id: "dialog-title" }, title),
        button("Закрыть", () => dialog.close(), "ghost small"),
      ),
    );
    const form = h(
      "form",
      { class: "dialog-body" },
      description && h("p", { class: "dialog-description" }, description),
      body,
    );
    const error = h("div", { class: "error-box", role: "alert", hidden: true });
    const submitButton = h(
      "button",
      { type: "submit", class: `button ${danger ? "danger" : "primary"}` },
      label,
    );
    form.append(
      error,
      h(
        "div",
        { class: "dialog-actions" },
        button("Отмена", () => dialog.close()),
        submitButton,
      ),
    );
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      if (state.user !== dialogUser) {
        dialog.close();
        return;
      }
      if (!form.reportValidity()) return;
      submitButton.disabled = true;
      error.hidden = true;
      try {
        const result = await submit(
          Object.fromEntries(new FormData(form)),
          form,
        );
        if (result !== false && dialog.contains(form)) dialog.close();
      } catch (e) {
        error.textContent = e.message;
        error.hidden = false;
      } finally {
        submitButton.disabled = false;
      }
    });
    dialog.append(form);
    dialog.showModal();
    setTimeout(
      () =>
        form
          .querySelector("input:not([readonly]),select,textarea,button")
          ?.focus(),
      50,
    );
    return form;
  }
  function confirmAction(
    title,
    description,
    action,
    { reason = false, label = "Подтвердить", danger = false } = {},
  ) {
    return openDialog(
      title,
      h(
        "div",
        {},
        h("p", { class: "dialog-description" }, description),
        reason &&
          field("Причина", "reason", {
            type: "textarea",
            required: true,
            placeholder: "Укажите причину решения",
          }),
      ),
      async (values) => {
        await action(values);
        toast("Изменения сохранены");
        await render();
      },
      label,
      { danger },
    );
  }
  async function showInvite(path) {
    const userAtRequest = state.user;
    try {
      const data = await api(path, { method: "POST", body: {} });
      if (state.user !== userAtRequest) return;
      const code = data.code || data.invite_code;
      const url = data.bot_url;
      openDialog(
        "Приглашение",
        h(
          "div",
          {},
          h(
            "p",
            { class: "dialog-description" },
            path.includes("/owner/")
              ? "Передайте приглашение руководителю. В боте он получит доступ к компании."
              : "Передайте приглашение сотруднику. В боте он присоединится к вашей компании.",
          ),
          h("div", { class: "code-box" }, text(code)),
          url &&
            h(
              "a",
              {
                class: "button full",
                href: safeBotUrl(url),
                target: "_blank",
                rel: "noopener noreferrer",
              },
              icon("telegram"),
              "Открыть бота",
            ),
          data.expires_at &&
            h(
              "p",
              { class: "section-footnote" },
              `Действует до ${datetime(data.expires_at)}`,
            ),
        ),
        async () => {
          await navigator.clipboard.writeText(url || code);
          toast("Приглашение скопировано");
        },
        "Скопировать",
      );
    } catch (e) {
      toast(e.message, true);
    }
  }
  async function downloadReport(params) {
    const userAtRequest = state.user;
    try {
      const res = await fetch("/api/reports/export?" + query(params), {
        headers: mini?.headers() || {},
        credentials: mini ? "omit" : "same-origin",
      });
      if (!res.ok) {
        const d = await res.json();
        throw new Error(
          typeof d.detail === "string"
            ? d.detail
            : "Не удалось сформировать Excel.",
        );
      }
      const blob = await res.blob();
      if (state.user !== userAtRequest) return;
      const url = URL.createObjectURL(blob);
      const filename =
        (res.headers.get("content-disposition") || "").match(
          /filename="?([^";]+)/,
        )?.[1] || "FIINOPS-report.xlsx";
      const a = h("a", { href: url, download: filename });
      document.body.append(a);
      a.click();
      a.remove();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
      toast("Excel подготовлен");
    } catch (e) {
      toast(e.message, true);
    }
  }
  const dateParams = (params) =>
    Object.fromEntries(
      ["period", "start", "end", "project_id", "employee_id"]
        .filter((k) => params[k])
        .map((k) => [k, params[k]]),
    );
  function openProjectsOverview(projects, params) {
    if (!Array.isArray(projects)) return null;
    return h(
      "section",
      {
        class: "project-overview",
        "aria-labelledby": "project-overview-title",
      },
      h(
        "h2",
        { id: "project-overview-title", class: "section-label" },
        "По открытым проектам",
      ),
      h(
        "p",
        { class: "section-footnote" },
        "Все неархивные проекты, включая проекты без операций. Суммы — за выбранный период, остатки — на его конец.",
      ),
      projects.length
        ? h(
            "div",
            { class: "project-overview-grid" },
            projects.map((p) => {
              const filters = query({
                ...dateParams(params),
                project_id: p.project_id,
              });
              return h(
                "article",
                { class: "panel project-overview-card" },
                h(
                  "div",
                  { class: "project-overview-heading" },
                  h(
                    "h3",
                    {},
                    h(
                      "a",
                      { href: `#/projects/${p.project_id}` },
                      p.project_name,
                    ),
                  ),
                  h(
                    "span",
                    { class: "muted" },
                    `Документов: ${p.document_count}`,
                  ),
                ),
                h(
                  "div",
                  { class: "panel-body" },
                  detail([
                    [
                      "Затраты по документам · RUB",
                      money(p.document_total),
                      "amount",
                    ],
                    ["Получено сотрудниками", money(p.received)],
                    ["У сотрудников", money(p.cash)],
                    ["Компания должна сотрудникам", money(p.debt)],
                    ["Расходы из выдач", money(p.spent)],
                    ["Возвращено", money(p.returned)],
                    ["Ожидает получения", money(p.pending)],
                    ["Возвраты к подтверждению", money(p.pending_returns)],
                    ["Бизнес-карты · учтено", money(p.card_spent)],
                  ]),
                  h(
                    "details",
                    { class: "project-review-breakdown" },
                    h("summary", {}, "Расшифровка остатков"),
                    detail([
                      ["Остаток на начало", money(p.opening)],
                      ["Расчётный остаток на конец", money(p.closing)],
                      ["Возвраты к подтверждению", money(p.pending_returns)],
                    ]),
                  ),
                  h(
                    "div",
                    { class: "inline-actions mt-24" },
                    link(
                      "Документы",
                      `#/documents?${filters}`,
                      "small",
                      "file",
                    ),
                    link("Выдачи", `#/money?${filters}`, "small", "wallet"),
                    link("Отчёт", `#/reports?${filters}`, "small", "chart"),
                  ),
                ),
              );
            }),
          )
        : empty(
            "Открытых проектов пока нет",
            "Создайте проект или восстановите его из архива.",
            link("Перейти к проектам", "#/projects", "", "folder"),
          ),
      h(
        "p",
        { class: "section-footnote" },
        "Общие итоги выше включают и архивные проекты. Здесь остатки показаны по каждому проекту; общий остаток сотрудника учитывает все его проекты.",
      ),
    );
  }
  function duplicateNotice(review) {
    if (!review?.total) return null;
    return h(
      "div",
      { class: "summary-strip duplicate-alert", role: "status" },
      icon("file"),
      h(
        "div",
        {},
        h("strong", {}, `Дубли документов к проверке: ${review.total}`),
        h(
          "p",
          {},
          `Точных: ${review.exact}. Возможных: ${review.probable}. За всё время, включая архивные проекты.`,
        ),
        review.involving_archived_projects
          ? h(
              "p",
              {},
              `Связаны с архивными проектами: ${review.involving_archived_projects}.`,
            )
          : null,
      ),
      link(
        "Проверить дубли",
        "#/documents?period=all_time&duplicate_status=flagged",
        "small",
        "arrow",
      ),
    );
  }
  async function overview(main, params) {
    const data = await api("/api/overview?" + query(params));
    const m = data.money || data;
    const t = m.totals || data.totals || data;
    const cash = m.cash_on_hand ?? m.cash ?? data.cash;
    const debt = m.employee_debt ?? m.debt ?? data.debt;
    main.replaceChildren(
      header(
        "Обзор финансов",
        "Все проекты, документы и деньги компании в одном месте.",
        [button("Выдать деньги", issueDialog, "primary", "plus")],
      ),
      filterForm("overview", params, [], { search: false, dates: true }),
      h(
        "div",
        { class: "metrics" },
        metric(
          "Затраты по документам",
          money(data.document_total ?? data.total_amount),
          "По дате загрузки · RUB",
          "file",
          "#/documents",
          true,
        ),
        metric(
          "У сотрудников",
          money(cash),
          "На конец выбранного периода",
          "wallet",
          "#/money",
        ),
        metric(
          "Компания должна сотрудникам",
          money(debt),
          "На конец выбранного периода",
          "users",
          "#/money",
        ),
        metric(
          "Возвраты к подтверждению",
          money(t.pending_returns),
          "Получение денег от сотрудников",
          "clock",
          "#/money/reviews",
        ),
      ),
      duplicateNotice(data.duplicate_review),
      openProjectsOverview(data.open_projects, params),
      h(
        "div",
        { class: "summary-strip" },
        icon("info"),
        h(
          "p",
          {},
          h("strong", {}, "Каждая сумма — на своём месте. "),
          "Выдачи не увеличивают затраты проекта. Расходы по бизнес-картам не уменьшают подотчётный остаток.",
        ),
      ),
      h(
        "div",
        { class: "two-column" },
        panel(
          "Движение подотчётных денег",
          h(
            "div",
            { class: "panel-body" },
            detail([
              ["Получено сотрудниками", money(t.received)],
              ["Учтённые расходы", money(t.spent)],
              ["Возвращено", money(t.returned)],
              ["Ожидает получения", money(t.pending)],
              ["Возвраты к подтверждению", money(t.pending_returns)],
            ]),
          ),
          "Выбранный период",
        ),
        panel(
          "Рабочее пространство",
          h(
            "div",
            { class: "panel-body" },
            detail([
              ["Компания", state.user.company_name, "wide"],
              ["Активных проектов", data.project_count],
              ["Сотрудников", data.employee_count],
              ["Документов за период", data.document_count],
            ]),
            h(
              "div",
              { class: "inline-actions mt-24" },
              link("Все отчёты", "#/reports", "small", "chart"),
              link("Подтвердить возвраты", "#/money/reviews", "small", "arrow"),
              link(
                "Дубли документов",
                "#/documents?period=all_time&duplicate_status=flagged",
                "small",
                "file",
              ),
            ),
          ),
        ),
      ),
      h(
        "p",
        { class: "section-footnote" },
        "Границы отчётных периодов: UTC. Денежные движения учитываются по времени подтверждения; документы — по времени загрузки.",
      ),
    );
  }
  function moneyTabs(active) {
    return h(
      "nav",
      { class: "tabs", "aria-label": "Разделы денег" },
      [
        ["", "Выдачи"],
        ["reviews", "Подтверждение возвратов"],
        ["cards", "Бизнес-карты"],
      ].map(([id, label]) =>
        h(
          "a",
          {
            href: `#/money${id ? "/" + id : ""}`,
            class: `tab ${active === id ? "active" : ""}`,
            "aria-current": active === id ? "page" : null,
          },
          label,
        ),
      ),
    );
  }
  async function moneyPage(main, parts, params) {
    if (parts[1] && /^\d+$/.test(parts[1]))
      return advanceDetail(main, parts[1]);
    const section = parts[1] || "";
    params = { period: "all_time", ...params };
    const actions =
      section === "cards"
        ? [button("Добавить карту", cardDialog, "primary", "plus")]
        : [button("Выдать деньги", issueDialog, "primary", "plus")];
    main.replaceChildren(
      header(
        "Деньги",
        "Выдачи сотрудникам, расходы и возвраты без лишних действий.",
        actions,
      ),
      moneyTabs(section),
      loading(),
    );
    if (section === "reviews") return reviewsPage(main, params);
    if (section === "cards") return cardsPage(main, params);
    const r = await refs();
    const data = await api("/api/advances?" + query(params));
    main.lastChild.remove();
    main.append(
      filterForm(
        "money",
        params,
        [
          {
            name: "employee_id",
            label: "Сотрудник",
            options: opts(r.employees),
          },
          { name: "project_id", label: "Проект", options: opts(r.projects) },
          {
            name: "status",
            label: "Получение",
            options: [
              { value: "", label: "Все состояния" },
              { value: "pending", label: "Ожидает получения" },
              { value: "received", label: "Получено" },
              { value: "canceled", label: "Отменено" },
            ],
          },
        ],
        { dates: true },
      ),
      panel(
        "",
        paginatedTable(
          [
            {
              label: "Сотрудник / назначение",
              render: (r) =>
                mainCell(
                  r.employee_name || who(r),
                  r.purpose,
                  `#/money/${r.id}`,
                ),
            },
            { label: "Проект", key: "project_name" },
            { label: "Сумма", numeric: true, render: (r) => money(r.amount) },
            {
              label: "Остаток",
              numeric: true,
              render: (r) => money(r.received_at ? r.balance : null),
            },
            {
              label: "Получение",
              render: (r) =>
                r.canceled_at
                  ? badge("Отменена", "danger")
                  : r.received_at
                    ? badge("Получено", "success")
                    : badge("Ожидает", "warning"),
            },
            { label: "Дата выдачи", render: (r) => date(r.created_at) },
            {
              label: "",
              render: (r) =>
                link("Открыть", `#/money/${r.id}`, "small ghost", "arrow"),
            },
          ],
          data,
          "money",
          params,
          {
            emptyTitle: "Выдач пока нет",
            emptyDescription:
              "Выдайте деньги сотруднику на закупку. Он подтвердит получение в боте.",
          },
        ),
      ),
    );
  }
  async function issueDialog() {
    try {
      const r = await refs();
      const employees = r.employees.filter(
        (e) =>
          e.role !== "manager" &&
          e.status === "active" &&
          e.is_active !== false,
      );
      const projects = r.projects.filter((p) => p.status !== "archived");
      if (!employees.length) {
        toast(
          "Сначала пригласите активного сотрудника в разделе «Сотрудники».",
          true,
        );
        return;
      }
      if (!projects.length) {
        toast("Сначала создайте активный проект в разделе «Проекты».", true);
        return;
      }
      const key = crypto.randomUUID();
      let confirmed = false;
      const body = h(
        "div",
        { class: "form-grid" },
        field("Сотрудник", "employee_id", {
          required: true,
          options: opts(employees, "Выберите сотрудника"),
        }),
        field("Проект", "project_id", {
          required: true,
          options: opts(projects, "Выберите проект"),
        }),
        field("Сумма, ₽", "amount", {
          required: true,
          type: "number",
          min: "0.01",
          max: "999999999999.99",
          step: "0.01",
          placeholder: "0,00",
        }),
        field("Назначение", "purpose", {
          required: true,
          placeholder: "Например, материалы для объекта",
        }),
      );
      const summary = h("div", {
        class: "dialog-confirm-summary wide",
        hidden: true,
      });
      const edit = button(
        "Изменить данные",
        () => {
          confirmed = false;
          summary.hidden = true;
          edit.hidden = true;
          form.querySelectorAll("input,select").forEach((x) => {
            x.disabled = false;
          });
          form.querySelector('button[type="submit"]').textContent =
            "Продолжить";
        },
        "small ghost",
        "back",
      );
      edit.hidden = true;
      body.append(summary, edit);
      const form = openDialog(
        "Выдать деньги сотруднику",
        body,
        async (values, f) => {
          if (!confirmed) {
            const employee = employees.find(
              (x) => String(x.id ?? x.user_id) === values.employee_id,
            );
            const project = projects.find(
              (x) => String(x.id) === values.project_id,
            );
            summary.replaceChildren(
              h("span", {}, who(employee)),
              h("span", {}, project.name),
              h("strong", {}, money(values.amount)),
              h("span", {}, values.purpose),
            );
            summary.hidden = false;
            edit.hidden = false;
            confirmed = true;
            f.querySelector('button[type="submit"]').textContent =
              "Подтвердить выдачу";
            f.querySelectorAll("input,select").forEach((x) => {
              x.disabled = true;
            });
            return false;
          }
          const values2 = Object.fromEntries(
            [...f.querySelectorAll("[name]")].map((x) => [x.name, x.value]),
          );
          const result = await api("/api/advances", {
            method: "POST",
            body: { ...values2, request_key: key },
          });
          toast(`Выдача №${result.id ?? result.advance_id ?? result} создана`);
          await render();
        },
        "Продолжить",
        {
          description:
            "Выберите получателя и проект, укажите сумму и назначение. Получение сотрудник подтвердит сам.",
        },
      );
      form.addEventListener("input", () => {
        if (confirmed) {
          confirmed = false;
          summary.hidden = true;
          form.querySelector('button[type="submit"]').textContent =
            "Продолжить";
        }
      });
    } catch (e) {
      toast(e.message, true);
    }
  }
  async function advanceDetail(main, id) {
    const a = await api(`/api/advances/${id}`);
    const expenses = a.expenses || [],
      returns = a.returns || [];
    const actions = [];
    if (!a.received_at && !a.canceled_at)
      actions.push(
        button(
          "Отменить выдачу",
          () =>
            confirmAction(
              "Отменить выдачу",
              `Выдача №${id} · ${money(a.amount)}. Сотрудник ещё не подтвердил получение.`,
              (v) =>
                api(`/api/advances/${id}/cancel`, { method: "POST", body: v }),
              { reason: true, danger: true, label: "Отменить выдачу" },
            ),
          "danger",
        ),
      );
    main.replaceChildren(
      back("К выдачам", "money"),
      header(`Выдача №${id}`, a.purpose || "", actions),
      panel(
        "Информация о выдаче",
        h(
          "div",
          { class: "panel-body" },
          detail([
            ["Сотрудник", a.employee_name || `Сотрудник №${a.employee_id}`],
            ["Проект", a.project_name || `Проект №${a.project_id}`],
            [
              "Состояние",
              a.canceled_at
                ? badge("Отменена", "danger")
                : a.received_at
                  ? badge("Получено", "success")
                  : badge("Ожидает получения", "warning"),
            ],
            ["Выдано", money(a.amount), "amount"],
            ["Остаток", money(a.received_at ? a.balance : null), "amount"],
            ["Дата выдачи", datetime(a.created_at)],
            ["Получение", datetime(a.received_at)],
            ["Причина отмены", a.cancel_reason || a.cancellation_reason],
          ]),
        ),
      ),
      h("h2", { class: "section-label" }, "Расходы по чекам"),
      panel(
        "",
        table(
          [
            {
              label: "Документ",
              render: (r) =>
                link(
                  `Чек №${r.document_id}`,
                  `#/documents/${r.document_id}`,
                  "small ghost",
                  "file",
                ),
            },
            { label: "Сумма", numeric: true, render: (r) => money(r.amount) },
            { label: "Состояние", render: status },
            { label: "Комментарий", render: (r) => text(r.rejection_reason) },
            {
              label: "Действия",
              render: (r) => decisionButtons("expense", r, id),
            },
          ],
          expenses,
          {
            emptyTitle: "Чеки ещё не приложены",
            emptyDescription:
              "Сотрудник прикрепит сохранённый чек к выдаче через бота.",
          },
        ),
      ),
      h("h2", { class: "section-label" }, "Возвраты"),
      panel(
        "",
        table(
          [
            { label: "Заявка", render: (r) => `№${r.id}` },
            { label: "Сумма", numeric: true, render: (r) => money(r.amount) },
            { label: "Состояние", render: status },
            { label: "Комментарий", render: (r) => text(r.rejection_reason) },
            {
              label: "Действия",
              render: (r) => decisionButtons("return", r, id),
            },
          ],
          returns,
          {
            emptyTitle: "Заявок на возврат нет",
            emptyDescription:
              "Сотрудник заявляет фактический возврат через бота.",
          },
        ),
      ),
    );
    if (a.events?.length)
      main.append(
        h("h2", { class: "section-label" }, "История действий"),
        panel(
          "",
          h(
            "div",
            { class: "panel-body" },
            h(
              "ol",
              { class: "timeline" },
              a.events.map((e) =>
                h(
                  "li",
                  {},
                  eventLabel(e.kind),
                  e.actor_name && ` · ${e.actor_name}`,
                  h("time", {}, datetime(e.created_at)),
                ),
              ),
            ),
          ),
        ),
      );
  }
  function eventLabel(kind) {
    return (
      {
        issued: "Выдача создана",
        received: "Получение подтверждено",
        canceled: "Выдача отменена",
        expense_submitted: "Документ привязан к выдаче",
        expense_approved: "Расход учтён",
        expense_recorded: "Расход учтён",
        expense_rejected: "Расход отклонён",
        return_submitted: "Заявлен возврат",
        return_approved: "Возврат подтверждён",
        return_rejected: "Возврат отклонён",
      }[kind] || kind
    );
  }
  function decisionButtons(type, row, advanceId) {
    if (row.approved_at || row.rejected_at)
      return h(
        "span",
        { class: "muted" },
        datetime(row.approved_at || row.rejected_at),
      );
    if (type !== "return") return null;
    const base = `/api/advances/${advanceId}/returns/${row.id}`;
    const label = "Подтвердить возврат";
    return h(
      "div",
      { class: "row-actions" },
      button(
        label,
        () =>
          confirmAction(
            label,
            `${money(row.amount)}${row.employee_name ? " · " + row.employee_name : ""}. Подтвердите фактическое получение возврата компанией.`,
            () => api(`${base}/approve`, { method: "POST", body: {} }),
            { label },
          ),
        "small",
      ),
      button(
        "Отклонить",
        () =>
          confirmAction(
            "Отклонить заявку",
            `${money(row.amount)}. Сотрудник увидит указанную причину.`,
            (v) => api(`${base}/reject`, { method: "POST", body: v }),
            { reason: true, danger: true, label: "Отклонить" },
          ),
        "small danger",
      ),
    );
  }
  async function reviewsPage(main, params) {
    const data = await api("/api/reviews?" + query(params));
    main.lastChild.remove();
    main.append(
      panel(
        "Возвраты на подтверждение",
        paginatedTable(
          [
            {
              label: "Операция",
              render: (r) =>
                mainCell(
                  r.type === "return"
                    ? "Возврат денег"
                    : r.type === "card"
                      ? "Расход по карте"
                      : "Расход по выдаче",
                  r.employee_name,
                  r.advance_id
                    ? `#/money/${r.advance_id}`
                    : r.document_id
                      ? `#/documents/${r.document_id}`
                      : null,
                ),
            },
            { label: "Проект", key: "project_name" },
            { label: "Сумма", numeric: true, render: (r) => money(r.amount) },
            {
              label: "Документ",
              render: (r) =>
                r.document_id
                  ? link(
                      `№${r.document_id}`,
                      `#/documents/${r.document_id}`,
                      "small ghost",
                    )
                  : text(null),
            },
            {
              label: "Действия",
              render: (r) => decisionButtons(r.type, r, r.advance_id),
            },
          ],
          data,
          "money/reviews",
          params,
          {
            emptyTitle: "Всё проверено",
            emptyDescription:
              "Здесь появляются возвраты, требующие подтверждения получения компанией. Расходы по документам учитываются сразу.",
          },
        ),
        "Расходы и возвраты",
      ),
    );
  }
  async function cardsPage(main, params) {
    const [cards, data, directory] = await Promise.all([
      api("/api/cards"),
      api("/api/card-expenses?" + query(params)),
      refs(),
    ]);
    main.lastChild.remove();
    if (items(cards).length)
      main.append(
        h(
          "div",
          { class: "card-grid" },
          items(cards).map((c) =>
            h(
              "article",
              { class: "bank-card" },
              h("h3", {}, c.name),
              h("p", {}, `••••  ••••  ••••  ${c.last4}`),
              h("small", {}, "Бизнес-карта компании"),
            ),
          ),
        ),
      );
    else
      main.append(
        panel(
          "",
          empty(
            "Карты пока не добавлены",
            "Добавьте название карты и последние четыре цифры. Полный номер не требуется.",
            button("Добавить карту", cardDialog, "primary", "plus"),
          ),
        ),
      );
    main.append(
      filterForm(
        "money/cards",
        params,
        [
          {
            name: "employee_id",
            label: "Сотрудник",
            options: opts(directory.employees),
          },
          {
            name: "project_id",
            label: "Проект",
            options: opts(directory.projects),
          },
          {
            name: "status",
            label: "Состояние расхода",
            options: [
              { value: "", label: "Все расходы" },
              { value: "pending", label: "Исторические: не учтено" },
              { value: "approved", label: "Учтено" },
              { value: "rejected", label: "Отклонено" },
            ],
          },
        ],
        { dates: true },
      ),
      panel(
        "Расходы по картам",
        paginatedTable(
          [
            {
              label: "Карта / сотрудник",
              render: (r) =>
                mainCell(
                  `${r.card_name} · ${r.last4}`,
                  r.employee_name || who(r),
                ),
            },
            { label: "Проект", key: "project_name" },
            {
              label: "Документ",
              render: (r) =>
                link(
                  `№${r.document_id}`,
                  `#/documents/${r.document_id}`,
                  "small ghost",
                ),
            },
            { label: "Сумма", numeric: true, render: (r) => money(r.amount) },
            { label: "Состояние", render: status },
            { label: "Действия", render: (r) => decisionButtons("card", r) },
          ],
          data,
          "money/cards",
          params,
          {
            emptyTitle: "Карточных расходов пока нет",
            emptyDescription:
              "Сотрудник сможет указать карту для сохранённого чека через бота.",
          },
        ),
      ),
      h(
        "p",
        { class: "section-footnote" },
        "Документ, оплаченный картой, учитывается сразу после привязки. Баланс банковского счёта здесь не ведётся.",
      ),
    );
  }
  function cardDialog() {
    openDialog(
      "Добавить бизнес-карту",
      h(
        "div",
        {},
        field("Название карты", "name", {
          required: true,
          placeholder: "Например, Основная карта",
        }),
        field("Последние 4 цифры", "last4", {
          required: true,
          pattern: "[0-9]{4}",
          placeholder: "1234",
          help: "Только последние четыре цифры. Полный номер, срок и CVV не нужны.",
        }),
      ),
      async (values) => {
        await api("/api/cards", { method: "POST", body: values });
        toast("Карта добавлена");
        await render();
      },
      "Добавить карту",
    );
  }
  async function documentsPage(main, parts, params) {
    if (parts[1]) return documentDetail(main, parts[1]);
    params = { period: "all_time", ...params };
    const r = await refs();
    const data = await api("/api/documents?" + query(params));
    main.replaceChildren(
      header(
        "Документы",
        "Все сохранённые документы входят в затраты, независимо от источника оплаты. Дубли требуют проверки руководителем.",
      ),
      filterForm(
        "documents",
        params,
        [
          { name: "project_id", label: "Проект", options: opts(r.projects) },
          {
            name: "employee_id",
            label: "Сотрудник",
            options: opts(r.employees),
          },
          {
            name: "duplicate_status",
            label: "Дубли",
            options: [
              { value: "", label: "Все документы" },
              { value: "flagged", label: "Все дубли к проверке" },
              { value: "exact", label: "Точные дубли" },
              { value: "probable", label: "Возможные дубли" },
              { value: "none", label: "Без дублей" },
            ],
          },
          {
            name: "payment_source",
            label: "Источник оплаты",
            options: [
              { value: "", label: "Все источники" },
              { value: "advance", label: "Выдача сотруднику" },
              { value: "card", label: "Бизнес-карта" },
              { value: "none", label: "Не указан" },
            ],
          },
          {
            name: "document_type",
            label: "Тип документа",
            options: [
              { value: "", label: "Все типы" },
              { value: "cash_receipt", label: "Кассовый чек" },
              { value: "goods_invoice", label: "Накладная" },
              { value: "service_act", label: "Акт" },
              { value: "upd", label: "УПД" },
              { value: "vat_invoice", label: "Счёт-фактура" },
              { value: "bso", label: "БСО" },
              { value: "transport_invoice", label: "Транспортная накладная" },
              { value: "cash_out_order", label: "Расходный кассовый ордер" },
            ],
          },
        ],
        { dates: true },
      ),
      panel(
        "",
        paginatedTable(
          [
            {
              label: "Документ / поставщик",
              render: (r) =>
                mainCell(
                  r.document_number
                    ? `№ ${r.document_number}`
                    : `Документ №${r.id}`,
                  r.vendor,
                  `#/documents/${r.id}`,
                ),
            },
            {
              label: "Проект / сотрудник",
              render: (r) => mainCell(documentProject(r), r.uploaded_by_name),
            },
            {
              label: "Сумма",
              numeric: true,
              render: (r) => money(r.total_amount, r.currency || "RUB"),
            },
            { label: "Оплата", render: (r) => fundingBadge(r.payment_source) },
            {
              label: "Дубли",
              render: (r) => duplicateBadge(r.duplicate_status),
            },
            { label: "Загружен", render: (r) => date(r.created_at) },
            {
              label: "",
              render: (r) =>
                link("Открыть", `#/documents/${r.id}`, "small ghost", "arrow"),
            },
          ],
          data,
          "documents",
          params,
          {
            emptyTitle: "Документов пока нет",
            emptyDescription:
              "Загрузите чек или накладную через бота. После сохранения документ появится здесь.",
          },
        ),
      ),
      h(
        "p",
        { class: "section-footnote" },
        "Период отбора — дата загрузки документа (UTC). Архивные проекты включены. Пометка дубля не исключает документ из затрат до решения руководителя.",
      ),
    );
  }
  function fundingBadge(source) {
    return source === "advance"
      ? badge("Подотчёт", "info")
      : source === "card"
        ? badge("Бизнес-карта", "success")
        : badge("Оплата не привязана");
  }
  function documentProject(document) {
    return (
      document.project_name +
      (document.project_status === "archived" ? " (архив)" : "")
    );
  }
  function duplicateBadge(s) {
    return s === "exact"
      ? badge("Точный дубль", "danger")
      : s === "probable"
        ? badge("Возможный дубль", "warning")
        : s === "none"
          ? badge("Нет дублей", "success")
          : badge("Не проверен");
  }
  async function documentDetail(main, id) {
    const d = await api(`/api/documents/${id}`);
    const actions = [];
    if (d.duplicate_of_document_id) {
      actions.push(
        button("Сравнить документы", () => compareDocuments(d), "", "file"),
      );
    }
    if (["exact", "probable"].includes(d.duplicate_status)) {
      actions.push(
        button(
          "Оставить отдельным",
          () =>
            confirmAction(
              "Оставить документ отдельным",
              "Подтвердите, что это самостоятельный расход, который нужно сохранить в учёте.",
              () =>
                api(`/api/documents/${id}/keep`, { method: "POST", body: {} }),
            ),
          "",
          "check",
        ),
        button(
          "Удалить ошибочный дубль",
          () =>
            confirmAction(
              "Удалить ошибочный документ",
              `Документ №${id} · ${money(d.total_amount, d.currency)}. Документ с финансовой историей удалить нельзя.`,
              async () => {
                await api(`/api/documents/${id}`, { method: "DELETE" });
                go("documents");
              },
              { danger: true, label: "Удалить" },
            ),
          "danger",
        ),
      );
    }
    main.replaceChildren(
      back("К документам", "documents"),
      header(`Документ №${id}`, d.vendor || "Распознанный документ", actions),
      panel(
        "Реквизиты",
        h(
          "div",
          { class: "panel-body" },
          detail([
            ["Поставщик", d.vendor],
            [
              "Номер",
              d.document_number ||
                d.external_document_number ||
                d.incoming_number,
            ],
            ["Проект", documentProject(d)],
            ["Сумма", money(d.total_amount, d.currency || "RUB"), "amount"],
            ["Дата документа", date(d.document_date)],
            ["Дата загрузки", datetime(d.created_at)],
            ["Сотрудник", d.uploaded_by_name],
            ["ИНН", d.vendor_inn],
            ["Источник оплаты", fundingBadge(d.payment_source)],
            ["Проверка дублей", duplicateBadge(d.duplicate_status)],
          ]),
        ),
      ),
      h("h2", { class: "section-label" }, "Позиции документа"),
      panel(
        "",
        table(
          [
            { label: "Наименование", key: "name" },
            { label: "Количество", numeric: true, key: "quantity" },
            {
              label: "Цена",
              numeric: true,
              render: (r) => money(r.price, d.currency || "RUB"),
            },
            {
              label: "Сумма",
              numeric: true,
              render: (r) => money(r.line_total, d.currency || "RUB"),
            },
          ],
          d.items || [],
          {
            emptyTitle: "Позиции не распознаны",
            emptyDescription: "Доступные реквизиты документа показаны выше.",
          },
        ),
      ),
    );
    if (d.funding_history?.length)
      main.append(
        h("h2", { class: "section-label" }, "История источника оплаты"),
        panel(
          "",
          table(
            [
              {
                label: "Источник",
                render: (r) =>
                  r.source === "advance"
                    ? link(
                        `Выдача №${r.source_id}`,
                        `#/money/${r.source_id}`,
                        "small ghost",
                      )
                    : h("span", {}, "Бизнес-карта"),
              },
              { label: "Сумма", numeric: true, render: (r) => money(r.amount) },
              { label: "Состояние", render: status },
              { label: "Причина", render: (r) => text(r.rejection_reason) },
            ],
            d.funding_history,
          ),
        ),
      );
    if (d.raw_text)
      main.append(
        h("h2", { class: "section-label" }, "Текст распознавания"),
        panel(
          "",
          h(
            "div",
            { class: "panel-body" },
            h("pre", { class: "raw-text" }, d.raw_text),
          ),
        ),
      );
    main.append(
      info(
        "В панели доступны распознанные данные. Оригиналы ранее загруженных фотографий не сохранялись.",
      ),
    );
  }
  async function compareDocuments(document) {
    const userAtRequest = state.user;
    try {
      const original = await api(
        `/api/documents/${document.duplicate_of_document_id}`,
      );
      if (state.user !== userAtRequest) return;
      const entries = [
        ["Запись", `№ ${document.id}`, `№ ${original.id}`],
        ["Поставщик", document.vendor, original.vendor],
        [
          "Номер",
          document.document_number || document.external_document_number,
          original.document_number || original.external_document_number,
        ],
        [
          "Дата документа",
          date(document.document_date),
          date(original.document_date),
        ],
        [
          "Сумма",
          money(document.total_amount, document.currency),
          money(original.total_amount, original.currency),
        ],
        ["Проект", documentProject(document), documentProject(original)],
        ["Загрузил", document.uploaded_by_name, original.uploaded_by_name],
      ].map(([label, current, source]) => ({ label, current, source }));
      openDialog(
        "Сравнение документов",
        table(
          [
            { label: "Поле", key: "label" },
            { label: "Текущий", key: "current" },
            { label: "Исходный", key: "source" },
          ],
          entries,
        ),
        async () => go(`documents/${original.id}`),
        "Открыть исходный документ",
      );
    } catch (error) {
      toast(error.message, true);
    }
  }
  async function projectsPage(main, parts, params) {
    if (parts[1]) return projectDetail(main, parts[1]);
    const data = await api("/api/projects?" + query(params));
    main.replaceChildren(
      header("Проекты", "Документы и расходы по каждому объекту.", [
        button("Создать проект", () => projectDialog(), "primary", "plus"),
      ]),
      filterForm("projects", params, [
        {
          name: "archived",
          label: "Состояние",
          options: [
            { value: "false", label: "Активные проекты" },
            { value: "true", label: "Архивные проекты" },
          ],
        },
      ]),
      panel(
        "",
        paginatedTable(
          [
            {
              label: "Проект",
              render: (r) =>
                mainCell(r.name, `№ ${r.id}`, `#/projects/${r.id}`),
            },
            { label: "Документов", numeric: true, key: "document_count" },
            {
              label: "Затраты · RUB",
              numeric: true,
              render: (r) => money(r.total_amount),
            },
            {
              label: "Состояние",
              render: (r) =>
                badge(
                  r.status === "archived" ? "В архиве" : "Активен",
                  r.status === "archived" ? "" : "success",
                ),
            },
            {
              label: "",
              render: (r) =>
                link("Открыть", `#/projects/${r.id}`, "small ghost", "arrow"),
            },
          ],
          data,
          "projects",
          params,
          {
            emptyTitle:
              params.archived === "true"
                ? "Архивных проектов нет"
                : "Создайте первый проект",
            emptyDescription:
              "Сотрудники смогут выбирать активные проекты при загрузке документов и получении денег.",
          },
        ),
      ),
    );
  }
  function projectDialog(project) {
    openDialog(
      project ? "Переименовать проект" : "Новый проект",
      field("Название проекта", "name", {
        required: true,
        value: project?.name || "",
        placeholder: "Например, Квартира на Лесной",
      }),
      async (values) => {
        await api(project ? `/api/projects/${project.id}` : "/api/projects", {
          method: project ? "PATCH" : "POST",
          body: values,
        });
        state.refs = null;
        toast(project ? "Название изменено" : "Проект создан");
        await render();
      },
      project ? "Сохранить" : "Создать проект",
    );
  }
  async function projectDetail(main, id) {
    const p = await api(`/api/projects/${id}`);
    const archived = p.status === "archived";
    main.replaceChildren(
      back("К проектам", "projects"),
      header(p.name, "Карточка проекта", [
        !archived && button("Переименовать", () => projectDialog(p)),
        button(
          archived ? "Восстановить" : "Архивировать",
          () =>
            confirmAction(
              archived ? "Восстановить проект" : "Архивировать проект",
              archived
                ? "Проект снова станет доступен для новых документов и выдач."
                : "Проект исчезнет из нового выбора. При незавершённых расчётах архивирование недоступно.",
              async () => {
                await api(
                  `/api/projects/${id}/${archived ? "restore" : "archive"}`,
                  { method: "POST", body: {} },
                );
                state.refs = null;
              },
            ),
          archived ? "" : "danger",
        ),
      ]),
      panel(
        "Сводка проекта",
        h(
          "div",
          { class: "panel-body" },
          detail([
            [
              "Состояние",
              badge(
                archived ? "В архиве" : "Активен",
                archived ? "" : "success",
              ),
            ],
            ["Документов", p.document_count],
            ["Затраты · RUB", money(p.total_amount), "amount"],
            [
              "Незавершённые расчёты",
              p.has_open_settlements === undefined
                ? undefined
                : p.has_open_settlements
                  ? "Есть"
                  : "Нет",
            ],
          ]),
          h(
            "div",
            { class: "inline-actions mt-24" },
            link(
              "Документы проекта",
              `#/documents?project_id=${id}`,
              "",
              "file",
            ),
            link("Выдачи проекта", `#/money?project_id=${id}`, "", "wallet"),
            link("Отчёт проекта", `#/reports?project_id=${id}`, "", "chart"),
          ),
        ),
      ),
    );
    if (p.money) main.append(financialSummary(p.money));
  }
  async function employeesPage(main, parts, params) {
    if (parts[1]) return employeeDetail(main, parts[1]);
    const data = await api("/api/employees?" + query(params));
    main.replaceChildren(
      header("Сотрудники", "Команда, документы и расчёты с сотрудниками.", [
        button(
          "Пригласить сотрудника",
          () => showInvite("/api/employees/invite"),
          "primary",
          "plus",
        ),
      ]),
      filterForm("employees", params, []),
      panel(
        "",
        paginatedTable(
          [
            {
              label: "Сотрудник",
              render: (r) =>
                mainCell(
                  who(r),
                  r.username ? "@" + r.username : `№ ${r.user_id || r.id}`,
                  `#/employees/${r.user_id || r.id}`,
                ),
            },
            { label: "Документов", numeric: true, key: "document_count" },
            {
              label: "У сотрудника",
              numeric: true,
              render: (r) =>
                money(
                  r.balance == null ? null : Math.max(Number(r.balance), 0),
                ),
            },
            {
              label: "Компания должна",
              numeric: true,
              render: (r) =>
                money(
                  r.balance == null ? null : Math.max(-Number(r.balance), 0),
                ),
            },
            {
              label: "Доступ",
              render: (r) =>
                r.is_active === false
                  ? badge("Приостановлен", "danger")
                  : r.status === "removed"
                    ? badge("Исключён")
                    : badge("Активен", "success"),
            },
            {
              label: "",
              render: (r) =>
                link(
                  "Открыть",
                  `#/employees/${r.user_id || r.id}`,
                  "small ghost",
                  "arrow",
                ),
            },
          ],
          data,
          "employees",
          params,
          {
            emptyTitle: "Команда пока не добавлена",
            emptyDescription:
              "Пригласите сотрудника через бота. После регистрации он появится в списке.",
          },
        ),
      ),
    );
  }
  async function employeeDetail(main, id) {
    const e = await api(`/api/employees/${id}`);
    main.replaceChildren(
      back("К сотрудникам", "employees"),
      header(
        who(e),
        "Карточка сотрудника",
        e.status !== "removed"
          ? [
              button(
                "Исключить сотрудника",
                () =>
                  confirmAction(
                    "Исключить сотрудника",
                    `${who(e)} потеряет доступ к компании. История останется в отчётах. При незавершённых расчётах исключение недоступно.`,
                    async () => {
                      await api(`/api/employees/${id}`, { method: "DELETE" });
                      state.refs = null;
                      go("employees");
                    },
                    { danger: true, label: "Исключить" },
                  ),
                "danger",
              ),
            ]
          : [],
      ),
      panel(
        "Сведения о сотруднике",
        h(
          "div",
          { class: "panel-body" },
          detail([
            ["Имя", who(e)],
            ["Username", e.username ? "@" + e.username : "—"],
            ["Роль", e.role === "manager" ? "Руководитель" : "Сотрудник"],
            [
              "Доступ",
              e.is_active === false
                ? badge("Приостановлен", "danger")
                : badge(
                    e.status === "removed" ? "Исключён" : "Активен",
                    e.status === "removed" ? "" : "success",
                  ),
            ],
            ["Документов", e.document_count],
            [
              "Незавершённые расчёты",
              e.has_open_settlements === undefined
                ? undefined
                : e.has_open_settlements
                  ? "Есть"
                  : "Нет",
            ],
          ]),
          h(
            "div",
            { class: "inline-actions mt-24" },
            link("Документы", `#/documents?employee_id=${id}`, "", "file"),
            link("Выдачи", `#/money?employee_id=${id}`, "", "wallet"),
            link("Отчёт", `#/reports?employee_id=${id}`, "", "chart"),
          ),
        ),
      ),
    );
    if (e.money) main.append(financialSummary(e.money, true));
  }
  function financialSummary(report, employee = false) {
    const totals = report.totals || {};
    return panel(
      "Деньги · всё время",
      h(
        "div",
        { class: "panel-body" },
        detail([
          [
            employee ? "У сотрудника" : "У сотрудников",
            money(report.cash_on_hand),
            "amount",
          ],
          ["Компания должна", money(report.employee_debt), "amount"],
          ["Ожидает получения", money(totals.pending)],
          ["Учтено по выдачам", money(totals.spent)],
          ["Возвращено", money(totals.returned)],
          ["Карты: учтено", money(report.card_spent)],
          ["Возвраты к подтверждению", money(totals.pending_returns)],
        ]),
      ),
    );
  }
  async function reportsPage(main, params) {
    const [r, data] = await Promise.all([
      refs(),
      api("/api/reports?" + query(params)),
    ]);
    const m = data.money || {},
      t = m.totals || {};
    main.replaceChildren(
      header("Отчёты", "Полная картина по документам и движению денег.", [
        button(
          "Скачать Excel",
          () => downloadReport(dateParams(params)),
          "primary",
          "down",
        ),
      ]),
      filterForm(
        "reports",
        params,
        [
          { name: "project_id", label: "Проект", options: opts(r.projects) },
          {
            name: "employee_id",
            label: "Сотрудник",
            options: opts(r.employees),
          },
        ],
        { search: false, dates: true },
      ),
      h(
        "div",
        { class: "metrics" },
        metric(
          "Затраты по документам",
          money(data.summary?.total_amount),
          "RUB · по дате загрузки",
          "file",
          null,
          true,
        ),
        metric(
          "Получено сотрудниками",
          money(t.received),
          "По дате получения",
          "wallet",
        ),
        metric(
          "У сотрудников",
          money(m.cash_on_hand),
          "Остаток на конец периода",
          "users",
        ),
        metric(
          "Компания должна",
          money(m.employee_debt),
          "Отдельно от денег сотрудников",
          "chart",
        ),
      ),
      panel(
        "Движение денег",
        h(
          "div",
          { class: "panel-body" },
          detail([
            ["Остаток на начало", money(t.opening)],
            ["Получено", money(t.received)],
            ["Учтённые расходы", money(t.spent)],
            ["Возвращено", money(t.returned)],
            ["Остаток на конец", money(t.closing)],
            ["Карты: учтено", money(m.card_spent)],
            ["Ожидает получения", money(t.pending)],
            ["Возвраты к подтверждению", money(t.pending_returns)],
          ]),
        ),
      ),
      h("h2", { class: "section-label" }, "По проектам"),
      panel(
        "",
        table(
          [
            {
              label: "Проект",
              render: (r) =>
                mainCell(r.project_name, null, `#/projects/${r.project_id}`),
            },
            { label: "Документов", numeric: true, key: "document_count" },
            {
              label: "Затраты · RUB",
              numeric: true,
              render: (r) => money(r.total_amount),
            },
          ],
          data.projects || [],
        ),
      ),
      h("h2", { class: "section-label" }, "По сотрудникам"),
      panel(
        "",
        table(
          [
            {
              label: "Сотрудник",
              render: (r) =>
                mainCell(
                  r.employee_name || who(r),
                  null,
                  `#/employees/${r.user_id || r.employee_id}`,
                ),
            },
            { label: "Документов", numeric: true, key: "document_count" },
            {
              label: "Затраты · RUB",
              numeric: true,
              render: (r) => money(r.total_amount),
            },
          ],
          data.employees || [],
        ),
      ),
      h("h2", { class: "section-label" }, "Подотчётные деньги"),
      panel(
        "",
        table(
          [
            {
              label: "Сотрудник / проект",
              render: (r) =>
                mainCell(r.employee_name || who(r), r.project_name),
            },
            {
              label: "На начало",
              numeric: true,
              render: (r) => money(r.opening),
            },
            {
              label: "Получено",
              numeric: true,
              render: (r) => money(r.received),
            },
            { label: "Расходы", numeric: true, render: (r) => money(r.spent) },
            {
              label: "Возвраты",
              numeric: true,
              render: (r) => money(r.returned),
            },
            {
              label: "На конец",
              numeric: true,
              render: (r) => money(r.closing),
            },
          ],
          m.rows || [],
        ),
      ),
      h(
        "p",
        { class: "section-footnote" },
        `Все даты — UTC. Документы отбираются по дате загрузки, денежные движения — по дате подтверждения. Excel включает все подходящие записи.${data.generated_at ? " Сформировано: " + datetime(data.generated_at) : ""}`,
      ),
    );
  }
  async function companyPage(main) {
    const c = await api("/api/company");
    main.replaceChildren(
      header("Моя компания", "Основные сведения о рабочем пространстве."),
      panel(
        c.name,
        h(
          "div",
          { class: "panel-body" },
          detail([
            ["Название", c.name],
            [
              "Руководитель",
              c.manager_name ||
                [c.manager_first_name, c.manager_last_name]
                  .filter(Boolean)
                  .join(" ") ||
                state.user.name,
            ],
            [
              "Состояние",
              badge(
                c.status === "archived" ? "В архиве" : "Активна",
                c.status === "archived" ? "" : "success",
              ),
            ],
            ["Сотрудников", c.employee_count],
            ["Лимит сотрудников", c.employee_limit],
            ["Проектов", c.project_count],
            ["Документов", c.document_count],
          ]),
        ),
      ),
      info(
        "Приглашайте сотрудников через раздел «Сотрудники». В первой версии к учётной записи привязана одна активная компания.",
      ),
    );
  }
  async function profilePage(main) {
    const [sessions, me] = await Promise.all([
      api("/api/auth/sessions"),
      api("/api/auth/profile"),
    ]);
    const accounts = me.accounts || me.user?.accounts || [];
    main.replaceChildren(
      header("Мой профиль", "Аккаунты, доступ и активные браузерные сессии."),
      panel(
        "Учётная запись",
        h(
          "div",
          { class: "panel-body" },
          detail([
            ["Имя", state.user.name],
            [
              "Роль",
              state.user.role === "owner" ? "Владелец системы" : "Руководитель",
            ],
            ["Компания", state.user.company_name || "Системный кабинет"],
            ["Внутренний ID", state.user.id],
          ]),
          accounts.length &&
            h(
              "div",
              { class: "mt-22" },
              h("h3", { class: "section-label" }, "Связанные аккаунты"),
              accounts.map((a) =>
                h(
                  "p",
                  { class: "detail-text" },
                  text(a.platform || a.provider),
                  " · ",
                  text(a.external_id),
                ),
              ),
            ),
        ),
        null,
        button("Выйти", logout, "small", "logout"),
      ),
      h("h2", { class: "section-label" }, "Браузерные сессии"),
      panel(
        "",
        h(
          "div",
          { class: "panel-body" },
          items(sessions).length
            ? items(sessions).map((s) =>
                h(
                  "div",
                  { class: "session-row" },
                  h(
                    "div",
                    {},
                    h(
                      "strong",
                      {},
                      s.browser_description ||
                        s.user_agent ||
                        s.browser ||
                        "Браузер",
                    ),
                    h(
                      "small",
                      {},
                      `Последняя активность: ${datetime(s.last_seen_at || s.last_used_at || s.last_seen)}`,
                    ),
                  ),
                  h(
                    "div",
                    {},
                    (s.current || s.is_current) && badge("Текущая", "success"),
                    h(
                      "small",
                      { class: "block" },
                      `До ${datetime(s.expires_at)}`,
                    ),
                  ),
                ),
              )
            : empty(
                "Нет данных о сессиях",
                "Обновите страницу, чтобы получить актуальный список.",
              ),
          h(
            "div",
            { class: "inline-actions mt-20" },
            button(
              "Завершить все веб-сессии",
              () =>
                confirmAction(
                  "Завершить все сессии",
                  "Будет выполнен выход на всех устройствах, включая текущее. Для входа потребуется подтверждение в боте.",
                  async () => {
                    await api("/api/auth/logout-all", {
                      method: "POST",
                      body: {},
                    });
                    state.user = null;
                    state.csrf = "";
                    login();
                  },
                  { danger: true, label: "Завершить все" },
                ),
              "danger",
              "logout",
            ),
          ),
        ),
      ),
    );
  }
  async function logout() {
    try {
      await api("/api/auth/logout", { method: "POST", body: {} });
      state.user = null;
      state.csrf = "";
      state.refs = null;
      login();
    } catch (e) {
      toast(e.message, true);
    }
  }
  async function companiesPage(main, parts, params) {
    if (parts[1]) return ownerCompanyDetail(main, parts[1]);
    const data = await api("/api/owner/companies?" + query(params));
    main.replaceChildren(
      header("Компании", "Рабочие пространства и доступ руководителей.", [
        button(
          "Создать компанию",
          () =>
            openDialog(
              "Новая компания",
              field("Название", "name", {
                required: true,
                placeholder: "Название компании",
              }),
              async (v) => {
                await api("/api/owner/companies", { method: "POST", body: v });
                toast("Компания создана");
                await render();
              },
              "Создать компанию",
            ),
          "primary",
          "plus",
        ),
      ]),
      filterForm("companies", params, [
        {
          name: "status",
          label: "Состояние",
          options: [
            { value: "", label: "Все компании" },
            { value: "active", label: "Активные" },
            { value: "archived", label: "Архивные" },
          ],
        },
      ]),
      panel(
        "",
        paginatedTable(
          [
            {
              label: "Компания",
              render: (r) =>
                mainCell(r.name, `№ ${r.id}`, `#/companies/${r.id}`),
            },
            {
              label: "Руководитель",
              render: (r) => text(r.manager_name, "Не назначен"),
            },
            { label: "Сотрудников", numeric: true, key: "employee_count" },
            {
              label: "Состояние",
              render: (r) =>
                badge(
                  r.status === "archived" ? "В архиве" : "Активна",
                  r.status === "archived" ? "" : "success",
                ),
            },
            {
              label: "",
              render: (r) =>
                link("Открыть", `#/companies/${r.id}`, "small ghost", "arrow"),
            },
          ],
          data,
          "companies",
          params,
          {
            emptyTitle: "Компаний пока нет",
            emptyDescription: "Создайте компанию и пригласите её руководителя.",
          },
        ),
      ),
    );
  }
  async function ownerCompanyDetail(main, id) {
    const c = await api(`/api/owner/companies/${id}`);
    const actions = [];
    if (c.status !== "archived") {
      actions.push(
        !c.manager_user_id &&
          button(
            "Пригласить руководителя",
            () => showInvite(`/api/owner/companies/${id}/invite`),
            "primary",
            "plus",
          ),
        button(
          "Архивировать",
          () =>
            confirmAction(
              "Архивировать компанию",
              `${c.name}. Участники потеряют доступ, приглашения будут отозваны. Незавершённые расчёты нужно закрыть до архивирования.`,
              () =>
                api(`/api/owner/companies/${id}/archive`, {
                  method: "POST",
                  body: {},
                }),
              { danger: true, label: "Архивировать" },
            ),
          "danger",
        ),
      );
    }
    main.replaceChildren(
      back("К компаниям", "companies"),
      header(c.name, "Рабочее пространство компании", actions),
      panel(
        "Сведения о компании",
        h(
          "div",
          { class: "panel-body" },
          detail([
            ["Название", c.name],
            [
              "Состояние",
              badge(
                c.status === "archived" ? "В архиве" : "Активна",
                c.status === "archived" ? "" : "success",
              ),
            ],
            [
              "Руководитель",
              c.manager_name ||
                [c.manager_first_name, c.manager_last_name]
                  .filter(Boolean)
                  .join(" ") ||
                "Не назначен",
            ],
            ["Сотрудников", c.employee_count],
            ["Проектов", c.project_count],
            ["Документов", c.document_count],
          ]),
        ),
      ),
    );
    if (c.invite?.code)
      main.append(
        h("h2", { class: "section-label" }, "Приглашение руководителя"),
        panel(
          "",
          h(
            "div",
            { class: "panel-body" },
            h("div", { class: "code-box" }, c.invite.code),
            h(
              "div",
              { class: "inline-actions" },
              button(
                "Скопировать код",
                async () => {
                  try {
                    await navigator.clipboard.writeText(c.invite.code);
                    toast("Код скопирован");
                  } catch {
                    toast("Не удалось скопировать код.", true);
                  }
                },
                "",
                "copy",
              ),
              button(
                "Отозвать приглашение",
                () =>
                  confirmAction(
                    "Отозвать приглашение",
                    "Текущий код больше не позволит войти в компанию.",
                    () =>
                      api(`/api/owner/companies/${id}/revoke-invite`, {
                        method: "POST",
                        body: {},
                      }),
                  ),
                "danger",
              ),
            ),
          ),
        ),
      );
    if (c.members)
      main.append(
        h("h2", { class: "section-label" }, "Участники"),
        panel(
          "",
          table(
            [
              {
                label: "Пользователь",
                render: (r) =>
                  mainCell(
                    who(r),
                    r.username ? "@" + r.username : "",
                    `#/users/${r.user_id || r.id}`,
                  ),
              },
              {
                label: "Роль",
                render: (r) =>
                  r.role === "manager" ? "Руководитель" : "Сотрудник",
              },
              {
                label: "Состояние",
                render: (r) =>
                  badge(
                    r.status === "removed" ? "Исключён" : "Активен",
                    r.status === "removed" ? "" : "success",
                  ),
              },
            ],
            c.members,
          ),
        ),
      );
  }
  async function usersPage(main, parts, params) {
    if (parts[1]) params = { ...params, q: parts[1] };
    const data = await api("/api/owner/users?" + query(params));
    main.replaceChildren(
      header("Пользователи", "Роли, принадлежность к компании и доступ."),
      filterForm("users", params, []),
      panel(
        "",
        paginatedTable(
          [
            {
              label: "Пользователь",
              render: (r) =>
                mainCell(
                  who(r),
                  r.username ? "@" + r.username : `№ ${r.user_id || r.id}`,
                ),
            },
            {
              label: "Компания",
              render: (r) => text(r.company_name, "Без компании"),
            },
            {
              label: "Роль",
              render: (r) =>
                r.role === "manager"
                  ? "Руководитель"
                  : r.role === "employee"
                    ? "Сотрудник"
                    : r.role === "owner" || r.system_role === "owner"
                      ? "Владелец"
                      : "Не назначена",
            },
            {
              label: "Доступ",
              render: (r) =>
                r.is_active === false
                  ? badge("Приостановлен", "danger")
                  : badge("Активен", "success"),
            },
            {
              label: "Действия",
              render: (r) =>
                r.role === "owner"
                  ? link("Профиль", "#/profile", "small", "user")
                  : button(
                      "Управление",
                      () => ownerUserDialog(r),
                      "small",
                      "user",
                    ),
            },
          ],
          data,
          "users",
          params,
          {
            emptyTitle: "Пользователи не найдены",
            emptyDescription:
              "Измените поисковый запрос. Новые пользователи регистрируются через бота.",
          },
        ),
      ),
    );
    if (parts[1]) {
      const user = items(data).find(
        (x) => String(x.id || x.user_id) === parts[1],
      );
      if (user && user.role !== "owner") await ownerUserDialog(user);
    }
  }
  async function ownerUserDialog(user) {
    const userAtRequest = state.user;
    try {
      const id = user.user_id || user.id;
      const companies = await allRows("/api/owner/companies?status=active");
      if (state.user !== userAtRequest) return;
      const body = h(
        "div",
        {},
        h(
          "p",
          { class: "dialog-description" },
          `${who(user)} · ${user.company_name || "Без компании"}`,
        ),
        field("Компания", "company_id", {
          value: user.company_id || "",
          options: opts(companies, "Выберите компанию"),
          required: true,
        }),
        field("Роль", "role", {
          value: user.role || "employee",
          options: [
            { value: "employee", label: "Сотрудник" },
            { value: "manager", label: "Руководитель" },
          ],
        }),
        h(
          "div",
          { class: "inline-actions mb-20" },
          user.company_id &&
            button(
              "Исключить из компании",
              () => {
                dialog.close();
                confirmAction(
                  "Исключить пользователя",
                  `${who(user)} потеряет доступ к компании. Незавершённые расчёты блокируют исключение.`,
                  () =>
                    api(`/api/owner/users/${id}/remove`, {
                      method: "POST",
                      body: {},
                    }),
                  { danger: true, label: "Исключить" },
                );
              },
              "small danger",
            ),
          button(
            user.is_active === false
              ? "Возобновить доступ"
              : "Приостановить доступ",
            () => {
              dialog.close();
              confirmAction(
                user.is_active === false
                  ? "Возобновить доступ"
                  : "Приостановить доступ",
                `${who(user)}. Членство в компании и финансовая история сохранятся.`,
                (v) =>
                  api(`/api/owner/users/${id}/access`, {
                    method: "POST",
                    body: { ...v, active: user.is_active === false },
                  }),
                { reason: true, danger: user.is_active !== false },
              );
            },
            "small",
          ),
        ),
      );
      openDialog(
        "Управление пользователем",
        body,
        async (v) => {
          await api(`/api/owner/users/${id}/assign`, {
            method: "POST",
            body: v,
          });
          toast("Назначение сохранено");
          await render();
        },
        "Сохранить назначение",
      );
    } catch (e) {
      toast(e.message, true);
    }
  }
  async function statsPage(main) {
    const s = await api("/api/owner/stats");
    main.replaceChildren(
      header(
        "Статистика системы",
        "Общие показатели FIINOPS без доступа к финансовым данным компаний.",
      ),
      h(
        "div",
        { class: "metrics" },
        metric(
          "Компаний",
          text(s.companies),
          "Рабочие пространства",
          "building",
          "#/companies",
          true,
        ),
        metric(
          "Активных компаний",
          text(s.active_companies),
          "Работают в системе",
          "grid",
          "#/companies?status=active",
        ),
        metric(
          "Пользователей",
          text(s.users),
          "Зарегистрированные аккаунты",
          "users",
          "#/users",
        ),
        metric("Документов", text(s.documents), "Во всех компаниях", "file"),
      ),
      panel(
        "Использование системы",
        h(
          "div",
          { class: "panel-body" },
          detail([
            ["Руководителей", s.managers],
            ["Сотрудников", s.employees],
            ["Проектов", s.projects],
          ]),
        ),
      ),
      info(
        "Финансовые действия доступны руководителю внутри его компании. Управление системными секретами выполняется вне панели.",
      ),
    );
  }
  async function render() {
    if (!state.user) return;
    const token = ++state.request;
    const { parts, params } = route();
    if (parts.length === 1) state.listRoutes[parts[0]] = location.hash;
    if (!parts.length) {
      go(state.user.role === "owner" ? "companies" : "overview");
      return;
    }
    const main = shell();
    document.title = `${pageTitle()} · FIINOPS`;
    const routes =
      state.user.role === "owner"
        ? {
            companies: () => companiesPage(main, parts, params),
            users: () => usersPage(main, parts, params),
            stats: () => statsPage(main),
            profile: () => profilePage(main),
          }
        : {
            overview: () => overview(main, params),
            money: () => moneyPage(main, parts, params),
            documents: () => documentsPage(main, parts, params),
            projects: () => projectsPage(main, parts, params),
            employees: () => employeesPage(main, parts, params),
            reports: () => reportsPage(main, params),
            company: () => companyPage(main),
            profile: () => profilePage(main),
          };
    try {
      if (!routes[parts[0]]) {
        go(state.user.role === "owner" ? "companies" : "overview");
        return;
      }
      await routes[parts[0]]();
      if (token === state.request) main.setAttribute("aria-busy", "false");
    } catch (e) {
      if (token !== state.request || e.status === 401) return;
      main.replaceChildren(
        header(pageTitle()),
        panel(
          "",
          empty(
            "Не удалось загрузить данные",
            e.message,
            button("Повторить", render, "", "refresh"),
          ),
        ),
      );
    }
  }
  function safeBotUrl(value) {
    try {
      const url = new URL(value);
      return url.protocol === "https:" && url.hostname === "t.me"
        ? url.href
        : "#";
    } catch {
      return "#";
    }
  }
  function login(message = "") {
    if (mini) {
      mini.clear();
      app.setAttribute("aria-busy", "false");
      app.replaceChildren(h("section", {class: "mini-gate"}, brand(),
        h("h1", {}, "Панель руководителя"),
        h("p", {}, message || "Вы вышли. Закройте приложение и откройте его заново из бота."),
        button("Закрыть", () => mini.close(), "primary")));
      return;
    }
    if (state.poll) {
      clearInterval(state.poll);
      state.poll = null;
    }
    state.loginAttempt = (state.loginAttempt || 0) + 1;
    state.request++;
    app.setAttribute("aria-busy", "false");
    document.title = "Вход · FIINOPS";
    const formCard = h(
      "div",
      { class: "login-card" },
      h("div", { class: "login-icon" }, icon("shield")),
      h("h2", {}, "Войти в рабочее пространство"),
      h(
        "p",
        { class: "intro" },
        "Подтвердите вход в Telegram — и продолжайте работу с проектами, документами и деньгами.",
      ),
      message && h("div", { class: "error-box", role: "alert" }, message),
    );
    const loginAction = button(
      "Продолжить через Telegram",
      async () => {
        const attempt = ++state.loginAttempt;
        if (state.poll) {
          clearInterval(state.poll);
          state.poll = null;
        }
        loginAction.disabled = true;
        try {
          const data = await api("/api/auth/start", {
            method: "POST",
            body: {},
          });
          if (attempt !== state.loginAttempt || state.user) return;
          waiting.replaceChildren(
            h(
              "div",
              { class: "login-waiting", role: "status" },
              h("span", { class: "spinner" }),
              h(
                "span",
                {},
                "Ожидаем подтверждение в боте. После подтверждения панель откроется автоматически.",
              ),
            ),
            h(
              "a",
              {
                class: "button primary full",
                href: safeBotUrl(data.bot_url),
                target: "_blank",
                rel: "noopener noreferrer",
              },
              icon("telegram"),
              "Открыть Telegram",
            ),
          );
          loginAction.textContent = "Создать новый запрос";
          loginAction.disabled = false;
          const expires = new Date(
            data.expires_at || Date.now() + 300000,
          ).valueOf();
          if (state.poll) clearInterval(state.poll);
          let busy = false;
          const poll = setInterval(async () => {
            if (attempt !== state.loginAttempt || state.user) {
              clearInterval(poll);
              return;
            }
            if (busy) return;
            if (Date.now() > expires) {
              clearInterval(poll);
              state.poll = null;
              waiting.replaceChildren(
                h(
                  "div",
                  { class: "error-box" },
                  "Время подтверждения истекло. Создайте новый запрос входа.",
                ),
              );
              return;
            }
            busy = true;
            try {
              const s = await api("/api/auth/status");
              if (attempt !== state.loginAttempt || state.user) return;
              if (s.status === "authenticated") {
                clearInterval(poll);
                state.poll = null;
                await boot();
              } else if (
                ["denied", "rejected", "expired", "canceled"].includes(s.status)
              ) {
                clearInterval(poll);
                state.poll = null;
                waiting.replaceChildren(
                  h(
                    "div",
                    { class: "error-box" },
                    "Вход не подтверждён. При необходимости создайте новый запрос.",
                  ),
                );
              }
            } catch (e) {
              if (attempt !== state.loginAttempt || state.user) return;
              if (e.status === 400 || e.status === 401 || e.status === 410) {
                clearInterval(poll);
                state.poll = null;
                waiting.replaceChildren(
                  h("div", { class: "error-box" }, e.message),
                );
              }
            } finally {
              busy = false;
            }
          }, 2200);
          state.poll = poll;
        } catch (e) {
          if (attempt !== state.loginAttempt || state.user) return;
          toast(e.message, true);
          loginAction.disabled = false;
        }
      },
      "primary full",
      "telegram",
    );
    const waiting = h("div");
    formCard.append(
      loginAction,
      waiting,
      h(
        "ol",
        { class: "login-steps" },
        h("li", {}, "Откройте бота по кнопке и нажмите «Запустить»."),
        h("li", {}, "Проверьте запрос и подтвердите вход в веб-панель."),
        h("li", {}, "Вернитесь в этот браузер — ваши данные уже здесь."),
      ),
      h(
        "p",
        { class: "login-footer" },
        "Доступ для руководителей и владельца системы. Используйте тот же Telegram-аккаунт, с которым вы работаете в боте.",
      ),
    );
    app.replaceChildren(
      h(
        "div",
        { class: "login-page" },
        h(
          "section",
          { class: "login-story" },
          brand(),
          h(
            "div",
            { class: "login-story-main" },
            h("p", { class: "eyebrow" }, "ЯСНОСТЬ В КАЖДОМ РАСХОДЕ"),
            h(
              "h1",
              {},
              "Ваши проекты.",
              h("br"),
              "Ваша команда.",
              h("br"),
              h("span", {}, "Ваш контроль."),
            ),
            h(
              "p",
              { class: "lead" },
              "Рабочее пространство, в котором документы и движение денег складываются в полную картину.",
            ),
            h(
              "div",
              { class: "login-benefits" },
              h(
                "div",
                { class: "login-benefit" },
                icon("wallet"),
                "Выдачи и расходы без путаницы",
              ),
              h(
                "div",
                { class: "login-benefit" },
                icon("file"),
                "Документы рядом с каждой операцией",
              ),
              h(
                "div",
                { class: "login-benefit" },
                icon("chart"),
                "Отчёты, которым можно доверять",
              ),
            ),
          ),
          h(
            "div",
            { class: "login-story-footer" },
            "FIINOPS · Управление финансами компании",
          ),
        ),
        h(
          "section",
          { class: "login-form-side" },
          h("div", { class: "login-mobile-brand" }, brand()),
          formCard,
        ),
      ),
    );
  }
  async function boot() {
    try {
      const me = mini ? await mini.authorize() : await api("/api/auth/me");
      state.user = me.user;
      state.csrf = me.csrf_token;
      state.refs = null;
      if (!state.user) throw new Error("Не удалось определить пользователя.");
      await render();
    } catch (e) {
      login(e.status === 401 ? "" : e.message);
    }
  }
  document.querySelector(".skip-link").addEventListener("click", (event) => {
    event.preventDefault();
    document.getElementById("main-content")?.focus();
  });
  window.addEventListener("hashchange", () => {
    if (state.user) render();
  });
  dialog.addEventListener("click", (event) => {
    if (event.target === dialog) {
      const rect = dialog.getBoundingClientRect();
      if (
        event.clientX < rect.left ||
        event.clientX > rect.right ||
        event.clientY < rect.top ||
        event.clientY > rect.bottom
      )
        dialog.close();
    }
  });
  boot();
})();
