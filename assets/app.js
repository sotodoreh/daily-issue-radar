/* 데일리 이슈 레이더 — 프론트엔드 */
(function () {
  "use strict";

  const $ = (sel) => document.querySelector(sel);
  const fmt = (n) => (n == null ? "-" : Number(n).toLocaleString("ko-KR"));
  const esc = (s) => String(s).replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

  const AGE_LABELS = { 10: "10대", 20: "20대", 30: "30대", 40: "40대", 50: "50대", 60: "60대", 70: "70+" };

  const state = { dates: [], date: null, data: null, age: "", gender: "", cat: "" };

  const CAT_ORDER = ["정치", "경제", "사회", "국제", "문화"];

  // ---------------- data loading ----------------
  async function loadIndex() {
    const res = await fetch("data/index.json", { cache: "no-store" });
    const idx = await res.json();
    state.dates = idx.dates || [];
    state.date = idx.latest;
  }

  async function loadDay(date) {
    showLoader(true);
    try {
      const res = await fetch(`data/${date}.json`, { cache: "no-store" });
      state.data = await res.json();
      state.date = date;
      state.cat = "";   // 날짜마다 있는 분야가 달라 필터는 초기화
      renderAll();
    } catch (e) {
      console.error(e);
      alert("데이터를 불러오지 못했습니다: " + date);
    } finally {
      showLoader(false);
    }
  }

  function showLoader(on) {
    $("#loader").classList.toggle("hide", !on);
  }

  // ---------------- header ----------------
  function renderHeader() {
    const sel = $("#dateSelect");
    sel.innerHTML = state.dates
      .slice()
      .reverse()
      .map((d) => `<option value="${d}" ${d === state.date ? "selected" : ""}>${dateLabel(d)}</option>`)
      .join("");
    const i = state.dates.indexOf(state.date);
    $("#btnPrev").disabled = i <= 0;
    $("#btnNext").disabled = i >= state.dates.length - 1;
    $("#collectedAt").textContent = state.data ? `수집 ${state.data.collectedAt}` : "";
  }

  function dateLabel(iso) {
    const d = state.data && state.data.date === iso ? state.data.weekday : weekdayOf(iso);
    const [y, m, dd] = iso.split("-");
    return `${y}년 ${Number(m)}월 ${Number(dd)}일 (${d})`;
  }

  function weekdayOf(iso) {
    return "일월화수목금토"[new Date(iso + "T00:00:00+09:00").getDay()];
  }

  // ---------------- 대문 ----------------
  function renderHome() {
    const d = state.data;
    const [y, m, dd] = d.date.split("-");
    $("#heroDate").textContent = `${Number(m)}월 ${Number(dd)}일 (${d.weekday}) 여론 브리핑`;
    $("#briefing").innerHTML = d.briefing.map((b) => `<p>${esc(b)}</p>`).join("");

    const tiles = [
      ["집계 기사", fmt(d.meta.totalArticles), "건"],
      ["총 댓글", fmt(d.meta.totalComments), "개"],
      ["성·연령 분석 기사", fmt(d.meta.demoArticles), "건"],
      ["탐지된 주제", fmt(d.topics.length), "개"],
    ];
    $("#statRow").innerHTML = tiles
      .map(([l, v, u]) => `<div class="stat-tile"><div class="lbl">${l}</div><div class="val">${v}<small>${u}</small></div></div>`)
      .join("");

    renderCatFilters();
    renderTopicTable();
  }

  function renderCatFilters() {
    const present = CAT_ORDER.filter((c) =>
      state.data.topics.some((t) => (t.category || "사회") === c));
    const box = $("#catFilters");
    box.innerHTML =
      '<span class="filter-label">분야</span>' +
      [["", "전체"], ...present.map((c) => [c, c])]
        .map(([v, label]) => {
          const n = v ? state.data.topics.filter((t) => (t.category || "사회") === v).length
                      : state.data.topics.length;
          return `<button class="chip ${state.cat === v ? "active" : ""}" data-cat="${v}">${label} <span class="chip-n">${n}</span></button>`;
        })
        .join("");
  }

  function renderTopicTable() {
    const d = state.data;
    const rows = d.topics.filter((t) => !state.cat || (t.category || "사회") === state.cat);
    const maxC = Math.max(...d.topics.map((t) => t.comments), 1);
    if (!rows.length) {
      $("#topicTable tbody").innerHTML =
        '<tr><td colspan="7" class="demo-empty">해당 분야의 주제가 없습니다.</td></tr>';
      return;
    }
    $("#topicTable tbody").innerHTML = rows
      .map((t) => {
        const badge =
          t.badge === "surge" ? '<span class="badge badge-surge">포착</span>' :
          t.badge === "new" ? '<span class="badge badge-new">신규 탐지</span>' : "";
        const rep = t.topArticles && t.topArticles[0];
        const cat = t.category || "사회";
        return `<tr class="${t.rank <= 3 ? "rank-top" : ""}">
          <td><span class="rank-num">${t.rank}</span></td>
          <td><span class="cat cat-${cat}">${cat}</span></td>
          <td><span class="topic-label">${esc(t.label)}</span>${badge}</td>
          <td><div class="kw-chips">${t.keywords.slice(0, 10).map((k) => `<span class="kw">${esc(k)}</span>`).join("")}</div></td>
          <td class="num">${fmt(t.articleCount)}</td>
          <td class="num"><div class="cmt-bar-wrap"><div class="cmt-bar" style="width:${Math.round((t.comments / maxC) * 70)}px"></div>${fmt(t.comments)}</div></td>
          <td>${rep ? `<a class="rep-article" href="${rep.url}" target="_blank" rel="noopener" title="${esc(rep.title)}">${esc(rep.title)}</a>` : ""}</td>
        </tr>`;
      })
      .join("");
  }

  // ---------------- 메인 이슈 ----------------
  function genderBar(a) {
    if (a.male == null) return '<span class="muted">-</span>';
    return `<div class="gender-bar">
      <span class="g-lbl-m">남 ${a.male}%</span>
      <div class="gender-track">
        <div class="gender-m" style="width:${a.male}%"></div>
        <div class="gender-f" style="width:${a.female}%"></div>
      </div>
      <span class="g-lbl-f">${a.female}%</span>
    </div>`;
  }

  function topAge(a) {
    if (!a.ages) return "";
    let best = null;
    for (const [age, v] of Object.entries(a.ages)) {
      if (!best || v > best[1]) best = [age, v];
    }
    return best ? `<span class="age-chip">${AGE_LABELS[best[0]] || best[0]} ${best[1]}%</span>` : "";
  }

  function renderMain() {
    const d = state.data;
    $("#commentTable tbody").innerHTML = d.commentTop
      .map((a, i) => `<tr class="${i < 3 ? "rank-top" : ""}">
          <td><span class="rank-num">${i + 1}</span></td>
          <td class="title-cell"><a href="${a.url}" target="_blank" rel="noopener">${esc(a.title)}</a></td>
          <td class="press">${esc(a.press)}</td>
          <td class="num">${fmt(a.comments)}</td>
          <td>${genderBar(a)}</td>
          <td>${topAge(a)}</td>
        </tr>`)
      .join("");

    $("#viewedTable tbody").innerHTML = d.viewedTop
      .map((a, i) => `<tr class="${i < 3 ? "rank-top" : ""}">
          <td><span class="rank-num">${i + 1}</span></td>
          <td class="title-cell"><a href="${a.url}" target="_blank" rel="noopener">${esc(a.title)}</a></td>
          <td class="press">${esc(a.press)}</td>
          <td class="num">${fmt(a.comments)}</td>
        </tr>`)
      .join("");
  }

  // ---------------- 연령·성별 ----------------
  function agePct(a, age) {
    if (!a.ages) return 0;
    if (age === "60") return (a.ages["60"] || 0) + (a.ages["70"] || 0);
    return a.ages[age] || 0;
  }

  function renderDemo() {
    const d = state.data;
    const pool = d.articles.filter((a) => a.ages && a.male != null);
    const { age, gender } = state;

    let scored = pool.map((a) => {
      let score = 1;
      const parts = [];
      if (age) {
        const p = agePct(a, age);
        score *= p / 100;
        parts.push(`${age === "60" ? "60대+" : AGE_LABELS[age]} ${p}%`);
      }
      if (gender) {
        const p = gender === "male" ? a.male : a.female;
        score *= p / 100;
        parts.push(`${gender === "male" ? "남성" : "여성"} ${p}%`);
      }
      if (!age && !gender) score = a.comments;
      return { a, score, parts };
    });

    scored = scored
      .filter((s) => s.score > 0)
      .sort((x, y) => y.score - x.score || y.a.comments - x.a.comments)
      .slice(0, 10);

    if (!scored.length) {
      $("#demoResult").innerHTML = '<div class="demo-empty">조건에 맞는 기사가 없습니다.</div>';
      return;
    }

    $("#demoResult").innerHTML = scored
      .map((s, i) => {
        const a = s.a;
        const bars = Object.keys(AGE_LABELS)
          .map((k) => {
            const v = a.ages[k] || 0;
            const hl = age && (k === age || (age === "60" && (k === "60" || k === "70")));
            return `<div class="agebar-col">
              <span class="agebar-val">${v}</span>
              <div class="agebar ${hl ? "hl" : ""}" style="height:${Math.max(2, v * 0.75)}px"></div>
              <span class="agebar-lbl">${AGE_LABELS[k].replace("대", "")}</span>
            </div>`;
          })
          .join("");
        const scoreTxt = s.parts.length
          ? `<span class="demo-score">${s.parts.join(" · ")}</span> · `
          : "";
        return `<div class="demo-item">
          <div class="demo-rank">${i + 1}</div>
          <div class="demo-body">
            <div class="demo-title"><a href="${a.url}" target="_blank" rel="noopener">${esc(a.title)}</a></div>
            <div class="demo-meta">${scoreTxt}${esc(a.press)} · 댓글 ${fmt(a.comments)}개</div>
            <div class="demo-charts">
              <div class="agebars">${bars}</div>
              ${genderBar(a)}
            </div>
          </div>
        </div>`;
      })
      .join("");
  }

  // ---------------- 주간 흐름 ----------------
  const allDays = new Map();   // date -> payload (lazy cache)

  async function loadAllDays() {
    const targets = state.dates.filter((d) => !allDays.has(d));
    await Promise.all(
      targets.map(async (d) => {
        try {
          const res = await fetch(`data/${d}.json`, { cache: "no-store" });
          allDays.set(d, await res.json());
        } catch (e) {
          console.warn("skip", d, e);
        }
      })
    );
    return state.dates.filter((d) => allDays.has(d)).map((d) => allDays.get(d));
  }

  // 주제명에서 의미 있는 토큰만 추출 (조사/일반어 제거)
  const TREND_STOP = new Set([
    "논란", "공방", "갈등", "이슈", "관련", "확산", "파문", "사태", "국면",
    "대응", "여론", "반발", "비판", "지속", "격화", "심화", "점화", "확인",
    "발표", "제기", "등장", "정리", "소식", "기타", "내홍", "신경전", "공세",
  ]);

  function trendTokens(topic) {
    const raw = String(topic.label || "").replace(/[()[\]{}'"“”‘’·,/]/g, " ");
    return new Set(
      raw
        .split(/\s+/)
        .map((w) => w.replace(/(에서|으로|이라는|라는|까지|부터|에게|의|을|를|이|가|은|는|와|과|도|만)$/, ""))
        .filter((w) => w.length >= 2 && !TREND_STOP.has(w))
    );
  }

  // 희소 단어에 큰 가중치(IDF)를 줘서 같은 사안인지 판정한다.
  // '대통령' 같은 흔한 말은 약하게, '하영'·'전당대회' 같은 말은 강하게 본다.
  function buildStreaks(days) {
    const all = [];
    days.forEach((day) =>
      (day.topics || []).forEach((t) =>
        all.push({ date: day.date, weekday: day.weekday, topic: t, tok: trendTokens(t) })
      )
    );
    if (!all.length) return [];

    const df = new Map();
    all.forEach((e) => e.tok.forEach((t) => df.set(t, (df.get(t) || 0) + 1)));
    const N = all.length;
    const idf = (t) => Math.log(N / (df.get(t) || 1));

    const sim = (a, b) => {
      let w = 0;
      a.tok.forEach((t) => { if (b.tok.has(t)) w += idf(t); });
      return w;
    };
    const THRESHOLD = 2.6;   // 희소 토큰 1개 또는 흔한 토큰 3개 수준

    const groups = [];
    all.forEach((entry) => {
      let best = null, bestScore = 0;
      groups.forEach((g) => {
        const s = Math.max(...g.members.map((m) => sim(m, entry)));
        if (s > bestScore) { bestScore = s; best = g; }
      });
      if (best && bestScore >= THRESHOLD) {
        if (!best.members.some((m) => m.date === entry.date)) best.members.push(entry);
      } else {
        groups.push({ members: [entry] });
      }
    });
    return groups
      .filter((g) => g.members.length >= 2)
      .map((g) => {
        const peak = g.members.reduce((a, b) =>
          b.topic.comments > a.topic.comments ? b : a);
        return {
          label: peak.topic.label,
          category: peak.topic.category || "사회",
          days: g.members.length,
          total: g.members.reduce((s, m) => s + m.topic.comments, 0),
          peak,
          members: g.members.slice().sort((a, b) => a.date.localeCompare(b.date)),
        };
      })
      .sort((a, b) => b.days - a.days || b.total - a.total)
      .slice(0, 12);
  }

  async function renderTrend() {
    const days = await loadAllDays();
    if (!days.length) return;

    // --- 일자별 활동량 막대 ---
    const maxV = Math.max(...days.map((d) => d.meta.totalComments), 1);
    $("#volChart").innerHTML = days
      .map((d) => {
        const v = d.meta.totalComments;
        const h = Math.max(4, Math.round((v / maxV) * 130));
        const top = (d.topics && d.topics[0]) ? d.topics[0].label : "";
        const isCur = d.date === state.date;
        const [, m, dd] = d.date.split("-");
        return `<button class="vol-col ${isCur ? "cur" : ""}" data-date="${d.date}"
                  title="${esc(d.date)} · 총 댓글 ${fmt(v)}개${top ? " · 1위: " + esc(top) : ""}">
            <span class="vol-val">${(v / 10000).toFixed(1)}만</span>
            <span class="vol-bar" style="height:${h}px"></span>
            <span class="vol-lbl">${Number(m)}/${Number(dd)}<br><em>${d.weekday}</em></span>
          </button>`;
      })
      .join("");

    // --- 연속 추적 이슈 ---
    const streaks = buildStreaks(days);
    if (!streaks.length) {
      $("#streaks").innerHTML =
        '<div class="demo-empty">아직 여러 날에 걸친 반복 주제가 없습니다. 데이터가 더 쌓이면 표시됩니다.</div>';
      return;
    }
    $("#streaks").innerHTML = streaks
      .map((s) => {
        const dots = days
          .map((d) => {
            const hit = s.members.find((m) => m.date === d.date);
            const isPeak = hit && hit.date === s.peak.date;
            const [, m, dd] = d.date.split("-");
            return `<span class="dot ${hit ? "on" : ""} ${isPeak ? "peak" : ""}"
                      title="${Number(m)}/${Number(dd)}${hit ? " · 댓글 " + fmt(hit.topic.comments) + "개 · " + esc(hit.topic.label) : " · 미등장"}"></span>`;
          })
          .join("");
        return `<div class="streak">
          <div class="streak-head">
            <span class="cat cat-${s.category}">${s.category}</span>
            <span class="streak-label">${esc(s.label)}</span>
            <span class="streak-days">${s.days}일 연속</span>
          </div>
          <div class="streak-body">
            <div class="dots">${dots}</div>
            <div class="streak-meta">누적 댓글 <b>${fmt(s.total)}</b>개 ·
              정점 ${s.peak.date.slice(5).replace("-", "/")}(${s.peak.weekday}) ${fmt(s.peak.topic.comments)}개</div>
          </div>
        </div>`;
      })
      .join("");
  }

  // ---------------- render all ----------------
  function renderAll() {
    document.title = `데일리 이슈 레이더 — ${state.date}`;
    renderHeader();
    renderHome();
    renderMain();
    renderDemo();
  }

  // ---------------- events ----------------
  function bindEvents() {
    document.querySelectorAll(".tab").forEach((btn) => {
      btn.addEventListener("click", () => {
        document.querySelectorAll(".tab").forEach((b) => b.classList.remove("active"));
        document.querySelectorAll(".tab-panel").forEach((p) => p.classList.remove("active"));
        btn.classList.add("active");
        $("#tab-" + btn.dataset.tab).classList.add("active");
        window.scrollTo({ top: 0 });
        if (btn.dataset.tab === "trend") renderTrend();
      });
    });

    $("#dateSelect").addEventListener("change", (e) => loadDay(e.target.value));
    $("#btnPrev").addEventListener("click", () => {
      const i = state.dates.indexOf(state.date);
      if (i > 0) loadDay(state.dates[i - 1]);
    });
    $("#btnNext").addEventListener("click", () => {
      const i = state.dates.indexOf(state.date);
      if (i < state.dates.length - 1) loadDay(state.dates[i + 1]);
    });

    $("#volChart").addEventListener("click", (e) => {
      const b = e.target.closest(".vol-col");
      if (!b) return;
      loadDay(b.dataset.date).then(() => {
        document.querySelector('.tab[data-tab="home"]').click();
      });
    });

    $("#catFilters").addEventListener("click", (e) => {
      const b = e.target.closest(".chip");
      if (!b) return;
      state.cat = b.dataset.cat;
      renderCatFilters();
      renderTopicTable();
    });

    $("#ageFilters").addEventListener("click", (e) => {
      const b = e.target.closest(".chip");
      if (!b) return;
      state.age = b.dataset.age;
      document.querySelectorAll("#ageFilters .chip").forEach((c) => c.classList.toggle("active", c === b));
      renderDemo();
    });
    $("#genderFilters").addEventListener("click", (e) => {
      const b = e.target.closest(".chip");
      if (!b) return;
      state.gender = b.dataset.gender;
      document.querySelectorAll("#genderFilters .chip").forEach((c) => c.classList.toggle("active", c === b));
      renderDemo();
    });
  }

  // ---------------- init ----------------
  (async function init() {
    bindEvents();
    try {
      await loadIndex();
      if (!state.date) throw new Error("no data");
      await loadDay(state.date);
    } catch (e) {
      console.error(e);
      showLoader(false);
      document.querySelector("main").insertAdjacentHTML(
        "afterbegin",
        '<div class="card" style="text-align:center;color:#8B93A7">아직 수집된 데이터가 없습니다. 수집기가 실행되면 자동으로 표시됩니다.</div>'
      );
    }
  })();
})();
