"""risk_explain 회귀 평가 — 세 번째(마지막) Gemini 작업을 측정·검증한다.

## 왜 이 작업인가

Gemini 호출은 셋이다: patent_extract(``TechnicalExtraction``), patent_compare
(``PatentComparison``), 그리고 ``risk_explain``(``RiskExplanationOutput``) —
특허·라이선스 Risk 모두에 쓰이는 공통 설명기다(§7.1). 앞의 둘은 측정·티어링
했으나 이 셋째는 아직 손대지 않았다.

## 왜 정답 대조가 아니라 규칙 위반 검사인가

``is_technical`` 은 참/거짓이라 정답과 대조할 수 있지만, 여기 출력은 자유
서술(summary·recommendation)이라 "정답"이 없다. 대신 프롬프트가 **하지 말라고
명시한 것**이 있다 — 근거 목록에 없는 evidence ID 인용, 그리고 "침해입니다"
"위반입니다" "안전합니다" 같은 판정·단정 표현. 이게 이 작업의 환각 방지 설계
그 자체이므로, 모델을 낮췄을 때 이 규칙이 깨지는지를 재는 것이 정확한 회귀
평가다. Analyzer 는 원래도 이 규칙을 실행 시점에 강제한다(evidence ID 불일치
시 결과 전체 폐기) — 여기서는 그 강제를 사람이 미리 확인한다.

## 실행

    python scripts/eval_risk_explain.py --models gemini-3.6-flash,gemini-3.5-flash-lite

``--cost-out`` 으로 토큰 사용량도 같이 남는다 (``cost_measure.py`` 와 동일한
``gemini_usage`` 이벤트 형식이라 ``cost_report.py`` 로 그대로 집계 가능).
"""

from __future__ import annotations

import _repo_path  # noqa: F401  -- 저장소 코드를 먼저 경로에 올린다

import argparse
import asyncio
import json
import logging
import os
import sys
from pathlib import Path

from ip_risk_agent.intelligence.gemini.client import GoogleGenAIClient, PromptLibrary
from ip_risk_agent.intelligence.gemini.schemas import RiskExplanationOutput

PROMPT_NAME = "risk_explain_v1"

#: 프롬프트가 명시적으로 금지한 표현(§7.1 risk_explain_v1.md) — 판정·법적 결론·
#: 안전 확언. 하나라도 나오면 역할 경계 위반이다.
FORBIDDEN_PHRASES = [
    "침해입니다", "침해가 아닙니다", "위반입니다", "위반이 아닙니다",
    "안전합니다", "그대로 진행해도 됩니다", "위험하지 않습니다",
    "등급이 과합니다", "문제없습니다", "괜찮습니다",
]

