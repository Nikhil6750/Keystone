'use client';

import * as React from 'react';
import { cn } from '@/lib/utils';

export interface StatusBadgeProps extends React.HTMLAttributes<HTMLSpanElement> {
  variant?: 'connected' | 'waiting' | 'pending' | 'outline';
  dot?: boolean;
}

export const StatusBadge: React.FC<StatusBadgeProps> = ({
  className,
  variant = 'waiting',
  dot = false,
  children,
  ...props
}) => {
  const variantStyles = {
    connected:
      'rounded-full border border-white/[0.08] bg-white/[0.04] px-3 py-1 text-xs font-medium text-zinc-300',
    waiting:
      'rounded-md border border-white/[0.08] bg-white/[0.04] px-2 py-0.5 text-[10px] font-medium text-zinc-400',
    pending:
      'rounded-full border border-white/[0.08] bg-white/[0.04] px-2 py-0.5 text-[10px] font-medium text-zinc-400',
    outline:
      'rounded-md border border-white/[0.08] bg-white/[0.04] px-2 py-0.5 text-[10px] font-medium text-zinc-400',
  };

  return (
    <span
      className={cn('inline-flex items-center gap-1.5', variantStyles[variant], className)}
      {...props}
    >
      {dot && (
        <span
          className={cn(
            'h-2 w-2 rounded-full',
            variant === 'connected' ? 'animate-pulse bg-emerald-500' : 'bg-zinc-500'
          )}
        />
      )}
      <span>{children}</span>
    </span>
  );
};
