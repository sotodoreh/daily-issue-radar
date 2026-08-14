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
    "없는", "있는", "하는", "되는", "같은", "위한", "대한", "받은", "못한",
    "않은", "많은", "모든", "새로운", "가능", "확인", "공개", "발표",
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
    words = re.split(r"[^\w가-힣·]+", t)                 # '5·18' 같은 표기는 유지
    tokens = []
    for w in words:
        w = w.strip("·")
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


CATEGORIES = ["정치", "경제", "사회", "국제", "문화"]

CATEGORY_HINTS = {
    "정치": ["대통령", "의원", "국회", "민주당", "국힘", "여당", "야당", "전당대회",
             "경선", "당대표", "장관", "청와대", "정부", "개헌", "총선", "지지율",
             "탄핵", "특검", "검찰", "공천", "내각", "국정", "정치", "표결", "법안"],
    "경제": ["부동산", "집값", "공급", "대출", "전세", "종부세", "세금", "세제",
             "아파트", "금리", "주식", "증시", "코스피", "반도체", "기업", "성과급",
             "물가", "경제", "재정", "예산", "임금", "고용", "투자", "분양", "청약"],
    "사회": ["경찰", "수사", "사건", "사고", "재판", "구속", "학대", "노숙",
             "인권위", "성차별", "논란", "교육", "학교", "의료", "병원", "노동",
             "환경", "폭염", "화재", "범죄", "판결", "시민", "복지"],
    "국제": ["미국", "트럼프", "일본", "중국", "북한", "러시아", "우크라", "젤렌스키",
             "외교", "정상회담", "관세", "무역", "파병", "동맹", "국제", "해외",
             "백악관", "유엔", "태국", "베트남"],
    "문화": ["배우", "가수", "아이돌", "영화", "드라마", "예능", "방송", "연예",
             "스포츠", "축구", "야구", "선수", "감독", "월드컵", "공연", "K팝"],
}


def guess_category(text):
    """주제 텍스트에서 카테고리를 추정한다 (LLM 없을 때의 기본값)."""
    scores = {c: 0 for c in CATEGORIES}
    for cat, hints in CATEGORY_HINTS.items():
        for h in hints:
            if h in text:
                scores[cat] += 1
    best = max(scores.items(), key=lambda x: x[1])
    return best[0] if best[1] > 0 else "사회"


def topic_phrases(articles, members, seed):
    """주제 멤버 기사들에서 구(bigram) 단위 핵심 키워드를 뽑는다."""
    uni, bi = {}, {}
    for i in members:
        toks = tokenize(articles[i]["title"])
        for t in set(toks):
            uni[t] = uni.get(t, 0) + 1
        for a, b in set(zip(toks, toks[1:])):
            bi[(a, b)] = bi.get((a, b), 0) + 1
    phrases = []
    used = set()
    # 2개 이상 기사에서 반복된 bigram을 구로 채택
    for (a, b), c in sorted(bi.items(), key=lambda x: -x[1]):
        if c >= 2 and a != seed and b != seed:
            phrases.append(f"{a} {b}")
            used.update((a, b))
    # 나머지는 빈도 높은 단독 키워드로 보충
    for t, c in sorted(uni.items(), key=lambda x: -x[1]):
        if c >= 2 and t != seed and t not in used:
            phrases.append(t)
    return phrases


def build_topics(articles, prev_topics):
    """댓글수 기반 탐욕적 키워드 클러스터링으로 주제 TOP N을 만든다."""
    kw_map = {}  # keyword -> set(article idx)
    for i, a in enumerate(articles):
        for tok in set(tokenize(a["title"])):
            kw_map.setdefault(tok, set()).add(i)
    kw_map = {k: v for k, v in kw_map.items() if len(v) >= 2}

    assigned = set()
    topics = []
    while len(topics) < TOPIC_COUNT + 4:      # 병합 대비 여유분 추출
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
        topics.append({
            "seed": best_kw,
            "articles": set(best_set),
            "comments": best_score,
        })
        assigned |= best_set

    # 유사 주제 병합: 시드가 서로 포함 관계('대통령'/'이대통령')면 하나로 합침
    merged = []
    for t in topics:
        target = None
        for m in merged:
            a, b = t["seed"], m["seed"]
            if len(a) >= 3 and len(b) >= 3 and (a in b or b in a):
                target = m
                break
        if target:
            target["articles"] |= t["articles"]
            target["comments"] += t["comments"]
        else:
            merged.append(t)
    topics = sorted(merged, key=lambda t: -t["comments"])[:TOPIC_COUNT]

    # 라벨/키워드/카테고리 구성
    for t in topics:
        members = sorted(t["articles"], key=lambda i: -articles[i]["comments"])
        phrases = topic_phrases(articles, members, t["seed"])
        t["label"] = " · ".join([t["seed"]] + [p for p in phrases if " " not in p][:2])
        t["keywords"] = [t["seed"]] + phrases[:10]
        t["articles"] = members
        t["articleCount"] = len(members)
        t["category"] = guess_category(
            " ".join(articles[i]["title"] for i in members[:6]) + " " + " ".join(t["keywords"]))
        del t["seed"]

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


# ---------------------------------------------------------------- LLM 요약 (선택)