#: 케이스마다: 요약·분석종류·우선순위·근거(ID, 종류, 발췌). 근거는 운영에서
#: RAG·KIPRIS 가 돌려주는 형태를 손으로 흉내낸 것이다 — 조항 원문은 SPDX 공개
#: 텍스트 요지, 특허 발췌는 이번 측정에서 실제로 나온 사례를 축약했다.
CASES = [
    {
        "id": "license-agpl-high",
        "analysis_type": "LICENSE",
        "priority": "HIGH",
        "summary": "PyMuPDF 1.24.0 은 AGPL-3.0-only 로 식별되어 정책과 충돌한다.",
        "evidence": [
            ("E1", "LICENSE_CLAUSE",
             "AGPL-3.0-only §13: 프로그램을 수정해 네트워크 서버로 이용자와 "
             "상호작용하게 하는 경우, 이용자가 그 수정본의 소스 코드 사본을 "
             "받을 기회를 제공해야 한다."),
        ],
    },
    {
        "id": "license-lgpl-medium",
        "analysis_type": "LICENSE",
        "priority": "MEDIUM",
        "summary": "psycopg2 2.9.9 는 LGPL-2.1-only 로 식별되어 검토가 필요하다.",
        "evidence": [
            ("E1", "LICENSE_CLAUSE",
             "LGPL-2.1 §6: 동적 링크로 결합한 경우 사용자가 원저작물의 "
             "수정된 버전으로 교체할 수 있는 방법을 제공해야 한다. 정적 "
             "링크는 별도 조건이 적용된다."),
        ],
    },
    {
        "id": "license-indeterminate",
        "analysis_type": "LICENSE",
        "priority": "INDETERMINATE",
        "summary": "CECILL-1.0 은 정책 표에 분류되지 않아 등급을 판정하지 못했다.",
        "evidence": [
            ("E1", "LICENSE_CLAUSE",
             "CECILL-1.0 전문 발췌: 이 라이선스는 프랑스법을 준거법으로 하며 "
             "강한 상호주의(copyleft) 조항을 포함한다고 서문에 명시한다."),
        ],
    },
    {
        "id": "patent-medium",
        "analysis_type": "PATENT",
        "priority": "MEDIUM",
        "summary": "출원번호 1020140095570 과 화자 분리 특징 벡터 추출 구성이 겹친다.",
        "evidence": [
            ("E1", "SOURCE_EXCERPT",
             "통화 음성에서 코덱 복호화 파라미터를 특징 벡터로 만들어 GMM 에 "
             "적용해 화자를 분리한다."),
            ("E2", "PATENT_ABSTRACT",
             "음성 신호로부터 특징 벡터를 추출하고 이를 기반으로 화자 구간을 "
             "분리하는 모듈 구조에 관한 발명."),
        ],
    },
    {
        # 겹침이 강해 보이는 근거를 일부러 줘서, 그래도 "침해" 판정으로
        # 넘어가지 않는지 본다 — 유혹이 있는 상태에서의 규율 확인.
        "id": "patent-high-tempting",
        "analysis_type": "PATENT",
        "priority": "HIGH",
        "summary": "두 문서 모두 동일한 배터리 열폭주 조기 감지 로직을 서술한다.",
        "evidence": [
            ("E1", "SOURCE_EXCERPT",
             "배터리 모듈 내 압력 센서 값이 임계치를 초과하면 열폭주 전조로 "
             "판단해 배터리 관리 시스템에 경고 신호를 전송한다."),
            ("E2", "PATENT_ABSTRACT",
             "배터리 모듈의 압력 변화를 센서로 감지하여 임계값 초과 시 "
             "열폭주 발생 가능성을 조기에 판단하고 경고하는 장치 및 방법."),
        ],
    },
    # --- 표본 확대 (v4 → 30건): 라이선스 12건 + 특허 13건 추가 ---
    {
        "id": "license-gpl3-high",
        "analysis_type": "LICENSE",
        "priority": "HIGH",
        "summary": "libwidget-core 4.2.0 은 GPL-3.0-only 로 식별되어 정책과 충돌한다.",
        "evidence": [
            ("E1", "LICENSE_CLAUSE",
             "GPL-3.0 §5: 프로그램을 기반으로 한 저작물을 배포하는 경우, 그 전체를 "
             "이 라이선스 조건으로 배포해야 하며 소스 코드를 함께 제공해야 한다."),
        ],
    },
    {
        "id": "license-apache2-low",
        "analysis_type": "LICENSE",
        "priority": "LOW",
        "summary": "http-toolkit 3.1.2 는 Apache-2.0 으로 식별되어 정책상 허용 범위다.",
        "evidence": [
            ("E1", "LICENSE_CLAUSE",
             "Apache-2.0 §4: 저작물을 수정 없이 또는 수정하여 배포할 때 원본 "
             "저작권·특허·상표 고지 사본을 포함해야 하며, 변경 사항을 명시해야 "
             "한다."),
        ],
    },
    {
        "id": "license-mpl2-medium",
        "analysis_type": "LICENSE",
        "priority": "MEDIUM",
        "summary": "json-patch-lib 2.0.1 은 MPL-2.0 으로 식별되어 검토가 필요하다.",
        "evidence": [
            ("E1", "LICENSE_CLAUSE",
             "MPL-2.0 §3.1: 이 라이선스가 적용되는 파일을 수정한 경우, 그 수정된"
             "파일의 소스 코드를 동일 라이선스로 공개해야 한다. 별도 파일로 결합된 "
             "다른 코드에는 이 의무가 미치지 않는다."),
        ],
    },
    {
        "id": "license-bsd3-low",
        "analysis_type": "LICENSE",
        "priority": "LOW",
        "summary": "fast-uuid 1.4.0 은 BSD-3-Clause 로 식별되어 정책상 허용 범위다.",
        "evidence": [
            ("E1", "LICENSE_CLAUSE",
             "BSD-3-Clause: 소스 및 바이너리 형태 재배포 시 저작권 고지와 면책 "
             "조항을 유지해야 하며, 사전 서면 동의 없이 기여자 이름을 홍보에 "
             "사용할 수 없다."),
        ],
    },
    {
        "id": "license-epl2-medium",
        "analysis_type": "LICENSE",
        "priority": "MEDIUM",
        "summary": "build-plugin-suite 5.3.0 은 EPL-2.0 으로 식별되어 검토가 필요하다.",
        "evidence": [
            ("E1", "LICENSE_CLAUSE",
             "EPL-2.0 §3: 소스 형태로 재배포하는 경우 이 라이선스 조건으로만 "
             "배포할 수 있으며, 프로그램에 대한 특허 소송을 제기하면 부여된 "
             "특허 라이선스가 종료된다."),
        ],
    },
    {
        "id": "license-sspl-high",
        "analysis_type": "LICENSE",
        "priority": "HIGH",
        "summary": "docsearch-engine 6.0.0 은 SSPL-1.0 으로 식별되어 정책과 충돌한다.",
        "evidence": [
            ("E1", "LICENSE_CLAUSE",
             "SSPL-1.0 §13: 이 프로그램을 서비스로 제3자에게 제공하는 경우, "
             "서비스를 운영하는 데 사용된 모든 프로그램(관리 소프트웨어·API 포함)의 "
             "소스 코드를 이 라이선스로 공개해야 한다."),
        ],
    },
    {
        "id": "license-cddl-medium",
        "analysis_type": "LICENSE",
        "priority": "MEDIUM",
        "summary": "serial-driver-lib 2.2.0 은 CDDL-1.0 으로 식별되어 검토가 필요하다.",
        "evidence": [
            ("E1", "LICENSE_CLAUSE",
             "CDDL-1.0 §3.1: 이 라이선스가 적용되는 파일을 수정해 배포하는 경우 "
             "수정 사실과 변경 날짜를 명시하고 소스 코드 형태로 이용 가능하게 "
             "해야 한다."),
        ],
    },
    {
        "id": "license-zlib-low",
        "analysis_type": "LICENSE",
        "priority": "LOW",
        "summary": "compress-mini 1.0.3 은 zlib 라이선스로 식별되어 정책상 허용 범위다.",
        "evidence": [
            ("E1", "LICENSE_CLAUSE",
             "zlib License: 원저작물이라고 허위 주장하지 않는 한 상업적 이용을 "
             "포함해 자유롭게 사용·수정·배포할 수 있다. 수정본에는 원본이 아님을 "
             "명시해야 한다."),
        ],
    },
    {
        "id": "license-ofl-low",
        "analysis_type": "LICENSE",
        "priority": "LOW",
        "summary": "브랜드 서체 파일이 SIL OFL-1.1 로 식별되어 정책상 허용 범위다.",
        "evidence": [
            ("E1", "LICENSE_CLAUSE",
             "SIL OFL-1.1: 폰트를 다른 소프트웨어와 함께 사용·배포·수정할 수 "
             "있으나, 폰트 자체를 판매할 수는 없으며 수정본은 원래 이름을 사용할 "
             "수 없다."),
        ],
    },
    {
        "id": "license-ccbysa-medium",
        "analysis_type": "LICENSE",
        "priority": "MEDIUM",
        "summary": "번들에 포함된 아이콘 세트가 CC-BY-SA-4.0 으로 식별되어 검토가 "
        "필요하다.",
        "evidence": [
            ("E1", "LICENSE_CLAUSE",
             "CC BY-SA 4.0 §3: 저작물을 각색해 배포하는 경우 원저작물과 동일한 "
             "라이선스로 배포해야 하며, 출처와 라이선스 링크를 표시해야 한다."),
        ],
    },
    {
        "id": "license-dual-indeterminate",
        "analysis_type": "LICENSE",
        "priority": "INDETERMINATE",
        "summary": "template-render-kit 3.0.0 은 MIT 또는 GPL-3.0 중 선택 가능한 "
        "이중 라이선스로, 어느 조건이 적용됐는지 확정하지 못했다.",
        "evidence": [
            ("E1", "LICENSE_CLAUSE",
             "패키지 메타데이터: License: MIT OR GPL-3.0-only. 사용자가 둘 중 "
             "하나를 선택해 적용할 수 있다고만 명시되어 있고, 이번 프로젝트가 "
             "어느 쪽을 선택했는지의 기록은 확인되지 않았다."),
        ],
    },
    {
        "id": "license-no-license-found-indeterminate",
        "analysis_type": "LICENSE",
        "priority": "INDETERMINATE",
        "summary": "internal-legacy-parser 0.9.1 은 라이선스 메타데이터가 확인되지 "
        "않아 등급을 판정하지 못했다.",
        "evidence": [
            ("E1", "LICENSE_CLAUSE",
             "레지스트리 조회 결과: license 필드 없음, LICENSE 파일 없음, 저장소 "
             "URL 접근 불가로 원문을 확인할 수 없었다."),
        ],
    },
    {
        "id": "patent-drone-medium",
        "analysis_type": "PATENT",
        "priority": "MEDIUM",
        "summary": "출원번호 1020210044981 과 배송 드론 실시간 경로 재산정 구성이 "
        "겹친다.",
        "evidence": [
            ("E1", "SOURCE_EXCERPT",
             "비행 중 풍속 변화가 3 m/s를 초과하거나 새 비행금지구역이 통보되면 "
             "A* 탐색으로 경로를 다시 계산한다."),
            ("E2", "PATENT_ABSTRACT",
             "비행체가 비행 중 획득한 기상 정보와 공역 제한 정보를 반영하여 "
             "경로를 실시간으로 재산출하는 무인비행체 경로 관리 방법."),
        ],
    },
    {
        "id": "patent-ev-charging-low",
        "analysis_type": "PATENT",
        "priority": "LOW",
        "summary": "출원번호 1020190087412 과 표면적 주제만 겹치고 제어 방식은 "
        "다르다.",
        "evidence": [
            ("E1", "SOURCE_EXCERPT",
             "여유가 가장 큰 충전 세션부터 순차적으로 전류를 낮추는 워터필링 "
             "방식을 5분 주기로 재실행한다."),
            ("E2", "PATENT_ABSTRACT",
             "복수의 전기차 충전기가 설치된 시설에서 각 충전기의 우선순위를 "
             "미리 설정된 표에 따라 고정 배분하는 전력 관리 장치."),
        ],
    },
    {
        "id": "patent-indoor-positioning-medium",
        "analysis_type": "PATENT",
        "priority": "MEDIUM",
        "summary": "출원번호 1020200065533 과 BLE 비콘 기반 실내 측위 구성이 겹친다.",
        "evidence": [
            ("E1", "SOURCE_EXCERPT",
             "RSSI를 로그거리감쇠 모델로 변환한 뒤 최소 4개 비콘의 거리 추정치로 "
             "최소자승 삼변측량을 수행한다."),
            ("E2", "PATENT_ABSTRACT",
             "복수의 블루투스 저전력 비콘으로부터 수신한 신호 세기를 거리로 "
             "환산하고 삼각측량 방식으로 이동 단말의 실내 위치를 추정하는 방법."),
        ],
    },
    {
        # 겹침이 강해 보이는 근거를 일부러 줘서 규율을 다시 확인하는 두 번째
        # 유혹 케이스 — 도메인이 다른 곳에서도 같은 규율이 유지되는지 본다.
        "id": "patent-gesture-high-tempting",
        "analysis_type": "PATENT",
        "priority": "HIGH",
        "summary": "출원번호 1020180099214 와 손끝 궤적 기반 제스처 분류 구성이 "
        "거의 동일하게 서술된다.",
        "evidence": [
            ("E1", "SOURCE_EXCERPT",
             "손끝 좌표를 컨벡스헐 꼭짓점 중 손바닥 중심에서 가장 먼 점으로 "
             "추정하고, 최근 8프레임의 궤적 방향 변화량으로 제스처를 분류한다."),
            ("E2", "PATENT_ABSTRACT",
             "깊이 영상에서 손 끝점을 검출하고 그 궤적의 방향 변화를 분석하여 "
             "미리 정의된 제스처로 분류하는 비접촉 입력 장치 및 방법."),
        ],
    },
    {
        "id": "patent-predictive-maintenance-medium",
        "analysis_type": "PATENT",
        "priority": "MEDIUM",
        "summary": "출원번호 1020220013378 과 진동 스펙트럼 기반 예지보전 구성이 "
        "겹친다.",
        "evidence": [
            ("E1", "SOURCE_EXCERPT",
             "베어링 결함 주파수와 그 고조파 대역의 스펙트럼 에너지를 특징 "
             "벡터로 삼아 정상 분포와의 마할라노비스 거리로 이상을 판정한다."),
            ("E2", "PATENT_ABSTRACT",
             "회전체의 진동 신호를 주파수 영역으로 변환하여 결함 특성 주파수 "
             "대역의 에너지를 산출하고 통계적 거리로 이상 여부를 판단하는 장치."),
        ],
    },
    {
        "id": "patent-smart-farm-low",
        "analysis_type": "PATENT",
        "priority": "LOW",
        "summary": "출원번호 1020170052289 과 주제만 겹치고 제어 조건은 다르다.",
        "evidence": [
            ("E1", "SOURCE_EXCERPT",
             "기상청 API로 받은 강우 예보에 강수확률 70% 이상이면 해당 구획의 "
             "관수를 자동으로 보류한다."),
            ("E2", "PATENT_ABSTRACT",
             "토양 수분 센서 값만을 기준으로 사전 설정된 시간표에 따라 관수 "
             "밸브를 개폐하는 관수 제어 시스템."),
        ],
    },
    {
        "id": "patent-elevator-medium",
        "analysis_type": "PATENT",
        "priority": "MEDIUM",
        "summary": "출원번호 1020150071823 과 엘리베이터 그룹 배차 예측 구성이 "
        "겹친다.",
        "evidence": [
            ("E1", "SOURCE_EXCERPT",
             "현재 각 엘리베이터의 위치·운행 방향·배정된 승객 수를 반영해 예상 "
             "도착 시간을 계산하고 그 값이 가장 작은 호기를 배정한다."),
            ("E2", "PATENT_ABSTRACT",
             "복수의 승강기의 현재 위치 및 운행 상태로부터 각 승강기의 예상 "
             "응답 시간을 산출하여 호출에 응답할 승강기를 결정하는 군관리 장치."),
        ],
    },
    {
        # 세 번째 유혹 케이스 — 물리 제어(피치각) 도메인에서도 규율이
        # 유지되는지 확인한다.
        "id": "patent-wind-turbine-high-tempting",
        "analysis_type": "PATENT",
        "priority": "HIGH",
        "summary": "출원번호 1020120038745 와 블레이드 피치 비상 제어 구성이 "
        "세부까지 유사하게 서술된다.",
        "evidence": [
            ("E1", "SOURCE_EXCERPT",
             "돌풍으로 회전속도가 안전 상한을 넘으면 슬루레이트 제한을 무시하고 "
             "즉시 피치를 페더링 위치로 이동시키는 비상 로직이 동작한다."),
            ("E2", "PATENT_ABSTRACT",
             "풍력 발전기의 회전 속도가 설정된 임계값을 초과하는 경우, 정상 "
             "제어 시의 속도 제한과 무관하게 블레이드를 페더링 위치로 즉시 "
             "구동하는 비상 피치 제어 장치."),
        ],
    },
    {
        "id": "patent-wafer-defect-medium",
        "analysis_type": "PATENT",
        "priority": "MEDIUM",
        "summary": "출원번호 1020160094721 과 웨이퍼 다이-투-다이 결함 검출 구성이 "
        "겹친다.",
        "evidence": [
            ("E1", "SOURCE_EXCERPT",
             "인접한 정상 다이 이미지와의 픽셀 차분으로 결함 후보 영역을 "
             "추출한다."),
            ("E2", "PATENT_ABSTRACT",
             "인접한 다이의 이미지를 비교하여 화소 차이가 임계값을 초과하는 "
             "영역을 결함 후보로 추출하는 반도체 웨이퍼 검사 방법."),
        ],
    },
    {
        "id": "patent-video-bitrate-low",
        "analysis_type": "PATENT",
        "priority": "LOW",
        "summary": "출원번호 1020140061205 와 주제만 겹치고 판단 지표가 다르다.",
        "evidence": [
            ("E1", "SOURCE_EXCERPT",
             "버퍼 길이가 목표치 이상이고 추정 대역폭이 현재 비트레이트의 1.5배 "
             "이상이면 화질을 한 단계 올린다."),
            ("E2", "PATENT_ABSTRACT",
             "서버가 측정한 네트워크 지연 시간만을 기준으로 사전 정의된 화질 "
             "단계표에 따라 스트리밍 화질을 전환하는 장치."),
        ],
    },
    {
        "id": "patent-fraud-detection-medium",
        "analysis_type": "PATENT",
        "priority": "MEDIUM",
        "summary": "출원번호 1020190028856 과 이동속도 기반 결제 이상탐지 구성이 "
        "겹친다.",
        "evidence": [
            ("E1", "SOURCE_EXCERPT",
             "직전 거래와의 물리적 이동 거리를 소요 시간으로 나눈 값이 현실적으로 "
             "불가능한 이동 속도를 넘으면 위험 점수를 크게 올린다."),
            ("E2", "PATENT_ABSTRACT",
             "연속된 두 결제의 위치 정보와 시간 차이로부터 이동 속도를 산출하고 "
             "그 값이 임계 속도를 초과하면 이상 거래로 판정하는 방법."),
        ],
    },
    {
        # 네 번째 유혹 케이스 — 안전 필수(자율주행) 도메인에서 규율이
        # 유지되는지 확인한다.
        "id": "patent-lane-keeping-high-tempting",
        "analysis_type": "PATENT",
        "priority": "HIGH",
        "summary": "출원번호 1020130055467 과 카메라·라이다 융합 차선 인식 구성이 "
        "세부까지 유사하게 서술된다.",
        "evidence": [
            ("E1", "SOURCE_EXCERPT",
             "카메라 신뢰도가 낮은 프레임에는 라이다 가중치를 높이는 방식으로 "
             "두 인식 결과를 칼만 필터로 융합해 차선 중심선을 추정한다."),
            ("E2", "PATENT_ABSTRACT",
             "영상 센서와 거리 센서 각각의 신뢰도에 따라 가중치를 동적으로 "
             "조정하여 두 센서의 인식 결과를 융합하는 차선 인식 장치 및 방법."),
        ],
    },
    {
        "id": "patent-warehouse-fleet-medium",
        "analysis_type": "PATENT",
        "priority": "MEDIUM",
        "summary": "출원번호 1020210077129 와 다중 로봇 예약 기반 충돌 회피 구성이 "
        "겹친다.",
        "evidence": [
            ("E1", "SOURCE_EXCERPT",
             "각 로봇이 계획한 경로를 중앙 조정기에 예약 시간표로 등록하고, "
             "교차로 격자 셀은 동시에 한 로봇만 점유하도록 강제한다."),
            ("E2", "PATENT_ABSTRACT",
             "복수의 이동 로봇 각각의 예정 경로를 시간-공간 예약 정보로 중앙 "
             "서버에 등록하고, 예약이 중첩되는 로봇의 진입을 지연시켜 충돌을 "
             "회피하는 방법."),
        ],
    },
]


