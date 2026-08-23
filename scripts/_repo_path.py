"""이 스크립트들이 **자기 저장소의** 코드를 읽게 만든다.

## 왜 필요한가

작업 트리가 여럿이고 (`integration-v2` 는 고정 백업, `integration-v3` 이 개발본),
가상 환경 하나를 함께 쓴다. 그 환경에는 ``ip_risk_agent`` 가 **editable** 로
설치되어 있고, 그 설치가 가리키는 곳은 `integration-v2` 다.

``python scripts/foo.py`` 로 부르면 ``sys.path[0]`` 은 ``scripts/`` 뿐이라
저장소의 ``backend/src`` 가 어디에도 없다. 그러면 editable finder 가 답하고,
스크립트는 **자기가 놓인 곳이 아닌 다른 체크아웃**을 읽는다.

실제로 `scripts/validate_gcp_deployment.py` 가 그렇게 돌았다. RAG 주제 표가
어긋났다고 보고했는데, 저장소의 표는 675 항목으로 맞아 있었고 틀린 것은 v2 에서
읽어 온 3 항목짜리 옛 표였다. **배포 관문이 배포될 코드가 아닌 것을 검사한** 것이다.
통과했더라면 더 나빴다 — 관문은 통과했는데 그것이 설명한 코드는 나가지 않는다.

pytest 는 이 문제가 없다. ``pyproject.toml`` 의 ``pythonpath`` 가 rootdir 기준으로
앞에 붙는다. 그래서 시험은 맞는 코드를 보고 스크립트만 틀렸고, 그래서 조용했다.

## 어떻게

``sys.path`` 앞에 넣는다. setuptools 의 editable finder 는 ``sys.meta_path`` 의
**맨 뒤**에 있어서 (``PathFinder`` 다음), 경로에 있기만 하면 저장소 쪽이 이긴다.

``ip_risk_agent`` 나 ``iprisk_contracts`` 를 들이기 **전에** 부른다::

    import _repo_path  # noqa: F401  -- 저장소 코드를 먼저 경로에 올린다

    from ip_risk_agent... import ...
"""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]

for _entry in (_ROOT / "backend" / "src", _ROOT / "shared" / "contracts" / "python"):
    _text = str(_entry)
    if _text in sys.path:
        sys.path.remove(_text)
    sys.path.insert(0, _text)

__all__: list[str] = []
