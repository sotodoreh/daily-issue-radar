# 데일리 이슈 레이더 📡

> **오늘, 여론은 어디를 향했나** — 네이버 뉴스 여론 집중도 데일리 브리핑

특정 키워드를 등록해 감시하는 방식이 아니라, **전체 여론이 실제로 향한 곳**을 매일 포착하는
대시보드입니다. 국회의원실 등에서 광범위한 이슈 동향을 빠르게 파악하는 용도로 만들어졌습니다.

## 무엇을 보여주나

| 탭 | 내용 |
|---|---|
| **대문** | 데일리 브리핑(자동 생성), 핵심 지표, 주제별 분류 TOP 10 (+«포착»/«신규 탐지» 배지) |
| **메인 이슈** | 댓글 TOP 10 (성별 반응·최다 연령 포함), 많이 본 뉴스 |
| **연령 · 성별** | 연령(20~60대+) × 성별 칩을 조합해 해당 집단의 관심 기사 탐색 |

날짜 네비게이션으로 과거 아카이브를 자유롭게 이동할 수 있습니다.

## 데이터 출처와 방법론

- **네이버 뉴스 랭킹**: '댓글 많은 뉴스' + '많이 본 뉴스' 언론사별 랭킹 (일자별)
- **댓글 통계**: 네이버 뉴스 댓글 API — 기사별 댓글 수, 작성자 성별·연령대 분포
- 성별·연령 집계는 **댓글 100개 이상** 기사만 대상 (네이버 공개 기준과 동일)
- 주제 분류는 기사 제목 키워드 동시출현 기반 자동 클러스터링 (형태소 분석기 없이 조사 제거 휴리스틱)
- «포착» = 전일 대비 댓글 1.8배 이상 급등 주제, «신규 탐지» = 전일에 없던 신규 주제
- 조회수 절대치는 네이버가 공개하지 않아 랭킹 순위만 반영

## 구조

```
daily-issue-radar/
├── index.html              # 대시보드 (정적, GitHub Pages)
├── assets/style.css
├── assets/app.js
├── data/
│   ├── index.json          # 날짜 목록
│   └── YYYY-MM-DD.json     # 일자별 수집 데이터 (아카이브)
├── scripts/collect.py      # 수집기 (Python 표준 라이브러리만 사용)
└── .github/workflows/collect.yml  # 매일 08:10 KST 자동 수집
```

## 수동 수집

```bash
python scripts/collect.py                  # 어제(KST) 하루치
python scripts/collect.py --date 2026-08-13
python scripts/collect.py --today          # 오늘(현재까지)
```

의존성 없음 (Python 3.9+). 사내망 등 SSL 가로채기 환경에서는 `pip install truststore` 권장.

## 배포 (GitHub Pages)

1. GitHub에 새 저장소 생성 후 푸시
2. **Settings → Pages** → Source: `Deploy from a branch`, Branch: `main` / `/ (root)`
3. **Settings → Actions → General** → Workflow permissions: `Read and write permissions` 체크
4. 매일 아침 8시 10분(KST)에 자동으로 전일 데이터가 수집·커밋됩니다
   (Actions 탭에서 `daily-collect` → `Run workflow`로 수동 실행도 가능)

## 주의

- 네이버 비공식 엔드포인트를 사용하므로 네이버 개편 시 수집기 수정이 필요할 수 있습니다
- 수집 데이터는 공개 통계이며, 개인 댓글 내용은 수집하지 않습니다
