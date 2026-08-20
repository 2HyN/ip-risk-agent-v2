import {
  createContext,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { ApiClient, ApiFailure } from "../shared/api/client";
import { ControlApi } from "../shared/api/control-api";
import type { User } from "../shared/api/types";

type SessionState = {
  api: ControlApi;
  user: User | null;
  loading: boolean;
  error: Error | null;
  refresh: () => Promise<void>;
  logout: () => Promise<void>;
};

const SessionContext = createContext<SessionState | null>(null);

export function SessionProvider({
  children,
  apiBaseUrl = "",
}: {
  children: ReactNode;
  apiBaseUrl?: string;
}) {
  const api = useMemo(
    () => new ControlApi(new ApiClient(apiBaseUrl)),
    [apiBaseUrl],
  );
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<Error | null>(null);

  async function refresh(): Promise<void> {
    setLoading(true);
    setError(null);
    try {
      const nextUser = await api.me();
      api.client.setCsrfToken(nextUser.csrf_token);
      setUser(nextUser);
    } catch (reason) {
      api.client.setCsrfToken(null);
      setUser(null);
      if (!(reason instanceof ApiFailure && reason.status === 401)) {
        setError(
          reason instanceof Error
            ? reason
            : new Error("Session could not be loaded"),
        );
      }
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void refresh();
  }, [api]);

  async function logout(): Promise<void> {
    await api.logout();
    api.client.setCsrfToken(null);
    setUser(null);
  }

  return (
    <SessionContext.Provider
      value={{ api, user, loading, error, refresh, logout }}
    >
      {children}
    </SessionContext.Provider>
  );
}

export function useSession(): SessionState {
  const value = useContext(SessionContext);
  if (value === null)
    throw new Error("useSession must be used inside SessionProvider");
  return value;
}
