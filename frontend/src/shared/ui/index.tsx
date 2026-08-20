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
    [
      "NEW",
      "UNREAD",
      "REAUTH_REQUIRED",
      "MANAGER_ACTION_REQUIRED",
      "HIGH",
    ].includes(value)
  )
    return "warning";
  if (["PATENT", "LICENSE", "MONITORING"].includes(value)) return "info";
  return "neutral";
}
