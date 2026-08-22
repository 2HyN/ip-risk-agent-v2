import { describe, expect, it } from "vitest";

import { analysisFailureNotice } from "./analysis-failure.js";

describe("analysisFailureNotice", () => {
  it("한도 소진을 다른 실패와 구분한다", () => {
    // 코드를 고칠 일이 아니라 기다리거나 키를 늘릴 일이다. 다시 눌러도 같다.
    const notice = analysisFailureNotice("PROVIDER:QUOTA_EXHAUSTED");
    expect(notice).not.toBeNull();
    expect(notice?.tone).toBe("warning");
    expect(notice?.detail).toContain("다시 검사해도 같은 결과");
  });

  it("파일이 앞서 나간 경우는 사용자가 할 일이 없다고 알린다", () => {
    const notice = analysisFailureNotice("SOURCE:REVISION_SUPERSEDED");
    expect(notice?.tone).toBe("warning");
    expect(notice?.detail).toContain("따로 하실 일은 없습니다");
  });

  it("모르는 코드는 실패로 두되 코드를 그대로 보여 준다", () => {
    const notice = analysisFailureNotice("CONTRACT:CANONICAL_INTAKE_REJECTED");
    expect(notice?.tone).toBe("danger");
    expect(notice?.detail).toContain("CONTRACT:CANONICAL_INTAKE_REJECTED");
  });

  it("실패가 없으면 아무것도 띄우지 않는다", () => {
    expect(analysisFailureNotice(null)).toBeNull();
    expect(analysisFailureNotice("")).toBeNull();
  });
});

describe("미판정", () => {
  it("일부만 판정된 검사는 실패가 아니라 경고다", () => {
    // 실패로 보여 주면 이미 확인된 Risk 까지 믿을 수 없는 것처럼 읽힌다.
    const notice = analysisFailureNotice("ANALYSIS:INCOMPLETE_COVERAGE");
    expect(notice?.tone).toBe("warning");
    expect(notice?.title).toContain("판정하지 못했습니다");
  });

  it("영어 원문을 그대로 내보내지 않는다", () => {
    const notice = analysisFailureNotice("ANALYSIS:INCOMPLETE_COVERAGE");
    expect(notice?.detail).not.toContain("non-authoritative");
  });
});

describe("검사 대상 아님", () => {
  it("판정할 것이 없던 문서에는 경고를 띄우지 않는다", () => {
    // 판정하지 못한 것과 판정할 것이 없던 것은 다르다. 뒤엣것에 경고를 붙이면
    // 아무 문제도 없는 README 에 경고가 달린다.
    const notice = analysisFailureNotice("ANALYSIS:NOT_APPLICABLE");
    expect(notice?.tone).toBe("info");
    expect(notice?.title).toContain("검사 대상이 아닙니다");
  });

  it("미판정과는 다른 안내를 낸다", () => {
    const skipped = analysisFailureNotice("ANALYSIS:NOT_APPLICABLE");
    const partial = analysisFailureNotice("ANALYSIS:INCOMPLETE_COVERAGE");
    expect(skipped?.title).not.toBe(partial?.title);
    expect(partial?.tone).toBe("warning");
  });
});
