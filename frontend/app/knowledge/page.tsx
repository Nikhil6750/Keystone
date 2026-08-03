import { BookOpen, GitBranch, ShieldCheck, Sparkles } from 'lucide-react';
import { AppLayout } from '@/components/common';

const FUTURE_CAPABILITIES = [
  {
    icon: GitBranch,
    title: 'Validated workflow memory',
    description: 'Remembering how past workflows were structured, once a human has reviewed them.',
  },
  {
    icon: Sparkles,
    title: 'Retrieval of successful and failed experiences',
    description: 'Surfacing prior runs relevant to a new goal, including what went wrong and why.',
  },
  {
    icon: BookOpen,
    title: 'Routing recommendations',
    description: 'Suggesting agents and step structures based on grounded evidence — never silent automation.',
  },
  {
    icon: ShieldCheck,
    title: 'Human-approved learning',
    description: 'Nothing is learned or applied automatically without an explicit human approval step.',
  },
];

export default function KnowledgePage() {
  return (
    <AppLayout showSidebar={true}>
      <main className="flex flex-1 flex-col items-center justify-center space-y-8 overflow-y-auto p-6 text-center md:p-8">
        <div className="flex h-14 w-14 items-center justify-center rounded-2xl border border-purple-500/30 bg-purple-950/30 text-purple-400">
          <BookOpen className="h-6 w-6" />
        </div>
        <div className="max-w-xl space-y-2">
          <span className="text-xs font-bold tracking-wider text-purple-400 uppercase">
            Coming in Phase 7
          </span>
          <h1 className="text-2xl font-bold tracking-tight text-white sm:text-3xl">
            Evidence-grounded workflow memory and adaptive routing are planned for Phase 7.
          </h1>
          <p className="text-sm leading-relaxed text-zinc-400">
            This prototype does not implement retrieval-augmented generation, a vector database,
            or any external knowledge API. Nothing on this page is connected to a real feature
            yet.
          </p>
        </div>

        <div className="grid w-full max-w-2xl gap-4 text-left sm:grid-cols-2">
          {FUTURE_CAPABILITIES.map((capability) => {
            const Icon = capability.icon;
            return (
              <div
                key={capability.title}
                className="space-y-2 rounded-xl border border-white/[0.08] bg-white/[0.03] p-4"
              >
                <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-purple-600/20 text-purple-400">
                  <Icon className="h-4 w-4" />
                </div>
                <h3 className="text-xs font-semibold text-white">{capability.title}</h3>
                <p className="text-[11px] leading-relaxed text-zinc-400">
                  {capability.description}
                </p>
              </div>
            );
          })}
        </div>
      </main>
    </AppLayout>
  );
}
