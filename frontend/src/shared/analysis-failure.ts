/**
 * 분석 실패 코드를 사람이 읽을 안내로 옮긴다.
 *
 * 실패를 "무언가 잘못되었습니다" 로 뭉뚱그리면 사용자는 무엇을 해야 할지 알 수 없다.
 * 특히 provider 호출 한도 소진은 **코드를 고칠 일이 아니라** 한도가 초기화되기를
 * 기다리거나 키 등급을 올릴 일이고, 그때까지 다시 눌러도 결과가 같다.
 */

export type AnalysisFailureNotice = {
  readonly tone: "info" | "warning" | "danger";
  readonly title: string;
  readonly detail: string;
};

const QUOTA_EXHAUSTED = "PROVIDER:QUOTA_EXHAUSTED";
const INCOMPLETE_COVERAGE = "ANALYSIS:INCOMPLETE_COVERAGE";
const NOT_APPLICABLE = "ANALYSIS:NOT_APPLICABLE";

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
  if (code === NOT_APPLICABLE) {
    // 판정하지 못한 것이 아니라 판정할 것이 없었다. 회의록이나 기술 내용이 없는
    // README 가 그렇다. 여기에 경고를 띄우면 아무 문제도 없는 문서에 경고가 붙고,
    // 사용자는 고칠 것을 찾아 시간을 쓴다.
    return {
      tone: "info",
      title: "검사 대상이 아닙니다",
      detail:
        "기술 내용이나 의존성 선언이 없어 이 문서에서는 검토할 것이 없습니다. " +
        "문제가 있는 것이 아니며 다시 검사해도 같은 결과입니다.",
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
  if (
    code === "SECURITY_GATE:GLOBAL_IGNORE_DENIED" ||
    code === "SECURITY_GATE:SOURCE_IGNORE_DENIED"
  ) {
    // 오류가 아니라 정책의 결과다. 이 파일의 열린 Risk 는 '제외됨' 으로 함께
    // 닫힌다 — 규칙을 지우고 다시 검사하면 되살아난다.
    return {
      tone: "info",
      title: "정책으로 검사에서 제외된 파일입니다",
      detail:
        "Security & data 의 .ipriskignore 규칙에 걸려 분석하지 않았습니다. " +
        "이 파일의 기존 Risk 는 '제외됨' 으로 닫힙니다. " +
        "다시 검사하려면 규칙을 지운 뒤 재검사하세요.",
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
