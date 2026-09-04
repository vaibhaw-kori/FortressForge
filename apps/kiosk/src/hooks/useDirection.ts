/**
 * Configure the document language and direction for RTL languages.
 * Sets <html lang="..."> and <html dir="..."> when the language changes.
 */
import { useEffect } from 'react';
import { directionFor } from '../i18n/catalog';

export function useDirection(language: string): void {
  useEffect(() => {
    if (typeof document === 'undefined') return;
    document.documentElement.setAttribute('lang', language);
    document.documentElement.setAttribute('dir', directionFor(language));
  }, [language]);
}