'use client';

import * as React from 'react';
import { cn } from '@/lib/utils';

export interface EmptyStateProps extends React.HTMLAttributes<HTMLDivElement> {
  icon?: React.ReactNode;
  title: string;
  description?: string;
}

export const EmptyState: React.FC<EmptyStateProps> = ({
  className,
  icon,
  title,
  description,
  children,
  ...props
}) => {
  return (
    <div
      className={cn(
        'my-auto flex flex-col items-center justify-center space-y-3 rounded-xl border border-white/[0.08] bg-white/[0.03] p-8 text-center',
        className
      )}
      {...props}
    >
      {icon && (
        <div className="flex h-10 w-10 items-center justify-center rounded-lg border border-white/10 bg-white/5 text-zinc-300">
          {icon}
        </div>
      )}
      <h3 className="text-base font-semibold text-white">{title}</h3>
      {description && <p className="max-w-xs text-xs text-zinc-400">{description}</p>}
      {children}
    </div>
  );
};
