'use client';

import { listCircuitBreakers } from '@/services/resilience';
import { useAsyncResource } from './use-async-resource';

export function useCircuitBreakers() {
  return useAsyncResource((signal) => listCircuitBreakers({ signal }), []);
}
