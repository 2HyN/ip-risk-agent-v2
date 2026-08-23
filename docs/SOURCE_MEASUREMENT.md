# 소스 실측 — 초기 스캔 비용과 변경 피드

`docs/DEVELOPMENT_SPEC.md` §11 의 **1-B · 1-A** 산출물이다. §11.5 가 이 둘의 완료 조건을
"답이 붙는 것 자체가 산출물" 로 두었으므로 결과를 여기에 남긴다.

| | 상태 |
|---|---|
| **1-B 초기 스캔 비용** | **끝났다.** §1 |
| **1-A 변경 피드** | **사람의 동작 둘을 기다린다.** §2 |

§1 을 재다가 나온 것이 하나 더 있다 — **비용을 막는 세 수단이 서로 다른 매처를 쓰고, 그중
둘은 잘못 쓰면 조용히 아무것도 거르지 않는다** (§1.4). 수치보다 이쪽이 중요할 수 있다.

---

## 1. 초기 스캔이 KIPRIS 를 얼마나 쓰는가 [1-B]

### 1.1 재는 방법 — 부르지 않고 센다

한도가 월 1,000 회인데 재보려고 한 번 마운트하면 그것으로 한도가 날아간다. 그래서
**호출하지 않고 센다.** 커넥터·분석기와 같은 규칙을 코드에서 그대로 불러 쓴다.

| 무엇 | 어디서 | 값 |
|---|---|---|
| 파일당 검색 상한 | `intelligence/patent/extraction.py:18` | `MAX_QUERIES = 5` |
| 파일당 상세 상한 | `intelligence/patent/candidate_rank.py:17` | `DEFAULT_CANDIDATE_CAP = 6` |
| 특허 경로 판정 | `connectors/github/adapter.py:259-275` | `dependency_format()` 이 `None` 이고 확장자가 코드/문서 |
| 코드 확장자 | 같은 파일 `:49` | `.py .js .ts .java .go .c .h .cpp .rs` |
| 문서 확장자 | 같은 파일 `:50` | `.md .txt .rst` |

**파일 하나가 쓰는 KIPRIS 는 최대 11 회다** (검색 5 + 상세 6). Gemini 추출 1 회는 별도이고
KIPRIS 한도와 무관하다.

### 1.2 이 저장소를 붙이면

| | 전체 파일 | 특허 경로 | KIPRIS 최대 | 월 한도 대비 |
|---|---|---|---|---|
| **GitHub 마운트** | 513 | 417 (코드 385 · 문서 32) | **4,587 회** | **4.6 배** |
| **Local 마운트** | 30,295 | **20,764** (코드 19,302 · 문서 1,462) | **228,404 회** | **228 배** |

**두 수가 이렇게 벌어지는 것이 이 실측의 첫 결론이다.** GitHub 은 추적 파일만 보므로
`.gitignore` 가 이미 걸러 준다. **Local 은 디스크에 있는 것을 본다** — `node_modules`,
`.venv`, `.pytest-tmp`, `dist` 가 전부 들어온다. 같은 디렉터리인데 소모가 **50 배** 차이난다.

폴더 마운트를 여는 것은 Local 쪽 문을 여는 일이므로, §9.1 이 "폴더 마운트를 열기 전에
최소 하나를 채운다" 고 한 것은 정확히 이 수 때문이다.

### 1.3 제외 목록으로 얼마나 줄어드는가

아래는 §1.4 에서 **실제 매처로 검증한 형식**을 적용한 결과다.

| 제외 | GitHub | Local |
|---|---|---|
| 없음 | 4,587 (4.6 배) | 228,404 (228 배) |
| **빌드 산출물·의존물** | 4,587 (4.6 배) | **4,829 (4.8 배)** |
| **빌드 + 소스 코드** | **352 (0.4 배)** | **561 (0.6 배)** |

**빌드 산출물 제외가 Local 의 구멍을 통째로 닫는다.** 228 배 → 4.8 배로, GitHub 과 같은
자리로 내려온다. 이것 없이 폴더 마운트를 여는 것은 한 번의 마운트로 한도를 200 배 넘기는
일이다. **다른 어떤 비용 항목보다 먼저다.**

