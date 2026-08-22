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
