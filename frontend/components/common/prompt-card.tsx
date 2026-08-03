'use client';

import * as React from 'react';
import type { LucideIcon } from 'lucide-react';
import { cn } from '@/lib/utils';

export interface PromptCardProps {
  title: string;
  subtitle: string;
  prompt: string;
  icon: LucideIcon;
  iconBg: string;
  onSelect: (prompt: string) => void;
  className?: string;
}

export const PromptCard: React.FC<PromptCardProps> = ({
  title,
  subtitle,
  prompt,
  icon: IconComponent,
  iconBg,
  onSelect,
  className,
}) => {
  return (
    <div
      onClick={() => onSelect(prompt)}
      className={cn(
        'group cursor-pointer rounded-xl border border-white/[0.08] bg-white/[0.04] p-4 transition-all duration-200 hover:border-white/20 hover:bg-white/[0.06]',
        className
      )}
    >
      <div className="flex items-center gap-3">
        <div className={cn('flex h-9 w-9 shrink-0 items-center justify-center rounded-lg', iconBg)}>
          <IconComponent className="h-4 w-4" />
        </div>
        <div className="space-y-0.5">
          <h3 className="text-xs font-semibold text-white transition-colors group-hover:text-blue-300">
            {title}
          </h3>
          <p className="line-clamp-1 text-[11px] text-zinc-400">{subtitle}</p>
        </div>
      </div>
    </div>
  );
};