**그것만으로는 한도 안에 못 들어온다.** 4.8 배가 남고, 그 비용의 대부분이 소스 코드다 —
남은 439 개 중 코드가 388, 문서가 51 이다. 코드를 빼면 **0.6 배**로, 한도 안에 들어오는
유일한 조합이다.

### 1.4 [중요] 세 수단이 서로 다른 매처를 쓴다

§9.1 은 비용을 막는 수단을 셋으로 적었다. **셋이 같은 문법을 쓰지 않는다.**

| 수단 | 구현 | 패턴이 틀리면 |
|---|---|---|
| source `.ipriskignore` | `connectors/common/ipriskignore.py` — `fnmatch(path, pattern)` 한 줄 | **조용히 아무것도 거르지 않는다** |
| workspace `global_ignore_text` | `application/security_gate/ignore.py` — 정규식 `fullmatch`, **선행 `/` 필수** | `IgnorePolicyError` → `POLICY_INVALID` 로 거부 |
| tracking scope `exclude_patterns` | `connectors/github/tracking_scope.py:26` — `fnmatch` | 조용히 거르지 않는다 |

같은 뜻을 적으려면 형식이 이렇게 갈린다. `/backend/node_modules/a/b.js` 를 기준으로
실측한 결과다.

| 쓴 것 | `.ipriskignore` | workspace |
|---|---|---|
| `node_modules` | **거르지 않음** | `IgnorePolicyError` |
| `node_modules/` | 거르지 않음 | 뿌리만 (`**` 가 자동으로 붙는다) |
| `**/node_modules/**` | 거르지 않음 | `IgnorePolicyError` (선행 `/` 없음) |
| `*node_modules/*` | **거른다** | `IgnorePolicyError` |
| `/**/node_modules/**` | 거르지 않음 | **거른다** |

**두 곳 모두에서 동작하는 패턴 문자열이 하나도 없다.** 그리고 사용자가 가장 자연스럽게
적을 `node_modules` 는 `.ipriskignore` 에서 **오류도 없이 0 개를 거른다** — 20,764 개가
그대로 남고 청구서로 돌아온다. workspace 쪽은 적어도 거부로 실패가 보인다.

실측 — 이 저장소 뿌리에서:

```
python - <<'EOF'
import sys; sys.path.insert(0,'backend/src'); sys.path.insert(0,'shared/contracts/python')
from ip_risk_agent.connectors.common.ipriskignore import is_denied_by_ipriskignore as src
from ip_risk_agent.application.security_gate.ignore import is_ignored as ws, parse_ipriskignore as wsp
p = "/backend/node_modules/a/b.js"
for pat in ["node_modules", "*node_modules/*", "/**/node_modules/**"]:
    try: w = ws(p, wsp(pat))
    except Exception as e: w = type(e).__name__
    print("%-24s source=%-5s workspace=%s" % (pat, src(p[1:], [pat]), w))
EOF
```

### 1.5 그래서 쓸 수 있는 기본 제외 목록

아래 둘은 **실제 매처로 검증했고 같은 집합을 거른다** (20,764 → 439).

**source `.ipriskignore` · tracking scope `exclude_patterns`** — 뿌리와 하위를 따로 적어야 한다.

```
node_modules/*      */node_modules/*
.venv/*             */.venv/*
venv/*              */venv/*
env/*               */env/*
dist/*              */dist/*
build/*             */build/*
out/*               */out/*
vendor/*            */vendor/*
target/*            */target/*
.next/*             */.next/*
coverage/*          */coverage/*
__pycache__/*       */__pycache__/*
.pytest-tmp/*       */.pytest-tmp/*
.tox/*              */.tox/*
.mypy_cache/*       */.mypy_cache/*
.ruff_cache/*       */.ruff_cache/*
site-packages/*     */site-packages/*
.gradle/*           */.gradle/*
.idea/*             */.idea/*
.cache/*            */.cache/*
*.egg-info/*        */*.egg-info/*
```

**workspace `global_ignore_text`** — 선행 `/` 와 `**` 를 쓴다.

```
/**/node_modules/**    /**/.venv/**        /**/venv/**        /**/env/**
/**/dist/**            /**/build/**        /**/out/**         /**/vendor/**
/**/target/**          /**/.next/**        /**/coverage/**    /**/__pycache__/**
/**/.pytest-tmp/**     /**/.tox/**         /**/.mypy_cache/** /**/.ruff_cache/**
/**/site-packages/**   /**/.gradle/**      /**/.idea/**       /**/.cache/**
/**/*.egg-info/**
```

