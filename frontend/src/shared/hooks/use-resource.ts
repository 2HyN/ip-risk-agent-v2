import { useCallback, useEffect, useState, type DependencyList } from "react";

export type Resource<T> = {
  readonly data: T | null;
  readonly error: Error | null;
  readonly loading: boolean;
  readonly reload: () => void;
};

export function useResource<T>(
  loader: () => Promise<T>,
  dependencies: DependencyList,
): Resource<T> {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<Error | null>(null);
  const [loading, setLoading] = useState(true);
  const [version, setVersion] = useState(0);
  const reload = useCallback(() => setVersion((value) => value + 1), []);

  useEffect(() => {
    let current = true;
    setLoading(true);
    setError(null);
    void loader().then(
      (value) => {
        if (current) {
          setData(value);
          setLoading(false);
        }
      },
      (reason: unknown) => {
        if (current) {
          setError(
            reason instanceof Error ? reason : new Error("Request failed"),
          );
          setLoading(false);
        }
      },
    );
    return () => {
      current = false;
    };
    // The caller supplies the exact stable request dependencies.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...dependencies, version]);

  return { data, error, loading, reload };
}
