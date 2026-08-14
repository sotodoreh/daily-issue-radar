# -*- coding: utf-8 -*-
"""
데일리 이슈 레이더 - 네이버 뉴스 여론 수집기

수집 소스:
  1. 댓글 많은 뉴스 랭킹 (news.naver.com/main/ranking/popularMemo.naver?date=YYYYMMDD)
  2. 많이 본 뉴스 랭킹   (news.naver.com/main/ranking/popularDay.naver?date=YYYYMMDD)
  3. 기사별 댓글 통계     (apis.naver.com commentBox — 댓글수 + 성별/연령 분포)

출력: data/YYYY-MM-DD.json, data/index.json

사용법:
  python scripts/collect.py                # 어제(KST) 하루치 수집 (기본)
  python scripts/collect.py --date 2026-08-13
  python scripts/collect.py --today        # 오늘(현재까지) 수집
"""
import argparse
import concurrent.futures
import datetime
import html as htmllib
import json
import os
import re
import sys
import unicodedata
import urllib.request

# 사내망 등 SSL 가로채기 환경 대응 (로컬 실행용; GitHub Actions에서는 불필요)
try:
    import truststore
    truststore.inject_into_ssl()
except ImportError:
    pass

KST = datetime.timezone(datetime.timedelta(hours=9))
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(ROOT, "data")

RANK_MEMO = "https://news.naver.com/main/ranking/popularMemo.naver?date={date}"
RANK_DAY = "https://news.naver.com/main/ranking/popularDay.naver?date={date}"
COMMENT_API = (
    "https://apis.naver.com/commentBox/cbox/web_naver_list_jsonp.json"
    "?ticket=news&templateId={tpl}&pool=cbox5&lang=ko&country=KR"
    "&objectId=news{oid}%2C{aid}&pageSize=1&indexSize=10&page=1"
    "&sort=favorite&initialize=true&_callback=cb"
)

MIN_COMMENTS_FOR_DEMO = 100   # 성별/연령 집계 최소 댓글수 (레퍼런스와 동일 기준)
MAX_ARTICLES = 160            # 댓글 통계를 조회할 최대 기사 수
TOPIC_COUNT = 10

STOPWORDS = {
    "단독", "속보", "영상", "포토", "종합", "인터뷰", "기자", "뉴스", "오늘",
    "어제", "내일", "이번", "지난", "관련", "논란의", "무슨", "왜", "어떻게",
    "그리고", "하지만", "돌연", "결국", "이후", "위해", "대해", "통해", "가장",
    "밝혀", "밝혔다", "말했다", "전했다", "이라고", "라고", "한다", "했다",
    "인가", "것인가", "무엇", "누가", "얼마나", "입력", "이렇게", "그렇게",
    "저렇게", "어쩌다", "이런", "그런", "저런", "다시", "계속", "아직",
    "벌써", "어디", "여기", "거기", "없다", "있다", "그날", "이유", "상황",
    "모습", "사실", "요즘", "당시", "먼저", "바로", "함께", "직접",
}
# 어절 끝 조사 제거용 (긴 것부터 시도)
PARTICLES = [
    "으로부터", "에서부터", "이라는", "라는", "에게서", "으로써", "으로서",
    "부터", "까지", "에서", "에게", "으로", "이라", "하고", "이며", "에도",
    "에는", "와의", "과의", "은", "는", "이", "가", "을", "를", "에", "의",
    "도", "만", "와", "과", "로", "요", "며",
]


def log(*args):
    print("[collect]", *args, flush=True)


def fetch(url, referer=None, timeout=20, binary=False):
    req = urllib.request.Request(url, headers={
        "User-Agent": UA,
        **({"Referer": referer} if referer else {}),
    })
    with urllib.request.urlopen(req, timeout=timeout) as r:
        body = r.read()
        if binary:
            return body
        ctype = (r.headers.get("Content-Type") or "").lower()
    for enc in (["euc-kr", "utf-8"] if "euc-kr" in ctype else ["utf-8", "euc-kr"]):
        try:
            return body.decode(enc)
        except UnicodeDecodeError:
            continue
    return body.decode("utf-8", errors="replace")


# ---------------------------------------------------------------- 랭킹 파싱

