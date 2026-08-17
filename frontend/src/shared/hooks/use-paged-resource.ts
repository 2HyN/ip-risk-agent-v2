import { useCallback, useEffect, useState, type DependencyList } from "react";

type PageLike = {
  items: unknown[];
  next_cursor: string | null;
};

export type PagedResource<P extends PageLike> = {
  readonly data: P | null;
  readonly error: Error | null;
  readonly loading: boolean;
  readonly loadingMore: boolean;
  readonly loadMore: () => void;
  readonly reload: () => void;
};

export function usePagedResource<P extends PageLike>(
  loader: (cursor: string | null) => Promise<P>,
  dependencies: DependencyList,
): PagedResource<P> {
  const [data, setData] = useState<P | null>(null);
  const [error, setError] = useState<Error | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [version, setVersion] = useState(0);
  const reload = useCallback(() => setVersion((value) => value + 1), []);

  useEffect(() => {
    let current = true;
    setLoading(true);
    setLoadingMore(false);
    setError(null);
    setData(null);
    void loader(null).then(
      (value) => {
        if (current) {
          setData(value);
          setLoading(false);
        }
      },
      (reason: unknown) => {
        if (current) {
          setError(reason instanceof Error ? reason : new Error("Request failed"));
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

  const loadMore = useCallback(() => {
    const cursor = data?.next_cursor;
    if (cursor === null || cursor === undefined || loadingMore) return;
    setLoadingMore(true);
    setError(null);
    void loader(cursor).then(
      (page) => {
        setData((current) =>
          current === null
            ? page
            : ({
                ...page,
                items: [...current.items, ...page.items],
              } as P),
        );
        setLoadingMore(false);
      },
      (reason: unknown) => {
        setError(reason instanceof Error ? reason : new Error("Request failed"));
        setLoadingMore(false);
      },
    );
  }, [data?.next_cursor, loader, loadingMore]);

  return { data, error, loading, loadingMore, loadMore, reload };
}
