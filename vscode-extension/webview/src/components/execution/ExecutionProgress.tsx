import React, { useEffect, useState } from 'react';
import { Loader2, CheckCircle2, AlertCircle, Clock, FileCode, ChevronDown, ChevronRight } from 'lucide-react';
import type { OrchestrationEvent } from '../../types/keystone';

export interface ExecutionProgressProps {
  events: OrchestrationEvent[];
}

export interface AgentTaskCard {
  taskId: string;
  agentId: string;
  taskTitle: string;
  status: 'queued' | 'working' | 'waiting' | 'verifying' | 'completed' | 'failed' | 'rerouted';
  activeFile?: string;
  elapsedSeconds: number;
}

const PHASE_PHRASES: Record<string, string[]> = {
  planning: [
    'Understanding your goal…',
    'Breaking it down…',
    'Mapping the work…',
    'Putting the pieces together…',
  ],
  team_assembly: [
    'Finding the best agent…',
    'Assembling the team…',
    'Matching skills to tasks…',
    'Lining things up…',
  ],
  coding: [
    'Working…',
    'Building…',
    'Shaping things up…',
    'Wiring it together…',
    'Shimming…',
    'Making changes…',
    'Putting the pieces in place…',
  ],
  testing: [
    'Checking the work…',
    'Running tests…',
    'Testing the edges…',
    'Making sure it holds…',
  ],
  verification: [
    'Verifying…',
    'Checking the result…',
    'One final pass…',
    'Making sure everything works…',
  ],
};

