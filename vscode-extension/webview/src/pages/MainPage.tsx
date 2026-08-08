import React from 'react';
import { WorkflowBuilder } from '../components/workflow/WorkflowBuilder';
import { AgentManager } from '../components/agents/AgentManager';
import { KnowledgeExplorer } from '../components/knowledge/KnowledgeExplorer';
import { WorkspaceExplorer } from '../components/workspace/WorkspaceExplorer';
import { useAppState } from '../hooks/useAppState';
import { GitFork, Bot, BookOpen, FolderTree } from 'lucide-react';

export const MainPage: React.FC = () => {
  const { activeTab, setActiveTab } = useAppState();

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

        <button
          type="button"
          role="tab"
          aria-selected={activeTab === 'knowledge'}
          className={`nav-tab ${activeTab === 'knowledge' ? 'active' : ''}`}
          onClick={() => setActiveTab('knowledge')}
        >
          <BookOpen size={15} />
          <span>Knowledge</span>
        </button>

        <button
          type="button"
          role="tab"
          aria-selected={activeTab === 'workspace'}
          className={`nav-tab ${activeTab === 'workspace' ? 'active' : ''}`}
          onClick={() => setActiveTab('workspace')}
        >
          <FolderTree size={15} />
          <span>Workspace</span>
        </button>
      </nav>

      {/* Main View Area */}
      <main className="tab-content-area">
        {activeTab === 'builder' && <WorkflowBuilder />}
        {activeTab === 'agents' && <AgentManager />}
        {activeTab === 'knowledge' && <KnowledgeExplorer />}
        {activeTab === 'workspace' && <WorkspaceExplorer />}
      </main>
    </div>
  );
};