`.pytest-tmp` 와 `*.egg-info` 는 이 저장소에서 실제로 걸린 것이라 넣었다.

### 1.6 판단이 필요한 것 — 비용이 아니라 제품 정의다

빌드 산출물을 다 빼고도 **남은 비용의 88% 가 소스 코드다** (439 중 388). 그런데 소스 코드를
특허 경로에 넣는 근거가 명세에 없다. §1.2 (B) 는 이 제품의 차별점을 이렇게 적는다 —
"도입 결정은 매니페스트보다 먼저 **기획 문서**에 나타난다. SCA 는 매니페스트에서 시작하므로
원리적으로 못 본다."

그 논거는 문서를 가리키지 코드를 가리키지 않는다. **코드를 기본에서 빼면 한도 안에 들어오고
(0.6 배), 빼지 않으면 어떤 조합으로도 한도를 넘는다.**

권하는 것 — 소스 코드는 **사용자가 켜는 선택**으로 두고, 켤 때 한도를 넘는다는 것을 그
자리에서 알린다. 기본값으로 켜 두면 첫 마운트에서 한도가 사라지고, 그 뒤의 모든 분석이
"KIPRIS 한도 초과" 로 실패한다.

### 1.7 이 수를 어떻게 읽어야 하나

**11 회는 상한이지 평균이 아니다.** 셋이 실제 값을 낮춘다.

* 모델이 `is_technical=false` 로 보면 **SKIPPED** 이고 KIPRIS 를 한 번도 쓰지 않는다.
  점검 저장소에서 `README.md` 가 그랬다.
* 검색이 0 건을 내면 상세 조회가 따라 붙지 않는다.
* 후보가 6 개 미만이면 상세도 그만큼만 부른다.

그래도 상한으로 판단해야 한다. **한도는 한 번의 마운트로 넘길 수 있고, 넘고 나서 알면
늦다.** 코드 파일은 문서와 달리 대부분 "기술적" 으로 읽힐 것이므로 코드 쪽 상한은 실제에
가깝다.

**남은 미측정** — SKIPPED 비율은 실제로 돌려야 나온다. 위 제외 목록을 넣은 뒤 작은 저장소
하나로 재는 것이 §10 의 "초기 스캔 KIPRIS" 칸을 채우는 마지막 조각이다.

---

## 2. 서비스 계정의 변경 피드가 무엇을 주는가 [1-A]

**아직 재지 못했다.** 사람의 동작 둘이 필요하다.

### 2.1 왜 이것이 설계 규모를 정하는가

D1 이 Drive 를 **서비스 계정 + 폴더 공유**로 바꾼다. 그러면 이탈·재진입을 무엇으로 아는가가
남는다. 확인할 것은 셋이다 (§6.1).

1. 폴더에 파일을 새로 넣으면 SA 의 `changes` 에 잡히는가
2. 폴더 밖으로 옮기면 `removed` 로 오는가
3. 되돌리면 다시 나타나는가

**셋 다 잡히면** 이탈·재진입이 이미 있는 DELETE / UPDATE 경로로 들어오고 폴더 대조 작업이
필요 없다. **안 잡히면** 주기적 대조를 새로 만들어야 한다. 1-D 와 1-F 의 크기가 여기서
갈린다.

**v1 의 동작을 근거로 삼으면 안 된다.** v1 의 폴더 펼침은 연결 시점의 스냅샷이라 이후 들어온
파일은 추적되지 않았고(`ea70787`), 스코프를 넓힌 이유(`f50a15b`)도 펼치기가 409 로 실패해서
였지 지속 추적 때문이 아니다.

### 2.1.1 실측 결과 (2026-08-23) — **셋 다 예**

버리는 서비스 계정(`iprisk-v2-drive-probe`, **프로젝트 역할 0**)에 폴더를 뷰어로 공유하고
잰 값이다. 운영 신원은 건드리지 않았다.

