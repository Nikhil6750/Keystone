'use client';

import * as React from 'react';
import { AppLayout } from '@/components/common';
import {
  Bot,
  Search,
  ChevronDown,
  RefreshCw,
  Plus,
  Package,
  BookOpen,
  Terminal,
  ShieldCheck,
  FileText,
  ArrowRight,
} from 'lucide-react';

const SYSTEM_AGENTS = [
  {
    name: 'Planner',
    badge: 'Waiting',
    dotBg: 'bg-blue-500',
    description: 'Understand goal and create execution plan',
    icon: Package,
    iconBg: 'bg-blue-600/20 text-blue-400',
    type: 'System Agent',
    capabilities: 'Planning, Reasoning, Task Decomposition',
    tools: 'Memory, File Read, Web Search',
    version: '1.0.0',
    lastSeen: '-',
  },
  {
    name: 'Research',
    badge: 'Waiting',
    dotBg: 'bg-emerald-500',
    description: 'Gather context and relevant information',
    icon: BookOpen,
    iconBg: 'bg-emerald-600/20 text-emerald-400',
    type: 'System Agent',
    capabilities: 'Information Retrieval, Analysis, Summarization',
    tools: 'Web Search, File Read, APIs',
    version: '1.0.0',
    lastSeen: '-',
  },
  {
    name: 'Executor',
    badge: 'Waiting',
    dotBg: 'bg-purple-500',
    description: 'Execute tasks and build requested solution',
    icon: Terminal,
    iconBg: 'bg-purple-600/20 text-purple-400',
    type: 'System Agent',
    capabilities: 'Code Execution, API Calls, Task Execution',
    tools: 'Code Runner, APIs, File Write',
    version: '1.0.0',
    lastSeen: '-',
  },
  {
    name: 'Validator',
    badge: 'Waiting',
    dotBg: 'bg-amber-500',
    description: 'Validate results and ensure quality standards',
    icon: ShieldCheck,
    iconBg: 'bg-amber-600/20 text-amber-400',
    type: 'System Agent',
    capabilities: 'Validation, Testing, Quality Assurance',
    tools: 'Test Runner, Lint, Analyzer',
    version: '1.0.0',
    lastSeen: '-',
  },
  {
    name: 'Reporter',
    badge: 'Waiting',
    dotBg: 'bg-cyan-500',
    description: 'Generate summary and final report',
    icon: FileText,
    iconBg: 'bg-cyan-600/20 text-cyan-400',
    type: 'System Agent',
    capabilities: 'Reporting, Documentation, Visualization',
    tools: 'File Write, Templates',
    version: '1.0.0',
    lastSeen: '-',
  },
];

