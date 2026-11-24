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
    historyDays: 7,
    selectedHistoryDay: "",
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
    const el = document.getElementById("toast");
    el.textContent = msg;
    el.classList.add("show");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => el.classList.remove("show"), 2200);
  }

  async function api(path, options = {}) {
    const headers = Object.assign(
      {
        "Content-Type": "application/json",
        "X-Telegram-Init-Data": tg ? tg.initData || "" : "",
      },
      options.headers || {}
    );
    const resp = await fetch(path, Object.assign({}, options, { headers }));
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

  function updateInboxBadge(count) {
    const badge = document.getElementById("nav-inbox-badge");
    if (count > 0) {
      badge.textContent = String(count);
      badge.classList.remove("hidden");
    } else {
      badge.classList.add("hidden");
    }
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
    body.appendChild(meta);

    row.appendChild(check);
    row.appendChild(body);
    return row;
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
    if (task.carried_over_count > 0) meta.appendChild(el("span", "chip", `↻${task.carried_over_count}`));
    if (meta.childNodes.length > 0) body.appendChild(meta);

    const actions = el("div", "item-actions");
    if (options.mode === "day") {
      const prioBtn = el("button", "mini-btn", task.priority === 1 ? "🔴" : task.priority === 3 ? "⚪" : "🟡");
      prioBtn.type = "button";
      prioBtn.title = "Приоритет";
      prioBtn.addEventListener("click", async () => {
        haptic("light");
        await api(`/api/tasks/${task.id}/priority`, { method: "POST" });
        await options.onRefresh();
      });

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
        showToast("Перенесено на следующий день");
        await options.onRefresh();
      });

      const delBtn = el("button", "mini-btn danger", "✕");
      delBtn.type = "button";
      delBtn.title = "Удалить";
      delBtn.addEventListener("click", async () => {
        haptic("light");
        await api(`/api/tasks/${task.id}`, { method: "DELETE" });
        await options.onRefresh();
      });

      actions.append(prioBtn, moveBtn, delBtn);
    } else if (options.mode === "inbox") {
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

      const delBtn = el("button", "mini-btn danger", "✕");
      delBtn.type = "button";
      delBtn.addEventListener("click", async () => {
        haptic("light");
        await api(`/api/tasks/${task.id}`, { method: "DELETE" });
        await options.onRefresh();
      });

      actions.append(todayBtn, tomBtn, delBtn);
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
      actions.append(moveBtn);
    } else if (options.mode === "evening-pick") {
      const pickBtn = el("button", "mini-btn", "＋ Завтра");
      pickBtn.type = "button";
      pickBtn.addEventListener("click", async () => {
        haptic("light");
        await api(`/api/tasks/${task.id}/plan`, {
          method: "POST",
          body: JSON.stringify({ target_date: state.tomorrow }),
        });
        showToast("Добавлено в план на завтра");
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

  function shiftIso(iso, delta) {
    const [y, m, d] = iso.split("-").map(Number);
    const dt = new Date(Date.UTC(y, m - 1, d + delta));
    return dt.toISOString().slice(0, 10);
  }

  async function loadDay(dayIso) {
    const data = await api(`/api/day?date=${encodeURIComponent(dayIso)}`);
    document.getElementById("day-title").textContent = data.label;
    document.getElementById("day-progress-label").textContent = `${data.completion_rate}%`;
    document.getElementById("day-progress-fill").style.width = `${data.completion_rate}%`;
    document.getElementById("day-progress-sub").textContent = `${data.done_items} из ${data.total_items} выполнено`;

    const schBlock = document.getElementById("day-schedule-block");
    const schList = document.getElementById("day-schedule-list");
    schList.replaceChildren();
    if (data.schedule_events.length > 0) {
      schBlock.classList.remove("hidden");
      data.schedule_events.forEach((ev) => {
        schList.appendChild(buildScheduleRow(ev, () => loadDay(dayIso)));
      });
    } else {
      schBlock.classList.add("hidden");
    }

    const taskList = document.getElementById("day-task-list");
    taskList.replaceChildren();
    if (data.tasks.length === 0) {
      taskList.appendChild(el("div", "empty-state", "На этот день задач пока нет — добавь выше или забери из Инбокса ✨"));
    } else {
      data.tasks.forEach((t) => {
        taskList.appendChild(buildTaskRow(t, { mode: "day", onRefresh: () => refreshAll() }));
      });
    }
  }

  async function loadInbox() {
    const data = await api("/api/inbox");
    updateInboxBadge(data.tasks.length);
    document.getElementById("inbox-heading").textContent = `📥 Входящие (${data.tasks.length})`;
    const list = document.getElementById("inbox-list");
    list.replaceChildren();
    if (data.tasks.length === 0) {
      list.appendChild(el("div", "empty-state", "Инбокс пуст — голова свободна ✨"));
      return;
    }
    data.tasks.forEach((t) => {
      list.appendChild(buildTaskRow(t, { mode: "inbox", onRefresh: () => refreshAll() }));
    });
  }

  async function loadEvening() {
    const [todayData, tomData, inboxData] = await Promise.all([
      api(`/api/day?date=${encodeURIComponent(state.today)}`),
      api(`/api/day?date=${encodeURIComponent(state.tomorrow)}`),
      api("/api/inbox"),
    ]);
    updateInboxBadge(inboxData.tasks.length);

    const pending = todayData.tasks.filter((t) => t.status === "planned");
    document.getElementById("evening-today-summary").textContent =
      `Сегодня закрыто ${todayData.done_items}/${todayData.total_items} (${todayData.completion_rate}%)`;

    const carryAllBtn = document.getElementById("carry-all-btn");
    carryAllBtn.classList.toggle("hidden", pending.length === 0);

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
    const tomSch = document.getElementById("evening-tomorrow-schedule");
    tomSch.replaceChildren();
    tomData.schedule_events.forEach((ev) => {
      tomSch.appendChild(buildScheduleRow(ev, () => loadEvening()));
    });

    const tomTasks = document.getElementById("evening-tomorrow-tasks");
    tomTasks.replaceChildren();
    if (tomData.tasks.length === 0 && tomData.schedule_events.length === 0) {
      tomTasks.appendChild(el("div", "empty-state", "На завтра пока пусто — выбери задачи ниже."));
    } else {
      tomData.tasks.forEach((t) => {
        tomTasks.appendChild(buildTaskRow(t, { mode: "day", onRefresh: () => loadEvening() }));
      });
    }

    const picker = document.getElementById("evening-inbox-picker");
    picker.replaceChildren();
    if (inboxData.tasks.length === 0) {
      picker.appendChild(el("div", "empty-state", "Инбокс пуст — всё уже разобрано."));
    } else {
      inboxData.tasks.forEach((t) => {
        picker.appendChild(buildTaskRow(t, { mode: "evening-pick", onRefresh: () => loadEvening() }));
      });
    }
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

    addGroup(
      `✅ Выполнено (${data.completed_tasks.length})`,
      data.completed_tasks.map((t) => t.title)
    );
    addGroup(
      `➡️ Перенесено (${data.carried_over_events.length})`,
      data.carried_over_events.map((e) => e.task_title)
    );
    addGroup(
      `❌ Не выполнено (${data.pending_tasks.length})`,
      data.pending_tasks.map((t) => t.title)
    );
    addGroup(
      `🎓 Пары (${data.schedule_events.length})`,
      data.schedule_events.map((e) => `${e.is_done ? "✅" : "▫️"} ${e.start_time} ${e.title}`)
    );
  }

  async function refreshAll() {
    if (state.activeTab === "day") {
      await Promise.all([loadDay(state.selectedDay), loadInbox()]);
    } else if (state.activeTab === "inbox") {
      await loadInbox();
    } else if (state.activeTab === "evening") {
      await loadEvening();
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

    document.getElementById("inbox-dump-form").addEventListener("submit", async (e) => {
      e.preventDefault();
      const input = document.getElementById("inbox-dump-input");
      const text = input.value.trim();
      if (!text) return;
      haptic("medium");
      const res = await api("/api/tasks/dump", {
        method: "POST",
        body: JSON.stringify({ text }),
      });
      input.value = "";
      showToast(res.count > 1 ? `🧠 Разобрал на ${res.count} задач` : "📥 Сохранено в инбокс");
      await refreshAll();
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

    document.querySelectorAll(".segment-btn").forEach((btn) => {
      btn.addEventListener("click", () => {
        haptic("light");
        state.historyDays = Number(btn.dataset.days);
        document.querySelectorAll(".segment-btn").forEach((b) => b.classList.remove("active"));
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
      updateInboxBadge(me.inbox_count);

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
