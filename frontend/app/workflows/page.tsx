'use client';

import * as React from 'react';
import Link from 'next/link';
import { AppLayout } from '@/components/common';
import {
  GitFork,
  Search,
  ChevronDown,
  RefreshCw,
  Plus,
  Play,
  ShieldCheck,
  History,
} from 'lucide-react';

const WORKFLOWS_PLACEHOLDER: Array<{
  id: string;
  name: string;
  status: string;
  currentStage: string;
  createdBy: string;
  duration: string;
  lastUpdated: string;
}> = [];

export default function WorkflowsPage() {
  const [searchTerm, setSearchTerm] = React.useState('');

  return (
    <AppLayout showSidebar={true}>
      <main className="flex flex-1 flex-col justify-between space-y-8 overflow-y-auto p-6 md:p-8">
        {/* Header Section */}
        <div className="flex flex-col justify-between gap-4 sm:flex-row sm:items-center">
          <div className="space-y-1">
            <span className="text-xs font-bold tracking-wider text-blue-400 uppercase">
              WORKFLOWS
            </span>
            <h1 className="text-3xl font-bold tracking-tight text-white sm:text-4xl">
              Autonomous AI Workflows
            </h1>
            <p className="text-sm leading-relaxed text-zinc-400">
              Monitor, manage and configure automated multi-agent workflow pipelines.
            </p>
          </div>

          <Link
            href="/chat"
            className="inline-flex shrink-0 items-center justify-center gap-1.5 self-start rounded-lg bg-blue-600 px-4 py-2 text-xs font-medium text-white shadow-sm transition-colors hover:bg-blue-500 sm:self-auto"
          >
            <Plus className="h-4 w-4" />
            <span>New Workflow</span>
          </Link>
        </div>

        {/* Filter Controls Toolbar */}
        <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-white/[0.08] bg-white/[0.04] p-3 backdrop-blur-md">
          {/* Search Input */}
          <div className="flex w-full items-center gap-2 rounded-lg border border-white/[0.08] bg-white/[0.04] px-3 py-1.5 text-xs text-zinc-400 transition-colors focus-within:border-white/20 sm:w-64">
            <Search className="h-3.5 w-3.5 shrink-0 text-zinc-400" />
            <input
              type="text"
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
              placeholder="Search workflows..."
              className="w-full bg-transparent text-xs text-white placeholder:text-zinc-500 focus:outline-none"
            />
          </div>

          {/* Dropdown Filters & Actions */}
          <div className="flex w-full flex-wrap items-center gap-3 sm:w-auto">
            {/* Status Filter */}
            <div className="flex min-w-[120px] cursor-pointer items-center justify-between gap-2 rounded-lg border border-white/[0.08] bg-white/[0.04] px-3 py-1.5 text-xs text-zinc-300 hover:border-white/20">
              <span className="text-zinc-500">Status</span>
              <span className="font-medium text-white">All</span>
              <ChevronDown className="h-3.5 w-3.5 text-zinc-400" />
            </div>

            {/* Agent Filter */}
            <div className="flex min-w-[120px] cursor-pointer items-center justify-between gap-2 rounded-lg border border-white/[0.08] bg-white/[0.04] px-3 py-1.5 text-xs text-zinc-300 hover:border-white/20">
              <span className="text-zinc-500">Agent</span>
              <span className="font-medium text-white">All</span>
              <ChevronDown className="h-3.5 w-3.5 text-zinc-400" />
            </div>

            {/* Date Range Filter */}
            <div className="flex min-w-[140px] cursor-pointer items-center justify-between gap-2 rounded-lg border border-white/[0.08] bg-white/[0.04] px-3 py-1.5 text-xs text-zinc-300 hover:border-white/20">
              <span className="text-zinc-500">Date Range</span>
              <span className="font-medium text-white">All time</span>
              <ChevronDown className="h-3.5 w-3.5 text-zinc-400" />
            </div>

            {/* Refresh Button */}
            <button
              type="button"
              className="inline-flex items-center justify-center gap-1.5 rounded-lg border border-white/[0.08] bg-white/[0.04] px-3 py-1.5 text-xs font-medium text-zinc-300 transition-colors hover:bg-white/[0.08] hover:text-white"
            >
              <RefreshCw className="h-3.5 w-3.5 text-zinc-400" />
              <span>Refresh</span>
            </button>
          </div>
        </div>

        {/* Main Workflows Table / Empty State Container */}
        <div className="flex min-h-[360px] flex-col overflow-hidden rounded-xl border border-white/[0.08] bg-white/[0.04] backdrop-blur-md">
          {/* Table Header Row */}
          <div className="grid grid-cols-7 gap-4 border-b border-white/[0.08] bg-white/[0.02] px-6 py-3.5 text-xs font-semibold text-zinc-400">
            <div>Workflow Name</div>
            <div>Status</div>
            <div>Current Stage</div>
            <div>Created By</div>
            <div>Duration</div>
            <div>Last Updated</div>
            <div className="text-right">Actions</div>
          </div>

          {/* Table Body Empty State */}
          {WORKFLOWS_PLACEHOLDER.length === 0 && (
            <div className="my-auto flex flex-col items-center justify-center space-y-4 p-12 text-center">
              <div className="flex h-12 w-12 items-center justify-center rounded-xl border border-blue-500/30 bg-blue-950/40 text-blue-400 shadow-sm">
                <GitFork className="h-6 w-6" />
              </div>
              <div className="space-y-1">
                <h3 className="text-base font-semibold text-white">No workflows yet</h3>
                <p className="max-w-sm text-xs text-zinc-400">
                  Create your first workflow from the chat workspace to get started.
                </p>
              </div>
              <Link
                href="/chat"
                className="inline-flex items-center justify-center rounded-lg bg-blue-600 px-4 py-2 text-xs font-medium text-white shadow-sm transition-colors hover:bg-blue-500"
              >
                Create New Workflow
              </Link>
            </div>
          )}
        </div>

        {/* Bottom Feature Cards (4 Columns) */}
        <div className="grid gap-4 pt-2 sm:grid-cols-2 lg:grid-cols-4">
          {/* Card 1 */}
          <div className="rounded-xl border border-white/[0.08] bg-white/[0.04] p-4 backdrop-blur-md">
            <div className="flex items-center gap-3.5">
              <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-blue-600/20 text-blue-400">
                <GitFork className="h-5 w-5" />
              </div>
              <div className="space-y-0.5">
                <h4 className="text-xs font-semibold text-white">AI Orchestration</h4>
                <p className="text-[11px] leading-snug text-zinc-400">
                  Coordinate multiple AI agents seamlessly
                </p>
              </div>
            </div>
          </div>

          {/* Card 2 */}
          <div className="rounded-xl border border-white/[0.08] bg-white/[0.04] p-4 backdrop-blur-md">
            <div className="flex items-center gap-3.5">
              <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-emerald-600/20 text-emerald-400">
                <Play className="h-5 w-5 fill-current" />
              </div>
              <div className="space-y-0.5">
                <h4 className="text-xs font-semibold text-white">Execution Engine</h4>
                <p className="text-[11px] leading-snug text-zinc-400">
                  Execute workflows with reliability
                </p>
              </div>
            </div>
          </div>

          {/* Card 3 */}
          <div className="rounded-xl border border-white/[0.08] bg-white/[0.04] p-4 backdrop-blur-md">
            <div className="flex items-center gap-3.5">
              <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-purple-600/20 text-purple-400">
                <ShieldCheck className="h-5 w-5" />
              </div>
              <div className="space-y-0.5">
                <h4 className="text-xs font-semibold text-white">Validation Layer</h4>
                <p className="text-[11px] leading-snug text-zinc-400">
                  Validate outputs and ensure quality
                </p>
              </div>
            </div>
          </div>

          {/* Card 4 */}
          <div className="rounded-xl border border-white/[0.08] bg-white/[0.04] p-4 backdrop-blur-md">
            <div className="flex items-center gap-3.5">
              <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-amber-600/20 text-amber-400">
                <History className="h-5 w-5" />
              </div>
              <div className="space-y-0.5">
                <h4 className="text-xs font-semibold text-white">Audit Trail</h4>
                <p className="text-[11px] leading-snug text-zinc-400">
                  Full visibility with event tracking
                </p>
              </div>
            </div>
          </div>
        </div>
      </main>
    </AppLayout>
  );
}
