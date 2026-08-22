"""전역 라이선스 정책.

정책은 법적 결론이 아니라 **검토 분류**다 (Agent 3 Spec 28). 조직마다 기준이 다르므로
어느 조직에도 맞는 하나의 답은 없다. 여기가 정하는 것은 "사람이 봐야 하는가, 얼마나
급한가" 뿐이다.

판정은 전적으로 결정론적이다. 모델이 이 결과를 바꾸지 못한다.

## 어휘와 판단을 나눈다

:mod:`.spdx` 는 SPDX 식별자 **전부**를 안다 (727 개). 여기 표는 그중 **분류한 것만**
담는다. 둘을 같게 맞추지 않는다 — 727 개를 전부 분류하면 근거 없는 단정을 700 개쯤
만들게 된다.

표에 없는 식별자는 :data:`LicensePolicyOutcome.UNKNOWN` 이고, 그것은 "위험하다" 가 아니라
**"우리가 아직 분류하지 않았으니 사람이 보라"** 는 뜻이다. `needs_review` 가 참이므로
조용히 통과하지 않는다.

## 기준

비공개 상용 배포를 가정한다. 이 가정이 바뀌면 분류도 바뀌므로, 워크스페이스별 배포 형태를
받는 것이 다음 단계다 (`DEVELOPMENT_SPEC.md` §5.10).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from iprisk_contracts.common import LicensePolicyOutcome

from .spdx import (
    UNKNOWN_LICENSE,
    AndNode,
    ExpressionNode,
    LicenseNode,
    OrNode,
    canonicalize_exception,
    parse_expression,
)

# 정책 표나 SPDX 스냅샷을 바꾸면 반드시 올린다. 과거 판정을 설명하는 근거가 된다.
POLICY_VERSION = "global-license-policy-2026-08-23.1"

# 심각도 순서. 값이 클수록 검토 부담이 크다.
_SEVERITY: dict[LicensePolicyOutcome, int] = {
    LicensePolicyOutcome.NO_ACTION: 0,
    LicensePolicyOutcome.NOTICE_REQUIRED: 1,
    LicensePolicyOutcome.UNKNOWN: 2,
    LicensePolicyOutcome.REVIEW_REQUIRED: 3,
    LicensePolicyOutcome.POLICY_CONFLICT: 4,
}


# --------------------------------------------------------------- 라이선스 분류
#
# 분류마다 **근거를 함께 적는다.** 근거 없는 분류는 나중에 되짚을 수 없고, 되짚을 수 없는
# 분류는 §1.3 이 경고한 "틀린 판정이 기록으로 굳는" 바로 그것이 된다.

_POLICY: tuple[tuple[LicensePolicyOutcome, str, tuple[str, ...]], ...] = (
    (
        LicensePolicyOutcome.POLICY_CONFLICT,
        "강한 copyleft — 결합 저작물 전체의 소스 공개를 요구한다",
        (
            "GPL-1.0-only", "GPL-1.0-or-later",
            "GPL-2.0-only", "GPL-2.0-or-later",
            "GPL-3.0-only", "GPL-3.0-or-later",
            "CECILL-2.0", "CECILL-2.1",
            "OSL-1.0", "OSL-1.1", "OSL-2.0", "OSL-2.1", "OSL-3.0",
            "EUPL-1.0", "EUPL-1.1", "EUPL-1.2",
            "Sleepycat", "NPOSL-3.0",
            # GPL 을 그대로 쓰거나 단순화한 것
            "NGPL", "SimPL-2.0",
            # 상호주의가 결합물 전체에 미친다
            "LiLiQ-Rplus-1.1",
            # 하드웨어 설계의 강한 상호주의. 설계를 쓴 제품에까지 미친다
            "CERN-OHL-S-2.0",
        ),
    ),
    (
        LicensePolicyOutcome.POLICY_CONFLICT,
        "네트워크 너머 이용까지 배포로 본다 — SaaS 로 감출 수 없다",
        (
            "AGPL-1.0-only", "AGPL-1.0-or-later",
            "AGPL-3.0-only", "AGPL-3.0-or-later",
            "SSPL-1.0", "RPL-1.1", "RPL-1.5",
            # 네트워크 이용자에게 소스를 제공해야 한다
            "CPAL-1.0", "RPSL-1.0",
            # 이용자에게 데이터와 소스를 함께 제공할 의무가 있다
            "CAL-1.0",
        ),
    ),
    (
        LicensePolicyOutcome.POLICY_CONFLICT,
        "이용 자체를 제한한다 — 상업적 또는 운영 환경 사용이 막힌다",
        (
            "BUSL-1.1", "Elastic-2.0",
            "PolyForm-Noncommercial-1.0.0", "PolyForm-Small-Business-1.0.0",
            "CC-BY-NC-1.0", "CC-BY-NC-2.0", "CC-BY-NC-2.5", "CC-BY-NC-3.0", "CC-BY-NC-4.0",
            "CC-BY-NC-SA-1.0", "CC-BY-NC-SA-2.0", "CC-BY-NC-SA-2.5",
            "CC-BY-NC-SA-3.0", "CC-BY-NC-SA-4.0",
            "CC-BY-NC-ND-3.0", "CC-BY-NC-ND-4.0",
            "CC-BY-ND-3.0", "CC-BY-ND-4.0",
        ),
    ),
    (
        LicensePolicyOutcome.REVIEW_REQUIRED,
        "약한 copyleft — 결합 방식(정적·동적)과 수정 여부에 따라 의무가 갈린다",
        (
            "LGPL-2.0-only", "LGPL-2.0-or-later",
            "LGPL-2.1-only", "LGPL-2.1-or-later",
            "LGPL-3.0-only", "LGPL-3.0-or-later",
            "MPL-1.0", "MPL-1.1", "MPL-2.0", "MPL-2.0-no-copyleft-exception",
            "EPL-1.0", "EPL-2.0",
            "CDDL-1.0", "CDDL-1.1",
            "CPL-1.0", "IPL-1.0", "APSL-2.0", "SISSL",
            "CECILL-C", "MS-RL",
            # APSL 계열 — 파일 단위 copyleft
            "APSL-1.0", "APSL-1.1", "APSL-1.2",
            # MPL 을 바탕으로 만든 회사별 판본
            "SPL-1.0", "CUA-OPL-1.0", "Motosoto", "Nokia", "OSET-PL-2.1",
            # 그 밖의 상호주의 — 수정한 파일의 소스를 내놓아야 한다
            "CATOSL-1.1", "LPL-1.0", "LPL-1.02", "RSCPL", "APL-1.0",
            "LiLiQ-R-1.1",
            # 하드웨어 설계의 약한 상호주의. 설계 자체에만 미친다
            "CERN-OHL-W-2.0",
            # CAL 의 결합 저작물 예외판 — 결합은 풀리지만 데이터 제공 의무는 남는다
            "CAL-1.0-Combined-Work-Exception",
        ),
    ),
    (
        LicensePolicyOutcome.REVIEW_REQUIRED,
        "share-alike — 파생물에 같은 조건을 요구한다. 무엇이 파생물인지가 갈린다",
        (
            "CC-BY-SA-1.0", "CC-BY-SA-2.0", "CC-BY-SA-2.5", "CC-BY-SA-3.0", "CC-BY-SA-4.0",
            "ODbL-1.0",
            "GFDL-1.1-only", "GFDL-1.1-or-later",
            "GFDL-1.2-only", "GFDL-1.2-or-later",
            "GFDL-1.3-only", "GFDL-1.3-or-later",
            "OFL-1.0", "OFL-1.1", "OFL-1.1-RFN", "OFL-1.1-no-RFN",
        ),
    ),
    (
        LicensePolicyOutcome.REVIEW_REQUIRED,
        "용도나 배포 형태에 조건이 붙어 있어 문면만으로 끝나지 않는다",
        (
            "JSON", "QPL-1.0", "Artistic-1.0", "Artistic-1.0-Perl", "Artistic-1.0-cl8",
            "SGI-B-1.1",
            # 배포하면 수정본의 소스를 공개해야 한다
            "Watcom-1.0",
        ),
    ),
    (
        LicensePolicyOutcome.REVIEW_REQUIRED,
        "파생물에 이름 변경이나 별도 표시를 요구한다 — 우리가 고쳐 쓰면 걸린다",
        ("LPPL-1.3c", "LPPL-1.3a", "IPA", "OGTSL"),
    ),
    (
        LicensePolicyOutcome.NOTICE_REQUIRED,
        "고지와 라이선스 사본 첨부로 충족된다",
        (
            "MIT", "MIT-CMU", "MIT-Modern-Variant", "MIT-advertising", "MIT-feh",
            "MIT-open-group", "X11", "X11-distribute-modifications-variant",
            "BSD-1-Clause", "BSD-2-Clause", "BSD-2-Clause-Views",
            "BSD-3-Clause", "BSD-3-Clause-Clear", "BSD-4-Clause", "BSD-4-Clause-UC",
            "BSD-Source-Code",
            "Apache-1.0", "Apache-1.1", "Apache-2.0",
            "ISC", "Zlib", "zlib-acknowledgement", "Libpng", "libpng-2.0",
            "NCSA", "PostgreSQL", "Python-2.0", "Python-2.0.1", "PSF-2.0",
            "AFL-1.1", "AFL-1.2", "AFL-2.0", "AFL-2.1", "AFL-3.0",
            "Artistic-2.0", "BSL-1.0", "ZPL-2.0", "ZPL-2.1",
            "MS-PL", "W3C", "W3C-19980720", "W3C-20150513",
            "CC-BY-1.0", "CC-BY-2.0", "CC-BY-2.5", "CC-BY-3.0", "CC-BY-4.0",
            "curl", "Vim", "Ruby", "PHP-3.0", "PHP-3.01", "TCL", "UPL-1.0",
            "HPND", "HPND-sell-variant", "ICU", "Unicode-DFS-2016",
            "FTL", "IJG", "SMLNJ", "bzip2-1.0.6", "Xnet", "OpenSSL",
            # OSI 승인 permissive — BSD·MIT 계열이거나 그와 같은 무게다
            "AAL", "BSD-2-Clause-Patent", "BSD-3-Clause-LBNL",
            "BSD-3-Clause-Open-MPI", "BlueOak-1.0.0", "CNRI-Python",
            "ECL-1.0", "ECL-2.0", "EFL-1.0", "EFL-2.0", "EUDatagrid", "Entessa",
            "Fair", "Intel", "Jam", "LiLiQ-P-1.1", "MirOS", "MulanPSL-2.0",
            "Multics", "NASA-1.3", "NTP", "Naumen", "OLDAP-2.8", "Unicode-3.0",
            "VSL-1.0", "WordNet",
            # 하드웨어 설계의 permissive 판
            "CERN-OHL-P-2.0",
            # SPDX 가 폐기했으나 대체 식별자를 주지 않은 것
            "Net-SNMP", "Nunit",
            # 목록 밖이지만 패키지 메타데이터에 자주 보이는 permissive
            "libtiff", "Info-ZIP", "SGI-B-2.0", "Spencer-99", "NAIST-2003",
            "mpich2", "Adobe-Glyph", "Bitstream-Vera",
        ),
    ),
    (
        LicensePolicyOutcome.NO_ACTION,
        "고지 의무도 없다 — 사실상 퍼블릭 도메인이다",
        (
            "0BSD", "CC0-1.0", "Unlicense", "WTFPL", "MIT-0",
            "blessing", "NIST-PD", "PDDL-1.0", "CC-PDDC", "SAX-PD",
            # 고지조차 요구하지 않는다
            "Beerware", "Zed",
        ),
    ),
)

_OUTCOME_BY_ID: dict[str, LicensePolicyOutcome] = {
    identifier: outcome
    for outcome, _reason, identifiers in _POLICY
    for identifier in identifiers
}

_REASON_BY_ID: dict[str, str] = {
    identifier: reason
    for _outcome, reason, identifiers in _POLICY
    for identifier in identifiers
}


# ------------------------------------------------------------------ 예외의 효과
#
# **SPDX 는 예외 목록만 주고 효과는 주지 않는다.** 그래서 여기가 손으로 채운 표다.
#
# 여기서 가장 중요한 것은 완화하는 예외를 모으는 것이 아니라, **완화처럼 보이지만 완화가
# 아닌 것**을 가려내는 일이다. OpenSSL 예외들이 그렇다 — GPL 과 OpenSSL 의 비양립을 푸는
# 장치이지 우리의 비공개 배포를 허락하는 것이 아니다. 그것을 완화로 분류하면 **거짓 하향**
# 이 되고, 거짓 하향은 §7.3 이 말한 대로 조용히 사라진다.


class ExceptionEffect(StrEnum):
    """예외가 우리 기준(비공개 상용 배포)에서 무엇을 하는가."""

    #: 결합·링크에 대한 copyleft 를 푼다. 다만 조건이 붙는다.
    RELIEVES_LINKING = "RELIEVES_LINKING"
    #: 도구를 쓴 **산출물**에 대한 의무를 푼다. 도구 자체를 배포하면 그대로다.
    RELIEVES_OUTPUT = "RELIEVES_OUTPUT"
    #: 다른 오픈소스와의 비양립만 푼다. **우리에게는 완화가 아니다.**
    COMPATIBILITY_ONLY = "COMPATIBILITY_ONLY"
    #: 오픈소스로 배포할 때만 쓸 수 있다. 비공개 배포에는 도움이 되지 않는다.
    OPEN_SOURCE_ONLY = "OPEN_SOURCE_ONLY"


_EXCEPTION_EFFECT: dict[str, tuple[ExceptionEffect, str]] = {
    # --- 링크를 허용한다. LGPL 과 같은 모양의 조건부다.
    "Classpath-exception-2.0": (
        ExceptionEffect.RELIEVES_LINKING,
        "링크한 저작물에까지 GPL 이 번지지 않는다. OpenJDK 전체가 쓴다",
    ),
    "Classpath-exception-2.0-short": (
        ExceptionEffect.RELIEVES_LINKING,
        "Classpath 예외의 축약 표기",
    ),
    "GPL-3.0-linking-exception": (
        ExceptionEffect.RELIEVES_LINKING,
        "링크한 저작물을 다른 조건으로 배포할 수 있다",
    ),
    "GPL-3.0-linking-source-exception": (
        ExceptionEffect.RELIEVES_LINKING,
        "링크는 허용하되 대응 소스 제공 조건이 붙는다",
    ),
    "LGPL-3.0-linking-exception": (
        ExceptionEffect.RELIEVES_LINKING,
        "LGPL 의 재링크 요구를 면제한다",
    ),
    "GPL-3.0-interface-exception": (
        ExceptionEffect.RELIEVES_LINKING,
        "정해진 인터페이스를 통한 결합을 허용한다",
    ),
    "Independent-modules-exception": (
        ExceptionEffect.RELIEVES_LINKING,
        "독립 모듈은 파생물로 보지 않는다",
    ),
    "Libtool-exception": (
        ExceptionEffect.RELIEVES_LINKING,
        "libtool 이 끼워 넣은 코드가 결합물의 조건을 바꾸지 않는다",
    ),
    "LLVM-exception": (
        ExceptionEffect.RELIEVES_LINKING,
        "컴파일 산출물에 Apache-2.0 의 고지·특허 조항이 따라붙지 않는다",
    ),
    "Swift-exception": (
        ExceptionEffect.RELIEVES_LINKING,
        "Swift 런타임을 링크한 산출물에 의무가 번지지 않는다",
    ),
    "Bootloader-exception": (
        ExceptionEffect.RELIEVES_LINKING,
        "부트로더가 적재한 것까지 파생물로 보지 않는다",
    ),
    "FLTK-exception": (
        ExceptionEffect.RELIEVES_LINKING,
        "정적 링크한 저작물을 다른 조건으로 배포할 수 있다",
    ),
    "OCaml-LGPL-linking-exception": (
        ExceptionEffect.RELIEVES_LINKING,
        "OCaml 정적 링크의 LGPL 재링크 요구를 면제한다",
    ),
    "Qt-GPL-exception-1.0": (
        ExceptionEffect.RELIEVES_LINKING,
        "Qt 와의 결합에 한해 GPL 이 번지지 않는다",
    ),
    "Qt-LGPL-exception-1.1": (
        ExceptionEffect.RELIEVES_LINKING,
        "Qt LGPL 결합의 조건을 완화한다",
    ),
    "Digia-Qt-LGPL-exception-1.1": (
        ExceptionEffect.RELIEVES_LINKING,
        "Qt LGPL 결합의 조건을 완화한다 (Digia 판)",
    ),
    "Nokia-Qt-exception-1.1": (
        ExceptionEffect.RELIEVES_LINKING,
        "Qt LGPL 결합의 조건을 완화한다 (Nokia 판, SPDX 폐기)",
    ),
    "WxWindows-exception-3.1": (
        ExceptionEffect.RELIEVES_LINKING,
        "결합물을 원하는 조건으로 배포할 수 있다",
    ),
    "eCos-exception-2.0": (
        ExceptionEffect.RELIEVES_LINKING,
        "eCos 를 링크한 저작물에 GPL 이 번지지 않는다",
    ),
    "u-boot-exception-2.0": (
        ExceptionEffect.RELIEVES_LINKING,
        "U-Boot 가 적재한 것까지 파생물로 보지 않는다",
    ),
    "Linux-syscall-note": (
        ExceptionEffect.RELIEVES_LINKING,
        "시스템 호출로만 커널을 쓰는 사용자 공간 코드는 파생물이 아니다",
    ),
    "OpenJDK-assembly-exception-1.0": (
        ExceptionEffect.RELIEVES_LINKING,
        "OpenJDK 조립물에 대한 결합 조건을 완화한다",
    ),
    "GCC-exception-3.1": (
        ExceptionEffect.RELIEVES_OUTPUT,
        "GCC 런타임을 포함한 **컴파일 산출물**을 자유롭게 배포할 수 있다",
    ),
    "GCC-exception-2.0": (
        ExceptionEffect.RELIEVES_OUTPUT,
        "GCC 런타임을 포함한 컴파일 산출물에 GPL 이 번지지 않는다",
    ),
    "GCC-exception-2.0-note": (
        ExceptionEffect.RELIEVES_OUTPUT,
        "GCC 런타임 예외 2.0 의 주석 변형",
    ),
    "Autoconf-exception-2.0": (
        ExceptionEffect.RELIEVES_OUTPUT,
        "생성된 configure 스크립트에 GPL 이 번지지 않는다",
    ),
    "Autoconf-exception-3.0": (
        ExceptionEffect.RELIEVES_OUTPUT,
        "생성된 configure 스크립트에 GPL 이 번지지 않는다",
    ),
    "Autoconf-exception-generic": (
        ExceptionEffect.RELIEVES_OUTPUT,
        "Autoconf 산출물에 대한 일반 예외",
    ),
    "Autoconf-exception-generic-3.0": (
        ExceptionEffect.RELIEVES_OUTPUT,
        "Autoconf 산출물에 대한 일반 예외 (GPL-3.0 용)",
    ),
    "Autoconf-exception-macro": (
        ExceptionEffect.RELIEVES_OUTPUT,
        "Autoconf 매크로를 쓴 산출물에 대한 예외",
    ),
    "Bison-exception-2.2": (
        ExceptionEffect.RELIEVES_OUTPUT,
        "Bison 이 생성한 파서 코드에 GPL 이 번지지 않는다",
    ),
    "Bison-exception-1.24": (
        ExceptionEffect.RELIEVES_OUTPUT,
        "Bison 이 생성한 파서 코드에 GPL 이 번지지 않는다",
    ),
    "Font-exception-2.0": (
        ExceptionEffect.RELIEVES_OUTPUT,
        "폰트를 **문서에 임베드**해도 문서에 GPL 이 번지지 않는다",
    ),
    "PS-or-PDF-font-exception-20170817": (
        ExceptionEffect.RELIEVES_OUTPUT,
        "PS·PDF 에 폰트를 임베드해도 문서에 의무가 번지지 않는다",
    ),
    "Texinfo-exception": (
        ExceptionEffect.RELIEVES_OUTPUT,
        "Texinfo 매크로를 쓴 산출물에 대한 예외",
    ),
    # --- 완화처럼 보이지만 우리에게는 완화가 아니다. 이 줄들이 이 표의 핵심이다.
    "cryptsetup-OpenSSL-exception": (
        ExceptionEffect.COMPATIBILITY_ONLY,
        "GPL 과 OpenSSL 의 비양립만 푼다. 비공개 배포와는 무관하다",
    ),
    "kvirc-openssl-exception": (
        ExceptionEffect.COMPATIBILITY_ONLY,
        "GPL 과 OpenSSL 의 비양립만 푼다",
    ),
    "openvpn-openssl-exception": (
        ExceptionEffect.COMPATIBILITY_ONLY,
        "GPL 과 OpenSSL 의 비양립만 푼다",
    ),
    "sqlitestudio-OpenSSL-exception": (
        ExceptionEffect.COMPATIBILITY_ONLY,
        "GPL 과 OpenSSL 의 비양립만 푼다",
    ),
    "vsftpd-openssl-exception": (
        ExceptionEffect.COMPATIBILITY_ONLY,
        "GPL 과 OpenSSL 의 비양립만 푼다",
    ),
    "x11vnc-openssl-exception": (
        ExceptionEffect.COMPATIBILITY_ONLY,
        "GPL 과 OpenSSL 의 비양립만 푼다",
    ),
    "stunnel-exception": (
        ExceptionEffect.COMPATIBILITY_ONLY,
        "GPL 과 OpenSSL 의 비양립만 푼다",
    ),
    "libpri-OpenH323-exception": (
        ExceptionEffect.COMPATIBILITY_ONLY,
        "GPL 과 OpenH323 의 비양립만 푼다",
    ),
    "GPL-CC-1.0": (
        ExceptionEffect.COMPATIBILITY_ONLY,
        "위반 시 유예 기간을 주겠다는 약속이다. 의무 자체는 그대로다",
    ),
    "Universal-FOSS-exception-1.0": (
        ExceptionEffect.OPEN_SOURCE_ONLY,
        "결합물을 **FOSS 로 배포할 때만** 쓸 수 있다. 비공개 배포에는 쓸 수 없다",
    ),
    "RRDtool-FLOSS-exception-2.0": (
        ExceptionEffect.OPEN_SOURCE_ONLY,
        "정해진 FLOSS 라이선스로 배포할 때만 쓸 수 있다",
    ),
    "DigiRule-FOSS-exception": (
        ExceptionEffect.OPEN_SOURCE_ONLY,
        "정해진 FOSS 라이선스로 배포할 때만 쓸 수 있다",
    ),
    "gnu-javamail-exception": (
        ExceptionEffect.RELIEVES_LINKING,
        "독립 모듈과의 결합을 허용한다",
    ),
    "i2p-gpl-java-exception": (
        ExceptionEffect.RELIEVES_LINKING,
        "정해진 방식의 결합을 허용한다",
    ),
    "mif-exception": (
        ExceptionEffect.RELIEVES_LINKING,
        "매크로와 인라인 함수를 쓴 것만으로 파생물이 되지 않는다",
    ),
    "freertos-exception-2.0": (
        ExceptionEffect.RELIEVES_LINKING,
        "FreeRTOS 와 결합한 독점 코드를 배포할 수 있다",
    ),
    "fmt-exception": (
        ExceptionEffect.RELIEVES_LINKING,
        "템플릿 인스턴스화 산출물에 의무가 번지지 않는다",
    ),
    "PCRE2-exception": (
        ExceptionEffect.RELIEVES_LINKING,
        "정적 링크한 저작물에 대한 예외",
    ),
}

#: 완화가 실제로 등급을 낮추는 경우. **낮추는 폭을 한 칸으로 묶는다.**
#:
#: `POLICY_CONFLICT` 를 `REVIEW_REQUIRED` 까지만 내린다. 예외의 조건(수정하지 않았는가,
#: 어떤 방식으로 링크했는가, 무엇을 배포하는가)은 코드가 확인할 수 없으므로 **사람이 볼
#: 자리까지만** 내리고 거기서 멈춘다. `NOTICE_REQUIRED` 로 내리면 "고지만 하면 된다" 가
#: 되어 확인하지 않은 조건을 충족했다고 단정하게 된다.
_RELIEF = frozenset({ExceptionEffect.RELIEVES_LINKING, ExceptionEffect.RELIEVES_OUTPUT})


@dataclass(frozen=True)
class LeafDecision:
    """leaf 하나가 어떻게 판정됐는가. 원장에 남길 재료다."""

    identifier: str
    exception: str | None
    outcome: LicensePolicyOutcome
    #: 예외가 등급을 낮췄으면 낮추기 전 값. 안 낮췄으면 ``None``.
    relieved_from: LicensePolicyOutcome | None = None
    #: 왜 그렇게 판정했는가. 사람이 읽는다.
    reason: str = ""

    @property
    def was_relieved(self) -> bool:
        return self.relieved_from is not None


@dataclass(frozen=True)
class Evaluation:
    """표현식 하나의 판정과 **그 판정을 이끈 것들.**

    ``leading`` 이 있어야 §5.5 의 관련성 게이트가 "판정을 이끈 leaf" 만 볼 수 있고,
    ``choice_note`` 가 있어야 §7.3 이 요구하는 "보이는 하향" 이 성립한다.
    """

    outcome: LicensePolicyOutcome
    #: 이 결과를 만든 leaf 들. AND 면 가장 무거운 것, OR 이면 택한 것.
    leading: tuple[LeafDecision, ...]
    #: 표현식에 등장한 모든 leaf.
    all_leaves: tuple[LeafDecision, ...]
    #: OR 에서 무엇을 택했는지, 예외가 무엇을 완화했는지 사람이 읽는 기록.
    notes: tuple[str, ...] = ()


def outcome_for_identifier(identifier: str) -> LicensePolicyOutcome:
    """단일 식별자의 분류. 표에 없으면 UNKNOWN 이다.

    모르는 라이선스를 통과시키지 않는다 (Agent 3 Spec 28).
    """
    if identifier == UNKNOWN_LICENSE:
        return LicensePolicyOutcome.UNKNOWN
    return _OUTCOME_BY_ID.get(identifier, LicensePolicyOutcome.UNKNOWN)


def reason_for_identifier(identifier: str) -> str:
    """왜 그 분류인가. 표에 없으면 빈 문자열."""
    return _REASON_BY_ID.get(identifier, "")


def exception_effect(exception: str | None) -> tuple[ExceptionEffect | None, str]:
    """예외가 무엇을 하는가. 등록되지 않았거나 분류하지 않았으면 ``(None, 사유)``."""
    if exception is None:
        return None, ""
    if canonicalize_exception(exception) is None:
        return None, "SPDX 에 등록되지 않은 예외다. 완화 근거로 쓰지 않는다"
    known = _EXCEPTION_EFFECT.get(exception)
    if known is None:
        return None, "등록된 예외이지만 효과를 아직 분류하지 않았다"
    return known


def _decide_leaf(node: LicenseNode) -> LeafDecision:
    """leaf 하나를 판정한다. 예외를 여기서 본다."""
    base = outcome_for_identifier(node.identifier)
    reason = reason_for_identifier(node.identifier) or "정책 표에 없다 — 사람이 분류해야 한다"

    effect, note = exception_effect(node.exception)
    if effect is None:
        if node.exception is not None:
            reason = f"{reason}. 예외 `{node.exception}`: {note}"
        return LeafDecision(node.identifier, node.exception, base, None, reason)

    if effect in _RELIEF and base is LicensePolicyOutcome.POLICY_CONFLICT:
        return LeafDecision(
            node.identifier,
            node.exception,
            LicensePolicyOutcome.REVIEW_REQUIRED,
            base,
            f"예외 `{node.exception}` 가 완화한다 — {note}. 조건 충족 여부는 코드가 "
            f"확인할 수 없으므로 사람이 볼 자리까지만 내린다",
        )

    return LeafDecision(
        node.identifier,
        node.exception,
        base,
        None,
        f"{reason}. 예외 `{node.exception}`: {note}",
    )


def _evaluate_node(node: ExpressionNode) -> tuple[
    LicensePolicyOutcome, tuple[LeafDecision, ...], tuple[LeafDecision, ...], tuple[str, ...]
]:
    if isinstance(node, LicenseNode):
        decision = _decide_leaf(node)
        # 완화한 경우와, **완화를 주지 않은 예외가 달려 있는** 경우를 모두 남긴다.
        # 뒤쪽이 특히 중요하다 — 등록되지 않은 예외는 대개 메타데이터의 오타이고,
        # 아무 말도 안 하면 그 오타가 조용히 맨 라이선스 판정으로 굳는다.
        notes = (
            (f"{decision.identifier}: {decision.reason}",)
            if decision.was_relieved or decision.exception is not None
            else ()
        )
        return decision.outcome, (decision,), (decision,), notes

    results = [_evaluate_node(operand) for operand in node.operands]
    every: tuple[LeafDecision, ...] = tuple(
        leaf for _o, _l, all_leaves, _n in results for leaf in all_leaves
    )
    notes: tuple[str, ...] = tuple(n for _o, _l, _a, ns in results for n in ns)

    if isinstance(node, AndNode):
        # 모든 의무가 동시에 적용된다. 가장 무거운 것이 결과다.
        heaviest = max(_SEVERITY[outcome] for outcome, _l, _a, _n in results)
        leading = tuple(
            leaf
            for outcome, leads, _a, _n in results
            if _SEVERITY[outcome] == heaviest
            for leaf in leads
        )
        return _by_severity(heaviest), leading, every, notes

    # OR 은 수취인이 고른다. 가장 가벼운 쪽을 택할 수 있으므로 그것이 결과다.
    # 다만 UNKNOWN 만 있는 선택지는 완화 근거가 되지 못한다.
    known = [r for r in results if r[0] is not LicensePolicyOutcome.UNKNOWN]
    if not known:
        return LicensePolicyOutcome.UNKNOWN, tuple(every), every, notes

    lightest = min(_SEVERITY[outcome] for outcome, _l, _a, _n in known)
    leading = tuple(
        leaf
        for outcome, leads, _a, _n in known
        if _SEVERITY[outcome] == lightest
        for leaf in leads
    )
    dropped = tuple(
        leaf
        for outcome, leads, _a, _n in results
        if _SEVERITY[outcome] > lightest
        for leaf in leads
    )
    if dropped:
        # 이것이 §7.3 이 말하는 "보이는 하향" 이다. 값은 같아도 무엇을 버렸는지 남는다.
        notes = notes + (
            "OR 에서 "
            + " · ".join(str(leaf.identifier) for leaf in leading)
            + " 를 택했다. 버린 선택지: "
            + " · ".join(str(leaf.identifier) for leaf in dropped),
        )
    return _by_severity(lightest), leading, every, notes


def _by_severity(value: int) -> LicensePolicyOutcome:
    for outcome, severity in _SEVERITY.items():
        if severity == value:
            return outcome
    raise AssertionError(f"unknown severity: {value}")


def evaluate(expression: str) -> Evaluation:
    """표현식을 판정하고 **무엇이 그 판정을 이끌었는지** 함께 돌려준다.

    :func:`evaluate_expression` 은 결과만 준다. 게이트와 원장은 그것으로 부족하다 —
    어느 leaf 가 판정을 이끌었는지 알아야 관련 없는 근거가 붙는 것을 막고, 무엇을 버렸는지
    알아야 하향이 보인다.
    """
    outcome, leading, every, notes = _evaluate_node(parse_expression(expression))
    return Evaluation(outcome, leading, every, notes)


def evaluate_expression(expression: str) -> LicensePolicyOutcome:
    """정규화된 SPDX 표현식의 검토 분류."""
    return evaluate(expression).outcome


def needs_review(outcome: LicensePolicyOutcome) -> bool:
    """사람이 봐야 하는 분류인지. 알림 여부 판단에 쓴다."""
    return _SEVERITY[outcome] >= _SEVERITY[LicensePolicyOutcome.UNKNOWN]


def describe(outcome: LicensePolicyOutcome) -> str:
    """설명 생성이 실패했을 때 쓰는 고정 문구. 모델 없이도 결과는 읽혀야 한다."""
    return {
        LicensePolicyOutcome.NO_ACTION: "별도 의무가 확인되지 않았다.",
        LicensePolicyOutcome.NOTICE_REQUIRED: "배포 시 라이선스 사본과 저작권 고지가 필요하다.",
        LicensePolicyOutcome.REVIEW_REQUIRED: "결합 방식에 따라 의무가 달라진다. 사람이 확인해야 한다.",
        LicensePolicyOutcome.POLICY_CONFLICT: "결합 저작물의 소스 공개를 요구한다. 비공개 배포와 충돌한다.",
        LicensePolicyOutcome.UNKNOWN: "라이선스를 식별하지 못했다. 자동 허용하지 않는다.",
    }[outcome]
