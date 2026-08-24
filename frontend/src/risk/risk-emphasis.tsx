/**
 * 위험을 만드는 구절만 굵게 + 등급 색으로 칠한다.
 *
 * v1(데스크톱 앱)에서 가져온 방식이다. 라이선스 전문과 설명은 길고, 전부 같은
 * 회색으로 두면 **무엇 때문에 위험한지**를 사람이 눈으로 못 찾는다 — 실제로
 * v1 이전 화면에서 사용자가 전문을 처음부터 끝까지 읽고 있었다. 의무를 만드는
 * 구절("소스코드를 제공", "파생저작물", "동일한 라이선스" …)은 정해져 있으므로,
 * 그것만 칠하면 훑는 것으로 판단이 선다.
 *
 * 색은 등급을 따른다 — HIGH 빨강, MEDIUM 주황. 강조가 "여기가 문제" 와
 * "얼마나 급한가" 를 한 번에 말하게 하려는 것이다.
 *
 * 상쇄 요인(면제·허용·배포 가능)은 초록으로 뺀다. 위험이 아니라 빠져나갈
 * 구멍이라, 같은 색으로 칠하면 정반대 뜻이 위험으로 읽힌다.
 *
 * ⚠️ 여기 걸리는 것은 **낱말**이지 판정이 아니다. 강조는 읽는 순서를 돕는
 * 장치일 뿐이고, 판정은 서버가 준 등급·근거가 한다.
 */

import { Fragment } from "react";

const PRIORITIES = ["HIGH", "INDETERMINATE", "MEDIUM", "LOW"];

/**
 * 등급별 강조 색을 고르는 클래스 접미사 (`risk-mark--high` 의 `high`).
 * 모르는 값이면 빈 문자열 — 색을 지어내지 않는다.
 */
export function prioritySlug(priority: string | null | undefined): string {
  if (priority === null || priority === undefined) return "";
  return PRIORITIES.includes(priority) ? priority.toLowerCase() : "";
}

// 의무를 만드는 구절. v1 의 RISK_PATTERNS 를 그대로 옮겼다.
const RISK_SOURCES = [
  "소스\\s?코드[를을]?\\s?(?:제공|공개)",
  "소스코드[를을]?\\s?(?:제공|공개)",
  "파생\\s?저작물",
  "동일한?\\s?라이선스",
  "공개(?:해야|하여야|할\\s?의무|\\s?의무)",
  "제공(?:해야|하여야|할\\s?의무)",
  "약정서",
  "설치\\s?정보",
  "인증키",
  "금지",
  "의무사항",
  "양립\\s?불가",
  "GPL[-\\s]?[23](?:\\.0)?(?:-or-later)?",
  "GPL",
  "AGPL",
  "LGPL",
  "HIGH",
];

// 상쇄 요인. v1 의 RELIEF_PATTERNS.
const RELIEF_SOURCES = [
  "소스\\s?코드\\s?제공\\s?없이",
  "소스코드\\s?제공없이",
  "면제",
  "배포\\s?가능",
  "허용",
];

/*
 * 상쇄 쪽을 먼저 넣는다. 정규식은 같은 위치에서 앞선 대안을 먼저 잡으므로,
 * "소스코드 제공없이" 가 "소스코드 제공" 에 먼저 먹히는 것을 막는다 — 이 순서가
 * 뒤집히면 면제 조항이 빨갛게 칠해져 뜻이 정반대로 읽힌다.
 */
const PATTERN = new RegExp(
  `(?<relief>${RELIEF_SOURCES.join("|")})|(?<risk>${RISK_SOURCES.join("|")})`,
  "gu",
);

/**
 * 문자열을 강조 조각으로 쪼갠다. 렌더링과 분리해 두어야 규칙을 시험할 수 있다.
 */
export type Segment = {
  readonly text: string;
  readonly kind: "plain" | "risk" | "relief";
};

export function emphasize(text: string): Segment[] {
  const segments: Segment[] = [];
  let cursor = 0;
  // 전역 정규식은 lastIndex 를 들고 다닌다. 모듈 상수를 재사용하므로 매번 되돌린다.
  PATTERN.lastIndex = 0;
  for (const match of text.matchAll(PATTERN)) {
    const start = match.index;
    if (start > cursor) {
      segments.push({ text: text.slice(cursor, start), kind: "plain" });
    }
    segments.push({
      text: match[0],
      kind: match.groups?.relief === undefined ? "risk" : "relief",
    });
    cursor = start + match[0].length;
  }
  if (cursor < text.length) {
    segments.push({ text: text.slice(cursor), kind: "plain" });
  }
  return segments;
}

/**
 * 강조를 입힌 본문. `priority` 가 없으면 위험 구절도 칠하지 않는다 — 등급을
 * 모르는 채 빨갛게 칠하면 없는 심각도를 만들어 낸다.
 */
export function RiskText({
  text,
  priority,
}: {
  text: string;
  priority: string | null | undefined;
}) {
  const slug = prioritySlug(priority);
  if (slug === "") return <>{text}</>;
  return (
    <>
      {emphasize(text).map((segment, index) =>
        segment.kind === "plain" ? (
          <Fragment key={index}>{segment.text}</Fragment>
        ) : (
          <strong
            key={index}
            className={`risk-mark ${segment.kind === "relief" ? "risk-mark--relief" : `risk-mark--${slug}`}`}
          >
            {segment.text}
          </strong>
        ),
      )}
    </>
  );
}

/** 강조를 쓸지 말지. 특허는 검증된 인용 구간이 따로 오므로 낱말 강조를 겹치지 않는다. */
export function keywordEmphasisApplies(analysisType: string): boolean {
  return analysisType === "LICENSE";
}
