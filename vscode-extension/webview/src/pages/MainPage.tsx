import React, { useState } from 'react';
import { WorkflowBuilder } from '../components/workflow/WorkflowBuilder';
import { AgentManager } from '../components/agents/AgentManager';
import { GitFork, Bot } from 'lucide-react';

type Tab = 'builder' | 'agents';

export const MainPage: React.FC = () => {
  const [activeTab, setActiveTab] = useState<Tab>('builder');

  return (
    <div className="app-container">
      {/* Navigation Tab Bar */}
      <nav className="top-nav-tabs" role="tablist" aria-label="Keystone Views">
        <button
          type="button"
          role="tab"
          aria-selected={activeTab === 'builder'}
          className={`nav-tab ${activeTab === 'builder' ? 'active' : ''}`}
          onClick={() => setActiveTab('builder')}
        >
          <GitFork size={15} />
          <span>Workflow Builder</span>
        </button>

        <button
          type="button"
          role="tab"
          aria-selected={activeTab === 'agents'}
          className={`nav-tab ${activeTab === 'agents' ? 'active' : ''}`}
          onClick={() => setActiveTab('agents')}
        >
          <Bot size={15} />
          <span>Agent Manager</span>
        </button>
      </nav>

      {/* Main View Area */}
      <main className="tab-content-area">
        {activeTab === 'builder' && <WorkflowBuilder />}
        {activeTab === 'agents' && <AgentManager />}
      </main>
    </div>
  );
};
