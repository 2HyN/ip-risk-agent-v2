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

`intelligence/license/reference_gate.py` 는 **메인 세션 것**이다. 커버리지 색인은
데이터 파일로만 내고, 읽는 쪽은 메인이 만든다.

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

## 현황

<!-- 여기에 적는다 -->
