/**
 * React binding for the kiosk reducer.
 * Returns [state, dispatch]; tests/hooks can also import reducer directly.
 */
import { useReducer } from 'react';
import { initialKioskState, KioskAction, KioskState, reducer } from './kioskReducer';

export function useKioskState(): [KioskState, (a: KioskAction) => void] {
  return useReducer(reducer, initialKioskState);
}