export const ExecutionProgress: React.FC<ExecutionProgressProps> = ({ events }) => {
  const [currentPhase, setCurrentPhase] = useState<string>('planning');
  const [phraseIndex, setPhraseIndex] = useState<number>(0);
  const [showTaskGraph, setShowTaskGraph] = useState<boolean>(false);
  const [elapsedSeconds, setElapsedSeconds] = useState<number>(0);

  // Determine current active phase from events
  useEffect(() => {
    if (events.length === 0) return;
    const latest = events[events.length - 1];
    const type = latest.event_type || '';

    if (type.includes('planning') || type.includes('goal')) {
      setCurrentPhase('planning');
    } else if (type.includes('team') || type.includes('routing')) {
      setCurrentPhase('team_assembly');
    } else if (type.includes('step.started') || type.includes('execution.started') || type.includes('file')) {
      setCurrentPhase('coding');
    } else if (type.includes('test')) {
      setCurrentPhase('testing');
    } else if (type.includes('verification')) {
      setCurrentPhase('verification');
    }
  }, [events]);

  // Rotate phase phrases every 3s
  useEffect(() => {
    const timer = setInterval(() => {
      setPhraseIndex((prev) => prev + 1);
    }, 3000);
    return () => clearInterval(timer);
  }, []);

  // Timer for elapsed seconds
  useEffect(() => {
    const timer = setInterval(() => {
      setElapsedSeconds((prev) => prev + 1);
    }, 1000);
    return () => clearInterval(timer);
  }, []);

  // Compute agent cards from events
  const taskMap = new Map<string, AgentTaskCard>();

  events.forEach((evt) => {
    if (evt.event_type === 'routing.task_selected' || evt.event_type === 'agent.selected') {
      if (evt.task_key && evt.agent_id) {
        taskMap.set(evt.task_key, {
          taskId: evt.task_key,
          agentId: evt.agent_id,
          taskTitle: `Task ${evt.task_key}`,
          status: 'queued',
          elapsedSeconds: 0,
        });
      }
    } else if (evt.event_type === 'step.started') {
      if (evt.task_key) {
        const card = taskMap.get(evt.task_key) || {
          taskId: evt.task_key,
          agentId: evt.agent_id || 'Agent',
          taskTitle: `Task ${evt.task_key}`,
          status: 'working',
          elapsedSeconds: 0,
        };
        card.status = 'working';
        if (evt.agent_id) card.agentId = evt.agent_id;
        taskMap.set(evt.task_key, card);
      }
    } else if (evt.event_type === 'file.activity') {
      if (evt.task_key && evt.message) {
        const card = taskMap.get(evt.task_key);
        if (card) {
          card.activeFile = evt.message;
        }
      }
    } else if (evt.event_type === 'step.completed') {
      if (evt.task_key) {
        const card = taskMap.get(evt.task_key);
        if (card) card.status = 'completed';
      }
    } else if (evt.event_type === 'step.failed') {
      if (evt.task_key) {
        const card = taskMap.get(evt.task_key);
        if (card) card.status = 'failed';
      }
    }
  });

  const cardsList = Array.from(taskMap.values());
  const phrases = PHASE_PHRASES[currentPhase] || PHASE_PHRASES.planning;
  const currentPhraseText = phrases[phraseIndex % phrases.length];

  return (
    <div className="execution-progress-view space-y-4" role="status" aria-live="polite">
      {/* Rotating Truthful Status Phrase */}
      <div className="flex items-center space-x-2 text-sm font-medium text-slate-300 bg-slate-900/60 px-3 py-2 rounded-md border border-slate-800">
        <Loader2 className="w-4 h-4 animate-spin text-blue-400" />
        <span>{currentPhraseText}</span>
        <span className="ml-auto text-xs text-slate-500 font-mono">{elapsedSeconds}s</span>
      </div>

      {/* Task Graph Expandable Toggle */}
      {cardsList.length > 0 && (
        <div className="border border-slate-800 rounded-md overflow-hidden bg-slate-950/40">
          <button
            onClick={() => setShowTaskGraph(!showTaskGraph)}
            className="w-full flex items-center justify-between px-3 py-2 text-xs font-semibold text-slate-400 hover:text-slate-200 transition-colors"
          >
            <span>{cardsList.length} Tasks Executing</span>
            {showTaskGraph ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
          </button>

          {showTaskGraph && (
            <div className="px-3 pb-3 space-y-2 border-t border-slate-800/60 pt-2">
              {cardsList.map((task) => (
                <div key={task.taskId} className="flex items-center justify-between text-xs py-1">
                  <div className="flex items-center space-x-2">
                    {task.status === 'completed' && <CheckCircle2 size={13} className="text-emerald-400" />}
                    {task.status === 'working' && <Loader2 size={13} className="animate-spin text-blue-400" />}
                    {task.status === 'queued' && <Clock size={13} className="text-slate-500" />}
                    {task.status === 'failed' && <AlertCircle size={13} className="text-rose-400" />}
                    <span className="font-mono text-slate-300">{task.taskId}</span>
                    <span className="text-slate-400">{task.taskTitle}</span>
                  </div>
                  <span className="text-slate-500 font-medium px-2 py-0.5 rounded bg-slate-900 border border-slate-800">
                    {task.agentId}
                  </span>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Agent Execution Cards */}
      {cardsList.length > 0 ? (
        <div className="grid gap-3">
          {cardsList.map((card) => (
            <div
              key={card.taskId}
              className="p-3 rounded-lg border border-slate-800 bg-slate-900/50 flex flex-col justify-between"
            >
              <div className="flex items-center justify-between mb-1">
                <span className="font-bold text-xs text-blue-400 uppercase tracking-wider">{card.agentId}</span>
                <span
                  className={`text-[10px] px-2 py-0.5 rounded font-semibold uppercase ${
                    card.status === 'completed'
                      ? 'bg-emerald-950 text-emerald-300 border border-emerald-800'
                      : card.status === 'working'
                      ? 'bg-blue-950 text-blue-300 border border-blue-800'
                      : 'bg-slate-800 text-slate-400'
                  }`}
                >
                  {card.status}
                </span>
              </div>
              <div className="text-sm font-medium text-slate-200">{card.taskTitle}</div>
              {card.activeFile && (
                <div className="flex items-center space-x-1.5 mt-2 text-xs text-emerald-400/90 font-mono">
                  <FileCode size={12} />
                  <span>{card.activeFile}</span>
                </div>
              )}
            </div>
          ))}
        </div>
      ) : (
        <div className="text-xs text-slate-500 text-center py-4">Waiting for execution stream…</div>
      )}
    </div>
  );
};
