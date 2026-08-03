'use client';

import * as React from 'react';
import { cn } from '@/lib/utils';

export interface GlassCardProps extends React.HTMLAttributes<HTMLDivElement> {
  variant?: 'default' | 'subtle' | 'interactive';
}

export const GlassCard = React.forwardRef<HTMLDivElement, GlassCardProps>(
  ({ className, variant = 'default', children, ...props }, ref) => {
    const variantStyles = {
      default: 'border-white/[0.08] bg-white/[0.04]',
      subtle: 'border-white/[0.06] bg-white/[0.02]',
      interactive:
        'border-white/[0.08] bg-white/[0.04] transition-all duration-200 hover:border-white/20 hover:bg-white/[0.06] cursor-pointer',
    };

    return (
      <div
        ref={ref}
        className={cn('rounded-xl border p-4 backdrop-blur-md', variantStyles[variant], className)}
        {...props}
      >
        {children}
      </div>
    );
  }
);

GlassCard.displayName = 'GlassCard';