| # | 물음 | 답 | 피드가 준 것 |
|---|---|---|---|
| 1 | 폴더에 새 파일을 넣으면 잡히는가 | **예** | `removed=False`, `parents=[폴더]` |
| 2 | 폴더 밖으로 옮기면 `removed` 로 오는가 | **예** | `removed=True`, `file` 자체가 `None` |
| 3 | 되돌리면 다시 나타나는가 | **예** | `removed=False`, `parents=[폴더]` |

**2 번이 예상보다 강하게 나왔다.** 파일이 폴더를 벗어나자 `parents` 만 바뀐 것이 아니라
**SA 에게서 파일이 통째로 사라졌다** — `name` 도 `parents` 도 오지 않는다. SA 의 접근이
오직 폴더 공유에서만 오기 때문이고, 벗어나는 순간 접근이 끊긴다.

그래서 **이탈과 삭제가 피드에서 같은 모양**이다. "이 파일이 아직 우리 폴더 안인가" 를
변경마다 따질 필요가 없다.

**귀결 — 폴더 대조 작업이 필요 없다.** 이탈은 기존 DELETE 경로가, 재진입은 기존 UPDATE
경로가 그대로 받는다. 1-D 와 1-F 가 그만큼 작아진다.

**D1 도 함께 확인됐다.** 프로젝트 IAM 역할이 **0** 인 서비스 계정이 공유받은 폴더와 그
안의 문서를 읽었다. "Drive 접근은 IAM 이 아니라 폴더 공유에서 온다" 가 참이고, 도메인
전체 위임은 필요 없다.

**주의 — 접근이 곧 가시성이다.** 폴더 공유를 풀면 그 안의 모든 파일이 한꺼번에
`removed` 로 온다. 삭제와 구별되지 않으므로, 그것을 "사용자가 전부 지웠다" 로 읽으면
Risk 가 통째로 해소된다. 마운트가 살아 있는지를 **따로** 봐야 한다 (1-D).

### 2.2 막혀 있던 것 둘 — 풀렸다

**(가) 폴더를 서비스 계정에 공유해야 한다.**

```
iprisk-v2-worker@proj-aj22-211200020328.iam.gserviceaccount.com
```

Drive 에서 시험용 폴더를 하나 만들고 이 주소를 **뷰어**로 공유한다. 서비스 계정도 사람과
같은 방식으로 공유받는다 — 도메인 전체 위임은 필요 없고, 그것이 D1 이 "봉쇄가 Google 에
남는다" 고 말하는 이유다.

**(나) 가장 권한.** 사람 계정이 `roles/owner` 를 가져도 `iam.serviceAccounts.getAccessToken`
이 없다 — Google 이 Owner 에서 일부러 뺐다. 프로젝트 소유만으로 아무 서비스 계정이나 될
수 있으면 SA 로 권한을 나눈 의미가 없어지기 때문이다.

**운영 신원에 가장 권한을 주지 않고 풀었다.** 권한 0 인 버리는 SA 를 만들고 **그 SA
하나에만** `roles/iam.serviceAccountTokenCreator` 를 붙였다. D1 의 핵심이 "접근은 공유에서
온다" 이므로 권한이 없어도 답은 똑같이 나오고, 오히려 그 전제를 함께 확인하게 된다.

### 2.3 준비해 둔 탐침

자격증명을 파일로 두지 않는다. 호출마다 `gcloud` 가장으로 토큰을 받고 범위는
`drive.readonly` 하나다.

```
python drive_feed_probe.py check    가장이 되는지, 폴더가 보이는지
python drive_feed_probe.py start    지금의 페이지 토큰을 기록한다
python drive_feed_probe.py poll     기록한 토큰 이후의 변경을 보여준다
```

`start` → 사람이 동작 하나 → `poll` 을 세 번 반복한다. `poll` 이 매번 다음 토큰을
기록하므로 세 물음이 서로 섞이지 않는다. 각 변경에 `removed` · `trashed` · `parents` 를
함께 찍어, **폴더 밖으로 나간 것이 `removed` 로 오는지, 아니면 `parents` 만 바뀐 채
평범한 변경으로 오는지**를 구별한다. 둘은 우리 쪽 처리가 전혀 다르다.

`PROBE_FOLDER_ID` 를 주면 각 변경이 그 폴더 안인지 밖인지도 함께 표시한다.

탐침은 저장소에 넣지 않았다 — 한 번 쓰는 측정 도구이고, 결과가 나오면 이 문서가 답을
들고 있으면 된다.
