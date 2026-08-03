/**
 * Generic client-side API plumbing types. Backend response/request shapes
 * live in `./backend.ts` — nothing here assumes a `data`/`success`/`message`
 * wrapper or `{items, total, page, ...}` pagination envelope, since the real
 * backend returns resources unwrapped and paginates only via `{items, count}`
 * (see `docs/api-contract.md`).
 */

export interface RequestOptions {
  signal?: AbortSignal;
  timeoutMs?: number;
}
