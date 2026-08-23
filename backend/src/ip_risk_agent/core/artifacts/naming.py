"""아티팩트에 보이는 이름을 붙이는 규칙 하나.

## 왜 한 곳에 두는가

같은 파일에 이름을 붙이는 곳이 다섯이었고, **서로 달랐다.**

| 어디 | 무엇을 넣었나 |
|---|---|
| GitHub 마운트 | 경로의 마지막 조각 |
| GitHub push | `file.filename` \u2014 **전체 경로** |
| GitHub push (이름 변경) | `file.previous_filename` \u2014 **전체 경로** |
| Local | 마지막 조각 |
| Drive | 파일 이름 (Drive 에는 경로가 없다) |

실패하지는 않았다. 등록이 갱신하고 ``display_name`` 은 불변 조건이 아니기 때문이다.
그래서 **하위 폴더에 있는 파일의 이름이 첫 push 뒤에 조용히 바뀌었다.** 목록에서
``main.py`` 였던 것이 ``src/app/main.py`` 가 된다. 같은 파일인데 다르게 보인다.

## 폴더를 넣지 않는다

트리는 ``logical_path`` 가 만든다 \u2014 거기에 이미 폴더가 들어 있다. ``display_name``
까지 경로를 들면 화면에 폴더가 두 번 나오고, 소스마다 그 중복이 다르게 나타난다.
Drive 는 애초에 경로가 없어 마지막 조각밖에 넣을 수 없으므로, 맞출 곳은 여기다.
"""

from __future__ import annotations


def display_name_for(path: str) -> str:
    """경로에서 보이는 이름을 뽑는다.

    구분자는 둘 다 받는다 \u2014 Local 은 기기가 보낸 상대 경로를 그대로 넘기고, 윈도우
    기기는 역슬래시를 쓴다.

    빈 문자열이나 폴더로 끝나는 값은 그대로 돌려준다. 여기서 판단하지 않고 부르는
    쪽의 검증(``require_non_empty``)이 잡게 둔다 \u2014 이름을 지어내면 그 검증이
    영영 통과한다.
    """
    normalized = path.replace("\\", "/").rstrip("/")
    return normalized.rsplit("/", 1)[-1] if normalized else path


__all__ = ["display_name_for"]
