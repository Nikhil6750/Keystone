import React, { createContext, useState, useCallback, useRef, useEffect } from 'react';
import {
  EXECUTION_STAGES,
  type ExecutionStatus,
  type LogEntry,
} from '../mock/execution';

export type Tab = 'builder' | 'agents' | 'knowledge' | 'workspace';

export type NotificationType = 'success' | 'info' | 'warning' | 'error';

export interface NotificationItem {
  id: string;
  type: NotificationType;
  title?: string;
  message: string;
  timestamp: string;
}

export type EventType =
  | 'WORKFLOW_STARTED'
  | 'WORKFLOW_COMPLETED'
  | 'AGENT_SELECTED'
  | 'KNOWLEDGE_SELECTED'
  | 'WORKSPACE_ITEM_SELECTED'
  | 'NOTIFICATION_PUSHED';

export interface AppEvent {
  type: EventType;
  payload?: unknown;
  timestamp: string;
}

type EventSubscriber = (event: AppEvent) => void;

export interface AppStateContextValue {
  activeTab: Tab;
  setActiveTab: (tab: Tab) => void;

  prompt: string;
  setPrompt: (prompt: string) => void;

  selectedTemplate: string | null;
  setSelectedTemplate: (templateId: string | null) => void;

  selectedAgentId: string | null;
  setSelectedAgentId: (agentId: string | null) => void;

  selectedKnowledgeId: string | null;
  setSelectedKnowledgeId: (docId: string | null) => void;

  selectedWorkspaceNodeId: string | null;
  setSelectedWorkspaceNodeId: (nodeId: string | null) => void;

  // Execution state
  executionStarted: boolean;
  executionCompleted: boolean;
  currentStageId: string | null;
  stageStatuses: Record<string, ExecutionStatus>;
  progressPercentage: number;
  executionLogs: LogEntry[];

  startExecution: () => void;
  resetExecution: () => void;

  // Notifications
  notifications: NotificationItem[];
  pushNotification: (type: NotificationType, message: string, title?: string) => void;
  dismissNotification: (id: string) => void;

  // Event bus
  publishEvent: (type: EventType, payload?: unknown) => void;
  subscribeEvent: (callback: EventSubscriber) => () => void;
}

export const AppStateContext = createContext<AppStateContextValue | null>(null);

