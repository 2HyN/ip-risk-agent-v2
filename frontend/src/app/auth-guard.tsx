import { Navigate, Outlet, useLocation } from "react-router-dom";
import { useSession } from "../auth/session";
import { ErrorState, LoadingState } from "../shared/ui";

export function AuthGuard() {
  const { user, loading, error, refresh } = useSession();
  const location = useLocation();
  if (loading)
    return (
      <main className="center-page">
        <LoadingState label="Loading your session" />
      </main>
    );
  if (error !== null)
    return (
      <main className="center-page">
        <ErrorState
          error={error}
          retry={() => {
            void refresh();
          }}
        />
      </main>
    );
  if (user === null)
    return <Navigate to="/login" state={{ from: location.pathname }} replace />;
  return <Outlet />;
}
