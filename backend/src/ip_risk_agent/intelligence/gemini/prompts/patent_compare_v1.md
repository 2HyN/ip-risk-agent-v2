---
prompt_id: patent_compare
version: v1
---

문서와 선행 특허를 대조해 겹치는 기술 구성을 찾는다.

## 하지 않는 것

침해 여부, 권리 범위, 법적 결론을 판단하지 않는다.
그것은 사람이 판단할 영역이며, 이 결과는 검토가 필요한 지점을 좁히는 데만 쓴다.

## matched_elements

문서와 특허 양쪽에 같은 기술 구성이 나타날 때만 적는다.

- `source_segment_id` 는 입력 segment 목록에 있는 ID 여야 한다
- `patent_evidence_id` 는 제시된 특허 근거 목록에 있는 ID 여야 한다
- 목록에 없는 ID 를 만들면 결과 전체가 폐기된다
- `explanation` 은 어느 구성이 어떻게 겹치는지를 한두 문장으로 적는다

같은 분야라는 이유만으로 겹친다고 적지 않는다. 처리 방식이 같아야 한다.

## distinct_elements

문서에만 있고 특허에는 없는 구성을 적는다.
겹치는 부분만 보면 사람이 판단할 수 없다. 다른 점도 함께 있어야 한다.

## uncertainty_flags

판단이 어려웠던 이유를 적는다. 예: 초록만 제공되어 청구항을 확인할 수 없음.

## 입력

문서 segment

```
{segments}
```

특허 근거

```
{patent_evidence}
```
