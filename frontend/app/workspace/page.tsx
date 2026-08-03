'use client';

import * as React from 'react';
import Link from 'next/link';
import {
  PanelLeft,
  ChevronDown,
  MessageSquare,
  GitFork,
  Bot,
  BookOpen,
  Terminal,
  Settings,
  Code2,
  FileCode,
  CheckSquare,
  ArrowUp,
  ArrowDown,
  FolderGit2,
  Clock,
} from 'lucide-react';
import { Button, Card, CardHeader, CardTitle } from '@/components/ui';

const NAV_ITEMS = [
  { label: 'Chat', icon: MessageSquare, active: true },
  { label: 'Workflows', icon: GitFork },
  { label: 'Agents', icon: Bot },
  { label: 'Knowledge', icon: BookOpen },
  { label: 'Logs', icon: Terminal },
  { label: 'Settings', icon: Settings },
];

const SUGGESTIONS = [
  {
    title: 'Build a REST API with FastAPI',
    description: 'Design endpoints, request models, validation, and async route handlers.',
    prompt: 'Build a REST API with FastAPI including endpoint routing and request validation.',
    icon: Code2,
  },
  {
    title: 'Create a Supply Chain AI Workflow',
    description: 'Orchestrate autonomous agents for logistics monitoring and inventory planning.',
    prompt: 'Create a Supply Chain AI Workflow to monitor inventory flow and detect delays.',
    icon: GitFork,
  },
  {
    title: 'Review my React Project',
    description: 'Inspect component architecture, state management, and performance bottlenecks.',
    prompt: 'Review my React project for component structure and performance best practices.',
    icon: FileCode,
  },
  {
    title: 'Generate Unit Tests',
    description: 'Draft comprehensive automated test suites and mock specifications.',
    prompt: 'Generate unit tests for service functions and handle edge-case scenarios.',
    icon: CheckSquare,
  },
];

const PIPELINE_STAGES = [
  { role: 'Planner', description: 'Decompose goal into sequential tasks' },
  { role: 'Executor', description: 'Run agent tools & code generation' },
  { role: 'Validator', description: 'Assert output schemas & syntax' },
  { role: 'Reporter', description: 'Synthesize final execution report' },
];

