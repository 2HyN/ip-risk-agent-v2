/**
 * 분석 실패 코드를 사람이 읽을 안내로 옮긴다.
 *
 * 실패를 "무언가 잘못되었습니다" 로 뭉뚱그리면 사용자는 무엇을 해야 할지 알 수 없다.
 * 특히 provider 호출 한도 소진은 **코드를 고칠 일이 아니라** 한도가 초기화되기를
 * 기다리거나 키 등급을 올릴 일이고, 그때까지 다시 눌러도 결과가 같다.
 */

export type AnalysisFailureNotice = {
  readonly tone: "warning" | "danger";
  readonly title: string;
  readonly detail: string;
};

const QUOTA_EXHAUSTED = "PROVIDER:QUOTA_EXHAUSTED";
const INCOMPLETE_COVERAGE = "ANALYSIS:INCOMPLETE_COVERAGE";

export function analysisFailureNotice(
  code: string | null | undefined,
): AnalysisFailureNotice | null {
  if (!code) return null;
  if (code === QUOTA_EXHAUSTED) {
    return {
      tone: "warning",
      title: "특허 조회 한도를 다 썼습니다",
      detail:
        "KIPRIS 호출 한도가 소진되어 이 문서를 검사하지 못했습니다. " +
        "문서나 설정 문제가 아니므로 다시 검사해도 같은 결과입니다. " +
        "한도가 초기화된 뒤(매월 1일) 또는 키 등급을 올린 뒤에 다시 검사하세요.",
    };
  }
  if (code === INCOMPLETE_COVERAGE) {
    // 미판정은 실패가 아니다. 본 것은 그대로 두고, 보지 못한 것이 있다는 뜻이다.
    // 실패로 보여 주면 이미 확인된 Risk 까지 믿을 수 없는 것처럼 읽힌다.
    return {
      tone: "warning",
      title: "일부 후보를 판정하지 못했습니다",
      detail:
        "검사는 끝났지만 후보 중 일부를 끝까지 대조하지 못했습니다. " +
        "확인된 Risk 는 그대로 유효하며, 판정하지 못한 부분 때문에 " +
        "기존 Risk 를 해소하지는 않습니다. 다시 검사하면 완결될 수 있습니다.",
    };
  }
  if (code.startsWith("SOURCE:REVISION_SUPERSEDED")) {
    return {
      tone: "warning",
      title: "파일이 그 사이 바뀌었습니다",
      detail:
        "검사하려던 판본보다 새 판본이 소스에 있습니다. " +
        "변경 감지가 새 판본을 곧 검사하므로 따로 하실 일은 없습니다.",
    };
  }
  return {
    tone: "danger",
    title: "분석에 실패했습니다",
    detail: `실패 코드: ${code}`,
  };
}
