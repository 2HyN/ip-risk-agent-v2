// 생성된 파일이다. 손으로 고치지 않는다.
//
//     python scripts/generate_source_filters.py
//
// 원본은 `backend/src/ip_risk_agent/core/artifacts/` 와 `core/security/` 의 표다.
// 같은 판단을 두 언어가 각자 적으면 어긋나고, 감시가 먼저 거르므로 그 어긋남은
// **Local 마운트에서 조용한 누락**이 된다.


export const CODE_EXTENSIONS: readonly string[] = [
  ".c",
  ".cc",
  ".cpp",
  ".cs",
  ".cxx",
  ".go",
  ".h",
  ".hpp",
  ".java",
  ".js",
  ".jsx",
  ".kt",
  ".kts",
  ".m",
  ".mjs",
  ".php",
  ".pl",
  ".py",
  ".pyi",
  ".r",
  ".rb",
  ".rs",
  ".scala",
  ".sh",
  ".sql",
  ".swift",
  ".ts",
  ".tsx",
  ".vue"
];


export const DOCUMENT_EXTENSIONS: readonly string[] = [
  ".adoc",
  ".cfg",
  ".conf",
  ".csv",
  ".env",
  ".ini",
  ".json",
  ".jsonl",
  ".log",
  ".markdown",
  ".md",
  ".org",
  ".properties",
  ".rst",
  ".text",
  ".toml",
  ".tsv",
  ".txt",
  ".xml",
  ".yaml",
  ".yml"
];


// 확장자가 없어도 텍스트인 관행적 이름.
export const EXTENSIONLESS_TEXT: readonly string[] = [
  "dockerfile",
  "makefile",
  "readme"
];


// 라이선스 전문 파일. 어느 분석기도 맡지 않으므로 감시해도 거부된 artifact 만
// 남는다 (결함 26).
export const LICENCE_STEMS: readonly string[] = [
  "copying",
  "licence",
  "licences",
  "license",
  "licenses",
  "notice",
  "unlicense"
];


// 의존성 선언. 이름이 정확히 맞아야 하는 것들.
export const DEPENDENCY_EXACT_NAMES: readonly string[] = [
  "constraints.txt",
  "package-lock.json",
  "package.json",
  "poetry.lock",
  "pyproject.toml",
  "setup.cfg",
  "uv.lock"
];


// `requirements` 로 시작하면 같은 형식이다. `requirements-dev.txt` ·
// `requirements.in` 처럼 쓰는 관행이 넓다.
export const DEPENDENCY_PREFIX = "requirements";


// `requirements/base.txt` 처럼 폴더가 형식을 말해 주는 관행.
export const DEPENDENCY_DIRECTORY = "requirements";


// 빌드 산출물과 의존성 트리. 워처가 가지치기에 쓴다.
export const SKIP_DIRECTORIES: readonly string[] = [
  ".git",
  ".gradle",
  ".hg",
  ".mypy_cache",
  ".next",
  ".nuxt",
  ".pytest_cache",
  ".ruff_cache",
  ".svn",
  ".terraform",
  ".tox",
  ".venv",
  "__pycache__",
  "build",
  "dist",
  "node_modules",
  "site-packages",
  "target",
  "vendor",
  "venv"
];
