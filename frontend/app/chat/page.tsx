'use client';

import * as React from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { AppLayout, PromptCard, WorkflowStageCard } from '@/components/common';
import { EmptyState } from '@/components/ui';
import { generateAssistantResponse } from '@/lib/mock';
import { ChatMessage } from '@/types';
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
  Paperclip,
  SendHorizontal,
  Bot,
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
  const [messages, setMessages] = React.useState<ChatMessage[]>([]);
  const [isTyping, setIsTyping] = React.useState(false);
  const messagesEndRef = React.useRef<HTMLDivElement>(null);
  const textareaRef = React.useRef<HTMLTextAreaElement>(null);

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  };

  React.useEffect(() => {
    scrollToBottom();
  }, [messages, isTyping]);

  const handleSelectSuggestion = (prompt: string) => {
    setTaskInput(prompt);
    textareaRef.current?.focus();
  };

  const handleTextareaChange = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    setTaskInput(e.target.value);
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto';
      textareaRef.current.style.height = `${Math.min(textareaRef.current.scrollHeight, 160)}px`;
    }
  };

  const handleSendMessage = () => {
    if (!taskInput.trim()) return;

    const timestamp = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    const userMessage: ChatMessage = {
      id: `user-${Date.now()}`,
      sender: 'user',
      content: taskInput.trim(),
      timestamp,
    };

    const currentPrompt = taskInput;
    setMessages((prev) => [...prev, userMessage]);
    setTaskInput('');
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto';
    }

    setIsTyping(true);
    setTimeout(() => {
      const assistantMessage = generateAssistantResponse(currentPrompt);
      setMessages((prev) => [...prev, assistantMessage]);
      setIsTyping(false);
    }, 1000);
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSendMessage();
    }
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

        {/* Conversation Area */}
        {messages.length === 0 ? (
          <EmptyState
            icon={<Sparkles className="h-5 w-5" />}
            title="No workflow started"
            description="Start a conversation to begin or choose a suggestion above."
          />
        ) : (
          <div className="my-4 max-h-[340px] space-y-4 overflow-y-auto rounded-xl border border-white/[0.08] bg-white/[0.03] p-4">
            <AnimatePresence>
              {messages.map((msg) => (
                <motion.div
                  key={msg.id}
                  initial={{ opacity: 0, y: 10 }}
                  animate={{ opacity: 1, y: 0 }}
                  exit={{ opacity: 0 }}
                  className={`flex gap-3 text-xs ${
                    msg.sender === 'user' ? 'justify-end' : 'justify-start'
                  }`}
                >
                  {msg.sender === 'assistant' && (
                    <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg border border-blue-500/30 bg-blue-600/20 text-blue-400">
                      <Bot className="h-4 w-4" />
                    </div>
                  )}

                  <div
                    className={`max-w-[80%] space-y-1 rounded-xl p-3 ${
                      msg.sender === 'user'
                        ? 'bg-blue-600 text-white'
                        : 'border border-white/[0.08] bg-white/[0.04] text-zinc-200'
                    }`}
                  >
                    <div className="flex items-center justify-between gap-4 text-[10px] opacity-75">
                      <span className="font-semibold">
                        {msg.sender === 'user' ? 'You' : 'Keystone AI'}
                      </span>
                      <span>{msg.timestamp}</span>
                    </div>
                    <p className="leading-relaxed">{msg.content}</p>
                  </div>

                  {msg.sender === 'user' && (
                    <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full border border-white/10 bg-zinc-800 text-xs font-semibold text-white">
                      KS
                    </div>
                  )}
                </motion.div>
              ))}
            </AnimatePresence>

            {isTyping && (
              <div className="flex items-center gap-2 pt-2 text-xs text-zinc-400">
                <Bot className="h-4 w-4 animate-spin text-blue-400" />
                <span>Orchestrating agents...</span>
              </div>
            )}
            <div ref={messagesEndRef} />
          </div>
        )}

        {/* Sticky Bottom Chat Composer */}
        <div className="sticky bottom-0 z-10 bg-[#0B1120] pt-4">
          <div className="rounded-xl border border-white/[0.08] bg-[#0B1120]/90 p-4 shadow-xl backdrop-blur-md transition-colors focus-within:border-white/20">
            <textarea
              ref={textareaRef}
              value={taskInput}
              onChange={handleTextareaChange}
              onKeyDown={handleKeyDown}
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
                onClick={handleSendMessage}
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
