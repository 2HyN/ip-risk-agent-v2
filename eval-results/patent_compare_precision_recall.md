# PatentComparison 재현율·정밀도 검증

## 대상
- Positive: KIPO 거절결정문에서 심사관이 신규성(특허법 제29조제1항)으로 확정한
  청구항-인용특허 쌍 157개 (samples/patent/verification_pairs_157.csv)
- Negative: 같은 출원에 실제로 인용되지 않은 특허를 무작위로 짝지은 142개
  (samples/patent/negative_pairs.csv, scripts/build_negative_pairs.py로 생성)

## 결과

|            | 모델: 겹침(positive) | 모델: 안겹침(negative) |
|---|---|---|
| 실제: 겹침   | TP 145 | FN 12 |
| 실제: 안겹침 | FP 48  | TN 94 |

- 재현율 = TP/(TP+FN) = 145/157 = 92.4%
- 오탐율 = FP/(FP+TN) = 48/142 = 33.8%
- 정밀도 = TP/(TP+FP) = 145/193 = 75.1%

## 한계
negative 쌍은 심사관이 "안 겹친다"고 확정한 게 아니라, 해당 출원에 인용되지
않았다는 사실만으로 안 겹칠 것이라 가정한 약한(weak) negative임. 대상 특허들이
동일 기술분야로 편중되어 있으면 정밀도/오탐율 수치가 실제보다 나쁘게 나올 수 있음.

## 산출 파일
- samples/patent/negative_pairs.csv
- eval-results/patent_compare_false_positive.csv
- scripts/build_negative_pairs.py
