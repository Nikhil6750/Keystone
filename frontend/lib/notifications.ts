import type { NotificationItem } from '@/types';

/** Starts empty — no fabricated activity history. This prototype does not
 * yet subscribe to real backend events, so notifications only ever reflect
 * what happens locally in this browser tab during the current session. */
export const INITIAL_NOTIFICATIONS: NotificationItem[] = [];
