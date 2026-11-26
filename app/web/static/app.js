(() => {
  const tg = window.Telegram && window.Telegram.WebApp ? window.Telegram.WebApp : null;
  if (tg) {
    tg.ready();
    tg.expand();
  }

  const state = {
    today: "",
    tomorrow: "",
    selectedDay: "",
    weekDays: [],
    activeTab: "day",
    activeBucket: "inbox", // inbox | pool
    activePoolTag: "",
    eveningSource: "inbox", // inbox | pool
    historyDays: 7,
    selectedHistoryDay: "",
    expandedTasks: new Set(),
  };

  function haptic(kind = "light") {
    try {
      if (tg && tg.HapticFeedback) {
        tg.HapticFeedback.impactOccurred(kind);
      }
    } catch (_) {}
  }

  let toastTimer = null;
  function showToast(msg) {
    const elNode = document.getElementById("toast");
    elNode.textContent = msg;
    elNode.classList.add("show");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => elNode.classList.remove("show"), 2400);
  }

  async function api(path, options = {}) {
    const headers = Object.assign(
      {
        "X-Telegram-Init-Data": tg ? tg.initData || "" : "",
      },
      options.isForm ? {} : { "Content-Type": "application/json" },
      options.headers || {}
    );
    const resp = await fetch(path, {
      method: options.method || "GET",
      body: options.body,
      headers,
    });
    if (!resp.ok) {
      let detail = `HTTP ${resp.status}`;
      try {
        const data = await resp.json();
        if (data.detail) detail = data.detail;
      } catch (_) {}
      const err = new Error(detail);
      err.status = resp.status;
      throw err;
    }
    return resp.json();
  }

  function el(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined && text !== null) node.textContent = String(text);
    return node;
  }

  function setBadge(id, count) {
    const badge = document.getElementById(id);
    if (!badge) return;
    if (count > 0) {
      badge.textContent = String(count);
      badge.classList.remove("hidden");
    } else {
      badge.classList.add("hidden");
    }
  }

  function shiftIso(iso, delta) {
    const [y, m, d] = iso.split("-").map(Number);
    const dt = new Date(Date.UTC(y, m - 1, d + delta));
    return dt.toISOString().slice(0, 10);
  }

  function renderWeekStrip() {
    const strip = document.getElementById("week-strip");
    strip.replaceChildren();
    state.weekDays.forEach((d) => {
      const parts = d.label.split(" ");
      const btn = el("button", "day-pill");
      btn.type = "button";
      if (d.is_today) btn.classList.add("today");
      if (d.iso === state.selectedDay) btn.classList.add("selected");
      btn.appendChild(el("span", "", parts[0] || ""));
      btn.appendChild(el("strong", "", (parts[1] || "").split(".")[0] || ""));
      btn.addEventListener("click", () => {
        haptic("light");
        state.selectedDay = d.iso;
        renderWeekStrip();
        loadDay(d.iso);
      });
      strip.appendChild(btn);
    });
  }

  function buildScheduleRow(ev, onAfterChange) {
    const row = el("div", `item-row${ev.is_done ? " done" : ""}`);
    const check = el("button", "check-btn", ev.is_done ? "✓" : "");
    check.type = "button";
    check.setAttribute("aria-label", "Отметить занятие");
    check.addEventListener("click", async () => {
      haptic("medium");
      await api(`/api/schedule/${ev.id}/toggle`, { method: "POST" });
      await onAfterChange();
    });

    const body = el("div", "item-body");
    body.appendChild(el("p", "item-title", ev.title));
    const meta = el("div", "item-meta");
    const timeStr = ev.end_time ? `${ev.start_time}–${ev.end_time}` : ev.start_time;
    meta.appendChild(el("span", "chip time", timeStr));
    if (ev.location) meta.appendChild(el("span", "chip", ev.location));
    if (ev.meeting_info) meta.appendChild(el("span", "chip zoom", `🔗 ${ev.meeting_info}`));
    body.appendChild(meta);

    row.appendChild(check);
    row.appendChild(body);
    return row;
  }

  function buildSubtaskPanel(task, onRefresh) {
    const box = el("div", "subtask-box");
    (task.subtasks || []).forEach((st) => {
      const sRow = el("div", `subtask-row${st.is_done ? " done" : ""}`);
      const btn = el("button", "subtask-check", st.is_done ? "✓" : "");
      btn.type = "button";
      btn.addEventListener("click", async () => {
        haptic("light");
        await api(`/api/subtasks/${st.id}/toggle`, { method: "POST" });
        await onRefresh();
      });
      const lbl = el("span", "", st.title);
      lbl.style.flex = "1";
      const del = el("button", "mini-btn danger", "✕");
      del.type = "button";
      del.style.padding = "2px 6px";
      del.addEventListener("click", async () => {
        await api(`/api/subtasks/${st.id}`, { method: "DELETE" });
        await onRefresh();
      });
      sRow.append(btn, lbl, del);
      box.appendChild(sRow);
    });

    const form = el("form", "subtask-add-form");
    const inp = el("input", "subtask-input");
    inp.type = "text";
    inp.placeholder = "Добавить подзадачу…";
    const addBtn = el("button", "mini-btn", "＋");
    addBtn.type = "submit";
    form.append(inp, addBtn);
    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      const val = inp.value.trim();
      if (!val) return;
      haptic("light");
      await api(`/api/tasks/${task.id}/subtasks`, {
        method: "POST",
        body: JSON.stringify({ title: val }),
      });
      inp.value = "";
      await onRefresh();
    });
    box.appendChild(form);
    return box;
  }

  function buildTaskRow(task, options) {
    const row = el("div", `item-row${task.status === "done" ? " done" : ""}`);
    const check = el("button", "check-btn", task.status === "done" ? "✓" : "");
    check.type = "button";
    check.setAttribute("aria-label", "Отметить задачу");
    check.addEventListener("click", async () => {
      haptic("medium");
      await api(`/api/tasks/${task.id}/toggle`, { method: "POST" });
      await options.onRefresh();
    });

    const body = el("div", "item-body");
    body.appendChild(el("p", "item-title", task.title));

    const meta = el("div", "item-meta");
    if (task.planned_time) meta.appendChild(el("span", "chip time", task.planned_time));
    if (task.priority === 1) meta.appendChild(el("span", "chip prio-1", "🔴 Важно"));
    else if (task.priority === 3) meta.appendChild(el("span", "chip", "⚪ Низкий"));
    if (task.recurrence_rule) meta.appendChild(el("span", "chip", "🔁 повтор"));
    if (task.deadline_badge && task.status !== "done") {
      const urgentDl = task.deadline_days_left !== null && task.deadline_days_left <= 3;
      meta.appendChild(el("span", `chip${urgentDl ? " deadline-urgent" : ""}`, task.deadline_badge));
    }
    (task.tags || []).forEach((tgName) => {
      meta.appendChild(el("span", "chip tag", `#${tgName}`));
    });
    if (task.carried_over_count > 0) meta.appendChild(el("span", "chip", `↻${task.carried_over_count}`));

    if (options.mode !== "evening-pick") {
      const subs = task.subtasks || [];
      const doneSubs = subs.filter((s) => s.is_done).length;
      const subToggle = el("button", "chip", subs.length ? `☑️ ${doneSubs}/${subs.length}` : "＋шаг");
      subToggle.type = "button";
      subToggle.style.border = "none";
      subToggle.style.cursor = "pointer";
      subToggle.addEventListener("click", () => {
        haptic("light");
        if (state.expandedTasks.has(task.id)) state.expandedTasks.delete(task.id);
        else state.expandedTasks.add(task.id);
        options.onRefresh();
      });
      meta.appendChild(subToggle);
    }

    if (meta.childNodes.length > 0) body.appendChild(meta);

    if (state.expandedTasks.has(task.id) && options.mode !== "evening-pick") {
      body.appendChild(buildSubtaskPanel(task, options.onRefresh));
    }

    const actions = el("div", "item-actions");
    const makeRemindBtn = () => {
      const btn = el("button", "mini-btn", "🔔");
      btn.type = "button";
      btn.title = "Напомнить через 1 час";
      btn.addEventListener("click", async () => {
        haptic("light");
        const res = await api(`/api/tasks/${task.id}/remind`, {
          method: "POST",
          body: JSON.stringify({ preset: "1h" }),
        });
        showToast(`🔔 Напомню: ${res.reminder.when_label}`);
        await loadBadges();
      });
      return btn;
    };

    if (options.mode === "day") {
      const moveBtn = el("button", "mini-btn", "➡️");
      moveBtn.type = "button";
      moveBtn.title = "На завтра";
      moveBtn.addEventListener("click", async () => {
        haptic("light");
        const nextIso = shiftIso(task.planned_date || state.today, 1);
        await api(`/api/tasks/${task.id}/plan`, {
          method: "POST",
          body: JSON.stringify({ target_date: nextIso, carry_over: true }),
        });
        showToast("Перенесено на следующий день ➡️");
        await options.onRefresh();
      });

      const poolBtn = el("button", "mini-btn", "🗂");
      poolBtn.type = "button";
      poolBtn.title = "Убрать в общий пул";
      poolBtn.addEventListener("click", async () => {
        haptic("light");
        await api(`/api/tasks/${task.id}/pool`, { method: "POST" });
        showToast("Убрано в общий пул 🗂");
        await options.onRefresh();
      });

      const delBtn = el("button", "mini-btn danger", "✕");
      delBtn.type = "button";
      delBtn.addEventListener("click", async () => {
        haptic("light");
        await api(`/api/tasks/${task.id}`, { method: "DELETE" });
        await options.onRefresh();
      });

      actions.append(makeRemindBtn(), moveBtn, poolBtn, delBtn);
    } else if (options.mode === "inbox" || options.mode === "pool") {
      const todayBtn = el("button", "mini-btn", "📅");
      todayBtn.type = "button";
      todayBtn.title = "На сегодня";
      todayBtn.addEventListener("click", async () => {
        haptic("light");
        await api(`/api/tasks/${task.id}/plan`, {
          method: "POST",
          body: JSON.stringify({ target_date: state.today }),
        });
        showToast("Запланировано на сегодня");
        await options.onRefresh();
      });

      const tomBtn = el("button", "mini-btn", "🌅");
      tomBtn.type = "button";
      tomBtn.title = "На завтра";
      tomBtn.addEventListener("click", async () => {
        haptic("light");
        await api(`/api/tasks/${task.id}/plan`, {
          method: "POST",
          body: JSON.stringify({ target_date: state.tomorrow }),
        });
        showToast("Запланировано на завтра");
        await options.onRefresh();
      });

      actions.append(todayBtn, tomBtn);
      if (options.mode === "inbox") {
        const poolBtn = el("button", "mini-btn", "🗂");
        poolBtn.type = "button";
        poolBtn.title = "В общий пул";
        poolBtn.addEventListener("click", async () => {
          haptic("light");
          await api(`/api/tasks/${task.id}/pool`, { method: "POST" });
          showToast("Перенесено в общий пул 🗂");
          await options.onRefresh();
        });
        actions.append(poolBtn);
      } else {
        actions.append(makeRemindBtn());
      }

      const delBtn = el("button", "mini-btn danger", "✕");
      delBtn.type = "button";
      delBtn.addEventListener("click", async () => {
        haptic("light");
        await api(`/api/tasks/${task.id}`, { method: "DELETE" });
        await options.onRefresh();
      });
      actions.append(delBtn);
    } else if (options.mode === "evening-pending") {
      const moveBtn = el("button", "mini-btn", "➡️ Завтра");
      moveBtn.type = "button";
      moveBtn.addEventListener("click", async () => {
        haptic("light");
        await api(`/api/tasks/${task.id}/plan`, {
          method: "POST",
          body: JSON.stringify({ target_date: state.tomorrow, carry_over: true }),
        });
        await options.onRefresh();
      });

      const poolBtn = el("button", "mini-btn", "🗂");
      poolBtn.type = "button";
      poolBtn.title = "В пул";
      poolBtn.addEventListener("click", async () => {
        haptic("light");
        await api(`/api/tasks/${task.id}/pool`, { method: "POST" });
        showToast("Убрано в общий пул 🗂");
        await options.onRefresh();
      });
      actions.append(moveBtn, poolBtn);
    } else if (options.mode === "evening-pick") {
      const pickBtn = el("button", "mini-btn", "＋ Завтра");
      pickBtn.type = "button";
      pickBtn.addEventListener("click", async () => {
        haptic("light");
        await api(`/api/tasks/${task.id}/plan`, {
          method: "POST",
          body: JSON.stringify({ target_date: state.tomorrow }),
        });
        showToast("Добавлено в план на завтра ✅");
        await options.onRefresh();
      });
      actions.append(pickBtn);
    }

    if (options.mode !== "evening-pick") {
      row.appendChild(check);
    }
    row.appendChild(body);
    if (actions.childNodes.length > 0) row.appendChild(actions);
    return row;
  }

  async function loadBadges() {
    const [inboxData, remData] = await Promise.all([api("/api/inbox"), api("/api/reminders")]);
    setBadge("nav-inbox-badge", inboxData.tasks.length);
    setBadge("nav-rem-badge", remData.reminders.length);
  }

  async function loadDay(dayIso) {
    const data = await api(`/api/day?date=${encodeURIComponent(dayIso)}`);
    document.getElementById("day-title").textContent = data.label;
    document.getElementById("day-progress-label").textContent = `${data.completion_rate}%`;
    document.getElementById("day-progress-fill").style.width = `${data.completion_rate}%`;
    document.getElementById("day-progress-sub").textContent = `${data.done_items} из ${data.total_items} выполнено`;

    // Deadlines banner
    const dlCard = document.getElementById("day-deadlines-card");
    const dlList = document.getElementById("day-deadlines-list");
    dlList.replaceChildren();
    const urgentDls = (data.deadlines || []).filter((d) => d.deadline_days_left !== null && d.deadline_days_left <= 7);
    if (urgentDls.length > 0 && dayIso === state.today) {
      dlCard.classList.remove("hidden");
      urgentDls.slice(0, 4).forEach((d) => {
        const line = el("div", "deadline-item");
        line.appendChild(el("span", "", d.title));
        const urgent = d.deadline_days_left <= 3;
        line.appendChild(el("span", `chip${urgent ? " deadline-urgent" : ""}`, d.deadline_badge));
        dlList.appendChild(line);
      });
    } else {
      dlCard.classList.add("hidden");
    }

    const schList = document.getElementById("day-schedule-list");
    schList.replaceChildren();
    if (data.schedule_events.length > 0) {
      data.schedule_events.forEach((ev) => {
        schList.appendChild(buildScheduleRow(ev, () => loadDay(dayIso)));
      });
    } else {
      schList.appendChild(
        el("div", "empty-state", "Пар на этот день нет — нажми «📤 Импорт» (.docx, .ics, .xlsx, .pdf, фото).")
      );
    }

    const taskList = document.getElementById("day-task-list");
    taskList.replaceChildren();
    if (data.tasks.length === 0) {
      taskList.appendChild(el("div", "empty-state", "На этот день задач пока нет — добавь выше или забери из Пула ✨"));
    } else {
      data.tasks.forEach((t) => {
        taskList.appendChild(buildTaskRow(t, { mode: "day", onRefresh: () => refreshAll() }));
      });
    }
  }

  async function loadBucket() {
    const tagParam = state.activeBucket === "pool" && state.activePoolTag ? `?tag=${encodeURIComponent(state.activePoolTag)}` : "";
    const [inboxData, poolData] = await Promise.all([api("/api/inbox"), api(`/api/pool${tagParam}`)]);
    setBadge("nav-inbox-badge", inboxData.tasks.length);
    document.getElementById("bucket-inbox-btn").textContent = `📥 Инбокс (${inboxData.tasks.length})`;
    document.getElementById("bucket-pool-btn").textContent = `🗂 Пул задач (${poolData.tasks.length})`;

    const isPool = state.activeBucket === "pool";
    document.getElementById("dump-title").textContent = isPool ? "🗂 Добавить в общий пул" : "🧠 Скинь всё в кучу";
    document.getElementById("dump-hint").textContent = isPool
      ? "Можно указывать #теги и дедлайны (например: «лаба #учёба до 05.12») — за 3 дня срочность поднимется сама."
      : "Пиши сплошным текстом — CheTam разобьёт на задачи, вытащит время, дедлайны, #теги и повторы.";
    document.getElementById("dump-submit-btn").textContent = isPool ? "Сохранить в Пул" : "Разобрать в Инбокс";

    const tagsBar = document.getElementById("pool-tags-bar");
    tagsBar.replaceChildren();
    if (isPool && poolData.tags && poolData.tags.length > 0) {
      tagsBar.classList.remove("hidden");
      const allBtn = el("button", `tag-chip${!state.activePoolTag ? " active" : ""}`, "Все");
      allBtn.type = "button";
      allBtn.addEventListener("click", () => {
        haptic("light");
        state.activePoolTag = "";
        loadBucket();
      });
      tagsBar.appendChild(allBtn);

      poolData.tags.forEach((tgName) => {
        const b = el("button", `tag-chip${state.activePoolTag === tgName ? " active" : ""}`, `#${tgName}`);
        b.type = "button";
        b.addEventListener("click", () => {
          haptic("light");
          state.activePoolTag = tgName;
          loadBucket();
        });
        tagsBar.appendChild(b);
      });
    } else {
      tagsBar.classList.add("hidden");
    }

    const tasks = isPool ? poolData.tasks : inboxData.tasks;
    document.getElementById("inbox-heading").textContent = isPool
      ? `🗂 Общий пул задач (${tasks.length})`
      : `📥 Входящие (${tasks.length})`;

    const list = document.getElementById("inbox-list");
    list.replaceChildren();
    if (tasks.length === 0) {
      list.appendChild(
        el("div", "empty-state", isPool ? "В пуле пока пусто — сюда можно парковать дела «на потом»." : "Инбокс пуст — голова свободна ✨")
      );
      return;
    }
    tasks.forEach((t) => {
      list.appendChild(buildTaskRow(t, { mode: state.activeBucket, onRefresh: () => loadBucket() }));
    });
  }

  async function loadEvening() {
    const [todayData, tomData, inboxData, poolData] = await Promise.all([
      api(`/api/day?date=${encodeURIComponent(state.today)}`),
      api(`/api/day?date=${encodeURIComponent(state.tomorrow)}`),
      api("/api/inbox"),
      api("/api/pool"),
    ]);
    setBadge("nav-inbox-badge", inboxData.tasks.length);

    const pending = todayData.tasks.filter((t) => t.status === "planned");
    document.getElementById("evening-today-summary").textContent =
      `Сегодня закрыто ${todayData.done_items}/${todayData.total_items} (${todayData.completion_rate}%)`;
    document.getElementById("carry-all-btn").classList.toggle("hidden", pending.length === 0);

    const pendList = document.getElementById("evening-pending-list");
    pendList.replaceChildren();
    if (pending.length === 0) {
      pendList.appendChild(el("div", "empty-state", "🎉 Все задачи на сегодня закрыты!"));
    } else {
      pending.forEach((t) => {
        pendList.appendChild(buildTaskRow(t, { mode: "evening-pending", onRefresh: () => loadEvening() }));
      });
    }

    document.getElementById("evening-tomorrow-heading").textContent = `🌅 ${tomData.label}`;

    const winBox = document.getElementById("evening-free-windows");
    winBox.replaceChildren();
    if (tomData.free_windows && tomData.free_windows.length > 0 && tomData.schedule_events.length > 0) {
      winBox.classList.remove("hidden");
      tomData.free_windows.slice(0, 4).forEach((w) => {
        const h = Math.floor(w.duration_minutes / 60);
        const m = w.duration_minutes % 60;
        const dur = h && m ? `${h}ч ${m}м` : h ? `${h}ч` : `${m}м`;
        winBox.appendChild(el("span", "chip time", `🕒 ${w.start_time}–${w.end_time} (${dur})`));
      });
    } else {
      winBox.classList.add("hidden");
    }

    const tomSch = document.getElementById("evening-tomorrow-schedule");
    tomSch.replaceChildren();
    tomData.schedule_events.forEach((ev) => {
      tomSch.appendChild(buildScheduleRow(ev, () => loadEvening()));
    });

    const tomTasks = document.getElementById("evening-tomorrow-tasks");
    tomTasks.replaceChildren();
    if (tomData.tasks.length === 0 && tomData.schedule_events.length === 0) {
      tomTasks.appendChild(el("div", "empty-state", "На завтра пока пусто — забери задачи из Инбокса или Пула ниже."));
    } else {
      tomData.tasks.forEach((t) => {
        tomTasks.appendChild(buildTaskRow(t, { mode: "day", onRefresh: () => loadEvening() }));
      });
    }

    document.getElementById("evn-src-inbox").textContent = `📥 Из Инбокса (${inboxData.tasks.length})`;
    document.getElementById("evn-src-pool").textContent = `🗂 Взять из Пула (${poolData.tasks.length})`;

    const picker = document.getElementById("evening-source-picker");
    picker.replaceChildren();
    const srcTasks = state.eveningSource === "pool" ? poolData.tasks : inboxData.tasks;
    if (srcTasks.length === 0) {
      picker.appendChild(
        el("div", "empty-state", state.eveningSource === "pool" ? "В пуле задач пока пусто." : "Инбокс пуст — загляни в «Взять из Пула»!")
      );
    } else {
      srcTasks.forEach((t) => {
        picker.appendChild(buildTaskRow(t, { mode: "evening-pick", onRefresh: () => loadEvening() }));
      });
    }
  }

  async function loadReminders() {
    const data = await api("/api/reminders");
    setBadge("nav-rem-badge", data.reminders.length);
    document.getElementById("reminders-heading").textContent = `⏰ Активные напоминания (${data.reminders.length})`;
    const list = document.getElementById("reminders-list");
    list.replaceChildren();
    if (data.reminders.length === 0) {
      list.appendChild(el("div", "empty-state", "Нет активных напоминаний — создай выше или нажми 🔔 на любой задаче."));
      return;
    }
    data.reminders.forEach((rem) => {
      const row = el("div", "item-row");
      const body = el("div", "item-body");
      body.appendChild(el("p", "item-title", rem.text));
      const meta = el("div", "item-meta");
      meta.appendChild(el("span", "chip time", rem.when_label));
      if (rem.repeat_rule === "daily") meta.appendChild(el("span", "chip", "🔁 ежедневно"));
      body.appendChild(meta);

      const actions = el("div", "item-actions");
      const snzBtn = el("button", "mini-btn", "💤 +15м");
      snzBtn.type = "button";
      snzBtn.addEventListener("click", async () => {
        haptic("light");
        await api(`/api/reminders/${rem.id}/snooze`, {
          method: "POST",
          body: JSON.stringify({ minutes: 15 }),
        });
        showToast("Отложено на 15 мин 💤");
        await loadReminders();
      });

      const delBtn = el("button", "mini-btn danger", "✕");
      delBtn.type = "button";
      delBtn.addEventListener("click", async () => {
        haptic("light");
        await api(`/api/reminders/${rem.id}`, { method: "DELETE" });
        await loadReminders();
      });

      actions.append(snzBtn, delBtn);
      row.append(body, actions);
      list.appendChild(row);
    });
  }

  async function loadHistory() {
    const stats = await api(`/api/history/stats?days=${state.historyDays}`);
    document.getElementById("kpi-rate").textContent = `${stats.completion_rate}%`;
    document.getElementById("kpi-ratio").textContent = `${stats.total_done} / ${stats.total_planned}`;
    document.getElementById("kpi-streak").textContent = `${stats.streak_days} дн.`;

    const bars = document.getElementById("history-bars");
    bars.replaceChildren();
    const visible = stats.daily_breakdown.slice(-14);
    if (!state.selectedHistoryDay) state.selectedHistoryDay = state.today;

    visible.forEach((item) => {
      const col = el("button", `bar-col${item.day === state.selectedHistoryDay ? " active" : ""}`);
      col.type = "button";
      const track = el("div", "bar-track");
      const fill = el("div", "bar-fill");
      fill.style.height = `${item.planned ? Math.max(8, item.pct) : 4}%`;
      if (!item.planned) fill.style.opacity = "0.25";
      track.appendChild(fill);
      col.appendChild(track);
      col.appendChild(el("span", "bar-label", item.label.split(" ")[0]));
      col.addEventListener("click", () => {
        haptic("light");
        state.selectedHistoryDay = item.day;
        loadHistoryDay(item.day);
        bars.querySelectorAll(".bar-col").forEach((c) => c.classList.remove("active"));
        col.classList.add("active");
      });
      bars.appendChild(col);
    });

    await loadHistoryDay(state.selectedHistoryDay);
  }

  async function loadHistoryDay(dayIso) {
    const data = await api(`/api/history/day?date=${encodeURIComponent(dayIso)}`);
    document.getElementById("history-day-title").textContent = `${data.label} · ${data.completion_rate}%`;
    const box = document.getElementById("history-day-details");
    box.replaceChildren();

    if (data.total_count === 0) {
      box.appendChild(el("div", "empty-state", "За этот день записей нет."));
      return;
    }

    const addGroup = (title, lines) => {
      if (!lines.length) return;
      box.appendChild(el("div", "hist-group-title", title));
      lines.forEach((txt) => box.appendChild(el("div", "hist-line", txt)));
    };

    addGroup(`✅ Выполнено (${data.completed_tasks.length})`, data.completed_tasks.map((t) => t.title));
    addGroup(`➡️ Перенесено (${data.carried_over_events.length})`, data.carried_over_events.map((e) => e.task_title));
    addGroup(`❌ Не выполнено (${data.pending_tasks.length})`, data.pending_tasks.map((t) => t.title));
    addGroup(
      `🎓 Пары (${data.schedule_events.length})`,
      data.schedule_events.map((e) => `${e.is_done ? "✅" : "▫️"} ${e.start_time} ${e.title}`)
    );
  }

  async function refreshAll() {
    if (state.activeTab === "day") {
      await Promise.all([loadDay(state.selectedDay), loadBadges()]);
    } else if (state.activeTab === "inbox") {
      await loadBucket();
    } else if (state.activeTab === "evening") {
      await loadEvening();
    } else if (state.activeTab === "reminders") {
      await loadReminders();
    } else if (state.activeTab === "history") {
      await loadHistory();
    }
  }

  function switchTab(tab) {
    haptic("light");
    state.activeTab = tab;
    document.querySelectorAll(".tab-panel").forEach((p) => p.classList.remove("active"));
    document.getElementById(`tab-${tab}`).classList.add("active");
    document.querySelectorAll(".nav-btn").forEach((b) => {
      b.classList.toggle("active", b.dataset.tab === tab);
    });
    refreshAll().catch((err) => showToast(err.message));
  }

  function bindEvents() {
    document.querySelectorAll(".nav-btn").forEach((btn) => {
      btn.addEventListener("click", () => switchTab(btn.dataset.tab));
    });

    document.getElementById("refresh-btn").addEventListener("click", () => {
      haptic("light");
      refreshAll().then(() => showToast("Обновлено")).catch((e) => showToast(e.message));
    });

    document.getElementById("schedule-file-input").addEventListener("change", async (e) => {
      const file = e.target.files && e.target.files[0];
      if (!file) return;
      const fd = new FormData();
      fd.append("file", file);
      showToast("⏳ Импортирую расписание…");
      try {
        const res = await api("/api/schedule/upload", { method: "POST", body: fd, isForm: true });
        showToast(`🎓 Импортировано занятий: ${res.saved}`);
        await loadDay(state.selectedDay);
      } catch (err) {
        showToast(err.message);
      } finally {
        e.target.value = "";
      }
    });

    document.getElementById("day-quick-add").addEventListener("submit", async (e) => {
      e.preventDefault();
      const input = document.getElementById("day-add-input");
      const text = input.value.trim();
      if (!text) return;
      haptic("medium");
      const res = await api("/api/tasks/dump", {
        method: "POST",
        body: JSON.stringify({ text, target_date: state.selectedDay }),
      });
      input.value = "";
      showToast(res.count > 1 ? `Разобрал на ${res.count} задач` : "Задача добавлена");
      await refreshAll();
    });

    document.querySelectorAll("#tab-inbox .segment-btn").forEach((btn) => {
      btn.addEventListener("click", () => {
        haptic("light");
        state.activeBucket = btn.dataset.bucket;
        document.querySelectorAll("#tab-inbox .segment-btn").forEach((b) => b.classList.remove("active"));
        btn.classList.add("active");
        loadBucket().catch((err) => showToast(err.message));
      });
    });

    document.getElementById("inbox-dump-form").addEventListener("submit", async (e) => {
      e.preventDefault();
      const input = document.getElementById("inbox-dump-input");
      const text = input.value.trim();
      if (!text) return;
      haptic("medium");
      const res = await api("/api/tasks/dump", {
        method: "POST",
        body: JSON.stringify({ text, target_bucket: state.activeBucket }),
      });
      input.value = "";
      const where = state.activeBucket === "pool" ? "в Пул" : "в Инбокс";
      showToast(res.count > 1 ? `Разобрал ${res.count} задач ${where}` : `Сохранено ${where}`);
      await loadBucket();
    });

    document.querySelectorAll("#tab-evening .segment-btn").forEach((btn) => {
      btn.addEventListener("click", () => {
        haptic("light");
        state.eveningSource = btn.dataset.source;
        document.querySelectorAll("#tab-evening .segment-btn").forEach((b) => b.classList.remove("active"));
        btn.classList.add("active");
        loadEvening().catch((err) => showToast(err.message));
      });
    });

    document.getElementById("carry-all-btn").addEventListener("click", async () => {
      haptic("medium");
      const res = await api("/api/evening/carry-over-all", {
        method: "POST",
        body: JSON.stringify({ from_date: state.today, to_date: state.tomorrow }),
      });
      showToast(`Перенесено задач: ${res.moved}`);
      await loadEvening();
    });

    document.getElementById("reminder-create-form").addEventListener("submit", async (e) => {
      e.preventDefault();
      const input = document.getElementById("reminder-input");
      const text = input.value.trim();
      if (!text) return;
      haptic("medium");
      try {
        const res = await api("/api/reminders", {
          method: "POST",
          body: JSON.stringify({ text }),
        });
        input.value = "";
        showToast(`🔔 Напомню: ${res.reminder.when_label}`);
        await loadReminders();
      } catch (err) {
        showToast(err.message);
      }
    });

    document.querySelectorAll("#tab-history .segment-btn").forEach((btn) => {
      btn.addEventListener("click", () => {
        haptic("light");
        state.historyDays = Number(btn.dataset.days);
        document.querySelectorAll("#tab-history .segment-btn").forEach((b) => b.classList.remove("active"));
        btn.classList.add("active");
        loadHistory().catch((err) => showToast(err.message));
      });
    });
  }

  async function init() {
    bindEvents();
    try {
      const me = await api("/api/me");
      state.today = me.today;
      state.tomorrow = me.tomorrow;
      state.selectedDay = me.today;
      state.selectedHistoryDay = me.today;
      state.weekDays = me.week_days;
      setBadge("nav-inbox-badge", me.inbox_count);
      setBadge("nav-rem-badge", me.reminders_count);

      const name = me.user.first_name || me.user.username || "Привет";
      const grp = me.user.study_group ? ` · ${me.user.study_group}` : "";
      document.getElementById("topbar-subtitle").textContent = `${name}${grp}`;

      renderWeekStrip();
      await loadDay(state.selectedDay);
    } catch (err) {
      document.querySelectorAll(".tab-panel").forEach((p) => p.classList.remove("active"));
      document.getElementById("auth-error").classList.remove("hidden");
      document.getElementById("auth-error-msg").textContent = err.message || "Открой CheTam через Telegram.";
      document.getElementById("topbar-subtitle").textContent = "Нужен вход через Telegram";
    }
  }

  init();
})();