def parse_ranking(url):
    """언론사별 랭킹 박스를 파싱해 기사 목록을 돌려준다."""
    page = fetch(url)
    articles = []
    boxes = page.split('class="rankingnews_box"')[1:]
    for box in boxes:
        m = re.search(r'class="rankingnews_name">([^<]+)<', box)
        press = htmllib.unescape(m.group(1)).strip() if m else ""
        for item in re.finditer(
            r'<em class="list_ranking_num">(\d+).*?'
            r'href="https://n\.news\.naver\.com/article/(\d+)/(\d+)[^"]*"'
            r'[^>]*class="list_title[^>]*>(.*?)</a>',
            box, re.S,
        ):
            rank, oid, aid, raw_title = item.groups()
            title = htmllib.unescape(re.sub(r"<[^>]+>", "", raw_title)).strip()
            if not title:
                continue
            articles.append({
                "oid": oid, "aid": aid, "press": press,
                "rank": int(rank), "title": title,
                "url": f"https://n.news.naver.com/article/{oid}/{aid}",
            })
    return articles


# ---------------------------------------------------------------- 댓글 통계

def fetch_comment_stats(article):
    """기사 1건의 댓글수 + 성별/연령 분포를 조회한다."""
    oid, aid = article["oid"], article["aid"]
    referer = f"https://n.news.naver.com/article/comment/{oid}/{aid}"
    for tpl in ("view_politics", "default_society"):
        try:
            raw = fetch(COMMENT_API.format(tpl=tpl, oid=oid, aid=aid), referer=referer)
            m = re.search(r"cb\((.*)\)\s*;?\s*$", raw, re.S)
            if not m:
                continue
            data = json.loads(m.group(1))
            if not data.get("success"):
                continue
            res = data.get("result") or {}
            count = (res.get("count") or {}).get("comment") or 0
            out = {"comments": int(count)}
            graph = res.get("graph")
            if graph and graph.get("gender"):
                out["male"] = graph["gender"].get("male")
                out["female"] = graph["gender"].get("female")
                out["ages"] = {
                    str(o.get("age")): o.get("value", 0)
                    for o in (graph.get("old") or [])
                }
            return out
        except Exception as e:
            last = e
            continue
    return {"comments": 0, "error": True}


# ---------------------------------------------------------------- 키워드/주제

HANJA = str.maketrans("李尹韓美中日北檢靑與野軍前現故新",
                      "이윤한미중일북검청여야군전현고신")


def tokenize(title):
    """제목에서 핵심 토큰을 뽑는다 (형태소 분석기 없이 조사 제거 휴리스틱)."""
    title = unicodedata.normalize("NFKC", title).translate(HANJA)
    t = re.sub(r"\[[^\]]{1,12}\]", " ", title)          # [단독] [속보] 등 제거
    t = re.sub(r"[\"'‘’“”「」…]", " ", t)
    words = re.split(r"[^\w가-힣]+", t)
    tokens = []
    for w in words:
        if len(w) < 2:
            continue
        base = w
        for p in PARTICLES:
            if len(base) - len(p) >= 2 and base.endswith(p):
                base = base[: -len(p)]
                break
        if len(base) < 2 or base in STOPWORDS or base.isdigit():
            continue
        tokens.append(base)
    return tokens


