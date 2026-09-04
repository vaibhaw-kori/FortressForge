// Display 1 (kiosk) state machine.
// Pure FSM, no React imports. Mirrors the brief's required flow:
// IDLE -> LANGUAGE_SELECTION -> EXPERIENCE_SELECTION -> READY_TO_CAPTURE
//      -> COUNTDOWN -> CAPTURED -> UPLOADING -> GENERATING -> COMPLETED -> RESET
import type { KioskScreen } from '@aura/contracts';
import { KIOSK_SCREEN_TRANSITIONS } from '@aura/contracts';

export function canTransition(from: KioskScreen, to: KioskScreen): boolean {
  return KIOSK_SCREEN_TRANSITIONS[from].includes(to);
}

export function assertTransition(from: KioskScreen, to: KioskScreen): void {
  if (!canTransition(from, to)) {
    throw new Error(`Illegal kiosk transition: ${from} -> ${to}`);
  }
}

export function isTerminalScreen(s: KioskScreen): boolean {
  return KIOSK_SCREEN_TRANSITIONS[s].length === 0;
}