ENRICH_SCHEMA = {
    "type": "object",
    "properties": {
        "topics": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "rank": {"type": "integer"},
                    "name": {"type": "string"},
                    "category": {"type": "string",
                                 "enum": ["정치", "경제", "사회", "국제", "문화"]},
                    "keywords": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["rank", "name", "category", "keywords"],
                "additionalProperties": False,
            },
        },
        "briefing": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["topics", "briefing"],
    "additionalProperties": False,
}

ENRICH_PROMPT = """당신은 국회의원실 보좌진을 위한 여론 브리핑 분석가입니다.
아래는 {date} 하루 동안 네이버 뉴스에서 여론(댓글)이 집중된 기사들을 키워드 기준으로 묶은 것입니다.
기사 제목들을 읽고 실제 내용과 맥락을 파악해, 각 주제에 대해 다음을 작성하세요.

1. name: 맥락이 한눈에 잡히는 주제명 (예: "캄보디아 관련 사건/사고", "부동산 공급 대책", "이재명 대통령 지지율/정국").
   같은 인물·사안이 여러 주제로 쪼개져 있으면 이름으로 구분되게 하되, 원래 rank는 유지하세요.
2. category: 정치 / 경제 / 사회 / 국제 / 문화 중 하나.
   - 정치: 대통령·국회·정당·선거·검찰개혁 등 국내 정치 권력 관련
   - 경제: 부동산·세제·금융·기업·산업·물가·고용
   - 사회: 사건사고·수사·재판·인권·교육·의료·노동·젠더
   - 국제: 외교·안보·해외 동향·한미/한일/한중/남북 관계
   - 문화: 연예·스포츠·방송·공연
   경계가 애매하면 그 주제에 대한 여론의 관심이 어디에 쏠려 있는지를 기준으로 고르세요
   (예: 부동산 정책을 둘러싼 여야 공방이 핵심이면 정치, 정책 내용·시장 영향이 핵심이면 경제).
3. keywords: 그 주제의 핵심 쟁점을 담은 구(phrase) 단위 키워드 8~14개
   (예: "한국인 납치·사망", "피싱조직", "대사관 신고 무용지물"). 기사 제목에 실제로 근거한 내용만.

그리고 briefing: 오늘 여론 지형을 요약하는 4~6문장. 첫 문장은 가장 큰 이슈와 그 함의,
이후 상위권 이슈 흐름, 세대·성별 반응 특징(자료가 있으면) 순으로. 담백한 보고서 문체(~습니다체).

집계 자료:
{digest}
"""


def enrich_with_llm(payload):
    """ANTHROPIC_API_KEY가 설정돼 있으면 Claude로 주제명·키워드·브리핑을 의미 단위로 재작성한다."""
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return False
    try:
        import anthropic
    except ImportError:
        log("anthropic SDK 미설치 — LLM 요약 건너뜀 (pip install anthropic)")
        return False

    lines = []
    for t in payload["topics"]:
        lines.append(f"\n[주제 {t['rank']}] 키워드: {', '.join(t['keywords'][:8])} "
                     f"(기사 {t['articleCount']}건, 댓글 {t['comments']:,}개)")
        for a in t["topArticles"]:
            lines.append(f"  - {a['title']} ({a['press']}, 댓글 {a['comments']:,})")
    lines.append("\n[댓글 TOP 10]")
    for a in payload["commentTop"]:
        demo = ""
        if a.get("male") is not None:
            top_age = max(a.get("ages", {}).items(), key=lambda x: x[1], default=None)
            demo = f" / 남 {a['male']}%·여 {a['female']}%" + (
                f", 최다 {top_age[0]}대 {top_age[1]}%" if top_age else "")
        lines.append(f"  - {a['title']} ({a['press']}, 댓글 {a['comments']:,}{demo})")

    try:
        client = anthropic.Anthropic()
        response = client.messages.create(
            model="claude-opus-5",
            max_tokens=8000,
            output_config={"format": {"type": "json_schema", "schema": ENRICH_SCHEMA}},
            messages=[{
                "role": "user",
                "content": ENRICH_PROMPT.format(
                    date=payload["date"], digest="\n".join(lines)),
            }],
        )
        if response.stop_reason == "refusal":
            log("LLM 요약 거절됨 — 휴리스틱 결과 유지")
            return False
        text = next(b.text for b in response.content if b.type == "text")
        data = json.loads(text)
    except Exception as e:
        log("LLM 요약 실패 — 휴리스틱 결과 유지:", repr(e))
        return False

    by_rank = {t["rank"]: t for t in data.get("topics", [])}
    for t in payload["topics"]:
        e = by_rank.get(t["rank"])
        if e and e.get("name"):
            t["label"] = e["name"]
            if e.get("keywords"):
                t["keywords"] = e["keywords"][:14]
            if e.get("category") in CATEGORIES:
                t["category"] = e["category"]
    if data.get("briefing"):
        payload["briefing"] = data["briefing"]
    payload["enriched"] = True
    log("LLM 요약 적용 완료")
    return True


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

    # 8) LLM 의미 분석 (API 키 있을 때만; 실패해도 휴리스틱 결과로 진행)
    enrich_with_llm(payload)

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
