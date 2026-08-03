'use client';

import * as React from 'react';
import { Header, Sidebar } from '@/components/common';
import {
  Code2,
  Atom,
  BarChart3,
  Bug,
  FileText,
  Search,
  Sparkles,
  Paperclip,
  SendHorizontal,
  Package,
  BookOpen,
  Terminal,
  ShieldCheck,
  Clock,
} from 'lucide-react';

const SUGGESTIONS = [
  {
    title: 'Build FastAPI Backend',
    subtitle: 'Scalable REST API with authentication',
    prompt: 'Build a FastAPI backend with REST endpoints and authentication.',
    icon: Code2,
    iconBg: 'bg-blue-600/20 text-blue-400',
  },
  {
    title: 'Create React Dashboard',
    subtitle: 'Modern dashboard with charts and tables',
    prompt: 'Create a modern React dashboard layout with charts and tables.',
    icon: Atom,
    iconBg: 'bg-emerald-600/20 text-emerald-400',
  },
  {
    title: 'Analyze CSV Dataset',
    subtitle: 'Extract insights and generate summary reports',
    prompt: 'Analyze a CSV dataset to extract summary insights and data trends.',
    icon: BarChart3,
    iconBg: 'bg-purple-600/20 text-purple-400',
  },
  {
    title: 'Debug Python Code',
    subtitle: 'Find issues and suggest fixes',
    prompt: 'Debug my Python code for runtime exceptions and performance fixes.',
    icon: Bug,
    iconBg: 'bg-amber-600/20 text-amber-400',
  },
  {
    title: 'Generate Test Cases',
    subtitle: 'Create unit and integration test suites',
    prompt: 'Generate unit and integration test suites for core service functions.',
    icon: FileText,
    iconBg: 'bg-cyan-600/20 text-cyan-400',
  },
  {
    title: 'Explain SQL Query',
    subtitle: 'Understand and optimize SQL queries',
    prompt: 'Explain this SQL query execution plan and suggest optimizations.',
    icon: Search,
    iconBg: 'bg-rose-600/20 text-rose-400',
  },
];

const WORKFLOW_STAGES = [
  {
    name: 'Planner',
    badge: 'Waiting',
    description: 'Understand goal and create execution plan',
    icon: Package,
    iconBg: 'bg-blue-600/20 text-blue-400',
    dotBg: 'bg-blue-500',
  },
  {
    name: 'Research',
    badge: 'Waiting',
    description: 'Gather context and relevant information',
    icon: BookOpen,
    iconBg: 'bg-emerald-600/20 text-emerald-400',
    dotBg: 'bg-emerald-500',
  },
  {
    name: 'Executor',
    badge: 'Waiting',
    description: 'Execute tasks and build requested solution',
    icon: Terminal,
    iconBg: 'bg-purple-600/20 text-purple-400',
    dotBg: 'bg-purple-500',
  },
  {
    name: 'Validator',
    badge: 'Waiting',
    description: 'Validate results and ensure quality standards',
    icon: ShieldCheck,
    iconBg: 'bg-amber-600/20 text-amber-400',
    dotBg: 'bg-amber-500',
  },
  {
    name: 'Reporter',
    badge: 'Waiting',
    description: 'Generate summary and final report',
    icon: FileText,
    iconBg: 'bg-cyan-600/20 text-cyan-400',
    dotBg: 'bg-cyan-500',
  },
];

