/**
 * 근거 발췌에서 위반 지점을 색칠한다.
 *
 * 발췌만 통째로 보여주면 사용자는 그 안에서 문제의 패키지·라이선스를 눈으로
 * 다시 찾아야 한다. v1 은 위반 등급을 색으로 구분해 그 수고를 없앴다 —
 * 같은 감각으로, Risk 요약에서 뽑은 토큰(패키지 이름, 라이선스 식별자)이
 * 발췌 안에 나타나는 자리를 우선순위 색으로 표시한다.
 *
 * 하이라이트는 표시일 뿐이다. 토큰을 못 찾으면 발췌를 그대로 보여주고,
 * 판단은 언제나 backend 의 분석 결과가 한다.
 */

const GENERIC_TOKENS = new Set(["pypi", "npm", "license", "the", "and"]);

/** "pypi:pyqt5@5.15.11 — GPL-3.0-ONLY" 류의 요약에서 표시할 토큰을 뽑는다. */
export function highlightTokens(summary: string): string[] {
  const tokens = new Set<string>();

  // "ecosystem:name@version" 의 name 과 version.
  const coordinate = summary.match(/([\w.-]+):([\w.-]+)@([\w.+-]+)/);
  if (coordinate?.[2] && coordinate[3]) {
    tokens.add(coordinate[2]);
    tokens.add(`${coordinate[2]}==${coordinate[3]}`);
  }

  // SPDX 식별자 모양 (GPL-3.0-ONLY, AGPL-3.0-only, LGPL-2.1 …).
  for (const match of summary.matchAll(/\b[A-Z]+[A-Za-z]*-[\d][\w.-]*\b/g)) {
    tokens.add(match[0]);
  }

  return [...tokens].filter(
    (token) => token.length >= 3 && !GENERIC_TOKENS.has(token.toLowerCase()),
  );
}

export type HighlightedExcerptProps = {
  text: string;
  tokens: string[];
  priority: "HIGH" | "MEDIUM" | "LOW";
};

function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

export function HighlightedExcerpt({
  text,
  tokens,
  priority,
}: HighlightedExcerptProps) {
  if (tokens.length === 0) {
    return <blockquote>{text}</blockquote>;
  }
  // 긴 토큰 먼저 — "pyqt5==5.15.11" 이 "pyqt5" 보다 먼저 잡혀야 한다.
  const pattern = new RegExp(
    `(${[...tokens]
      .sort((a, b) => b.length - a.length)
      .map(escapeRegExp)
      .join("|")})`,
    "gi",
  );
  // 캡처 그룹으로 나누면 홀수 인덱스가 일치한 조각이다. g 플래그 정규식의
  // test() 는 lastIndex 상태를 남겨 번갈아 틀리므로 쓰지 않는다.
  const parts = text.split(pattern);
  const markClass = `evidence-mark evidence-mark--${priority.toLowerCase()}`;

  return (
    <blockquote>
      {parts.map((part, index) =>
        index % 2 === 1 ? (
          // eslint-disable-next-line react/no-array-index-key
          <mark key={index} className={markClass}>
            {part}
          </mark>
        ) : (
          // eslint-disable-next-line react/no-array-index-key
          <span key={index}>{part}</span>
        ),
      )}
    </blockquote>
  );
}
