/**
 * Watcher 필터/디바운스 설정.
 * Agent 2 Spec 26번(recursive watch, debounce, temp/build output filter).
 *
 * Sora3780/ip-risk-agent (팀 공개 저장소)의 detect.py/watcher.py에 있던
 * 검증된 필터 규칙(제외 폴더, 임시파일 패턴, 확장자 분류)을 TypeScript로
 * 옮겼다 — 로직만 참고했고 실행 코드 자체는 새로 작성했다.
 *
 * 지금 Local 이 보는 것은 **코드와 문서**뿐이다. 의존성 선언은 License 판별을
 * 손볼 때까지 대상에서 빼 두었다 (`isLicenseTarget`).
 */

import { extname } from "node:path";

export const SKIP_DIRS = new Set([".git", ".venv", "venv", "__pycache__", "node_modules", ".idea"]);

export const CODE_EXTENSIONS = new Set([
  ".py", ".js", ".ts", ".java", ".go", ".c", ".h", ".cpp", ".rs",
]);

export const DOC_EXTENSIONS = new Set([".md", ".txt", ".rst"]);

/**
 * License 검사가 맡을 파일인가.
 *
 * 서버가 쓰는 표(`core/artifacts/dependency_files.py`)와 **같은 판정**이어야 한다.
 * 이름 목록으로 두면 어긋난다 — `requirements.txt` 만 막고 `requirements-dev.txt`
 * 는 `.txt` 확장자로 그대로 통과하는 식이다.
 *
 * 라이선스 본문(`LICENSE`, `NOTICE`)도 여기 넣는다. 지금은 어느 분석기도 맡지
 * 않아 감시해 봐야 거부된 artifact 만 남는다.
 */
function isLicenseTarget(name: string): boolean {
  if (["license", "license.md", "license.txt", "notice"].includes(name)) {
    return true;
  }
  if (
    ["package-lock.json", "uv.lock", "poetry.lock", "pyproject.toml", "setup.cfg", "package.json"].includes(name)
  ) {
    return true;
  }
  return name.startsWith("requirements") && (name.endsWith(".txt") || name.endsWith(".in"));
}

const TEMP_SUFFIXES = [".swp", ".swx", ".tmp", "~", ".part", ".crdownload"];

export const DEBOUNCE_MS = 3000;
export const MAX_FILE_BYTES = 1_000_000;

export function isWatchedPath(relativePath: string): boolean {
  const parts = relativePath.split(/[\\/]/).filter((part) => part.length > 0);
  if (parts.length === 0) {
    return false;
  }

  const dirParts = parts.slice(0, -1);
  if (dirParts.some((part) => SKIP_DIRS.has(part) || part.startsWith("."))) {
    return false;
  }

  const name = parts[parts.length - 1] ?? "";
  if (name.startsWith(".") || TEMP_SUFFIXES.some((suffix) => name.endsWith(suffix))) {
    return false;
  }
  if (/^\d+$/.test(name)) {
    return false;
  }

  // License 대상은 지금 Local 에서 보지 않는다. 판별을 크게 손볼 예정이고,
  // 지금 확인하려는 것은 **로컬 디렉터리 추적** 자체다. GitHub 과 Drive 는
  // 그대로 License 검사를 받는다 — 이 규칙은 Local 워처에만 적용된다.
  //
  // 되돌릴 때는 이 세 줄을 지우면 된다. 무엇이 빠져 있는지 filters.test.ts 가 고정한다.
  if (isLicenseTarget(name)) {
    return false;
  }
  const suffix = extname(name).toLowerCase();
  return CODE_EXTENSIONS.has(suffix) || DOC_EXTENSIONS.has(suffix);
}
