/* 사용량 집계 — 방문 기록 + 비공개 통계 화면
 * 기기마다 무작위 번호 하나를 브라우저에 저장해 사용자 수를 셉니다.
 * 이름·IP 등 개인을 알아볼 수 있는 정보는 보내지 않습니다. */
(function () {
  "use strict";

  // Cloudflare Worker 배포 후 그 주소를 여기에 넣으세요 (끝에 / 없이)
  // 예: "https://issue-radar-stats.내계정.workers.dev"
  var STATS_API = "";

  var $ = function (s) { return document.querySelector(s); };
  var fmt = function (n) { return Number(n || 0).toLocaleString("ko-KR"); };

  // ---------- 기기 번호 ----------
  function deviceId() {
    try {
      var id = localStorage.getItem("_ir_did");
      if (!id) {
        id = (window.crypto && crypto.randomUUID)
          ? crypto.randomUUID().replace(/-/g, "")
          : (Date.now().toString(36) + Math.random().toString(36).slice(2, 12));
        id = id.replace(/[^a-zA-Z0-9]/g, "").slice(0, 32);
        localStorage.setItem("_ir_did", id);
      }
      return id;
    } catch (e) {
      return "";               // 시크릿 모드 등 저장 불가 시 집계 생략
    }
  }

  // ---------- 방문 기록 ----------
  function sendHit() {
    if (!STATS_API) return;
    var did = deviceId();
    if (!did) return;
    try {
      fetch(STATS_API + "/hit", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ did: did }),
        keepalive: true,
      })["catch"](function () {});
    } catch (e) { /* 집계 실패가 서비스에 영향을 주지 않도록 무시 */ }
  }

  // ---------- 통계 화면 ----------
  function openPanel() {
    $("#usageModal").classList.add("show");
    setTimeout(function () { $("#usagePw").focus(); }, 50);
  }
  function closePanel() {
    $("#usageModal").classList.remove("show");
    $("#usageErr").textContent = "";
    $("#usagePw").value = "";
    if (location.hash === "#usage") {
      history.replaceState(null, "", location.pathname + location.search);
    }
  }

  function renderStats(d) {
    var maxU = Math.max.apply(null, d.series.map(function (s) { return s.users; }).concat([1]));
    var bars = d.series.map(function (s) {
      var h = s.users ? Math.max(3, Math.round((s.users / maxU) * 90)) : 0;
      var md = s.date.slice(5).replace("-", "/");
      return '<div class="ub" title="' + md + " · 사용자 " + s.users + "명 · 방문 " + s.visits + '회">' +
             '<span class="ub-bar" style="height:' + h + 'px"></span></div>';
    }).join("");

    var first = d.series[0].date.slice(5).replace("-", "/");
    var last = d.series[d.series.length - 1].date.slice(5).replace("-", "/");

    $("#usageBody").innerHTML =
      '<div class="ustats">' +
        '<div class="ustat"><div class="lbl">오늘 사용자</div><div class="val">' + fmt(d.today) +
          '<small>명</small></div><div class="sub">방문 ' + fmt(d.todayVisits) + '회</div></div>' +
        '<div class="ustat"><div class="lbl">최근 7일</div><div class="val">' + fmt(d.week) +
          '<small>명</small></div><div class="sub">중복 제외</div></div>' +
        '<div class="ustat"><div class="lbl">최근 30일</div><div class="val">' + fmt(d.month) +
          '<small>명</small></div><div class="sub">중복 제외</div></div>' +
        '<div class="ustat"><div class="lbl">누적 방문</div><div class="val">' + fmt(d.totalVisits) +
          '<small>회</small></div><div class="sub">기기 ' + fmt(d.totalDevices) + '대</div></div>' +
      '</div>' +
      '<div class="uchart-wrap"><div class="uchart-title">일별 사용자 수 (최근 30일)</div>' +
        '<div class="uchart">' + bars + '</div>' +
        '<div class="uchart-axis"><span>' + first + '</span><span>' + last + '</span></div></div>' +
      '<p class="unote">기기마다 부여한 무작위 번호로 셉니다. 같은 사람이 PC와 휴대폰으로 보면 2명으로, ' +
        '브라우저 기록을 지우면 새 사람으로 집계됩니다.</p>';
  }

  function loadStats() {
    var pw = $("#usagePw").value.trim();
    if (!pw) return;
    if (!STATS_API) {
      $("#usageErr").textContent = "집계 서버가 아직 연결되지 않았습니다. (assets/usage.js의 STATS_API)";
      return;
    }
    $("#usageErr").textContent = "";
    $("#usageBody").innerHTML = '<div class="uloading">불러오는 중…</div>';

    fetch(STATS_API + "/stats?key=" + encodeURIComponent(pw))
      .then(function (r) {
        if (r.status === 401) throw new Error("비밀번호가 맞지 않습니다.");
        if (!r.ok) throw new Error("서버 오류 (" + r.status + ")");
        return r.json();
      })
      .then(renderStats)
      ["catch"](function (e) {
        $("#usageBody").innerHTML = "";
        $("#usageErr").textContent = e.message || "불러오지 못했습니다.";
      });
  }

  // ---------- 초기화 ----------
  document.addEventListener("DOMContentLoaded", function () {
    sendHit();

    var link = $("#usageLink");
    if (link) {
      link.addEventListener("click", function (e) { e.preventDefault(); openPanel(); });
    }
    $("#usageClose").addEventListener("click", closePanel);
    $("#usageModal").addEventListener("click", function (e) {
      if (e.target.id === "usageModal") closePanel();
    });
    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape") closePanel();
    });
    $("#usageGo").addEventListener("click", loadStats);
    $("#usagePw").addEventListener("keydown", function (e) {
      if (e.key === "Enter") loadStats();
    });

    if (location.hash === "#usage") openPanel();
  });
})();