def build_topics(articles, prev_topics):
    """댓글수 기반 탐욕적 키워드 클러스터링으로 주제 TOP N을 만든다."""
    kw_map = {}  # keyword -> set(article idx)
    for i, a in enumerate(articles):
        for tok in set(tokenize(a["title"])):
            kw_map.setdefault(tok, set()).add(i)
    kw_map = {k: v for k, v in kw_map.items() if len(v) >= 2}

    assigned = set()
    topics = []
    while len(topics) < TOPIC_COUNT:
        best_kw, best_score, best_set = None, 0, None
        for kw, idxs in kw_map.items():
            live = idxs - assigned
            if len(live) < 2:
                continue
            score = sum(articles[i]["comments"] for i in live)
            if score > best_score:
                best_kw, best_score, best_set = kw, score, live
        if not best_kw:
            break
        # 시드 키워드와 함께 등장한 연관 키워드 수집
        related = {}
        for kw, idxs in kw_map.items():
            if kw == best_kw:
                continue
            inter = len(idxs & best_set)
            if inter >= max(2, len(best_set) * 0.3):
                related[kw] = inter
        rel_sorted = [k for k, _ in sorted(related.items(), key=lambda x: -x[1])][:8]
        members = sorted(best_set, key=lambda i: -articles[i]["comments"])
        topic = {
            "label": best_kw,
            "keywords": [best_kw] + rel_sorted,
            "articles": members,
            "articleCount": len(members),
            "comments": best_score,
        }
        topics.append(topic)
        assigned |= best_set

    # 전일 대비 배지: 신규 탐지 / 포착(급등)
    prev_kw = []
    prev_comments = {}
    for pt in prev_topics or []:
        kws = set(pt.get("keywords") or [])
        prev_kw.append(kws)
        for k in kws:
            prev_comments[k] = max(prev_comments.get(k, 0), pt.get("comments", 0))
    for rank, t in enumerate(topics, 1):
        t["rank"] = rank
        tkws = set(t["keywords"][:4])
        overlap = any(len(tkws & pk) >= 1 for pk in prev_kw)
        if prev_topics is None:
            t["badge"] = None
        elif not overlap:
            t["badge"] = "new"          # 신규 탐지
        else:
            prev_max = max((prev_comments.get(k, 0) for k in tkws), default=0)
            t["badge"] = "surge" if prev_max and t["comments"] >= prev_max * 1.8 else None
    return topics


# ---------------------------------------------------------------- 브리핑 문장

def build_briefing(topics, articles, demo_articles):
    lines = []
    if topics:
        top = topics[0]
        kw = "·".join(top["keywords"][:3])
        lines.append(
            f"오늘 여론이 가장 집중된 주제는 「{top['label']}」입니다. "
            f"관련 기사 {top['articleCount']}건에 댓글 {top['comments']:,}개가 몰리며 "
            f"핵심 키워드로 {kw} 등이 함께 언급됐습니다."
        )
    if len(topics) >= 3:
        others = ", ".join(f"「{t['label']}」" for t in topics[1:4])
        lines.append(f"뒤이어 {others} 이슈가 상위권에서 여론 소비를 이끌었습니다.")
    if demo_articles:
        male_top = max(demo_articles, key=lambda a: a.get("male") or 0)
        female_top = max(demo_articles, key=lambda a: a.get("female") or 0)
        lines.append(
            f"성별로는 남성 비율이 가장 높았던 기사({male_top.get('male')}%)와 "
            f"여성 비율이 가장 높았던 기사({female_top.get('female')}%)의 주제가 뚜렷이 갈리며 "
            "관심사의 차이를 드러냈습니다."
        )
        newest = [a for a in demo_articles if a.get("ages")]
        if newest:
            young = max(newest, key=lambda a: (a["ages"].get("20", 0) + a["ages"].get("30", 0)))
            old = max(newest, key=lambda a: (a["ages"].get("50", 0) + a["ages"].get("60", 0)))
            lines.append(
                "세대별로는 20·30대와 50·60대가 각기 다른 기사에 집중하며 "
                "뉴스 소비 패턴의 다양성을 보였습니다."
            )
    total_c = sum(a["comments"] for a in articles)
    lines.append(
        f"집계 대상 기사 {len(articles)}건의 총 댓글은 {total_c:,}개입니다."
    )
    return lines


