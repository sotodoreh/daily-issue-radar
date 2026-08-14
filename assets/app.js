/* 데일리 이슈 레이더 — 프론트엔드 */
(function () {
  "use strict";

  const $ = (sel) => document.querySelector(sel);
  const fmt = (n) => (n == null ? "-" : Number(n).toLocaleString("ko-KR"));
  const esc = (s) => String(s).replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

  const AGE_LABELS = { 10: "10대", 20: "20대", 30: "30대", 40: "40대", 50: "50대", 60: "60대", 70: "70+" };

  const state = { dates: [], date: null, data: null, age: "", gender: "" };

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
      .map((d) => {
        const dd = state.dates.indexOf(d) >= 0 ? d : d;
        return `<option value="${d}" ${d === state.date ? "selected" : ""}>${dateLabel(d)}</option>`;
      })
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

    const maxC = Math.max(...d.topics.map((t) => t.comments), 1);
    $("#topicTable tbody").innerHTML = d.topics
      .map((t) => {
        const badge =
          t.badge === "surge" ? '<span class="badge badge-surge">포착</span>' :
          t.badge === "new" ? '<span class="badge badge-new">신규 탐지</span>' : "";
        const rep = t.topArticles && t.topArticles[0];
        return `<tr class="${t.rank <= 3 ? "rank-top" : ""}">
          <td><span class="rank-num">${t.rank}</span></td>
          <td><span class="topic-label">${esc(t.label)}</span>${badge}</td>
          <td><div class="kw-chips">${t.keywords.slice(0, 6).map((k) => `<span class="kw">${esc(k)}</span>`).join("")}</div></td>
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
