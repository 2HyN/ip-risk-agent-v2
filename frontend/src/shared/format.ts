export function formatDate(value: string | null): string {
  if (value === null) return "—";
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value));
}

export function humanize(value: string): string {
  return value
    .toLowerCase()
    .split("_")
    .map((part) => part[0]?.toUpperCase() + part.slice(1))
    .join(" ");
}

/**
 * 사람이 보는 판본 표기. git SHA 같은 긴 16진수는 앞 8자면 충분하다 —
 * 전체를 보여 주면 판본이 아니라 소음으로 읽힌다. 16진수가 아닌 판본
 * (Drive 의 리비전 번호 등)은 그대로 둔다.
 */
export function shortRevision(value: string): string {
  return /^[0-9a-f]{12,}$/iu.test(value) ? value.slice(0, 8) : value;
}

export function formatBytes(value: number): string {
  if (value < 1024) return `${value} B`;
  if (value < 1024 ** 2) return `${(value / 1024).toFixed(1)} KB`;
  return `${(value / 1024 ** 2).toFixed(1)} MB`;
}
