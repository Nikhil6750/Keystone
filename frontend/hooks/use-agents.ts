'use client';

import { listAgents } from '@/services/agents';
import { useAsyncResource } from './use-async-resource';

export function useAgents() {
  return useAsyncResource((signal) => listAgents({ signal }), []);
}
