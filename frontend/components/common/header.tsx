import * as React from 'react';
import { APP_CONFIG } from '@/lib/constants';

export const Header: React.FC = () => {
  return (
    <header className="glass-panel sticky top-0 z-40 flex w-full items-center justify-between border-b px-6 py-4">
      <div className="flex items-center gap-3">
        <h1 className="text-foreground text-xl font-bold tracking-tight">{APP_CONFIG.name}</h1>
      </div>
    </header>
  );
};
