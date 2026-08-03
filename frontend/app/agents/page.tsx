'use client';

import * as React from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { AppLayout } from '@/components/common';
import { INITIAL_AGENTS } from '@/lib/mock';
import { AgentModel } from '@/types';
import {
  Bot,
  Search,
  RefreshCw,
  Plus,
  Package,
  BookOpen,
  Terminal,
  ShieldCheck,
  FileText,
  ArrowRight,
  X,
} from 'lucide-react';

export default function AgentsPage() {
  const [agents, setAgents] = React.useState<AgentModel[]>(INITIAL_AGENTS);
  const [searchTerm, setSearchTerm] = React.useState('');
  const [statusFilter, setStatusFilter] = React.useState('All');
  const [selectedAgent, setSelectedAgent] = React.useState<AgentModel | null>(null);
  const [isRegisterOpen, setIsRegisterOpen] = React.useState(false);
  const [newAgentName, setNewAgentName] = React.useState('');
  const [newAgentDesc, setNewAgentDesc] = React.useState('');
  const [newAgentTools, setNewAgentTools] = React.useState('');

  React.useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        setSelectedAgent(null);
        setIsRegisterOpen(false);
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, []);

  const handleRegisterAgent = (e: React.FormEvent) => {
    e.preventDefault();
    if (!newAgentName.trim()) return;

    const newAgent: AgentModel = {
      id: `agent-${Date.now()}`,
      name: newAgentName.trim(),
      badge: 'Waiting',
      dotBg: 'bg-blue-500',
      description: newAgentDesc.trim() || 'Custom AI Agent',
      type: 'Custom Agent',
      capabilities: 'Custom Automated Execution',
      tools: newAgentTools.trim() || 'Custom Tools',
      version: '1.0.0',
      lastSeen: 'Just now',
    };

    setAgents((prev) => [...prev, newAgent]);
    setNewAgentName('');
    setNewAgentDesc('');
    setNewAgentTools('');
    setIsRegisterOpen(false);
  };

  const filteredAgents = agents.filter((agent) => {
    const matchesSearch =
      agent.name.toLowerCase().includes(searchTerm.toLowerCase()) ||
      agent.capabilities.toLowerCase().includes(searchTerm.toLowerCase());
    const matchesStatus = statusFilter === 'All' || agent.badge === statusFilter;
    return matchesSearch && matchesStatus;
  });

  const getAgentIcon = (name: string) => {
    switch (name) {
      case 'Planner':
        return Package;
      case 'Research':
        return BookOpen;
      case 'Executor':
        return Terminal;
      case 'Validator':
        return ShieldCheck;
      case 'Reporter':
        return FileText;
      default:
        return Bot;
    }
  };

  const getAgentIconBg = (name: string) => {
    switch (name) {
      case 'Planner':
        return 'bg-blue-600/20 text-blue-400';
      case 'Research':
        return 'bg-emerald-600/20 text-emerald-400';
      case 'Executor':
        return 'bg-purple-600/20 text-purple-400';
      case 'Validator':
        return 'bg-amber-600/20 text-amber-400';
      case 'Reporter':
        return 'bg-cyan-600/20 text-cyan-400';
      default:
        return 'bg-blue-600/20 text-blue-400';
    }
  };

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
            onClick={() => setIsRegisterOpen(true)}
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
              <select
                value={statusFilter}
                onChange={(e) => setStatusFilter(e.target.value)}
                className="cursor-pointer bg-transparent font-medium text-white focus:outline-none"
              >
                <option value="All" className="bg-[#0B1120] text-white">
                  All
                </option>
                <option value="Waiting" className="bg-[#0B1120] text-white">
                  Waiting
                </option>
                <option value="Active" className="bg-[#0B1120] text-white">
                  Active
                </option>
              </select>
            </div>

            {/* Refresh Button */}
            <button
              type="button"
              onClick={() => setSearchTerm('')}
              className="inline-flex items-center justify-center gap-1.5 rounded-lg border border-white/[0.08] bg-white/[0.04] px-3 py-1.5 text-xs font-medium text-zinc-300 transition-colors hover:bg-white/[0.08] hover:text-white"
            >
              <RefreshCw className="h-3.5 w-3.5 text-zinc-400" />
              <span>Refresh</span>
            </button>
          </div>
        </div>

        {/* System Agent Cards Grid */}
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-5">
          {filteredAgents.map((agent) => {
            const IconComponent = getAgentIcon(agent.name);
            const iconBg = getAgentIconBg(agent.name);
            return (
              <div
                key={agent.id}
                className="flex flex-col justify-between space-y-4 rounded-xl border border-white/[0.08] bg-white/[0.04] p-4 backdrop-blur-md"
              >
                <div className="space-y-3">
                  {/* Top Card Header */}
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2.5">
                      <div
                        className={`flex h-8 w-8 items-center justify-center rounded-lg ${iconBg}`}
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
                  onClick={() => setSelectedAgent(agent)}
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
            onClick={() => setIsRegisterOpen(true)}
            className="inline-flex items-center gap-1.5 pt-1 text-xs font-semibold text-blue-400 transition-colors hover:text-blue-300"
          >
            <span>Register your first agent</span>
            <ArrowRight className="h-3.5 w-3.5" />
          </button>
        </div>

        {/* View Details Drawer / Modal */}
        <AnimatePresence>
          {selectedAgent && (
            <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4 backdrop-blur-sm">
              <motion.div
                initial={{ scale: 0.95, opacity: 0 }}
                animate={{ scale: 1, opacity: 1 }}
                exit={{ scale: 0.95, opacity: 0 }}
                className="w-full max-w-md space-y-4 rounded-xl border border-white/[0.08] bg-[#0B1120] p-6 shadow-2xl"
              >
                <div className="flex items-center justify-between border-b border-white/[0.08] pb-3">
                  <h3 className="text-sm font-bold text-white">
                    Agent Details: {selectedAgent.name}
                  </h3>
                  <button
                    type="button"
                    onClick={() => setSelectedAgent(null)}
                    className="text-zinc-400 hover:text-white"
                  >
                    <X className="h-4 w-4" />
                  </button>
                </div>

                <div className="space-y-3 text-xs text-zinc-300">
                  <div>
                    <span className="block text-zinc-500">Description</span>
                    <p className="mt-0.5 text-white">{selectedAgent.description}</p>
                  </div>
                  <div>
                    <span className="block text-zinc-500">Type</span>
                    <p className="mt-0.5 text-white">{selectedAgent.type}</p>
                  </div>
                  <div>
                    <span className="block text-zinc-500">Capabilities</span>
                    <p className="mt-0.5 text-white">{selectedAgent.capabilities}</p>
                  </div>
                  <div>
                    <span className="block text-zinc-500">Tools</span>
                    <p className="mt-0.5 text-white">{selectedAgent.tools}</p>
                  </div>
                  <div>
                    <span className="block text-zinc-500">Status</span>
                    <p className="mt-0.5 text-white">{selectedAgent.badge}</p>
                  </div>
                </div>

                <div className="flex justify-end border-t border-white/[0.08] pt-2">
                  <button
                    type="button"
                    onClick={() => setSelectedAgent(null)}
                    className="rounded-lg bg-blue-600 px-4 py-2 text-xs font-medium text-white hover:bg-blue-500"
                  >
                    Close
                  </button>
                </div>
              </motion.div>
            </div>
          )}
        </AnimatePresence>

        {/* Register Agent Modal */}
        <AnimatePresence>
          {isRegisterOpen && (
            <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4 backdrop-blur-sm">
              <motion.div
                initial={{ scale: 0.95, opacity: 0 }}
                animate={{ scale: 1, opacity: 1 }}
                exit={{ scale: 0.95, opacity: 0 }}
                className="w-full max-w-md space-y-4 rounded-xl border border-white/[0.08] bg-[#0B1120] p-6 shadow-2xl"
              >
                <div className="flex items-center justify-between border-b border-white/[0.08] pb-3">
                  <h3 className="text-sm font-bold text-white">Register New Agent</h3>
                  <button
                    type="button"
                    onClick={() => setIsRegisterOpen(false)}
                    className="text-zinc-400 hover:text-white"
                  >
                    <X className="h-4 w-4" />
                  </button>
                </div>

                <form onSubmit={handleRegisterAgent} className="space-y-3 text-xs">
                  <div className="space-y-1">
                    <label className="block font-medium text-zinc-400">Agent Name</label>
                    <input
                      type="text"
                      value={newAgentName}
                      onChange={(e) => setNewAgentName(e.target.value)}
                      placeholder="e.g. Security Analyzer Agent"
                      className="w-full rounded-lg border border-white/[0.08] bg-white/[0.04] px-3 py-2 text-white placeholder:text-zinc-500 focus:border-white/20 focus:outline-none"
                      required
                    />
                  </div>

                  <div className="space-y-1">
                    <label className="block font-medium text-zinc-400">Description</label>
                    <input
                      type="text"
                      value={newAgentDesc}
                      onChange={(e) => setNewAgentDesc(e.target.value)}
                      placeholder="e.g. Scans outputs for security vulnerabilities"
                      className="w-full rounded-lg border border-white/[0.08] bg-white/[0.04] px-3 py-2 text-white placeholder:text-zinc-500 focus:border-white/20 focus:outline-none"
                    />
                  </div>

                  <div className="space-y-1">
                    <label className="block font-medium text-zinc-400">Tools</label>
                    <input
                      type="text"
                      value={newAgentTools}
                      onChange={(e) => setNewAgentTools(e.target.value)}
                      placeholder="e.g. Snyk, SonarQube, Linter"
                      className="w-full rounded-lg border border-white/[0.08] bg-white/[0.04] px-3 py-2 text-white placeholder:text-zinc-500 focus:border-white/20 focus:outline-none"
                    />
                  </div>

                  <div className="flex justify-end gap-2 pt-3">
                    <button
                      type="button"
                      onClick={() => setIsRegisterOpen(false)}
                      className="rounded-lg border border-white/[0.08] bg-white/[0.04] px-4 py-2 text-zinc-300 hover:bg-white/[0.08]"
                    >
                      Cancel
                    </button>
                    <button
                      type="submit"
                      className="rounded-lg bg-blue-600 px-4 py-2 font-medium text-white shadow-sm hover:bg-blue-500"
                    >
                      Register Agent
                    </button>
                  </div>
                </form>
              </motion.div>
            </div>
          )}
        </AnimatePresence>
      </main>
    </AppLayout>
  );
}