export default function ChatPage() {
  const [taskInput, setTaskInput] = React.useState('');

  const handleSelectSuggestion = (prompt: string) => {
    setTaskInput(prompt);
  };

  return (
    <div className="flex min-h-screen flex-col bg-[#0B1120] font-sans text-white">
      <Header />

      <div className="flex flex-1 overflow-hidden">
        <Sidebar />

        {/* Center Workspace Area */}
        <main className="flex flex-1 flex-col justify-between overflow-y-auto p-6 md:p-8">
          {/* Top Title & Header */}
          <div className="space-y-2">
            <span className="text-xs font-bold tracking-wider text-blue-400 uppercase">
              CHAT WORKSPACE
            </span>
            <h1 className="text-3xl font-bold tracking-tight text-white sm:text-4xl">
              What would you like Keystone to accomplish today?
            </h1>
            <p className="max-w-2xl text-sm leading-relaxed text-zinc-400">
              Describe your goal and Keystone will orchestrate multiple AI agents to plan, execute,
              validate and report the results.
            </p>
          </div>

          {/* 6 Suggestion Cards Grid (2x3) */}
          <div className="py-6">
            <div className="grid w-full gap-4 sm:grid-cols-2 lg:grid-cols-3">
              {SUGGESTIONS.map((item) => {
                const IconComponent = item.icon;
                return (
                  <div
                    key={item.title}
                    onClick={() => handleSelectSuggestion(item.prompt)}
                    className="group cursor-pointer rounded-xl border border-white/[0.08] bg-white/[0.04] p-4 transition-all duration-200 hover:border-white/20 hover:bg-white/[0.06]"
                  >
                    <div className="flex items-center gap-3">
                      <div
                        className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-lg ${item.iconBg}`}
                      >
                        <IconComponent className="h-4 w-4" />
                      </div>
                      <div className="space-y-0.5">
                        <h3 className="text-xs font-semibold text-white transition-colors group-hover:text-blue-300">
                          {item.title}
                        </h3>
                        <p className="line-clamp-1 text-[11px] text-zinc-400">{item.subtitle}</p>
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>

          {/* Conversation Area (Empty State) */}
          <div className="my-auto flex flex-col items-center justify-center space-y-3 rounded-xl border border-white/[0.08] bg-white/[0.03] p-8 text-center">
            <div className="flex h-10 w-10 items-center justify-center rounded-lg border border-white/10 bg-white/5 text-zinc-300">
              <Sparkles className="h-5 w-5" />
            </div>
            <h3 className="text-base font-semibold text-white">No workflow started</h3>
            <p className="max-w-xs text-xs text-zinc-400">
              Start a conversation to begin or choose a suggestion above.
            </p>
          </div>

          {/* Sticky Bottom Chat Composer */}
          <div className="sticky bottom-0 z-10 bg-[#0B1120] pt-4">
            <div className="rounded-xl border border-white/[0.08] bg-[#0B1120]/90 p-4 shadow-xl backdrop-blur-md transition-colors focus-within:border-white/20">
              <textarea
                value={taskInput}
                onChange={(e) => setTaskInput(e.target.value)}
                placeholder="Ask Keystone anything..."
                rows={2}
                className="w-full resize-none bg-transparent text-sm text-white placeholder:text-zinc-500 focus:outline-none"
              />
              <div className="flex items-center justify-between border-t border-white/[0.08] pt-2">
                {/* Left Attachment Button */}
                <button
                  type="button"
                  className="flex h-8 w-8 items-center justify-center rounded-lg border border-white/[0.08] bg-white/[0.04] text-zinc-400 transition-colors hover:text-white"
                  title="Attach file"
                  aria-label="Attach file"
                >
                  <Paperclip className="h-4 w-4" />
                </button>

                {/* Right Send Button */}
                <button
                  type="button"
                  className="flex h-9 w-9 items-center justify-center rounded-lg bg-blue-600 text-white shadow-sm transition-colors hover:bg-blue-500"
                  aria-label="Send message"
                >
                  <SendHorizontal className="h-4 w-4" />
                </button>
              </div>
            </div>
          </div>
        </main>

        {/* Right Workflow Execution Panel (~320px) */}
        <aside className="hidden w-[320px] shrink-0 flex-col justify-between space-y-6 border-l border-white/[0.08] bg-[#0B1120]/80 p-6 lg:flex">
          <div className="space-y-4">
            <h2 className="text-base font-semibold text-white">Workflow Execution</h2>

            {/* Vertical Execution Pipeline */}
            <div className="relative space-y-3">
              {WORKFLOW_STAGES.map((stage, index) => {
                const IconComponent = stage.icon;
                return (
                  <div key={stage.name} className="relative space-y-2">
                    <div className="space-y-2 rounded-xl border border-white/[0.08] bg-white/[0.04] p-4">
                      <div className="flex items-center justify-between">
                        <div className="flex items-center gap-3">
                          <div
                            className={`flex h-8 w-8 items-center justify-center rounded-lg ${stage.iconBg}`}
                          >
                            <IconComponent className="h-4 w-4" />
                          </div>
                          <span className="text-xs font-semibold text-white">{stage.name}</span>
                        </div>
                        <span className="rounded-md border border-white/[0.08] bg-white/[0.04] px-2 py-0.5 text-[10px] font-medium text-zinc-400">
                          {stage.badge}
                        </span>
                      </div>
                      <p className="pl-11 text-[11px] leading-snug text-zinc-400">
                        {stage.description}
                      </p>
                    </div>

                    {/* Vertical Connecting Node */}
                    {index < WORKFLOW_STAGES.length - 1 && (
                      <div className="flex items-center justify-center py-0.5">
                        <div className="h-2 w-2 rounded-full border border-white/20 bg-zinc-800" />
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          </div>

          {/* Recent Activity Section */}
          <div className="space-y-3 border-t border-white/[0.08] pt-4">
            <h3 className="text-xs font-semibold text-white">Recent Activity</h3>
            <div className="flex flex-col items-center justify-center space-y-1.5 rounded-xl border border-white/[0.06] bg-white/[0.02] p-6 text-center">
              <Clock className="h-4 w-4 text-zinc-500" />
              <p className="text-xs font-medium text-zinc-400">No activity yet.</p>
              <p className="text-[11px] text-zinc-500">Workflow events will appear here.</p>
            </div>
          </div>
        </aside>
      </div>
    </div>
  );
}
