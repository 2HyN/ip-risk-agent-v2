# RAG Corpus

라이선스 의무사항 등 **참조 지식**만 둔다.

비공개 저장소 원문, Drive 문서, 로컬 프로젝트 소스는 넣지 않는다.
분석 대상과 참조 지식은 분리한다 (Blueprint 19).

## 구성

```
manifest.yaml    적재 대상과 체크섬
licenses/        SPDX 라이선스 **전문**. 스크립트가 받아 쓴다 — 손대지 않는다
sources/         손으로 쓴 배포 형태별 의무 해설
```

두 종류를 나누는 이유가 있다. 파이프라인 3 단계는 식별자로 하는 **조회**이고 4 단계가 그
전문 안에서 조항을 찾는다 (`docs/DEVELOPMENT_SPEC.md` §5.1). 조회 대상은 라이선스 본문
이어야 하고, 해설은 그것과 성질이 다르다.

## 다시 만들기

```
python scripts/build_rag_corpus.py          # 받아서 매니페스트까지 다시 쓴다
python scripts/build_rag_corpus.py --check  # 달라지는지만 본다 (CI 용)
```

전문은 SPDX license-list-data 에서 받는다. CC0 라 자유롭게 쓸 수 있다. 무엇을 받을지는
**정책 표가 정한다** — `needs_review` 가 참인 식별자만 넣는다. 나머지는 표가 이미 결론을
내므로 RAG 를 부르지 않고, 넣어 봤자 오부착 원천만 늘린다 (§5.5).

본문이 같은 식별자는 한 문서로 묶는다. `GPL-3.0-only` 와 `GPL-3.0-or-later` 는 같은 글이라
따로 넣으면 4 단계 검색이 같은 조항을 두 번 돌려준다.

**손으로 만들지 않는 이유** — 다음 사람이 같은 corpus 를 다시 만들 수 없으면
`rag_corpus_version` 이 내용을 설명하지 못한다. 판정이 왜 달라졌는지 되짚는 §7.4 의
전제가 거기서 무너진다.

## 커버리지 색인

매니페스트의 `covers` 가 "이 문서가 어느 라이선스를 다루는가" 의 유일한 원천이다.
같은 스크립트가 그것을 뽑아
`backend/src/ip_risk_agent/intelligence/license/corpus_coverage.json` 으로 내고, 참조
게이트가 그 파일을 읽는다. **표를 코드에 손으로 적지 않는다** — 문서를 늘릴 때마다 코드를
고쳐야 했고, 둘이 어긋나면 게이트가 조용히 잘못 판정한다.

## 이미지에는 싣지 않는다 [결정]

`Dockerfile` 은 `rag-corpus/` 를 복사하지 않는다. 그대로 둔다.

런타임은 이 디렉터리를 읽지 않는다. 전문은 Vertex RAG 안에 있고, 적재는 배포와 분리된
별도 단계다. 게이트가 필요로 하는 것은 커버리지 색인 하나뿐이고 그것은 wheel 에 실린다
(`pyproject.toml` 의 package-data). 전문까지 이미지에 넣으면 쓰지도 않는 것을 리비전마다
나른다.

## 적재

```python
from ip_risk_agent.intelligence.rag.ingestion import ingest
```

`manifest.yaml` 의 `checksum` 이 파일 내용과 다르면 적재를 중단한다. 지문은 본문을
`strip()` 한 뒤의 sha256 이다 — 배포 validator 도 같은 규칙으로 본다. 두 규칙이 어긋나면
배포는 통과하는데 적재가 거부한다.

자료를 고치면 체크섬과 `corpus_version` 을 함께 올린다. 스크립트로 만든 것은 스크립트가
둘 다 해 준다.

## 버전

`YYYY-MM-DD.N` 형식이며 분석 결과에 기록된다.
과거 판단이 어떤 지식에 근거했는지 되짚기 위한 것이다.

## Phase 6 ingestion dry-run

외부 corpus에 쓰기 전에 repository root에서 다음 명령을 실행한다.

```powershell
.\.venv\Scripts\python.exe scripts/prepare_rag_ingestion.py
```

이 명령은 manifest에 승인된 경로만 읽고 checksum과 corpus version을 검증한다.
출력의 `external_write_performed`는 항상 `false`이며, 실제 RAG corpus upload와
resource ID 확정은 GCP 외부 작업에서 별도 승인 후 수행한다.
