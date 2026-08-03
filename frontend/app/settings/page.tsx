'use client';

import * as React from 'react';
import { AppLayout } from '@/components/common';
import {
  Home,
  Sun,
  Cpu,
  Server,
  Key,
  Layers,
  ShieldCheck,
  Bell,
  Info,
  ChevronDown,
  Copy,
  Upload,
  Trash2,
} from 'lucide-react';

const SETTINGS_NAV = [
  { id: 'general', label: 'General', description: 'Workspace and profile', icon: Home },
  { id: 'appearance', label: 'Appearance', description: 'Theme and display', icon: Sun },
  { id: 'models', label: 'Models', description: 'AI models and parameters', icon: Cpu },
  { id: 'providers', label: 'Providers', description: 'LLM providers and endpoints', icon: Server },
  { id: 'apikeys', label: 'API Keys', description: 'Manage API keys', icon: Key },
  {
    id: 'integrations',
    label: 'Integrations',
    description: 'Third-party integrations',
    icon: Layers,
  },
  {
    id: 'security',
    label: 'Security',
    description: 'Authentication and access',
    icon: ShieldCheck,
  },
  { id: 'notifications', label: 'Notifications', description: 'Alerts and updates', icon: Bell },
  { id: 'about', label: 'About', description: 'Version and system info', icon: Info },
];

