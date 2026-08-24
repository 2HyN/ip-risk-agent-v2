import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { RiskText, emphasize, prioritySlug } from "./risk-emphasis.js";

describe("emphasize", () => {
  it("의무를 만드는 구절을 위험으로 잡는다", () => {
    const segments = emphasize("원본 및 파생저작물을 GPL 3.0에 의해 배포");
    expect(
      segments.filter((s) => s.kind === "risk").map((s) => s.text),
    ).toEqual(["파생저작물", "GPL 3.0"]);
  });

  it("상쇄 요인은 위험보다 먼저 잡는다", () => {
    // "소스코드 제공없이" 가 "소스코드 제공" 에 먹히면 면제 조항이 빨갛게 칠해져
    // 뜻이 정반대로 읽힌다. 이 순서가 이 모듈의 유일한 함정이다.
    const segments = emphasize("소스코드 제공없이 배포 가능");
    expect(segments.every((s) => s.kind !== "risk")).toBe(true);
    expect(
      segments.filter((s) => s.kind === "relief").map((s) => s.text),
    ).toEqual(["소스코드 제공없이", "배포 가능"]);
  });

  it("걸리는 것이 없으면 본문을 통째로 돌려준다", () => {
    expect(emphasize("평범한 문장이다")).toEqual([
      { text: "평범한 문장이다", kind: "plain" },
    ]);
  });

  it("연달아 부르면 같은 결과를 낸다", () => {
    // 전역 정규식은 lastIndex 를 들고 다닌다. 되돌리지 않으면 두 번째 호출이
    // 앞부분을 건너뛴다.
    const text = "금지 · 의무사항";
    expect(emphasize(text)).toEqual(emphasize(text));
  });
});

describe("prioritySlug", () => {
  it("아는 등급만 색을 준다", () => {
    expect(prioritySlug("HIGH")).toBe("high");
    expect(prioritySlug("INDETERMINATE")).toBe("indeterminate");
    // 모르는 값에 색을 지어내면 없는 심각도를 만든다.
    expect(prioritySlug("URGENT")).toBe("");
    expect(prioritySlug(null)).toBe("");
  });
});

describe("RiskText", () => {
  it("등급 색으로 굵게 칠한다", () => {
    render(<RiskText text="파생저작물 조항" priority="HIGH" />);
    const mark = screen.getByText("파생저작물");
    expect(mark.tagName).toBe("STRONG");
    expect(mark.className).toContain("risk-mark--high");
  });

  it("등급을 모르면 강조하지 않는다", () => {
    const { container } = render(
      <RiskText text="파생저작물 조항" priority={null} />,
    );
    expect(container.querySelector("strong")).toBeNull();
  });
});
