import { useCallback, useEffect, useState } from "react";

export function useAsync<T>(load: () => Promise<T>, dependencies: readonly unknown[]) {
  const [value, setValue] = useState<T | null>(null);
  const [error, setError] = useState<Error | null>(null);
  const [loading, setLoading] = useState(true);
  const run = useCallback(() => {
    setLoading(true); setError(null);
    return load().then(setValue).catch((reason) => setError(reason instanceof Error ? reason : new Error(String(reason)))).finally(() => setLoading(false));
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, dependencies);
  useEffect(() => { void run(); }, [run]);
  return { value, error, loading, retry: run };
}