export default function AgentsPage() {
  const [searchTerm, setSearchTerm] = React.useState('');

  return (
    <AppLayout showSidebar={true}>
      <main className="flex flex-1 flex-col justify-between space-y-8 overflow-y-auto p-6 md:p-8">
        {/* Header Section */}
        <div className="flex flex-col justify-between gap-4 sm:flex-row sm:items-center">
          <div className="space-y-1">
            <span className="text-xs font-bold tracking-wider text-blue-400 uppercase">AGENTS</span>
            <h1 className="text-3xl font-bold tracking-tight text-white sm:text-4xl">AI Agents</h1>
            <p className="text-sm leading-relaxed text-zinc-400">
              Manage and monitor AI agents that execute workflows. Configure capabilities, tools and
              settings.
            </p>
          </div>

          <button
            type="button"
            className="inline-flex shrink-0 items-center justify-center gap-1.5 self-start rounded-lg bg-blue-600 px-4 py-2 text-xs font-medium text-white shadow-sm transition-colors hover:bg-blue-500 sm:self-auto"
          >
            <Plus className="h-4 w-4" />
            <span>Register Agent</span>
          </button>
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
              placeholder="Search agents..."
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

            {/* Capability Filter */}
            <div className="flex min-w-[140px] cursor-pointer items-center justify-between gap-2 rounded-lg border border-white/[0.08] bg-white/[0.04] px-3 py-1.5 text-xs text-zinc-300 hover:border-white/20">
              <span className="text-zinc-500">Capability</span>
              <span className="font-medium text-white">All</span>
              <ChevronDown className="h-3.5 w-3.5 text-zinc-400" />
            </div>

            {/* Type Filter */}
            <div className="flex min-w-[120px] cursor-pointer items-center justify-between gap-2 rounded-lg border border-white/[0.08] bg-white/[0.04] px-3 py-1.5 text-xs text-zinc-300 hover:border-white/20">
              <span className="text-zinc-500">Type</span>
              <span className="font-medium text-white">All</span>
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

        {/* 5 System Agent Cards (Horizontal 5-Column Grid) */}
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-5">
          {SYSTEM_AGENTS.map((agent) => {
            const IconComponent = agent.icon;
            return (
              <div
                key={agent.name}
                className="flex flex-col justify-between space-y-4 rounded-xl border border-white/[0.08] bg-white/[0.04] p-4 backdrop-blur-md"
              >
                <div className="space-y-3">
                  {/* Top Card Header */}
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2.5">
                      <div
                        className={`flex h-8 w-8 items-center justify-center rounded-lg ${agent.iconBg}`}
                      >
                        <IconComponent className="h-4 w-4" />
                      </div>
                      <h3 className="text-xs font-bold text-white">{agent.name}</h3>
                    </div>
                    <span className="inline-flex items-center gap-1 rounded-full border border-white/[0.08] bg-white/[0.04] px-2 py-0.5 text-[10px] font-medium text-zinc-300">
                      <span className={`h-1.5 w-1.5 rounded-full ${agent.dotBg}`} />
                      {agent.badge}
                    </span>
                  </div>

                  <p className="text-[11px] leading-snug text-zinc-400">{agent.description}</p>

                  {/* Properties List */}
                  <div className="space-y-2 border-t border-white/[0.06] pt-2 text-[11px]">
                    <div>
                      <span className="block text-zinc-500">Type</span>
                      <span className="font-medium text-zinc-300">{agent.type}</span>
                    </div>

                    <div>
                      <span className="block text-zinc-500">Capabilities</span>
                      <span className="font-medium text-zinc-300">{agent.capabilities}</span>
                    </div>

                    <div>
                      <span className="block text-zinc-500">Tools</span>
                      <span className="font-medium text-zinc-300">{agent.tools}</span>
                    </div>

                    <div>
                      <span className="block text-zinc-500">Version</span>
                      <span className="font-medium text-zinc-300">{agent.version}</span>
                    </div>

                    <div>
                      <span className="block text-zinc-500">Last Seen</span>
                      <span className="font-medium text-zinc-300">{agent.lastSeen}</span>
                    </div>
                  </div>
                </div>

                {/* View Details Action Button */}
                <button
                  type="button"
                  className="w-full rounded-lg border border-white/[0.08] bg-white/[0.04] py-2 text-xs font-medium text-zinc-300 transition-colors hover:bg-white/[0.08] hover:text-white"
                >
                  View Details
                </button>
              </div>
            );
          })}
        </div>

        {/* Bottom Empty State Box */}
        <div className="flex flex-col items-center justify-center space-y-3 rounded-xl border border-white/[0.08] bg-white/[0.03] p-8 text-center backdrop-blur-md">
          <div className="flex h-12 w-12 items-center justify-center rounded-xl border border-purple-500/30 bg-purple-950/40 text-purple-400 shadow-sm">
            <Bot className="h-6 w-6" />
          </div>
          <div className="space-y-1">
            <h3 className="text-base font-semibold text-white">No custom agents registered</h3>
            <p className="max-w-sm text-xs text-zinc-400">
              System agents are ready to orchestrate your workflows.
            </p>
          </div>
          <button
            type="button"
            className="inline-flex items-center gap-1.5 pt-1 text-xs font-semibold text-blue-400 transition-colors hover:text-blue-300"
          >
            <span>Register your first agent</span>
            <ArrowRight className="h-3.5 w-3.5" />
          </button>
        </div>
      </main>
    </AppLayout>
  );
}
