import Link from 'next/link';
import { Header } from '@/components/common';
import { Bot, GitFork, History, ArrowRight, BookOpen } from 'lucide-react';

export default function Home() {
  return (
    <div className="flex min-h-screen flex-col bg-[#0B1120] font-sans text-white">
      <Header />

      <main className="mx-auto w-full max-w-[1200px] flex-1 space-y-20 px-6 py-16 md:py-24">
        {/* Hero Section */}
        <section className="flex flex-col items-start space-y-6">
          {/* Small Badge */}
          <div className="rounded-full border border-white/[0.08] bg-white/[0.04] px-4 py-1.5 text-xs font-medium text-blue-400 backdrop-blur-md">
            Adaptive Multi-Agent AI Orchestration Platform
          </div>

          {/* Large Heading */}
          <h1 className="max-w-3xl text-4xl leading-[1.15] font-bold tracking-tight text-white sm:text-5xl md:text-6xl">
            Build, Execute and Monitor Intelligent AI Workflows
          </h1>

          {/* Supporting Text */}
          <p className="max-w-2xl text-base leading-relaxed text-zinc-400 sm:text-lg md:text-xl">
            Coordinate multiple AI agents through a single workspace. Plan tasks, execute workflows,
            validate outputs and monitor every step in real time.
          </p>

          {/* CTA Buttons */}
          <div className="flex flex-wrap items-center gap-4 pt-4">
            <Link
              href="/chat"
              className="inline-flex items-center gap-2 rounded-lg bg-blue-600 px-6 py-3 text-sm font-semibold text-white shadow-md transition-all hover:bg-blue-500"
            >
              <span>Start New Workflow</span>
              <ArrowRight className="h-4 w-4" />
            </Link>
            <a
              href="https://github.com/Nikhil6750/Keystone"
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-2 rounded-lg border border-white/[0.08] bg-white/[0.04] px-6 py-3 text-sm font-semibold text-zinc-300 transition-all hover:bg-white/[0.08] hover:text-white"
            >
              <BookOpen className="h-4 w-4" />
              <span>View Documentation</span>
            </a>
          </div>
        </section>

        {/* Feature Cards Section */}
        <section className="grid gap-6 pt-4 md:grid-cols-3">
          {/* Card 1: AI Orchestration */}
          <div className="rounded-xl border border-white/[0.08] bg-white/[0.04] p-6 transition-all duration-200 hover:border-white/20 hover:bg-white/[0.06]">
            <div className="space-y-4">
              <div className="flex h-10 w-10 items-center justify-center rounded-lg border border-blue-500/20 bg-blue-600/20 text-blue-400">
                <Bot className="h-5 w-5" />
              </div>
              <h3 className="text-lg font-semibold tracking-tight text-white">AI Orchestration</h3>
              <p className="text-sm leading-relaxed text-zinc-400">
                Coordinate multiple AI agents through one workflow.
              </p>
            </div>
          </div>

          {/* Card 2: Workflow Engine */}
          <div className="rounded-xl border border-white/[0.08] bg-white/[0.04] p-6 transition-all duration-200 hover:border-white/20 hover:bg-white/[0.06]">
            <div className="space-y-4">
              <div className="flex h-10 w-10 items-center justify-center rounded-lg border border-emerald-500/20 bg-emerald-600/20 text-emerald-400">
                <GitFork className="h-5 w-5" />
              </div>
              <h3 className="text-lg font-semibold tracking-tight text-white">Workflow Engine</h3>
              <p className="text-sm leading-relaxed text-zinc-400">
                Track planning, execution, retries and validation.
              </p>
            </div>
          </div>

          {/* Card 3: Audit Trail */}
          <div className="rounded-xl border border-white/[0.08] bg-white/[0.04] p-6 transition-all duration-200 hover:border-white/20 hover:bg-white/[0.06]">
            <div className="space-y-4">
              <div className="flex h-10 w-10 items-center justify-center rounded-lg border border-purple-500/20 bg-purple-600/20 text-purple-400">
                <History className="h-5 w-5" />
              </div>
              <h3 className="text-lg font-semibold tracking-tight text-white">Audit Trail</h3>
              <p className="text-sm leading-relaxed text-zinc-400">
                Every workflow is fully traceable with event history.
              </p>
            </div>
          </div>
        </section>
      </main>
    </div>
  );
}
