"""Drive 파일이 어느 폴더 아래 있는지.

## 왜 필요한가

Drive 어댑터는 ``logical_path_hint`` 를 ``None`` 으로 넘겼다. 그래서 Drive 아티팩트의
``logical_path`` 가 ``별칭/파일이름`` 으로 **평평했다.** 폴더가 다른 같은 이름의 파일이
목록에서 구별되지 않고, UI 트리를 만들 근거가 없다 (§6.1).

GitHub 과 Local 은 경로를 그대로 들고 온다. Drive 만 **부모를 물어야** 안다.

## 클라이언트가 준 값을 쓰지 않는다

지금 마운트는 브라우저 picker 가 보낸 ``display_metadata_by_file`` 을 쓴다. 그것은
**클라이언트가 보낸 값**이라 경로의 근거로 삼을 수 없다 — 경로는 제외 패턴 판정에
쓰이므로, 클라이언트가 정하게 두면 게이트를 지나가는 방법이 생긴다.

그래서 서버에서 부모를 따라 올라간다. picker 는 D1 로 없어지지만 (§2 결정 D1) 이
경로 해석은 폴더 마운트에서도 그대로 쓰인다.

## 어디서 멈추는가

* **마운트가 보는 폴더에 닿으면 멈춘다.** 그 폴더가 뿌리이므로 경로에 넣지 않는다.
  넣으면 ``별칭/폴더이름/파일`` 이 되는데 별칭이 이미 그 폴더 이름이라 같은 이름이
  두 번 나오고, 무엇보다 **등록된 ``logical_path`` 와 달라져 게이트가
  ``CANONICAL_CONTEXT_MISMATCH`` 로 거부한다.**
* 부모가 없으면 뿌리다 (내 드라이브).
* ``max_depth`` 를 넘으면 멈춘다. §6.1 이 v1 의 값을 그대로 쓰기로 했다 — **깊이 10**.
* 부모를 읽지 못하면 (공유 범위 밖) 거기서 멈춘다. 오류가 아니다 — 우리가 볼 수 있는
  만큼이 경로다.

## 뿌리를 명시적으로 받는 이유

예전에는 "읽지 못하는 조상" 이 사실상 뿌리 노릇을 했다. `drive.file` 로는 공유받은
폴더 위가 안 읽혔기 때문이다. D1 의 서비스 계정에서는 **무엇이 읽히는가가 사용자가
무엇을 공유했는가에 달려 있다.** 부모 폴더까지 공유하면 경로가 조용히 한 단 길어지고
그 순간 게이트가 모든 분석을 거부한다. 뿌리는 우연히 정해지면 안 된다.

**자른 것은 조용히 넘기지 않는다.** 깊이에서 잘리면 맨 앞에 ``…`` 를 남겨 "여기가 전부가
아니다" 를 표시한다. 조용히 자르면 그 경로가 뿌리부터인 것처럼 읽힌다.
"""

from __future__ import annotations

from typing import Protocol

#: §6.1 이 v1 의 값을 그대로 쓴다.
MAX_PATH_DEPTH = 10

#: 깊이에서 잘렸다는 표시. 경로 조각으로 쓸 수 없는 문자여야 오해가 없다.
TRUNCATED_MARKER = "…"


class _FileLookup(Protocol):
    def get_file(self, file_id: str): ...


def sanitize_segment(name: str) -> str:
    """폴더·파일 이름 하나를 경로 조각으로 만든다.

    Drive 이름에는 ``/`` 가 들어갈 수 있다. 그대로 이으면 조각 하나가 둘이 되어
    경로의 뜻이 바뀌고, ``_logical_path_from_hint`` 의 검증에도 걸린다. 역슬래시와
    앞뒤 공백도 같은 이유로 정리한다.

    되돌릴 수 없는 변환이다. 원래 이름은 ``display_name`` 이 그대로 들고 있으므로
    여기서는 **경로로 쓸 수 있는 모양**만 만든다.
    """
    cleaned = name.replace("/", "_").replace("\\", "_").strip()
    if cleaned in {"", ".", ".."}:
        return "_"
    return cleaned


def resolve_path_hint(
    provider: _FileLookup,
    file_id: str,
    name: str,
    parents: tuple[str, ...],
    *,
    root_folder_id: str | None = None,
    cache: dict[str, tuple[str, tuple[str, ...]]] | None = None,
    max_depth: int = MAX_PATH_DEPTH,
) -> str:
    """이 파일의 ``logical_path_hint``. **마운트 뿌리 기준의 상대 경로**다.

    ``root_folder_id`` 는 이 마운트가 보는 폴더다. 거기 닿으면 멈추고 그 폴더는 경로에
    넣지 않는다 — 뿌리이기 때문이다.

    ``cache`` 는 ``file_id -> (이름, 부모들)`` 이다. 같은 폴더가 여러 파일의 조상이므로
    한 번 훑는 동안 재사용하면 호출 수가 크게 줄어든다.
    """
    memo = cache if cache is not None else {}
    segments: list[str] = [sanitize_segment(name)]
    current = parents[0] if parents else None
    depth = 0

    while current is not None:
        if current == root_folder_id:
            break
        if depth >= max_depth:
            segments.insert(0, TRUNCATED_MARKER)
            break
        found = memo.get(current)
        if found is None:
            try:
                folder = provider.get_file(current)
            except Exception:  # noqa: BLE001 - 볼 수 없는 조상은 경로의 끝이다
                break
            found = (folder.name, tuple(folder.parents))
            memo[current] = found
        folder_name, folder_parents = found
        segments.insert(0, sanitize_segment(folder_name))
        current = folder_parents[0] if folder_parents else None
        depth += 1

    return "/".join(segments)


__all__ = [
    "MAX_PATH_DEPTH",
    "TRUNCATED_MARKER",
    "resolve_path_hint",
    "sanitize_segment",
]
