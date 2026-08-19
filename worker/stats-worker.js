/**
 * 데일리 이슈 레이더 — 사용량 집계 서버 (Cloudflare Worker)
 *
 * 하는 일 두 가지뿐입니다.
 *   POST /hit    : 방문 1건 기록 (기기별 무작위 번호 기준)
 *   GET  /stats  : 집계 결과 반환 (비밀번호 필요)
 *
 * 저장 방식: KV에 `d:{날짜}:{기기번호}` = 그날 그 기기의 방문 횟수
 *   - 같은 날짜 키 개수 = 그날 사용자 수
 *   - 값을 더하면 = 방문 횟수
 * 개인을 식별할 수 있는 정보(IP·이름 등)는 저장하지 않습니다.
 */

// 이 주소에서 오는 요청만 허용 (도메인 추가 시 여기에 한 줄 추가)
const ALLOWED_ORIGINS = [
  "https://sotodoreh.github.io",
  "http://localhost:8642",
];

const RETAIN_DAYS = 400;             // 기록 보관 기간
const CHART_DAYS = 30;               // 그래프에 표시할 일수
const KST_OFFSET = 9 * 60 * 60 * 1000;

const todayKST = () => new Date(Date.now() + KST_OFFSET).toISOString().slice(0, 10);

const shiftDay = (isoDate, delta) =>
  new Date(Date.parse(isoDate) + delta * 86400000).toISOString().slice(0, 10);

function corsHeaders(origin) {
  const allow = ALLOWED_ORIGINS.includes(origin) ? origin : ALLOWED_ORIGINS[0];
  return {
    "Access-Control-Allow-Origin": allow,
    "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type",
    "Access-Control-Max-Age": "86400",
    "Cache-Control": "no-store",
  };
}

const json = (body, headers, status = 200) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { ...headers, "Content-Type": "application/json; charset=utf-8" },
  });

/** KV의 모든 기기 키를 나열한다 (d:날짜:기기번호) */
async function listDeviceKeys(kv) {
  const names = [];
  let cursor;
  do {
    const res = await kv.list({ prefix: "d:", cursor, limit: 1000 });
    res.keys.forEach((k) => names.push(k.name));
    cursor = res.list_complete ? null : res.cursor;
  } while (cursor);
  return names;
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const headers = corsHeaders(request.headers.get("Origin") || "");

    if (request.method === "OPTIONS") return new Response(null, { headers });

    // ---------------------------------------------------- 방문 기록
    if (url.pathname === "/hit" && request.method === "POST") {
      let did = "";
      try {
        const body = await request.json();
        did = String(body.did || "").replace(/[^a-zA-Z0-9]/g, "").slice(0, 32);
      } catch (_) { /* 잘못된 본문은 무시 */ }
      if (!did) return json({ ok: false }, headers, 400);

      const key = `d:${todayKST()}:${did}`;
      const prev = parseInt((await env.STATS.get(key)) || "0", 10) || 0;
      await env.STATS.put(key, String(prev + 1), {
        expirationTtl: RETAIN_DAYS * 86400,
      });
      return json({ ok: true }, headers);
    }

    // ---------------------------------------------------- 집계 조회
    if (url.pathname === "/stats") {
      const given = url.searchParams.get("key") || "";
      // 비밀번호는 이 서버의 환경변수에만 있고, 웹사이트 코드에는 없습니다.
      if (!env.STATS_PASSWORD || given !== env.STATS_PASSWORD) {
        return json({ error: "unauthorized" }, headers, 401);
      }

      const names = await listDeviceKeys(env.STATS);
      const values = await Promise.all(names.map((n) => env.STATS.get(n)));

      const usersByDay = {};   // 날짜 -> Set(기기번호)
      const visitsByDay = {};  // 날짜 -> 방문 횟수
      let totalVisits = 0;

      names.forEach((name, i) => {
        const [, day, did] = name.split(":");
        if (!day || !did) return;
        (usersByDay[day] = usersByDay[day] || new Set()).add(did);
        const n = parseInt(values[i] || "0", 10) || 0;
        visitsByDay[day] = (visitsByDay[day] || 0) + n;
        totalVisits += n;
      });

      const today = todayKST();
      const uniqueSince = (days) => {
        const from = shiftDay(today, -(days - 1));
        const s = new Set();
        Object.keys(usersByDay)
          .filter((d) => d >= from && d <= today)
          .forEach((d) => usersByDay[d].forEach((x) => s.add(x)));
        return s.size;
      };

      // 그래프용: 최근 CHART_DAYS일을 빈 날짜까지 포함해 채운다
      const series = [];
      for (let i = CHART_DAYS - 1; i >= 0; i--) {
        const d = shiftDay(today, -i);
        series.push({
          date: d,
          users: usersByDay[d] ? usersByDay[d].size : 0,
          visits: visitsByDay[d] || 0,
        });
      }

      const activeDays = Object.keys(usersByDay).length;
      const allDevices = new Set();
      Object.values(usersByDay).forEach((s) => s.forEach((x) => allDevices.add(x)));

      return json({
        today: usersByDay[today] ? usersByDay[today].size : 0,
        todayVisits: visitsByDay[today] || 0,
        week: uniqueSince(7),
        month: uniqueSince(30),
        totalDevices: allDevices.size,
        totalVisits,
        activeDays,
        since: Object.keys(usersByDay).sort()[0] || null,
        series,
      }, headers);
    }

    return new Response("daily-issue-radar stats", { headers });
  },
};
