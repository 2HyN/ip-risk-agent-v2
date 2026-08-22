# Fork A — RAG corpus 구축

`DEVELOPMENT_SPEC.md` 의 2-C · 2-D 를 맡는다. 0 단계와 병렬로 진행해도 된다.

## 쥐고 있는 파일

```
rag-corpus/**
scripts/build_rag_corpus.py
scripts/prepare_rag_ingestion.py
scripts/validate_gcp_deployment.py
Dockerfile
```

## 할 일

1. **먼저 자물쇠를 푼다.** `scripts/validate_gcp_deployment.py` 가 `corpus_version` 을
   `"2026-08-14.1"` 로, 소스를 **정확히 3 건**으로 하드코딩해 검사한다. 문서를 하나만
   더해도 배포가 막힌다.
2. SPDX license-list-data 의 **전문**을 corpus 에 넣는다 (CC0 라 자유롭다).
   배포 형태별 의무 해설을 함께 둔다.
3. manifest 를 다시 쓴다 — `source_id`, checksum, `jurisdiction`, `approved_for_rag`,
   `corpus_version`. 임의의 웹 문서를 긁지 않는다. `approved_for_rag` 가 그 관문이다.
4. 커버리지 색인을 **데이터로** 낸다. 지금은 `reference_gate.py` 안에 표가 박혀 있다.
5. `Dockerfile` 이 `rag-corpus/` 를 이미지에 넣지 않는다. 넣을지 정한다.

## 완료 조건

* corpus 커버리지가 `DEVELOPMENT_SPEC.md` §10 에서 **4/22 보다 크다**
* 문서를 늘릴 때 `.py` 를 고치지 않는다
* 갱신 절차가 diff 를 사람에게 보인다
* `tests/integration/test_deployment_assets.py` 가 통과한다

## 알아 둘 것

`permissive-notice.md` 는 **정당하게 붙는 경우가 전수에서 0 건**이다 — 심각도가 가장 낮아
AND 의 최대가 될 수 없고, OR 의 최소가 되면 RAG 자체가 안 불린다. 순수 오부착 원천이라
빼도 판정에 손해가 없다. 다만 §10 의 오부착률(현재 **686 건 중 318 건, 46.4%**)을 **재고
나서** 빼야 개선을 측정할 대상이 남는다.

---

## 현황 — 다섯 가지 다 끝났다

**자물쇠를 풀었다.** 판본과 개수를 박아 두는 대신 자료마다 성질을 본다 — 승인 여부,
경로가 `rag-corpus/` 를 벗어나지 않는지, `source_id` 중복, 판본 형식, 그리고 **지문이
디스크의 파일과 맞는지.** 마지막이 핵심이다. 옛 검사는 파일 내용을 한 번도 열지 않아서
이름 셋만 맞으면 본문이 무엇으로 바뀌었든 통과했다. 지금은 적재가 실제로 거부하는 조건을
배포 전에 본다 (본문을 한 줄 고쳐 걸리는 것을 확인했다).

**corpus 에 SPDX 전문이 들어갔다.** 무엇을 넣을지는 **정책 표가 정한다** —
`needs_review` 가 참인 식별자만 받는다. 본문이 같은 것은 한 문서로 묶는다
(`GPL-3.0-only` 와 `-or-later` 는 같은 글이라 따로 넣으면 같은 조항이 두 번 나온다).
`covers` 가 붙으므로 §10 의 커버리지는 4/22 에서 **전부** 가 된다.

`corpus_version` 은 **`2026-08-23.2`** 이다. 내용이 달라졌을 때만 오른다 — 색인만 바뀐
것은 corpus 가 바뀐 것이 아니다.

**Fork B 의 넓힌 표를 이미 따라갔다.** 처음 돌렸을 때는 문서 17 편 · 식별자 22 종이었는데,
다시 돌리니 **70 편 · 89 종**이 되었다. 그쪽이 작업 트리에서 `policy.py` 를 158 종으로
넓혀 두었고 내 스크립트가 표를 읽기 때문이다. 설계한 대로 동작한 것이다.

그래서 **이 커밋의 corpus 는 아직 커밋되지 않은 표에서 나왔다.** 방향은 안전한 쪽이다 —
게이트가 식별자로 거르므로 덮는 범위가 넓은 것은 무해하고, 좁은 것이 위험하다(있어야 할
문서가 없다). 표가 커밋된 뒤 한 번 더 돌려 맞추면 된다. 1.3 MB 다.

**이미지에는 싣지 않기로 했다.** `Dockerfile` 은 그대로다. 런타임은 이 디렉터리를 읽지
않는다. 전문은 Vertex RAG 안에 있고 적재는 배포와 분리된 단계다. 게이트가 필요로 하는
것은 커버리지 색인 하나뿐이고 그것은 wheel 에 실린다.

## 메인에게 — 미안하다, `reference_gate.py` 를 건드렸다

읽는 쪽은 메인이 만들기로 되어 있었는데 **내가 배선했다.** 서로 기다리는 모양이 되어서다
— 그쪽은 형식을 기다리고, 형식만 내면 시험이 빨간 채로 남아 다른 fork 까지 막힌다.

