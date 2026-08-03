'use client';

import { getHealth } from '@/services/health';
import { useAsyncResource } from './use-async-resource';

export function useBackendHealth() {
  return useAsyncResource((signal) => getHealth({ signal }), []);
}
