'use client';

import * as React from 'react';
import { AlertTriangle, X } from 'lucide-react';

export interface CompensateDialogProps {
  open: boolean;
  onConfirm: () => void;
  onCancel: () => void;
  busy?: boolean;
}

export const CompensateDialog: React.FC<CompensateDialogProps> = ({
  open,
  onConfirm,
  onCancel,
  busy = false,
}) => {
  const dialogRef = React.useRef<HTMLDivElement>(null);

  React.useEffect(() => {
    if (!open) return;
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onCancel();
    };
    window.addEventListener('keydown', handleKeyDown);
    dialogRef.current?.focus();
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [open, onCancel]);

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4 backdrop-blur-sm"
      role="presentation"
      onClick={onCancel}
    >
      <div
        ref={dialogRef}
        role="alertdialog"
        aria-modal="true"
        aria-labelledby="compensate-dialog-title"
        aria-describedby="compensate-dialog-description"
        tabIndex={-1}
        onClick={(e) => e.stopPropagation()}
        className="w-full max-w-md space-y-4 rounded-xl border border-amber-900/40 bg-[#0B1120] p-6 shadow-2xl focus:outline-none"
      >
        <div className="flex items-start justify-between border-b border-white/[0.08] pb-3">
          <div className="flex items-center gap-2.5">
            <AlertTriangle className="h-5 w-5 text-amber-400" />
            <h3 id="compensate-dialog-title" className="text-sm font-bold text-white">
              Compensate workflow
            </h3>
          </div>
          <button
            type="button"
            onClick={onCancel}
            aria-label="Close dialog"
            className="text-zinc-400 hover:text-white"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <p id="compensate-dialog-description" className="text-xs leading-relaxed text-zinc-300">
          Keystone will run configured compensation handlers for eligible successful steps in
          reverse order. Compensation is best-effort and may not reverse every external side
          effect.
        </p>

        <div className="flex justify-end gap-2 pt-2">
          <button
            type="button"
            onClick={onCancel}
            disabled={busy}
            className="rounded-lg border border-white/[0.08] bg-white/[0.04] px-4 py-2 text-xs text-zinc-300 hover:bg-white/[0.08] disabled:opacity-50"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={onConfirm}
            disabled={busy}
            className="rounded-lg bg-amber-600 px-4 py-2 text-xs font-medium text-white shadow-sm hover:bg-amber-500 disabled:opacity-50"
          >
            {busy ? 'Compensating…' : 'Compensate workflow'}
          </button>
        </div>
      </div>
    </div>
  );
};
