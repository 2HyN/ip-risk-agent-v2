import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { EvidenceExcerpt, quoteSpan } from "./evidence-highlight.js";

describe("quoteSpan", () => {
  it("정상 구간을 받아들인다", () => {
    expect(quoteSpan({ quote_start: 2, quote_end: 5 }, 10)).toEqual({
      start: 2,
      end: 5,
    });
  });

  it("발췌 밖을 가리키면 강조하지 않는다", () => {
    // 발췌는 보존 정책이 잘라낼 수 있다. 잘린 뒤를 가리키면 보여 줄 것이 없다.
    expect(quoteSpan({ quote_start: 2, quote_end: 99 }, 10)).toBeNull();
  });

  it("값이 이상하면 강조하지 않는다", () => {
    // 잘못된 구간으로 엉뚱한 곳을 강조하면 사람이 그것을 근거로 읽는다.
    expect(quoteSpan({ quote_start: 5, quote_end: 5 }, 10)).toBeNull();
    expect(quoteSpan({ quote_start: -1, quote_end: 3 }, 10)).toBeNull();
    expect(quoteSpan({ quote_start: "2", quote_end: 5 }, 10)).toBeNull();
    expect(quoteSpan({}, 10)).toBeNull();
    expect(quoteSpan(null, 10)).toBeNull();
  });
});

describe("EvidenceExcerpt", () => {
  it("구간이 있으면 그 부분만 강조한다", () => {
    const excerpt = "앞 문장이다. 겹치는 구성이 여기 있다. 뒤 문장이다.";
    const start = excerpt.indexOf("겹치는");
    render(
      <EvidenceExcerpt
        excerpt={excerpt}
        metadata={{ quote_start: start, quote_end: start + 13 }}
      />,
    );
    const mark = screen.getByText("겹치는 구성이 여기 있다");
    expect(mark.tagName).toBe("MARK");
  });

  it("구간이 없으면 발췌를 그대로 보여 준다", () => {
    render(<EvidenceExcerpt excerpt="강조할 것이 없다" metadata={{}} />);
    expect(screen.getByText("강조할 것이 없다").tagName).toBe("BLOCKQUOTE");
  });
});
