import * as React from 'react';
import type { SemanticTone } from '@/lib/presentation';

const TONE_STYLES: Record<SemanticTone, string> = {
  neutral: 'border-white/[0.08] bg-white/[0.04] text-zinc-300',
  info: 'border-blue-500/30 bg-blue-950/40 text-blue-300',
  success: 'border-emerald-500/30 bg-emerald-950/40 text-emerald-300',
  warning: 'border-amber-500/30 bg-amber-950/40 text-amber-300',
  error: 'border-rose-500/30 bg-rose-950/40 text-rose-300',
};

const TONE_DOT: Record<SemanticTone, string> = {
  neutral: 'bg-zinc-500',
  info: 'bg-blue-400',
  success: 'bg-emerald-400',
  warning: 'bg-amber-400',
  error: 'bg-rose-400',
};

export interface ToneBadgeProps {
  tone: SemanticTone;
  children: React.ReactNode;
  className?: string;
}

/**
 * A status badge that always pairs its color with a text label and a
 * distinctly shaped dot indicator — never relies on color alone (see
 * `docs/phase5-integration.md`'s accessibility notes).
 */
export const ToneBadge: React.FC<ToneBadgeProps> = ({ tone, children, className = '' }) => {
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-[11px] font-medium ${TONE_STYLES[tone]} ${className}`}
    >
      <span className={`h-1.5 w-1.5 rounded-full ${TONE_DOT[tone]}`} aria-hidden="true" />
      <span>{children}</span>
    </span>
  );
};
