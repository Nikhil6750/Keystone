import * as React from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { CheckCircle2, AlertTriangle, AlertCircle, Info, X } from 'lucide-react';

export type ToastVariant = 'success' | 'warning' | 'error' | 'info';

export interface ToastProps {
  id?: string;
  message: string;
  variant?: ToastVariant;
  onClose?: () => void;
}

const variantStyles: Record<
  ToastVariant,
  { border: string; bg: string; text: string; icon: React.FC<{ className?: string }> }
> = {
  success: {
    border: 'border-emerald-500/30',
    bg: 'bg-emerald-950/90',
    text: 'text-emerald-300',
    icon: CheckCircle2,
  },
  warning: {
    border: 'border-amber-500/30',
    bg: 'bg-amber-950/90',
    text: 'text-amber-300',
    icon: AlertTriangle,
  },
  error: {
    border: 'border-rose-500/30',
    bg: 'bg-rose-950/90',
    text: 'text-rose-300',
    icon: AlertCircle,
  },
  info: {
    border: 'border-blue-500/30',
    bg: 'bg-blue-950/90',
    text: 'text-blue-300',
    icon: Info,
  },
};

export const Toast: React.FC<ToastProps> = ({ message, variant = 'info', onClose }) => {
  const config = variantStyles[variant];
  const IconComponent = config.icon;

  return (
    <AnimatePresence>
      <motion.div
        initial={{ y: 20, opacity: 0 }}
        animate={{ y: 0, opacity: 1 }}
        exit={{ y: 20, opacity: 0 }}
        transition={{ duration: 0.15 }}
        className={`fixed right-6 bottom-6 z-50 flex items-center gap-2.5 rounded-xl border ${config.border} ${config.bg} px-4 py-3 text-xs font-semibold ${config.text} shadow-2xl backdrop-blur-md`}
        role="alert"
        aria-live="polite"
      >
        <IconComponent className="h-4 w-4 shrink-0" />
        <span>{message}</span>
        {onClose && (
          <button
            type="button"
            onClick={onClose}
            className="ml-2 text-zinc-400 transition-colors hover:text-white"
            aria-label="Close toast notification"
          >
            <X className="h-3.5 w-3.5" />
          </button>
        )}
      </motion.div>
    </AnimatePresence>
  );
};
