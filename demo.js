/* Browser-only simulation. Never loaded by the production web application. */
"use strict";
(() => {
  const now = () => new Date().toISOString();
  const day = (n) => new Date(Date.now() - n * 86400000).toISOString();
  const cents = (v) => {
    if (!/^\d+(?:[.,]\d{1,2})?$/.test(String(v)))
      throw new Error("Укажите сумму до копейки.");
    const [a, b = ""] = String(v).replace(",", ".").split(".");
    return BigInt(a) * 100n + BigInt(b.padEnd(2, "0"));
  };
  const amount = (v) =>
    `${v < 0n ? "-" : ""}${(v < 0n ? -v : v) / 100n}.${String((v < 0n ? -v : v) % 100n).padStart(2, "0")}`;
  const sum = (rows, key = "amount") =>
    rows.reduce((s, r) => s + cents(r[key] || "0"), 0n);
  let role = "manager";
  try {
    role =
      sessionStorage.getItem("fiinops-demo-role") === "owner"
        ? "owner"
        : "manager";
  } catch {}
  const company = {
    id: 1,
    name: "Стройпроект · Демокомпания",
    status: "active",
    manager_name: "Александр Иванов",
    manager_first_name: "Александр",
    manager_last_name: "Иванов",
    employee_count: 2,
    employee_limit: 10,
    project_count: 2,
    document_count: 3,
    created_at: day(20),
  };
  const user = () => ({
    id: role === "owner" ? 1 : 2,
    name: role === "owner" ? "Администратор демо" : "Александр Иванов",
    role,
    company_id: role === "owner" ? null : 1,
    company_name: role === "owner" ? null : company.name,
  });
  const employees = [
    {
      id: 3,
      user_id: 3,
      first_name: "Иван",
      last_name: "Петров",
      name: "Иван Петров",
      role: "employee",
      status: "active",
      is_active: true,
      joined_at: day(20),
    },
    {
      id: 4,
      user_id: 4,
      first_name: "Анна",
      last_name: "Соколова",
      name: "Анна Соколова",
      role: "employee",
      status: "active",
      is_active: true,
      joined_at: day(18),
    },
  ];
  const projects = [
    {
      id: 1,
      name: "Ремонт офиса",
      company_id: 1,
      status: "active",
      created_at: day(20),
    },
    {
      id: 2,
      name: "Загородный дом",
      company_id: 1,
      status: "active",
      created_at: day(16),
    },
  ];
  const documents = [
    {
      id: 1,
      project_id: 1,
      uploaded_by_user_id: 3,
      vendor: "Магазин стройматериалов",
      total_amount: "4250.00",
      payment_source: "advance",
      advance_id: 1,
    },
    {
      id: 2,
      project_id: 1,
      uploaded_by_user_id: 3,
      vendor: "Демонстрационный поставщик",
      total_amount: "3860.00",
      payment_source: "advance",
      advance_id: 1,
    },
    {
      id: 3,
      project_id: 2,
      uploaded_by_user_id: 4,
      vendor: "Инструменты · Демо",
      total_amount: "19900.00",
      payment_source: "card",
      card_id: 1,
    },
  ].map((d) => ({
    ...d,
    document_number: `ДЕМО-${1000 + d.id}`,
    document_type: "cash_receipt",
    currency: "RUB",
    duplicate_status: "none",
    created_at: day(0),
    document_date: day(0),
    raw_text: "Демонстрационный чек. Не является реальным документом.",
    items: [
      {
        line_no: 1,
        name: "Материалы · демонстрационная позиция",
        quantity: "1",
        price: d.total_amount,
        line_total: d.total_amount,
      },
    ],
  }));
  const advances = [
    {
      id: 1,
      employee_id: 3,
      project_id: 1,
      amount: "25000.00",
      purpose: "Материалы для ремонта",
      received_at: day(0),
      created_at: day(0),
      expenses: [
        {
          id: 1,
          document_id: 1,
          amount: "4250.00",
          created_at: day(0),
          approved_at: day(0),
        },
        {
          id: 2,
          document_id: 2,
          amount: "3860.00",
          created_at: day(0),
          approved_at: null,
        },
      ],
      returns: [
        { id: 1, amount: "1000.00", created_at: day(0), approved_at: null },
      ],
    },
    {
      id: 2,
      employee_id: 4,
      project_id: 2,
      amount: "7500.00",
      purpose: "Расходные материалы",
      received_at: null,
      created_at: day(0),
      expenses: [],
      returns: [],
    },
  ];
  const cards = [{ id: 1, name: "Закупки · Демо", last4: "4821" }];
  const cardExpenses = [
    {
      id: 1,
      card_id: 1,
      document_id: 3,
      submitted_by: 4,
      employee_id: 4,
      project_id: 2,
      amount: "19900.00",
      created_at: day(0),
      approved_at: null,
    },
  ];
  const companies = [company];
  const person = (id) => employees.find((e) => e.id === Number(id));
  const project = (id) => projects.find((p) => p.id === Number(id));
  const name = (id) => person(id)?.name || "Александр Иванов";
  const decorate = (r) => ({
    ...r,
    employee_name: name(r.employee_id || r.submitted_by),
    project_name: project(r.project_id)?.name,
  });
  const balance = (a) =>
    (a.received_at && !a.canceled_at ? cents(a.amount) : 0n) -
    sum(a.expenses.filter((e) => e.approved_at)) -
    sum(a.returns.filter((e) => e.approved_at));
  const advance = (a) => ({
    ...decorate(a),
    balance: amount(balance(a)),
    events: [
      {
        id: 1,
        kind: "issued",
        actor_name: "Александр Иванов",
        created_at: a.created_at,
        details: { amount: a.amount },
      },
    ],
  });
  const cardExpense = (e) => ({
    ...decorate(e),
    card_name: cards.find((c) => c.id === e.card_id)?.name,
    last4: cards.find((c) => c.id === e.card_id)?.last4,
    accepted: !!e.approved_at,
  });
  const doc = (d) => ({
    ...d,
    project_name: project(d.project_id)?.name,
    uploaded_by_name: name(d.uploaded_by_user_id),
    funding_history: [],
  });
  function scope(rows, p) {
    return rows.filter(
      (r) =>
        (!p.get("project_id") ||
          Number(p.get("project_id")) === r.project_id) &&
        (!p.get("employee_id") ||
          Number(p.get("employee_id")) ===
            (r.employee_id || r.uploaded_by_user_id || r.submitted_by)),
    );
  }
  function page(rows, p) {
    const q = (p.get("q") || "").toLocaleLowerCase();
    let out = rows.filter(
      (r) =>
        !q ||
        Object.values(r).some(
          (v) => typeof v === "string" && v.toLocaleLowerCase().includes(q),
        ),
    );
    const sort = p.get("sort") || "newest";
    out.sort((a, b) =>
      sort === "name" || sort === "vendor"
        ? String(a.name || a.vendor || a.employee_name).localeCompare(
            String(b.name || b.vendor || b.employee_name),
            "ru",
          )
        : sort.startsWith("amount_")
          ? (cents(a.amount || a.total_amount || "0") >
            cents(b.amount || b.total_amount || "0")
              ? 1
              : -1) * (sort === "amount_desc" ? -1 : 1)
          : sort === "oldest"
            ? a.id - b.id
            : b.id - a.id,
    );
    const n = Math.max(1, Number(p.get("page") || 1)),
      size = Math.min(100, Math.max(1, Number(p.get("per_page") || 25)));
    return {
      items: out.slice((n - 1) * size, n * size),
      total: out.length,
      page: n,
      per_page: size,
    };
  }
  function money(p) {
    const rows = [];
    for (const a of scope(advances, p).filter((a) => !a.canceled_at)) {
      let r = rows.find(
        (r) => r.employee_id === a.employee_id && r.project_id === a.project_id,
      );
      if (!r) {
        r = {
          employee_id: a.employee_id,
          project_id: a.project_id,
          first_name: person(a.employee_id)?.first_name,
          last_name: person(a.employee_id)?.last_name,
          project_name: project(a.project_id)?.name,
        };
        for (const k of [
          "opening",
          "received",
          "spent",
          "returned",
          "closing",
          "pending",
          "pending_expenses",
          "pending_returns",
        ])
          r[k] = "0.00";
        rows.push(r);
      }
      const add = (k, v) => (r[k] = amount(cents(r[k]) + v));
      add(a.received_at ? "received" : "pending", cents(a.amount));
      add("spent", sum(a.expenses.filter((e) => e.approved_at)));
      add("returned", sum(a.returns.filter((e) => e.approved_at)));
      add(
        "pending_expenses",
        sum(a.expenses.filter((e) => !e.approved_at && !e.rejected_at)),
      );
      add(
        "pending_returns",
        sum(a.returns.filter((e) => !e.approved_at && !e.rejected_at)),
      );
      r.closing = amount(
        cents(r.received) - cents(r.spent) - cents(r.returned),
      );
    }
    const totals = {};
    for (const k of [
      "opening",
      "received",
      "spent",
      "returned",
      "closing",
      "pending",
      "pending_expenses",
      "pending_returns",
    ])
      totals[k] = amount(
        rows.reduce((s, r) => s + BigInt(r[k].replace(".", "")), 0n),
      );
    const perPerson = new Map();
    for (const r of rows)
      perPerson.set(
        r.employee_id,
        (perPerson.get(r.employee_id) || 0n) +
          BigInt(r.closing.replace(".", "")),
      );
    const cs = scope(cardExpenses, p).filter((e) => !e.rejected_at);
    return {
      rows,
      totals,
      card_rows: cs.map(cardExpense),
      card_spent: amount(sum(cs.filter((e) => e.approved_at))),
      card_pending: amount(sum(cs.filter((e) => !e.approved_at))),
      cash_on_hand: amount(
        [...perPerson.values()].reduce((s, v) => s + (v > 0n ? v : 0n), 0n),
      ),
      employee_debt: amount(
        [...perPerson.values()].reduce((s, v) => s + (v < 0n ? -v : 0n), 0n),
      ),
    };
  }
  function report(p) {
    const ds = scope(documents, p).map(doc),
      m = money(p);
    const grouped = (key, label) =>
      [...new Set(ds.map((d) => d[key]))].map((id) => ({
        id,
        project_id: key === "project_id" ? id : null,
        user_id: key === "uploaded_by_user_id" ? id : null,
        project_name: project(id)?.name,
        employee_name: name(id),
        document_count: ds.filter((d) => d[key] === id).length,
        total_amount: amount(
          sum(
            ds.filter((d) => d[key] === id),
            "total_amount",
          ),
        ),
        exact_duplicate_count: 0,
        probable_duplicate_count: 0,
      }));
    return {
      start: day(0),
      end: now(),
      generated_at: now(),
      summary: {
        document_count: ds.length,
        total_amount: amount(sum(ds, "total_amount")),
        exact_duplicates: 0,
        probable_duplicates: 0,
        totals_by_currency: { RUB: amount(sum(ds, "total_amount")) },
      },
      projects: grouped("project_id"),
      employees: grouped("uploaded_by_user_id"),
      documents: ds,
      items: ds.flatMap((d) =>
        d.items.map((i) => ({ ...i, document_id: d.id })),
      ),
      duplicates: [],
      money: m,
    };
  }
  const result = (data, status = 200, headers = {}) =>
    new Response(JSON.stringify(data), {
      status,
      headers: { "Content-Type": "application/json", ...headers },
    });
  function handle(path, p, method, b) {
    if (path === "/api/auth/me" || path === "/api/auth/status")
      return {
        user: user(),
        csrf_token: "demo-no-real-session",
        status: "authenticated",
      };
    if (path === "/api/auth/profile")
      return {
        user: user(),
        accounts: [
          {
            platform: "demo",
            external_id: "fictional-account",
            created_at: day(0),
          },
        ],
      };
    if (path === "/api/auth/sessions")
      return {
        items: [
          {
            id: "demo",
            browser_description: "Демонстрация в вашем браузере",
            created_at: day(0),
            last_seen_at: now(),
            expires_at: day(-1),
            current: true,
          },
        ],
      };
    if (path.startsWith("/api/auth/logout")) return { ok: true };
    if (path === "/api/company") return company;
    if (path === "/api/overview") {
      const r = report(p),
        m = r.money;
      return {
        ...r.summary,
        document_total: r.summary.total_amount,
        ...m.totals,
        cash: m.cash_on_hand,
        debt: m.employee_debt,
        card_spent: m.card_spent,
        card_pending: m.card_pending,
        money: m,
        open_projects: projects
          .filter((project) => project.status === "active")
          .map((project) => {
            const pr = report(
              new URLSearchParams({
                ...Object.fromEntries(p),
                project_id: project.id,
              }),
            );
            const pm = pr.money;
            return {
              project_id: project.id,
              project_name: project.name,
              document_count: pr.summary.document_count,
              document_total: pr.summary.total_amount,
              totals_by_currency: pr.summary.totals_by_currency,
              ...pm.totals,
              cash: pm.cash_on_hand,
              debt: pm.employee_debt,
              card_spent: pm.card_spent,
              card_pending: pm.card_pending,
              review_total: amount(
                cents(pm.totals.pending_expenses) +
                  cents(pm.totals.pending_returns) +
                  cents(pm.card_pending),
              ),
            };
          }),
        project_count: projects.filter((p) => p.status === "active").length,
        employee_count: employees.filter((e) => e.status === "active").length,
      };
    }
    if (path === "/api/reports") return report(p);
    if (path === "/api/reviews") {
      const rows = [];
      for (const a of advances.filter((a) => !a.canceled_at))
        for (const [type, list] of [
          ["expense", a.expenses],
          ["return", a.returns],
        ])
          for (const e of list.filter((e) => !e.approved_at && !e.rejected_at))
            rows.push({ ...decorate(a), ...e, advance_id: a.id, type });
      for (const e of cardExpenses.filter(
        (e) => !e.approved_at && !e.rejected_at,
      ))
        rows.push({ ...cardExpense(e), type: "card" });
      return page(rows, p);
    }
    if (path === "/api/advances") {
      if (method === "POST") {
        const existing = advances.find((a) => a.request_key === b.request_key);
        if (existing) return { id: existing.id };
        if (
          !person(b.employee_id) ||
          person(b.employee_id).status !== "active" ||
          !project(b.project_id) ||
          project(b.project_id).status !== "active"
        )
          throw new Error("Выберите активного сотрудника и проект.");
        if (cents(b.amount) <= 0n || !b.purpose.trim())
          throw new Error("Укажите сумму и назначение.");
        const a = {
          ...b,
          id: Math.max(0, ...advances.map((a) => a.id)) + 1,
          employee_id: Number(b.employee_id),
          project_id: Number(b.project_id),
          amount: amount(cents(b.amount)),
          created_at: now(),
          received_at: null,
          expenses: [],
          returns: [],
        };
        advances.push(a);
        return { id: a.id };
      }
      return page(
        scope(advances, p)
          .filter(
            (a) =>
              !p.get("status") ||
              p.get("status") ===
                (a.canceled_at
                  ? "canceled"
                  : a.received_at
                    ? "received"
                    : "pending"),
          )
          .map(advance),
        p,
      );
    }
    let match = path.match(
      /^\/api\/advances\/(\d+)(?:\/(cancel|expenses|returns)(?:\/(\d+)\/(approve|reject))?)?$/,
    );
    if (match) {
      const a = advances.find((a) => a.id === Number(match[1]));
      if (!a) throw new Error("Выдача не найдена.");
      if (method === "GET") return advance(a);
      if (match[2] === "cancel") {
        if (a.received_at)
          throw new Error("Полученную выдачу отменять нельзя.");
        if (!b.reason?.trim()) throw new Error("Укажите причину.");
        a.canceled_at = now();
        a.cancel_reason = b.reason;
      } else {
        const e = a[match[2]].find((e) => e.id === Number(match[3]));
        if (!e || e.approved_at || e.rejected_at)
          throw new Error("Операция уже обработана.");
        if (match[4] === "approve") {
          if (match[2] === "returns" && cents(e.amount) > balance(a))
            throw new Error("Возврат превышает остаток.");
          e.approved_at = now();
        } else {
          if (!b.reason?.trim()) throw new Error("Укажите причину.");
          e.rejected_at = now();
          e.rejection_reason = b.reason;
        }
      }
      return { ok: true };
    }
    if (path === "/api/cards") {
      if (method === "POST") {
        if (!/^\d{4}$/.test(b.last4) || !b.name.trim())
          throw new Error("Укажите название и последние 4 цифры.");
        cards.push({ ...b, id: cards.length + 1 });
        return { id: cards.length };
      }
      return { items: cards };
    }
    if (path === "/api/card-expenses")
      return page(
        scope(cardExpenses, p)
          .filter(
            (e) =>
              !p.get("status") ||
              p.get("status") ===
                (e.rejected_at
                  ? "rejected"
                  : e.approved_at
                    ? "approved"
                    : "pending"),
          )
          .map(cardExpense),
        p,
      );
    match = path.match(/^\/api\/card-expenses\/(\d+)\/(approve|reject)$/);
    if (match) {
      const e = cardExpenses.find((e) => e.id === Number(match[1]));
      if (!e || e.approved_at || e.rejected_at)
        throw new Error("Операция уже обработана.");
      if (match[2] === "reject") {
        if (!b.reason?.trim()) throw new Error("Укажите причину.");
        e.rejected_at = now();
        e.rejection_reason = b.reason;
      } else e.approved_at = now();
      return { ok: true };
    }
    if (path === "/api/documents")
      return page(
        scope(documents, p)
          .filter(
            (d) =>
              (!p.get("document_type") ||
                d.document_type === p.get("document_type")) &&
              (!p.get("duplicate_status") ||
                d.duplicate_status === p.get("duplicate_status")) &&
              (!p.get("payment_source") ||
                d.payment_source === p.get("payment_source")),
          )
          .map(doc),
        p,
      );
    match = path.match(/^\/api\/documents\/(\d+)(?:\/keep)?$/);
    if (match) {
      const d = documents.find((d) => d.id === Number(match[1]));
      if (!d) throw new Error("Документ не найден.");
      if (method === "GET") return doc(d);
      throw new Error(
        "Демонстрационные документы связаны с операциями и защищены от удаления.",
      );
    }
    if (path === "/api/projects") {
      if (method === "POST") {
        if (!b.name.trim()) throw new Error("Введите название.");
        const id = Math.max(...projects.map((p) => p.id)) + 1;
        projects.push({
          id,
          name: b.name,
          status: "active",
          company_id: 1,
          created_at: now(),
        });
        return { id };
      }
      return page(
        projects
          .filter(
            (r) =>
              r.status ===
              (p.get("archived") === "true" ? "archived" : "active"),
          )
          .map((r) => ({
            ...r,
            document_count: documents.filter((d) => d.project_id === r.id)
              .length,
            total_amount: amount(
              sum(
                documents.filter((d) => d.project_id === r.id),
                "total_amount",
              ),
            ),
          })),
        p,
      );
    }
    match = path.match(/^\/api\/projects\/(\d+)(?:\/(archive|restore))?$/);
    if (match) {
      const r = project(match[1]);
      if (!r) throw new Error("Проект не найден.");
      if (method === "GET")
        return {
          ...r,
          document_count: documents.filter((d) => d.project_id === r.id).length,
          total_amount: amount(
            sum(
              documents.filter((d) => d.project_id === r.id),
              "total_amount",
            ),
          ),
          money: money(new URLSearchParams({ project_id: r.id })),
        };
      if (method === "PATCH") {
        if (!b.name.trim()) throw new Error("Введите название.");
        r.name = b.name;
      } else if (match[2] === "archive") {
        if (
          advances.some(
            (a) =>
              a.project_id === r.id &&
              !a.canceled_at &&
              (!a.received_at || balance(a) !== 0n),
          )
        )
          throw new Error("Сначала завершите расчёты по проекту.");
        r.status = "archived";
      } else r.status = "active";
      return r;
    }
    if (
      path === "/api/employees/invite" ||
      /^\/api\/owner\/companies\/\d+\/invite$/.test(path)
    )
      return { code: "DEMO-NOT-A-REAL-INVITE", expires_at: day(-3) };
    if (path === "/api/employees")
      return page(
        employees.map((e) => ({
          ...e,
          balance: money(new URLSearchParams({ employee_id: e.id })).totals
            .closing,
          document_count: documents.filter(
            (d) => d.uploaded_by_user_id === e.id,
          ).length,
        })),
        p,
      );
    match = path.match(/^\/api\/employees\/(\d+)$/);
    if (match) {
      const e = person(match[1]);
      if (!e) throw new Error("Сотрудник не найден.");
      if (method === "DELETE")
        throw new Error("У сотрудника есть незавершённые расчёты.");
      return {
        ...e,
        money: money(new URLSearchParams({ employee_id: e.id })),
        document_count: documents.filter((d) => d.uploaded_by_user_id === e.id)
          .length,
        has_open_settlements: true,
      };
    }
    if (path === "/api/owner/companies") {
      if (method === "POST") {
        if (!b.name.trim()) throw new Error("Введите название.");
        const c = {
          id: companies.length + 1,
          name: b.name,
          status: "active",
          employee_count: 0,
          project_count: 0,
          document_count: 0,
          created_at: now(),
        };
        companies.push(c);
        return c;
      }
      return page(
        companies.filter(
          (c) => !p.get("status") || c.status === p.get("status"),
        ),
        p,
      );
    }
    match = path.match(
      /^\/api\/owner\/companies\/(\d+)(?:\/(archive|revoke-invite))?$/,
    );
    if (match) {
      const c = companies.find((c) => c.id === Number(match[1]));
      if (!c) throw new Error("Компания не найдена.");
      if (method === "GET")
        return { ...c, members: c.id === 1 ? employees : [], invite: null };
      if (match[2] === "archive") {
        if (c.id === 1) throw new Error("Сначала завершите расчёты компании.");
        c.status = "archived";
      }
      return { ok: true };
    }
    if (path === "/api/owner/users")
      return page(
        [
          { id: 1, name: "Администратор демо", role: "owner", is_active: true },
          {
            id: 2,
            name: "Александр Иванов",
            role: "manager",
            company_id: 1,
            company_name: company.name,
            is_active: true,
          },
          ...employees.map((e) => ({
            ...e,
            company_id: 1,
            company_name: company.name,
          })),
        ],
        p,
      );
    match = path.match(/^\/api\/owner\/users\/(\d+)\/(access|assign|remove)$/);
    if (match) {
      const e = person(match[1]);
      if (!e)
        throw new Error("Изменение системного пользователя в демо недоступно.");
      if (match[2] === "access") {
        if (!b.reason?.trim()) throw new Error("Укажите причину.");
        e.is_active = b.active;
        return { ok: true };
      }
      throw new Error(
        "Изменение роли или исключение заблокировано незавершёнными расчётами.",
      );
    }
    if (path === "/api/owner/stats")
      return {
        users: 4,
        companies: companies.length,
        active_companies: companies.filter((c) => c.status === "active").length,
        managers: 1,
        employees: 2,
        projects: projects.length,
        documents: documents.length,
      };
    throw new Error(
      "Этот сценарий требует серверной версии. Демо предназначено для проверки интерфейса.",
    );
  }
  window.fetch = async (input, options = {}) => {
    const url = new URL(
      typeof input === "string" ? input : input.url,
      location.href,
    );
    if (url.origin !== location.origin || !url.pathname.startsWith("/api/"))
      throw new Error("Демоверсия не выполняет внешних API-запросов.");
    if (url.pathname === "/api/reports/export") {
      const rows = scope(documents, url.searchParams).map(doc);
      const csv =
        "\ufeff" +
        [
          ["ID", "Проект", "Поставщик", "Сумма RUB"],
          ...rows.map((d) => [d.id, d.project_name, d.vendor, d.total_amount]),
        ]
          .map((row) =>
            row
              .map((v) => {
                const text = String(v);
                const safe = /^[=+\-@\t\r]/.test(text) ? "'" + text : text;
                return '"' + safe.replaceAll('"', '""') + '"';
              })
              .join(";"),
          )
          .join("\r\n");
      return new Response(csv, {
        headers: {
          "Content-Type": "text/csv;charset=utf-8",
          "Content-Disposition": 'attachment; filename="FIINOPS-demo.csv"',
        },
      });
    }
    try {
      return result(
        handle(
          url.pathname,
          url.searchParams,
          options.method || "GET",
          options.body ? JSON.parse(options.body) : {},
        ),
      );
    } catch (e) {
      return result({ detail: e.message }, 400);
    }
  };
  document.addEventListener("DOMContentLoaded", () => {
    const bar = document.createElement("section");
    bar.className = "demo-bar";
    bar.setAttribute("aria-label", "Режим демонстрации");
    const description = document.createElement("p");
    description.textContent =
      "ДЕМО · Вымышленные данные. Изменения до обновления страницы. Периоды и операции имитируются.";
    const label = document.createElement("label");
    label.textContent = "Кабинет";
    const select = document.createElement("select");
    for (const [v, t] of [
      ["manager", "Руководитель"],
      ["owner", "Владелец"],
    ]) {
      const o = document.createElement("option");
      o.value = v;
      o.textContent = t;
      select.append(o);
    }
    select.value = role;
    select.addEventListener("change", () => {
      try {
        sessionStorage.setItem("fiinops-demo-role", select.value);
      } catch {}
      location.hash = select.value === "owner" ? "#/companies" : "#/overview";
      location.reload();
    });
    label.append(select);
    const reset = document.createElement("button");
    reset.textContent = "Сбросить демо";
    reset.onclick = () => location.reload();
    bar.append(description, label, reset);
    document.body.prepend(bar);
    new ResizeObserver(() =>
      document.documentElement.style.setProperty(
        "--demo-height",
        bar.getBoundingClientRect().height + "px",
      ),
    ).observe(bar);
  });
})();
