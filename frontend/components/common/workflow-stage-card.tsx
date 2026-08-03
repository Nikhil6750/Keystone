'use client';

import * as React from 'react';
import type { LucideIcon } from 'lucide-react';
import { StatusBadge } from '@/components/ui';

export interface WorkflowStageCardProps {
  name: string;
  badge?: string;
  description: string;
  icon: LucideIcon;
  iconBg: string;
  isLast?: boolean;
}

export const WorkflowStageCard: React.FC<WorkflowStageCardProps> = ({
  name,
  badge = 'Waiting',
  description,
  icon: IconComponent,
  iconBg,
  isLast = false,
}) => {
  return (
    <div className="relative space-y-2">
      <div className="space-y-2 rounded-xl border border-white/[0.08] bg-white/[0.04] p-4">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className={`flex h-8 w-8 items-center justify-center rounded-lg ${iconBg}`}>
              <IconComponent className="h-4 w-4" />
            </div>
            <span className="text-xs font-semibold text-white">{name}</span>
          </div>
          <StatusBadge variant="waiting">{badge}</StatusBadge>
        </div>
        <p className="pl-11 text-[11px] leading-snug text-zinc-400">{description}</p>
      </div>

      {!isLast && (
        <div className="flex items-center justify-center py-0.5">
          <div className="h-2 w-2 rounded-full border border-white/20 bg-zinc-800" />
        </div>
      )}
    </div>
  );
};
