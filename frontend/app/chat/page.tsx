'use client';

import * as React from 'react';
import { AppLayout, PromptCard, WorkflowStageCard, ChatComposer } from '@/components/common';
import { EmptyState } from '@/components/ui';
import {
  Code2,
  Atom,
  BarChart3,
  Bug,
  FileText,
  Search,
  Sparkles,
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
  },
  {
    name: 'Research',
    badge: 'Waiting',
    description: 'Gather context and relevant information',
    icon: BookOpen,
    iconBg: 'bg-emerald-600/20 text-emerald-400',
  },
  {
    name: 'Executor',
    badge: 'Waiting',
    description: 'Execute tasks and build requested solution',
    icon: Terminal,
    iconBg: 'bg-purple-600/20 text-purple-400',
  },
  {
    name: 'Validator',
    badge: 'Waiting',
    description: 'Validate results and ensure quality standards',
    icon: ShieldCheck,
    iconBg: 'bg-amber-600/20 text-amber-400',
  },
  {
    name: 'Reporter',
    badge: 'Waiting',
    description: 'Generate summary and final report',
    icon: FileText,
    iconBg: 'bg-cyan-600/20 text-cyan-400',
  },
];

export default function ChatPage() {
  const [taskInput, setTaskInput] = React.useState('');

  const handleSelectSuggestion = (prompt: string) => {
    setTaskInput(prompt);
  };

  return (
    <AppLayout showSidebar={true}>
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
            {SUGGESTIONS.map((item) => (
              <PromptCard
                key={item.title}
                title={item.title}
                subtitle={item.subtitle}
                prompt={item.prompt}
                icon={item.icon}
                iconBg={item.iconBg}
                onSelect={handleSelectSuggestion}
              />
            ))}
          </div>
        </div>

        {/* Conversation Area (Empty State) */}
        <EmptyState
          icon={<Sparkles className="h-5 w-5" />}
          title="No workflow started"
          description="Start a conversation to begin or choose a suggestion above."
        />

        {/* Sticky Bottom Chat Composer */}
        <ChatComposer value={taskInput} onChange={setTaskInput} />
      </main>

      {/* Right Workflow Execution Panel (~320px) */}
      <aside className="hidden w-[320px] shrink-0 flex-col justify-between space-y-6 border-l border-white/[0.08] bg-[#0B1120]/80 p-6 lg:flex">
        <div className="space-y-4">
          <h2 className="text-base font-semibold text-white">Workflow Execution</h2>

          {/* Vertical Execution Pipeline */}
          <div className="relative space-y-3">
            {WORKFLOW_STAGES.map((stage, index) => (
              <WorkflowStageCard
                key={stage.name}
                name={stage.name}
                badge={stage.badge}
                description={stage.description}
                icon={stage.icon}
                iconBg={stage.iconBg}
                isLast={index === WORKFLOW_STAGES.length - 1}
              />
            ))}
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
    </AppLayout>
  );
}
