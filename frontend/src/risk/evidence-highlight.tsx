/**
 * 근거 발췌 안에서 문제가 된 구간만 강조한다.
 *
 * 근거는 조각(문단) 단위까지 좁혀져 있다. 그 조각 전체를 보여 주는 이유는 문맥이
 * 있어야 사람이 판단할 수 있기 때문이고, 그 안에서 **어느 문장이 겹치는지**를
 * 짚어 주는 것이 이 컴포넌트의 일이다.
 *
 * 구간은 분석기가 인용의 실재를 확인한 것만 온다. 모델이 지어낸 인용은 그 대조
 * 전체가 폐기되므로 여기까지 오지 않는다.
 *
 * 값이 이상하면 강조하지 않고 원문을 그대로 보여 준다. 잘못된 구간으로 엉뚱한 곳을
 * 강조하면 사람이 그것을 근거로 읽는다 — 강조가 없는 것보다 나쁘다.
 *
 * 강조 색은 Risk 등급을 따른다 (HIGH 빨강 · MEDIUM 주황). 구간 밖의 본문은
 * `keywords` 를 켠 경우에 한해 낱말 강조를 받는다 — 라이선스처럼 검증된 인용
 * 구간이 없는 근거에서 "어느 조항이 문제인가" 를 짚어 주기 위한 것이다.
 */

import { RiskText, prioritySlug } from "./risk-emphasis.js";

type Span = { readonly start: number; readonly end: number };

export function quoteSpan(
  metadata: Record<string, unknown> | null | undefined,
  length: number,
): Span | null {
  if (metadata === null || metadata === undefined) return null;
  const start = metadata["quote_start"];
  const end = metadata["quote_end"];
  if (typeof start !== "number" || typeof end !== "number") return null;
  if (!Number.isInteger(start) || !Number.isInteger(end)) return null;
  // 발췌는 보존 정책이 잘라낼 수 있다. 잘린 뒤를 가리키는 구간은 보여 줄 것이 없다.
  if (start < 0 || end <= start || end > length) return null;
  // 발췌의 거의 전부를 덮는 구간은 강조하지 않는다. 모델이 짧은 초록을 통째로
  // 인용하면 이렇게 되는데, 전부를 칠한 강조는 "어디가 문제인가" 에 아무 답도
  // 주지 않으면서 화면만 시끄럽다.
  if (end - start >= length * 0.9) return null;
  return { start, end };
}

export function EvidenceExcerpt({
  excerpt,
  metadata,
  priority,
  keywords = false,
}: {
  excerpt: string;
  metadata: Record<string, unknown> | null | undefined;
  priority?: string | null;
  keywords?: boolean;
}) {
  const span = quoteSpan(metadata, excerpt.length);
  const slug = prioritySlug(priority);
  // 낱말 강조는 등급을 알 때만. 구간 강조와 규칙이 같다 — 등급 없이 칠하면
  // 없는 심각도를 만들어 낸다.
  const rest = (text: string) =>
    keywords ? <RiskText text={text} priority={priority} /> : text;
  if (span === null) return <blockquote>{rest(excerpt)}</blockquote>;
  return (
    <blockquote>
      {rest(excerpt.slice(0, span.start))}
      <mark
        className={`evidence-quote${slug === "" ? "" : ` evidence-quote--${slug}`}`}
      >
        {excerpt.slice(span.start, span.end)}
      </mark>
      {rest(excerpt.slice(span.end))}
    </blockquote>
  );
}
