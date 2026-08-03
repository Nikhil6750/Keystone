import * as React from 'react';

export interface SkeletonProps extends React.HTMLAttributes<HTMLDivElement> {
  className?: string;
}

export const Skeleton: React.FC<SkeletonProps> = ({ className = '', ...props }) => {
  return <div className={`animate-pulse rounded-md bg-white/[0.08] ${className}`} {...props} />;
};

export const SkeletonCard: React.FC = () => {
  return (
    <div className="space-y-3 rounded-xl border border-white/[0.08] bg-white/[0.04] p-4">
      <div className="flex items-center gap-3">
        <Skeleton className="h-8 w-8 rounded-lg" />
        <Skeleton className="h-4 w-24" />
      </div>
      <Skeleton className="h-3 w-full" />
      <Skeleton className="h-3 w-2/3" />
    </div>
  );
};

export const SkeletonTable: React.FC<{ rows?: number }> = ({ rows = 5 }) => {
  return (
    <div className="space-y-3 rounded-xl border border-white/[0.08] bg-white/[0.04] p-4">
      <Skeleton className="h-8 w-full rounded-lg" />
      {Array.from({ length: rows }).map((_, i) => (
        <Skeleton key={i} className="h-10 w-full rounded-lg" />
      ))}
    </div>
  );
};

export const SkeletonChat: React.FC = () => {
  return (
    <div className="space-y-4 p-4">
      <div className="flex justify-start">
        <Skeleton className="h-12 w-3/4 rounded-xl" />
      </div>
      <div className="flex justify-end">
        <Skeleton className="h-10 w-1/2 rounded-xl" />
      </div>
    </div>
  );
};