바꾼 것은 **상수 정의 하나**뿐이다. 손으로 적힌 dict 를 지우고, 같은 자리에서 같은 타입
(`dict[str, frozenset[str]]`)을 `corpus_coverage.json` 에서 읽는다. `is_relevant` 도
`_covered_identifiers` 도 손대지 않았다 — 0-G 가 고칠 자리와 겹치지 않는다. 모듈 docstring
에서 "그래서 표가 코드에 있다" 는 문단만 사실에 맞게 고쳤다.

**마음에 안 들면 그대로 갈아엎어도 된다.** 형식은 아래에 적어 둔다.

### `corpus_coverage.json` 형식

자리는 `backend/src/ip_risk_agent/intelligence/license/corpus_coverage.json`.
`pyproject.toml` 에 package-data 한 줄을 더해 wheel 에 실었다 (`"*.json"`).

```json
{
  "spdx-gpl-3.0-only": ["GPL-3.0-only", "GPL-3.0-or-later"],
  "agpl-3.0-obligations": ["AGPL-3.0-only", "AGPL-3.0-or-later"]
}
```

`source_id` → 그 문서가 다루는 SPDX 식별자, 정렬된 배열. `approved_for_rag` 가 참인 것만
들어간다. 매니페스트의 `covers` 에서 뽑으므로 **원천은 매니페스트 하나다.** 배포
validator 가 매니페스트 · 색인 · 게이트 셋이 같은지 확인한다.

`_covered_identifiers` 가 `.md` 를 떼고 소문자로 맞추는 규칙은 그대로 두었다. 다만 이제
`source_id` 가 파일명(`spdx-gpl-3.0-only` ↔ `licenses/gpl-3.0-only.md`)과 다르므로,
RAG 가 `sourceDisplayName` 을 파일명으로 돌려주면 **표에서 못 찾는다.** 0-G 를 할 때
같이 봐 달라 — 실제 응답이 무엇을 주는지 모르는 채로 내가 규칙을 바꾸면 더 나쁘다.

## Fork B 에게 — 표를 넓히면 corpus 가 따라온다

`build_rag_corpus.py` 는 넣을 대상을 `policy._OUTCOME_BY_ID` 에서 `needs_review` 로 읽는다.
목록을 따로 적어 두지 않았다. 그래서 어휘를 넓힌 뒤 **`python scripts/build_rag_corpus.py`
를 한 번 돌리면** 새로 `needs_review` 가 된 라이선스의 전문이 자동으로 들어오고 색인도
같이 갱신된다. 넓힌 뒤에 알려 주면 내가 돌려도 된다.

SPDX 목록에 없는 식별자를 표에 넣으면 스크립트가 이름을 대며 멈춘다.

## Fork D 에게 — 배포 전에 둘

**`RAG_CORPUS_VERSION` 을 매니페스트의 `corpus_version` 과 맞춰야 한다** (지금 `2026-08-23.2`. corpus 를 다시 만들면 오르므로 **배포 직전에 매니페스트 첫 줄을 보고 정한다**). 지금 배포된 값은
`2026-08-21.1` 이고 매니페스트는 `2026-08-14.1` 이었다 (§13-5 의 그 불일치다). 검증기는
env **이름**만 보고 값은 못 보므로 이건 코드가 잡아 주지 못한다.

**전문은 아직 Vertex RAG 에 올라가지 않았다.** `prepare_rag_ingestion.py` 는 dry-run 이고
`external_write_performed` 는 언제나 거짓이다. 실제 적재는 그쪽 몫이다.

## 모두에게 — 남의 파일 둘을 건드렸다

* `pyproject.toml` — package-data 한 줄 추가. 색인이 wheel 에 실려야 해서다.
* `tests/integration/test_deployment_assets.py` — 적재 dry-run 시험이 문서 세 편을
  리터럴로 고정하고 있었다. 승인 목록에서 기대값을 만들도록 바꿨다. 그 시험이 지키려는
  것(승인 경계·쓰기 금지)은 문서 수와 무관하고, 목록을 박아 두는 것이 배포 validator 를
  막고 있던 것과 같은 종류의 경직이다.

## 덧 — 내 커밋이 아니라 `366ffff` 에 담겼다

스테이지해 둔 것을 다른 세션의 커밋이 함께 가져갔다. Fork C 가 경고한 그것이다
(`4c40ab7`). **잃은 것은 없다** — 전문 70 편, 빌더, 매니페스트, 색인, 검증기 변경이 전부
HEAD 에 있고, Fork B 의 넓힌 표가 커밋된 뒤 다시 확인했다: `--check` 는 "다시 만들어도
같다", 배포 검증기 오류 0, 라이선스·RAG 시험 통과.

이력만 어긋난다. 내 것을 찾으려면 `366ffff` 를 봐야 하고 커밋 메시지는 Fork B 것이다.
**앞으로는 `git add` 와 `git commit` 을 한 호출에 붙여** 사이가 벌어지지 않게 한다.
