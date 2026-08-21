import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, expect, test } from "vitest";

import { HighlightedExcerpt, highlightTokens } from "./evidence-highlight.js";

afterEach(() => cleanup());

test("요약에서 패키지와 라이선스 토큰을 뽑는다", () => {
  const tokens = highlightTokens("pypi:pyqt5@5.15.11 — GPL-3.0-ONLY");

  expect(tokens).toContain("pyqt5");
  expect(tokens).toContain("pyqt5==5.15.11");
  expect(tokens).toContain("GPL-3.0-ONLY");
});

test("발췌 안의 위반 지점이 우선순위 색으로 칠해진다", () => {
  render(
    <HighlightedExcerpt
      text={"requests==2.32.3\npyqt5==5.15.11\nnumpy==2.1.3"}
      tokens={highlightTokens("pypi:pyqt5@5.15.11 — GPL-3.0-ONLY")}
      priority="HIGH"
    />,
  );

  const mark = screen.getByText("pyqt5==5.15.11");
  expect(mark.tagName).toBe("MARK");
  expect(mark.className).toContain("evidence-mark--high");
  // 위반이 아닌 줄은 칠하지 않는다. 전부 칠하면 아무것도 강조되지 않는다.
  expect(screen.getByText(/requests==2\.32\.3/).tagName).not.toBe("MARK");
});

test("토큰이 없으면 발췌를 그대로 보여준다", () => {
  render(
    <HighlightedExcerpt text="plain excerpt" tokens={[]} priority="LOW" />,
  );

  expect(screen.getByText("plain excerpt").tagName).toBe("BLOCKQUOTE");
});

test("긴 토큰이 짧은 토큰보다 먼저 잡힌다", () => {
  // "pyqt5" 가 먼저 잡히면 "pyqt5==5.15.11" 이 두 조각으로 갈라진다.
  render(
    <HighlightedExcerpt
      text="pyqt5==5.15.11"
      tokens={["pyqt5", "pyqt5==5.15.11"]}
      priority="MEDIUM"
    />,
  );

  expect(screen.getByText("pyqt5==5.15.11").tagName).toBe("MARK");
});