# ---------------------------------------------------------------- 메인

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", help="수집 대상 날짜 YYYY-MM-DD (기본: 어제 KST)")
    ap.add_argument("--today", action="store_true", help="오늘(현재까지) 랭킹 수집")
    args = ap.parse_args()

    now = datetime.datetime.now(KST)
    if args.date:
        target = datetime.date.fromisoformat(args.date)
    elif args.today:
        target = now.date()
    else:
        target = (now - datetime.timedelta(days=1)).date()
    dstr = target.strftime("%Y%m%d")
    diso = target.isoformat()
    log("target date:", diso)

    # 1) 랭킹 수집
    memo = parse_ranking(RANK_MEMO.format(date=dstr))
    day = parse_ranking(RANK_DAY.format(date=dstr))
    log(f"ranking: comment={len(memo)} viewed={len(day)}")
    if len(memo) < 10:
        log("ERROR: ranking parse too small; aborting")
        sys.exit(1)

    # 중복 제거 (댓글랭킹 우선)
    seen = {}
    for a in memo:
        key = (a["oid"], a["aid"])
        if key not in seen:
            a["sources"] = ["memo"]
            seen[key] = a
    for a in day:
        key = (a["oid"], a["aid"])
        if key in seen:
            if "day" not in seen[key]["sources"]:
                seen[key]["sources"].append("day")
            seen[key]["viewRank"] = a["rank"]
        else:
            a["sources"] = ["day"]
            a["viewRank"] = a["rank"]
            seen[key] = a
    articles = list(seen.values())[:MAX_ARTICLES * 2]

    # 2) 댓글 통계 (병렬)
    targets = articles[:MAX_ARTICLES] if len(articles) > MAX_ARTICLES else articles
    log(f"fetching comment stats for {len(targets)} articles ...")
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as ex:
        results = list(ex.map(fetch_comment_stats, targets))
    for a, r in zip(targets, results):
        a.update(r)
    for a in articles:
        a.setdefault("comments", 0)
    errors = sum(1 for a in articles if a.get("error"))
    log(f"comment stats done (errors: {errors})")

    articles.sort(key=lambda a: -a["comments"])

    # 3) 전일 데이터 로드 (배지 판단용)
    prev_path = os.path.join(
        DATA_DIR, (target - datetime.timedelta(days=1)).isoformat() + ".json")
    prev_topics = None
    if os.path.exists(prev_path):
        with open(prev_path, encoding="utf-8") as f:
            prev_topics = (json.load(f).get("topics")) or []

    # 4) 주제 클러스터링
    topics = build_topics(articles, prev_topics)
    log("topics:", [t["label"] for t in topics])

    # 5) 세대/성별 집계 대상
    demo_articles = [a for a in articles
                     if a["comments"] >= MIN_COMMENTS_FOR_DEMO and a.get("ages")]
    log(f"demographic articles: {len(demo_articles)}")

    # 6) 브리핑
    briefing = build_briefing(topics, articles, demo_articles)

    # 7) 저장 (기사 필드 정리)
    def slim(a):
        out = {
            "title": a["title"], "press": a["press"], "url": a["url"],
            "comments": a["comments"],
        }
        for k in ("male", "female", "ages", "viewRank"):
            if a.get(k) is not None:
                out[k] = a[k]
        return out

    keep = articles[:120]
    payload = {
        "date": diso,
        "weekday": "월화수목금토일"[target.weekday()],
        "collectedAt": now.strftime("%Y-%m-%d %H:%M") + " KST",
        "briefing": briefing,
        "topics": [
            {k: v for k, v in t.items() if k != "articles"} | {
                "topArticles": [slim(articles[i]) for i in t["articles"][:3]],
            } for t in topics
        ],
        "commentTop": [slim(a) for a in articles[:10]],
        "viewedTop": [slim(a) for a in sorted(
            [a for a in articles if a.get("viewRank")],
            key=lambda x: (x["viewRank"], -x["comments"]))[:10]],
        "articles": [slim(a) for a in keep],
        "meta": {
            "totalArticles": len(articles),
            "totalComments": sum(a["comments"] for a in articles),
            "demoArticles": len(demo_articles),
            "minCommentsForDemo": MIN_COMMENTS_FOR_DEMO,
        },
    }

    os.makedirs(DATA_DIR, exist_ok=True)
    out_path = os.path.join(DATA_DIR, diso + ".json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, separators=(",", ":"))
    log("saved", out_path, f"({os.path.getsize(out_path):,} bytes)")

    # index.json 갱신
    idx_path = os.path.join(DATA_DIR, "index.json")
    dates = sorted(
        fn[:-5] for fn in os.listdir(DATA_DIR)
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}\.json", fn)
    )
    with open(idx_path, "w", encoding="utf-8") as f:
        json.dump({"dates": dates, "latest": dates[-1] if dates else None},
                  f, ensure_ascii=False)
    log("index updated:", dates[-5:])


if __name__ == "__main__":
    main()
