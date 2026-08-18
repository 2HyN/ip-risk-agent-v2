# RAG Corpus

라이선스 의무사항 등 **참조 지식**만 둔다.

비공개 저장소 원문, Drive 문서, 로컬 프로젝트 소스는 넣지 않는다.
분석 대상과 참조 지식은 분리한다 (Blueprint 19).

## 구성

```
manifest.yaml    적재 대상과 체크섬
sources/         실제 자료
```

## 적재

```python
from ip_risk_agent.intelligence.rag.ingestion import ingest
```

`manifest.yaml` 의 `checksum` 이 파일 내용과 다르면 적재를 중단한다.
자료를 고치면 체크섬과 `corpus_version` 을 함께 올린다.

## 버전

`YYYY-MM-DD.N` 형식이며 분석 결과에 기록된다.
과거 판단이 어떤 지식에 근거했는지 되짚기 위한 것이다.
