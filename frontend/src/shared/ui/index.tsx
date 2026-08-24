import type {
  ButtonHTMLAttributes,
  InputHTMLAttributes,
  ReactNode,
  SelectHTMLAttributes,
  TextareaHTMLAttributes,
} from "react";

export function Button({
  className = "",
  variant = "primary",
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: "primary" | "secondary" | "danger" | "ghost";
}) {
  return (
    <button className={`button button--${variant} ${className}`} {...props} />
  );
}

export function Card({
  children,
  className = "",
}: {
  children: ReactNode;
  className?: string;
}) {
  return <section className={`card ${className}`}>{children}</section>;
}

export function Badge({
  children,
  tone = "neutral",
}: {
  children: ReactNode;
  tone?: "neutral" | "success" | "warning" | "danger" | "info";
}) {
  return <span className={`badge badge--${tone}`}>{children}</span>;
}

const PRIORITIES = ["HIGH", "INDETERMINATE", "MEDIUM", "LOW"] as const;

/**
 * Risk 등급 배지.
 *
 * 등급은 다른 상태값과 성격이 다르다 — 훑어보는 사람이 "먼저 볼 것" 을 고르는
 * 유일한 단서라서, 일반 Badge 의 5색 톤(neutral·success·…)에 끼워 맞추면
 * MEDIUM 과 LOW 가 똑같은 회색이 되어 순서가 사라진다. 등급만 별도 색을 준다:
 * HIGH 빨강 · INDETERMINATE 파랑 · MEDIUM 주황 · LOW 초록.
 *
 * 색 점을 앞에 두는 이유는 글자를 읽지 않고도 열을 훑을 수 있어야 하기 때문이다.
 * 모르는 값이 오면 색을 지어내지 않고 중립 배지로 둔다.
 */
export function PriorityBadge({ value }: { value: string }) {
  const known = (PRIORITIES as readonly string[]).includes(value);
  if (!known) return <Badge>{value}</Badge>;
  return (
    <span
      className={`badge badge--priority badge--priority-${value.toLowerCase()}`}
    >
      <span className="badge__dot" aria-hidden="true" />
      {value}
    </span>
  );
}

export function Field({
  label,
  hint,
  children,
}: {
  label: string;
  hint?: string;
  children: ReactNode;
}) {
  return (
    <label className="field">
      <span className="field__label">{label}</span>
      {children}
      {hint === undefined ? null : <span className="field__hint">{hint}</span>}
    </label>
  );
}

export function Input(props: InputHTMLAttributes<HTMLInputElement>) {
  return <input className="input" {...props} />;
}
export function Select(props: SelectHTMLAttributes<HTMLSelectElement>) {
  return <select className="input" {...props} />;
}
export function Textarea(props: TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return <textarea className="input textarea" {...props} />;
}

export function PageHeader({
  eyebrow,
  title,
  description,
  actions,
}: {
  eyebrow?: string;
  title: string;
  description?: string;
  actions?: ReactNode;
}) {
  return (
    <header className="page-header">
      <div>
        {eyebrow === undefined ? null : <p className="eyebrow">{eyebrow}</p>}
        <h1>{title}</h1>
        {description === undefined ? null : <p>{description}</p>}
      </div>
      {actions === undefined ? null : (
        <div className="page-header__actions">{actions}</div>
      )}
    </header>
  );
}

export function LoadingState({ label = "Loading" }: { label?: string }) {
  return (
    <div className="state" role="status">
      <span className="spinner" aria-hidden="true" />
      {label}…
    </div>
  );
}

export function ErrorState({
  error,
  retry,
}: {
  error: Error;
  retry?: () => void;
}) {
  return (
    <div className="state state--error" role="alert">
      <strong>Something went wrong</strong>
      <span>{error.message}</span>
      {retry === undefined ? null : (
        <Button variant="secondary" onClick={retry}>
          Try again
        </Button>
      )}
    </div>
  );
}

export function EmptyState({
  title,
  description,
  action,
}: {
  title: string;
  description: string;
  action?: ReactNode;
}) {
  return (
    <div className="empty">
      <div className="empty__mark" aria-hidden="true">
        ◇
      </div>
      <h2>{title}</h2>
      <p>{description}</p>
      {action}
    </div>
  );
}

export function toneFor(
  value: string,
): "neutral" | "success" | "warning" | "danger" | "info" {
  if (["ACTIVE", "SUCCEEDED", "READ", "ACCEPTED_RISK"].includes(value))
    return "success";
  if (["FAILED", "SOURCE_OFFLINE", "DISABLED"].includes(value)) return "danger";
  if (
    ["NEW", "UNREAD", "REAUTH_REQUIRED", "MANAGER_ACTION_REQUIRED"].includes(
      value,
    )
  )
    return "warning";
  // Risk 등급(HIGH·INDETERMINATE·MEDIUM·LOW)은 여기서 다루지 않는다 —
  // PriorityBadge 가 전담한다. 두 곳에서 색을 정하면 같은 등급이 화면마다
  // 다른 색으로 나온다.
  if (["PATENT", "LICENSE", "MONITORING"].includes(value)) return "info";
  return "neutral";
}