export const AppStateProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  // Navigation
  const [activeTab, setActiveTab] = useState<Tab>('builder');

  // Shared State
  const [prompt, setPrompt] = useState<string>('');
  const [selectedTemplate, setSelectedTemplate] = useState<string | null>(null);
  const [selectedAgentId, setSelectedAgentId] = useState<string | null>('claude-code');
  const [selectedKnowledgeId, setSelectedKnowledgeId] = useState<string | null>(null);
  const [selectedWorkspaceNodeId, setSelectedWorkspaceNodeId] = useState<string | null>('.');

  // Notifications
  const [notifications, setNotifications] = useState<NotificationItem[]>([]);

  // Execution State
  const [executionStarted, setExecutionStarted] = useState<boolean>(false);
  const [executionCompleted, setExecutionCompleted] = useState<boolean>(false);
  const [currentStageId, setCurrentStageId] = useState<string | null>(null);
  const [stageStatuses, setStageStatuses] = useState<Record<string, ExecutionStatus>>(() => {
    const initial: Record<string, ExecutionStatus> = {};
    for (const stage of EXECUTION_STAGES) {
      initial[stage.id] = 'Waiting';
    }
    return initial;
  });
  const [executionLogs, setExecutionLogs] = useState<LogEntry[]>([]);
  const [progressPercentage, setProgressPercentage] = useState<number>(0);

  const timeoutsRef = useRef<NodeJS.Timeout[]>([]);
  const subscribersRef = useRef<Set<EventSubscriber>>(new Set());

  // Event Bus
  const subscribeEvent = useCallback((callback: EventSubscriber) => {
    subscribersRef.current.add(callback);
    return () => {
      subscribersRef.current.delete(callback);
    };
  }, []);

  const publishEvent = useCallback((type: EventType, payload?: unknown) => {
    const now = new Date();
    const timestamp = `${String(now.getHours()).padStart(2, '0')}:${String(
      now.getMinutes()
    ).padStart(2, '0')}:${String(now.getSeconds()).padStart(2, '0')}`;

    const event: AppEvent = { type, payload, timestamp };
    subscribersRef.current.forEach((subscriber) => {
      try {
        subscriber(event);
      } catch {
        // ignore callback errors
      }
    });
  }, []);

  // Notifications Manager
  const dismissNotification = useCallback((id: string) => {
    setNotifications((prev) => prev.filter((n) => n.id !== id));
  }, []);

  const pushNotification = useCallback(
    (type: NotificationType, message: string, title?: string) => {
      const id = `notif-${Date.now()}-${Math.random().toString(36).substring(2, 6)}`;
      const now = new Date();
      const timestamp = `${String(now.getHours()).padStart(2, '0')}:${String(
        now.getMinutes()
      ).padStart(2, '0')}:${String(now.getSeconds()).padStart(2, '0')}`;

      const newNotif: NotificationItem = { id, type, message, title, timestamp };
      setNotifications((prev) => [newNotif, ...prev]);

      publishEvent('NOTIFICATION_PUSHED', newNotif);

      // Auto dismiss after 4 seconds
      setTimeout(() => {
        dismissNotification(id);
      }, 4000);
    },
    [dismissNotification, publishEvent]
  );

  // Execution Control
  const clearAllTimeouts = useCallback(() => {
    for (const t of timeoutsRef.current) {
      clearTimeout(t);
    }
    timeoutsRef.current = [];
  }, []);

  useEffect(() => {
    return () => {
      clearAllTimeouts();
    };
  }, [clearAllTimeouts]);

  const resetExecution = useCallback(() => {
    clearAllTimeouts();
    setExecutionStarted(false);
    setExecutionCompleted(false);
    setCurrentStageId(null);
    setProgressPercentage(0);
    setExecutionLogs([]);
    const initial: Record<string, ExecutionStatus> = {};
    for (const stage of EXECUTION_STAGES) {
      initial[stage.id] = 'Waiting';
    }
    setStageStatuses(initial);
  }, [clearAllTimeouts]);

  const startExecution = useCallback(() => {
    resetExecution();
    setExecutionStarted(true);
    publishEvent('WORKFLOW_STARTED', { prompt, templateId: selectedTemplate });
    pushNotification('info', 'Workflow execution simulation started.', 'Execution Running');

    let cumulativeTime = 0;
    const totalStages = EXECUTION_STAGES.length;

    EXECUTION_STAGES.forEach((stage, index) => {
      const startTime = cumulativeTime;
      cumulativeTime += stage.durationMs;

      // 1. Stage Running
      const startTimeout = setTimeout(() => {
        setCurrentStageId(stage.id);
        setStageStatuses((prev) => ({ ...prev, [stage.id]: 'Running' }));
        setProgressPercentage(Math.round((index / totalStages) * 100));
      }, startTime);
      timeoutsRef.current.push(startTimeout);

      // 2. Logs
      const logCount = stage.logs.length;
      stage.logs.forEach((logMsg, logIdx) => {
        const logDelay = startTime + Math.round(((logIdx + 1) / (logCount + 1)) * stage.durationMs);
        const logTimeout = setTimeout(() => {
          const now = new Date();
          const timeStr = `${String(now.getHours()).padStart(2, '0')}:${String(
            now.getMinutes()
          ).padStart(2, '0')}:${String(now.getSeconds()).padStart(2, '0')}`;

          setExecutionLogs((prev) => [
            ...prev,
            {
              id: `${stage.id}-${logIdx}-${Date.now()}`,
              stageId: stage.id,
              stageTitle: stage.title,
              message: logMsg,
              timestamp: timeStr,
            },
          ]);
        }, logDelay);
        timeoutsRef.current.push(logTimeout);
      });

      // 3. Stage Completed
      const endTimeout = setTimeout(() => {
        setStageStatuses((prev) => ({ ...prev, [stage.id]: 'Completed' }));

        if (index === totalStages - 1) {
          setCurrentStageId(null);
          setExecutionCompleted(true);
          setProgressPercentage(100);
          publishEvent('WORKFLOW_COMPLETED', { status: 'success' });
          pushNotification('success', 'Workflow completed successfully.', 'Execution Success');
        }
      }, cumulativeTime);
      timeoutsRef.current.push(endTimeout);
    });
  }, [resetExecution, publishEvent, pushNotification, prompt, selectedTemplate]);

  // Synchronized Selection Wrappers
  const handleSetSelectedAgentId = useCallback(
    (agentId: string | null) => {
      setSelectedAgentId(agentId);
      if (agentId) publishEvent('AGENT_SELECTED', { agentId });
    },
    [publishEvent]
  );

  const handleSetSelectedKnowledgeId = useCallback(
    (docId: string | null) => {
      setSelectedKnowledgeId(docId);
      if (docId) publishEvent('KNOWLEDGE_SELECTED', { docId });
    },
    [publishEvent]
  );

  const handleSetSelectedWorkspaceNodeId = useCallback(
    (nodeId: string | null) => {
      setSelectedWorkspaceNodeId(nodeId);
      if (nodeId) publishEvent('WORKSPACE_ITEM_SELECTED', { nodeId });
    },
    [publishEvent]
  );

  const value: AppStateContextValue = {
    activeTab,
    setActiveTab,
    prompt,
    setPrompt,
    selectedTemplate,
    setSelectedTemplate,
    selectedAgentId,
    setSelectedAgentId: handleSetSelectedAgentId,
    selectedKnowledgeId,
    setSelectedKnowledgeId: handleSetSelectedKnowledgeId,
    selectedWorkspaceNodeId,
    setSelectedWorkspaceNodeId: handleSetSelectedWorkspaceNodeId,
    executionStarted,
    executionCompleted,
    currentStageId,
    stageStatuses,
    progressPercentage,
    executionLogs,
    startExecution,
    resetExecution,
    notifications,
    pushNotification,
    dismissNotification,
    publishEvent,
    subscribeEvent,
  };

  return <AppStateContext.Provider value={value}>{children}</AppStateContext.Provider>;
};