export default function SettingsPage() {
  const [activeTab, setActiveTab] = React.useState('general');
  const [autoSave, setAutoSave] = React.useState(true);
  const [confirmDestructive, setConfirmDestructive] = React.useState(true);
  const [enableTelemetry, setEnableTelemetry] = React.useState(false);

  return (
    <AppLayout showSidebar={true}>
      <main className="flex flex-1 flex-col justify-between space-y-6 overflow-y-auto p-6 md:p-8">
        {/* Header Section */}
        <div className="space-y-1">
          <h1 className="text-3xl font-bold tracking-tight text-white sm:text-4xl">Settings</h1>
          <p className="text-sm leading-relaxed text-zinc-400">
            Configure Keystone to match your workflow and preferences.
          </p>
        </div>

        {/* Settings Grid (25% Left Nav / 75% Right Main Panel) */}
        <div className="grid flex-1 gap-6 lg:grid-cols-10">
          {/* LEFT SUB-NAVIGATION MENU (25%) */}
          <div className="space-y-1 lg:col-span-3">
            {SETTINGS_NAV.map((item) => {
              const IconComponent = item.icon;
              const isActive = activeTab === item.id;
              return (
                <button
                  key={item.id}
                  type="button"
                  onClick={() => setActiveTab(item.id)}
                  className={`flex w-full items-center gap-3 rounded-xl px-4 py-3 text-left transition-colors ${
                    isActive
                      ? 'border border-blue-500/30 bg-blue-950/40 font-semibold text-white shadow-sm'
                      : 'text-zinc-400 hover:bg-white/[0.04] hover:text-white'
                  }`}
                >
                  <IconComponent
                    className={`h-4 w-4 shrink-0 ${isActive ? 'text-blue-400' : 'text-zinc-400'}`}
                  />
                  <div className="space-y-0.5">
                    <div className="text-xs font-semibold">{item.label}</div>
                    <div className="text-[11px] text-zinc-500">{item.description}</div>
                  </div>
                </button>
              );
            })}
          </div>

          {/* RIGHT MAIN SETTINGS PANEL (75%) */}
          <div className="flex flex-col space-y-6 lg:col-span-7">
            {/* Top General Header & Save Changes Button */}
            <div className="flex items-center justify-between border-b border-white/[0.08] pb-4">
              <div>
                <h2 className="text-lg font-bold text-white">General</h2>
                <p className="text-xs text-zinc-400">
                  Manage your workspace settings and profile information.
                </p>
              </div>
              <button
                type="button"
                className="rounded-lg bg-blue-600 px-4 py-2 text-xs font-medium text-white shadow-sm transition-colors hover:bg-blue-500"
              >
                Save Changes
              </button>
            </div>

            {/* Section 1: Workspace Information */}
            <div className="space-y-4 rounded-xl border border-white/[0.08] bg-white/[0.04] p-5 backdrop-blur-md">
              <div>
                <h3 className="text-xs font-bold text-white">Workspace Information</h3>
                <p className="text-[11px] text-zinc-400">Basic information about your workspace.</p>
              </div>

              <div className="grid gap-4 text-xs sm:grid-cols-2">
                <div className="space-y-1.5">
                  <label className="block font-medium text-zinc-400">Workspace Name</label>
                  <input
                    type="text"
                    defaultValue="Keystone"
                    className="w-full rounded-lg border border-white/[0.08] bg-white/[0.04] px-3 py-2 text-white placeholder:text-zinc-500 focus:border-white/20 focus:outline-none"
                  />
                </div>

                <div className="space-y-1.5">
                  <label className="block font-medium text-zinc-400">Workspace ID</label>
                  <div className="flex items-center gap-2 rounded-lg border border-white/[0.08] bg-white/[0.04] px-3 py-2 text-zinc-300">
                    <span className="w-full font-mono text-xs text-zinc-400">ks_7f3a2c1e8b9d</span>
                    <button
                      type="button"
                      className="text-zinc-400 transition-colors hover:text-white"
                      title="Copy ID"
                    >
                      <Copy className="h-3.5 w-3.5" />
                    </button>
                  </div>
                </div>
              </div>
            </div>

            {/* Section 2: Profile */}
            <div className="space-y-4 rounded-xl border border-white/[0.08] bg-white/[0.04] p-5 backdrop-blur-md">
              <div>
                <h3 className="text-xs font-bold text-white">Profile</h3>
                <p className="text-[11px] text-zinc-400">Your personal profile information.</p>
              </div>

              <div className="grid items-end gap-4 text-xs sm:grid-cols-2">
                <div className="space-y-1.5">
                  <label className="block font-medium text-zinc-400">Display Name</label>
                  <input
                    type="text"
                    defaultValue="KS"
                    className="w-full rounded-lg border border-white/[0.08] bg-white/[0.04] px-3 py-2 text-white placeholder:text-zinc-500 focus:border-white/20 focus:outline-none"
                  />
                </div>

                <div className="space-y-1.5">
                  <label className="block font-medium text-zinc-400">Email</label>
                  <input
                    type="email"
                    defaultValue="ks@example.com"
                    className="w-full rounded-lg border border-white/[0.08] bg-white/[0.04] px-3 py-2 text-white placeholder:text-zinc-500 focus:border-white/20 focus:outline-none"
                  />
                </div>

                <div className="flex items-center gap-4 pt-2 sm:col-span-2">
                  <div className="flex h-10 w-10 items-center justify-center rounded-full border border-white/10 bg-zinc-800 text-xs font-bold text-white">
                    KS
                  </div>
                  <button
                    type="button"
                    className="inline-flex items-center gap-1.5 rounded-lg border border-white/[0.08] bg-white/[0.04] px-3 py-1.5 text-xs font-medium text-zinc-300 transition-colors hover:bg-white/[0.08] hover:text-white"
                  >
                    <Upload className="h-3.5 w-3.5" />
                    <span>Change Avatar</span>
                  </button>
                </div>
              </div>
            </div>

            {/* Section 3: Language & Region */}
            <div className="space-y-4 rounded-xl border border-white/[0.08] bg-white/[0.04] p-5 backdrop-blur-md">
              <div>
                <h3 className="text-xs font-bold text-white">Language & Region</h3>
                <p className="text-[11px] text-zinc-400">
                  Set your language and regional preferences.
                </p>
              </div>

              <div className="grid gap-4 text-xs sm:grid-cols-3">
                <div className="space-y-1.5">
                  <label className="block font-medium text-zinc-400">Language</label>
                  <div className="flex cursor-pointer items-center justify-between rounded-lg border border-white/[0.08] bg-white/[0.04] px-3 py-2 text-white hover:border-white/20">
                    <span>English (US)</span>
                    <ChevronDown className="h-3.5 w-3.5 text-zinc-400" />
                  </div>
                </div>

                <div className="space-y-1.5">
                  <label className="block font-medium text-zinc-400">Time Zone</label>
                  <div className="flex cursor-pointer items-center justify-between rounded-lg border border-white/[0.08] bg-white/[0.04] px-3 py-2 text-white hover:border-white/20">
                    <span>(GMT+5:30) Asia/Kolkata</span>
                    <ChevronDown className="h-3.5 w-3.5 text-zinc-400" />
                  </div>
                </div>

                <div className="space-y-1.5">
                  <label className="block font-medium text-zinc-400">Date Format</label>
                  <div className="flex cursor-pointer items-center justify-between rounded-lg border border-white/[0.08] bg-white/[0.04] px-3 py-2 text-white hover:border-white/20">
                    <span>May 24, 2025</span>
                    <ChevronDown className="h-3.5 w-3.5 text-zinc-400" />
                  </div>
                </div>
              </div>
            </div>

            {/* Section 4: Default Settings */}
            <div className="space-y-4 rounded-xl border border-white/[0.08] bg-white/[0.04] p-5 backdrop-blur-md">
              <div>
                <h3 className="text-xs font-bold text-white">Default Settings</h3>
                <p className="text-[11px] text-zinc-400">
                  Configure default behavior for workflows.
                </p>
              </div>

              <div className="space-y-4 pt-1 text-xs">
                {/* Item 1 */}
                <div className="flex items-center justify-between">
                  <div>
                    <span className="block font-semibold text-white">Auto-save conversations</span>
                    <span className="text-[11px] text-zinc-400">
                      Automatically save conversations and workflow drafts
                    </span>
                  </div>
                  <button
                    type="button"
                    onClick={() => setAutoSave((prev) => !prev)}
                    className={`relative h-5 w-9 rounded-full p-0.5 transition-colors ${
                      autoSave ? 'bg-blue-600' : 'bg-zinc-700'
                    }`}
                    aria-label="Toggle auto save"
                  >
                    <span
                      className={`block h-4 w-4 rounded-full bg-white transition-transform ${
                        autoSave ? 'translate-x-4' : 'translate-x-0'
                      }`}
                    />
                  </button>
                </div>

                {/* Item 2 */}
                <div className="flex items-center justify-between">
                  <div>
                    <span className="block font-semibold text-white">
                      Confirm before destructive actions
                    </span>
                    <span className="text-[11px] text-zinc-400">
                      Show confirmation prompts for delete and reset actions
                    </span>
                  </div>
                  <button
                    type="button"
                    onClick={() => setConfirmDestructive((prev) => !prev)}
                    className={`relative h-5 w-9 rounded-full p-0.5 transition-colors ${
                      confirmDestructive ? 'bg-blue-600' : 'bg-zinc-700'
                    }`}
                    aria-label="Toggle confirm destructive"
                  >
                    <span
                      className={`block h-4 w-4 rounded-full bg-white transition-transform ${
                        confirmDestructive ? 'translate-x-4' : 'translate-x-0'
                      }`}
                    />
                  </button>
                </div>

                {/* Item 3 */}
                <div className="flex items-center justify-between">
                  <div>
                    <span className="block font-semibold text-white">Enable telemetry</span>
                    <span className="text-[11px] text-zinc-400">
                      Help us improve Keystone by sharing anonymous usage data
                    </span>
                  </div>
                  <button
                    type="button"
                    onClick={() => setEnableTelemetry((prev) => !prev)}
                    className={`relative h-5 w-9 rounded-full p-0.5 transition-colors ${
                      enableTelemetry ? 'bg-blue-600' : 'bg-zinc-700'
                    }`}
                    aria-label="Toggle enable telemetry"
                  >
                    <span
                      className={`block h-4 w-4 rounded-full bg-white transition-transform ${
                        enableTelemetry ? 'translate-x-4' : 'translate-x-0'
                      }`}
                    />
                  </button>
                </div>
              </div>
            </div>

            {/* Section 5: Danger Zone */}
            <div className="space-y-4 rounded-xl border border-rose-900/40 bg-rose-950/10 p-5 backdrop-blur-md">
              <div>
                <h3 className="text-xs font-bold tracking-wider text-rose-400 uppercase">
                  Danger Zone
                </h3>
                <p className="text-[11px] text-zinc-400">Irreversible and sensitive actions.</p>
              </div>

              <div className="space-y-4 pt-1 text-xs">
                {/* Action 1 */}
                <div className="flex items-center justify-between">
                  <div>
                    <span className="block font-semibold text-white">
                      Clear all workflow history
                    </span>
                    <span className="text-[11px] text-zinc-400">
                      Permanently delete all workflow executions and logs
                    </span>
                  </div>
                  <button
                    type="button"
                    className="inline-flex items-center gap-1.5 rounded-lg border border-rose-800/40 bg-rose-950/40 px-3 py-1.5 text-xs font-medium text-rose-300 transition-colors hover:bg-rose-900/40"
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                    <span>Clear History</span>
                  </button>
                </div>

                {/* Action 2 */}
                <div className="flex items-center justify-between">
                  <div>
                    <span className="block font-semibold text-white">Delete Workspace</span>
                    <span className="text-[11px] text-zinc-400">
                      Permanently delete this workspace and all associated data
                    </span>
                  </div>
                  <button
                    type="button"
                    className="inline-flex items-center gap-1.5 rounded-lg border border-rose-800/40 bg-rose-950/40 px-3 py-1.5 text-xs font-medium text-rose-300 transition-colors hover:bg-rose-900/40"
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                    <span>Delete Workspace</span>
                  </button>
                </div>
              </div>
            </div>
          </div>
        </div>
      </main>
    </AppLayout>
  );
}