export default function WorkspacePage() {
  const [isSidebarCollapsed, setIsSidebarCollapsed] = React.useState(false);
  const [taskInput, setTaskInput] = React.useState('');

  const handleSelectSuggestion = (prompt: string) => {
    setTaskInput(prompt);
  };

  return (
    <div className="bg-background text-foreground flex min-h-screen flex-col font-sans">
      <div className="flex flex-1 overflow-hidden">
        {/* Left Sidebar (280px, Collapsible) */}
        <aside
          className={`border-border/40 bg-card/20 relative hidden flex-col border-r transition-all duration-200 ease-in-out md:flex ${
            isSidebarCollapsed ? 'w-16' : 'w-[280px]'
          }`}
        >
          {/* Sidebar Header / Logo */}
          <div className="border-border/40 flex h-16 items-center justify-between border-b px-4">
            <Link
              href="/"
              className={`flex items-center gap-2.5 transition-opacity hover:opacity-90 ${
                isSidebarCollapsed ? 'w-full justify-center' : ''
              }`}
            >
              <div className="bg-foreground text-background flex h-7 w-7 shrink-0 items-center justify-center rounded-md text-xs font-bold">
                K
              </div>
              {!isSidebarCollapsed && (
                <span className="text-foreground text-base font-bold tracking-tight">Keystone</span>
              )}
            </Link>

            {!isSidebarCollapsed && (
              <Button
                variant="ghost"
                size="icon"
                className="text-muted-foreground hover:text-foreground h-8 w-8"
                onClick={() => setIsSidebarCollapsed(true)}
                aria-label="Collapse sidebar"
              >
                <PanelLeft className="h-4 w-4" />
              </Button>
            )}
          </div>

          {/* Sidebar Expand Toggle when Collapsed */}
          {isSidebarCollapsed && (
            <div className="border-border/40 flex justify-center border-b p-3">
              <Button
                variant="ghost"
                size="icon"
                className="text-muted-foreground hover:text-foreground h-8 w-8"
                onClick={() => setIsSidebarCollapsed(false)}
                aria-label="Expand sidebar"
              >
                <PanelLeft className="h-4 w-4" />
              </Button>
            </div>
          )}

          {/* Sidebar Navigation Items */}
          <nav className="flex-1 space-y-1 p-3">
            {NAV_ITEMS.map((item) => {
              const IconComponent = item.icon;
              return (
                <button
                  key={item.label}
                  className={`flex w-full items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-medium transition-colors ${
                    item.active
                      ? 'bg-secondary text-foreground font-semibold'
                      : 'text-muted-foreground hover:bg-muted/50 hover:text-foreground'
                  } ${isSidebarCollapsed ? 'justify-center px-2' : ''}`}
                  title={isSidebarCollapsed ? item.label : undefined}
                >
                  <IconComponent className="h-4 w-4 shrink-0" />
                  {!isSidebarCollapsed && <span>{item.label}</span>}
                </button>
              );
            })}
          </nav>
        </aside>

        {/* Main Content Area */}
        <div className="flex flex-1 flex-col overflow-y-auto">
          {/* Top Header */}
          <header className="border-border/40 bg-background/90 sticky top-0 z-30 flex h-16 w-full items-center justify-between border-b px-6 backdrop-blur-md">
            <div className="flex items-center gap-4">
              <h1 className="text-foreground text-base font-bold tracking-tight">Workspace</h1>
              <div className="bg-border/40 h-4 w-px" />

              {/* Current Project Selector */}
              <div className="border-border/60 bg-muted/30 text-foreground hover:bg-muted/50 flex cursor-pointer items-center gap-2 rounded-md border px-3 py-1.5 text-xs font-medium">
                <FolderGit2 className="text-muted-foreground h-3.5 w-3.5" />
                <span>Keystone AI Orchestrator</span>
                <ChevronDown className="text-muted-foreground h-3.5 w-3.5" />
              </div>
            </div>

            {/* User Avatar */}
            <div className="flex items-center gap-3">
              <div className="border-border bg-muted text-foreground flex h-8 w-8 items-center justify-center rounded-full border text-xs font-semibold select-none">
                KS
              </div>
            </div>
          </header>

          {/* Main Body Grid */}
          <main className="mx-auto flex w-full max-w-7xl flex-1 flex-col gap-8 p-6 md:p-8">
            {/* Split Panels Container */}
            <div className="grid flex-1 gap-8 lg:grid-cols-10">
              {/* LEFT PANEL (70%) */}
              <div className="flex flex-col justify-between space-y-6 lg:col-span-7">
                {/* Title & Centered Suggestions */}
                <div className="flex flex-1 flex-col items-center justify-center space-y-8 py-8 text-center">
                  <h2 className="text-foreground text-2xl font-semibold tracking-tight sm:text-3xl">
                    How can Keystone help today?
                  </h2>

                  {/* 4 Prompt Suggestion Cards */}
                  <div className="grid w-full gap-4 text-left sm:grid-cols-2">
                    {SUGGESTIONS.map((item) => {
                      const IconComponent = item.icon;
                      return (
                        <Card
                          key={item.title}
                          onClick={() => handleSelectSuggestion(item.prompt)}
                          className="border-border bg-card/40 hover:border-muted-foreground/40 hover:bg-card cursor-pointer rounded-xl border p-1.5 transition-all duration-200"
                        >
                          <CardHeader className="flex flex-row items-center gap-3 p-4">
                            <div className="border-border bg-muted/40 text-foreground flex h-9 w-9 shrink-0 items-center justify-center rounded-lg border">
                              <IconComponent className="h-4 w-4" />
                            </div>
                            <div className="space-y-1">
                              <CardTitle className="text-foreground text-sm leading-snug font-semibold">
                                {item.title}
                              </CardTitle>
                              <p className="text-muted-foreground line-clamp-1 text-xs">
                                {item.description}
                              </p>
                            </div>
                          </CardHeader>
                        </Card>
                      );
                    })}
                  </div>
                </div>

                {/* Bottom Multiline Task Input */}
                <div className="border-border bg-card/80 focus-within:border-muted-foreground/40 rounded-xl border p-3.5 shadow-sm transition-colors">
                  <textarea
                    value={taskInput}
                    onChange={(e) => setTaskInput(e.target.value)}
                    placeholder="Describe your task..."
                    rows={3}
                    className="placeholder:text-muted-foreground w-full resize-none bg-transparent px-1 text-sm focus:outline-none"
                  />
                  <div className="border-border/40 flex items-center justify-end border-t pt-2.5">
                    <Button size="sm" className="gap-2 px-4 py-2 font-medium">
                      <span>Send</span>
                      <ArrowUp className="h-4 w-4" />
                    </Button>
                  </div>
                </div>
              </div>

              {/* RIGHT PANEL (30%) - Workflow Monitor */}
              <div className="border-border bg-card/20 flex flex-col space-y-6 rounded-xl border p-5 lg:col-span-3">
                <div className="border-border/40 space-y-1 border-b pb-4">
                  <h3 className="text-foreground text-sm font-bold tracking-tight uppercase">
                    Workflow Monitor
                  </h3>
                  <p className="text-muted-foreground text-xs">Execution Pipeline Stages</p>
                </div>

                {/* Vertical Execution Pipeline */}
                <div className="flex flex-1 flex-col space-y-3">
                  {PIPELINE_STAGES.map((stage, index) => (
                    <React.Fragment key={stage.role}>
                      <div className="border-border bg-card/60 space-y-2 rounded-lg border p-3">
                        <div className="flex items-center justify-between">
                          <span className="text-foreground text-xs font-semibold">
                            {stage.role}
                          </span>
                          <span className="border-border/60 bg-muted/40 text-muted-foreground inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-[10px] font-medium">
                            <span className="bg-muted-foreground/60 h-1.5 w-1.5 rounded-full" />
                            Waiting
                          </span>
                        </div>
                        <p className="text-muted-foreground text-[11px] leading-tight">
                          {stage.description}
                        </p>
                      </div>

                      {index < PIPELINE_STAGES.length - 1 && (
                        <div className="flex justify-center py-0.5">
                          <ArrowDown className="text-muted-foreground/50 h-3.5 w-3.5" />
                        </div>
                      )}
                    </React.Fragment>
                  ))}
                </div>
              </div>
            </div>

            {/* Bottom Section - Recent Activity Empty State */}
            <div className="border-border/60 bg-card/20 space-y-3 rounded-xl border p-6">
              <h3 className="text-foreground text-sm font-semibold">Recent Activity</h3>
              <div className="border-border/60 text-muted-foreground flex items-center justify-center gap-2 rounded-lg border border-dashed py-8 text-center text-xs">
                <Clock className="h-4 w-4" />
                <span>No workflow executed yet.</span>
              </div>
            </div>
          </main>
        </div>
      </div>
    </div>
  );
}
