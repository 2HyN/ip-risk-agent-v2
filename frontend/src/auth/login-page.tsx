import { Navigate } from "react-router-dom";
import { useSession } from "./session";
import { Button, Card, ErrorState, LoadingState } from "../shared/ui";

export function LoginPage() {
  const { api, user, loading, error } = useSession();
  if (loading)
    return (
      <main className="center-page">
        <LoadingState label="Checking your session" />
      </main>
    );
  if (user !== null) return <Navigate to="/" replace />;
  return (
    <main className="login-page">
      <div className="login-brand">
        <span className="brand-mark">IP</span>
        <span>IP Risk Agent</span>
      </div>
      <Card className="login-card">
        <p className="eyebrow">Platform &amp; Control Plane</p>
        <h1>
          Know what changed.
          <br />
          Review what matters.
        </h1>
        <p className="login-copy">
          A focused workspace for patent and license risk across your connected
          sources. Original content remains with its provider.
        </p>
        {error === null ? null : <ErrorState error={error} />}
        <Button
          className="login-button"
          onClick={() => {
          window.location.assign(api.googleLoginUrl());
          }}
        >
          <span aria-hidden="true">G</span> Continue with Google
        </Button>
        <p className="fine-print">
          Authentication establishes application identity only. Source access is
          authorized separately by each provider.
        </p>
      </Card>
    </main>
  );
}
