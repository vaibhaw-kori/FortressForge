/**
 * Fetch the experience catalog once per language and cache by language.
 */
import { useEffect, useState } from 'react';
import type { ExperienceDTO } from '@aura/contracts';
import { api, ApiError } from '../services/api';

interface State {
  experiences: ExperienceDTO[];
  loading: boolean;
  error: { code: string; message: string } | null;
}

let cache: Record<string, ExperienceDTO[]> = {};

export function useExperiences(language: string): State {
  const [state, setState] = useState<State>({
    experiences: cache[language] ?? [],
    loading: !cache[language],
    error: null,
  });

  useEffect(() => {
    if (cache[language]) {
      setState({ experiences: cache[language], loading: false, error: null });
      return;
    }
    let cancelled = false;
    setState({ experiences: [], loading: true, error: null });
    api
      .listExperiences(language)
      .then((items) => {
        if (cancelled) return;
        cache[language] = items;
        setState({ experiences: items, loading: false, error: null });
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        const e: ApiError = err instanceof ApiError ? err : new ApiError('network', 'Network error', 0);
        setState({ experiences: [], loading: false, error: { code: e.code, message: e.message } });
      });
    return () => {
      cancelled = true;
    };
  }, [language]);

  return state;
}