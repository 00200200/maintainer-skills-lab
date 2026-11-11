import { useCallback, useEffect, useRef, useState } from 'react';
import { parseProfile } from './profile';
import type { Profile } from './profile';

export function useProfile(intervalSeconds: number) {
  const [profile, setProfile] = useState<Profile | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [updatedAt, setUpdatedAt] = useState<Date | null>(null);
  const pending = useRef<AbortController | null>(null);

  const refresh = useCallback(async () => {
    if (pending.current) return;
    const controller = new AbortController();
    pending.current = controller;
    setLoading(true);
    setError(null);
    let timedOut = false;
    const timeout = window.setTimeout(() => { timedOut = true; controller.abort(); }, 30_000);
    try {
      const response = await fetch('/api/profile', {
        signal: controller.signal, cache: 'no-store', headers: { Accept: 'application/json' },
      });
      if (!response.ok) throw new Error(`Profile request failed (HTTP ${response.status}).`);
      const next = parseProfile(await response.json());
      if (pending.current !== controller) return;
      setProfile(next);
      setUpdatedAt(new Date());
    } catch (cause) {
      if (pending.current !== controller) return;
      setError(timedOut ? 'The profile request timed out. Please try again.' :
        cause instanceof Error ? cause.message : 'Unable to reach the local profile server.');
    } finally {
      window.clearTimeout(timeout);
      if (pending.current === controller) {
        pending.current = null;
        setLoading(false);
      }
    }
  }, []);

  useEffect(() => {
    void refresh();
    return () => { pending.current?.abort(); pending.current = null; };
  }, [refresh]);

  useEffect(() => {
    if (!intervalSeconds) return;
    const timer = window.setInterval(() => {
      if (!document.hidden) void refresh();
    }, intervalSeconds * 1000);
    return () => window.clearInterval(timer);
  }, [intervalSeconds, refresh]);

  return { profile, error, loading, updatedAt, refresh };
}
