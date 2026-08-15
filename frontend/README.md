# Keystone Frontend

The Keystone web app — Next.js 15 (App Router) + React 19 + Tailwind v4, wired to the
real Keystone backend API (no mock data on any page except `/knowledge`, which is an
explicitly labeled future-feature stub).

## Setup

```bash
npm install
npm run dev
```

Serves at `http://localhost:3000`. Expects the backend at `http://localhost:8000` by
default; override with `NEXT_PUBLIC_API_URL`.

## Scripts

| Command | Purpose |
| --- | --- |
| `npm run dev` | Local dev server |
| `npm run build` | Production build |
| `npm run start` | Serve the production build |
| `npm run lint` | ESLint |
| `npm run typecheck` | `tsc --noEmit` |
| `npm run test:run` | Vitest, single run |
| `npm run format` / `format:check` | Prettier |

## Pages

| Route | Purpose |
| --- | --- |
| `/chat` | Manual workflow builder — you define each step and its agent explicitly, then execute (Stage 2/3 engine only; no automatic planning). |
| `/orchestrate` | Automatic pipeline — describe a goal, pick from real connected agents, and run the full Task Graph → Agent Organization → Skill Foundry → execution → recovery → Quality Factory → Intelligence Graph pipeline. |
| `/workflows` | List and inspect workflows created via either flow. |
| `/agents` | Real, truthful connection status (installed / registered / authenticated / connected) for every canonical agent type; trigger a live verification. |
| `/logs` | Real audit events, tamper-evident audit-chain verification, and provenance for a workflow. |
| `/settings` | Backend health, theme, and prototype status. |
| `/knowledge` | Explicitly labeled stub — not wired to a real feature yet. |

## Contract source of truth

`types/backend.ts` mirrors the backend's actual Pydantic schemas field-for-field (see
`../docs/api-contract.md` and `backend/app/schemas/*.py` / relevant route response
models). Presentation-only mapping (labels, colors) lives in `lib/presentation.ts`, never
in the types themselves.
