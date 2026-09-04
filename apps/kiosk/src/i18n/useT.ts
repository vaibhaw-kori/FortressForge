/**
 * Translation hook. Supports `{var}` interpolation.
 */
import { useMemo } from 'react';
import { CATALOGS, KioskKey } from './catalog';

export interface TranslateVars {
  [key: string]: string | number;
}

export function useT(language: string) {
  const dict = useMemo(() => CATALOGS[language] ?? CATALOGS.en, [language]);

  function t(key: KioskKey, vars?: TranslateVars): string {
    let value = dict[key] ?? key;
    if (vars) {
      for (const [k, v] of Object.entries(vars)) {
        value = value.replace(new RegExp(`\\{${k}\\}`, 'g'), String(v));
      }
    }
    return value;
  }

  return { t, language };
}