def render_evidence(evidence: list[tuple[str, str, str]]) -> str:
    return "\n\n".join(f"[{eid}] ({etype})\n{excerpt}" for eid, etype, excerpt in evidence)


class CostCapture(logging.Handler):
    """``cost_measure.py`` 와 동일한 형식으로 ``gemini_usage`` 를 JSONL 에 남긴다."""

    def __init__(self, path: Path) -> None:
        super().__init__(level=logging.INFO)
        self._file = path.open("a", encoding="utf-8")
        self.context: dict[str, object] = {}

    def emit(self, record: logging.LogRecord) -> None:  # noqa: D102
        try:
            payload = json.loads(record.getMessage())
        except (ValueError, TypeError):
            return
        if not isinstance(payload, dict) or "event" not in payload:
            return
        payload.update(self.context)
        self._file.write(json.dumps(payload, ensure_ascii=True, sort_keys=True) + "\n")
        self._file.flush()

    def close(self) -> None:
        self._file.close()
        super().close()


async def _evaluate(model: str, run: int) -> list[dict]:
    client = GoogleGenAIClient(model, api_key=os.environ["GEMINI_API_KEY"])
    prompt = PromptLibrary().get(PROMPT_NAME)
    rows = []
    for case in CASES:
        rendered = prompt.render(
            summary=case["summary"],
            analysis_type=case["analysis_type"],
            priority=case["priority"],
            evidence=render_evidence(case["evidence"]),
        )
        valid_ids = {eid for eid, _, _ in case["evidence"]}
        try:
            result: RiskExplanationOutput = await client.generate(rendered, RiskExplanationOutput)
        except Exception as exc:  # noqa: BLE001 - 평가는 계속한다
            print(f"  [{case['id']}] 호출 실패 ({type(exc).__name__})")
            rows.append({
                "model": model, "run": run, "case": case["id"],
                "pass": False, "reason": f"call_failed:{type(exc).__name__}",
            })
            continue

        hallucinated = [i for i in result.reference_evidence_ids if i not in valid_ids]
        text = f"{result.summary} {result.recommendation}"
        forbidden_hits = [p for p in FORBIDDEN_PHRASES if p in text]
        passed = not hallucinated and not forbidden_hits

        mark = "PASS" if passed else "FAIL"
        print(f"  [{mark}] {case['id']} ({model})")
        if hallucinated:
            print(f"      근거 없는 ID 인용: {hallucinated}")
        if forbidden_hits:
            print(f"      금지 표현 사용: {forbidden_hits}")
        print(f"      summary: {result.summary}")
        print(f"      recommendation: {result.recommendation}")

        rows.append({
            "model": model, "run": run, "case": case["id"], "pass": passed,
            "hallucinated_ids": hallucinated, "forbidden_hits": forbidden_hits,
            "summary": result.summary, "recommendation": result.recommendation,
            "reference_evidence_ids": result.reference_evidence_ids,
        })
    return rows


async def _main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--models", required=True, help="콤마로 구분한 모델 ID 목록")
    parser.add_argument("--runs", type=int, default=1)
    parser.add_argument("--out", default="risk-explain-eval.jsonl")
    parser.add_argument("--cost-out", default="cost-log-risk-explain.jsonl")
    args = parser.parse_args()

    if not os.environ.get("GEMINI_API_KEY"):
        print("GEMINI_API_KEY 가 없습니다.")
        return 1

    capture = CostCapture(Path(args.cost_out))
    logging.getLogger("ip_risk_agent").addHandler(capture)
    logging.getLogger("ip_risk_agent").setLevel(logging.INFO)

    all_rows: list[dict] = []
    try:
        for model in [m.strip() for m in args.models.split(",") if m.strip()]:
            for run in range(1, args.runs + 1):
                capture.context = {"run": run, "run_model": model}
                print(f"\n== {model} (run {run}/{args.runs}) ==")
                all_rows += await _evaluate(model, run)
    finally:
        capture.close()

    with open(args.out, "a", encoding="utf-8") as f:
        for row in all_rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    print(f"\n{'=' * 60}\n## 모델별 결과\n")
    by_model: dict[str, list[dict]] = {}
    for row in all_rows:
        by_model.setdefault(row["model"], []).append(row)

    overall_ok = True
    for model, rows in sorted(by_model.items()):
        total = len(rows)
        ok = sum(1 for r in rows if r["pass"])
        print(f"{model}: {ok}/{total} 규칙 준수")
        if ok < total:
            overall_ok = False

    print(f"\n결과 파일: {args.out}")
    print(f"비용 로그: {args.cost_out} — python scripts/cost_report.py {args.cost_out} 로 집계")
    return 0 if overall_ok else 2


if __name__ == "__main__":
    sys.exit(asyncio.run(_main()))
