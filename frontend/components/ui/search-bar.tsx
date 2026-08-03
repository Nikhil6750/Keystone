'use client';

import * as React from 'react';
import { Search } from 'lucide-react';
import { cn } from '@/lib/utils';

export interface SearchBarProps extends React.InputHTMLAttributes<HTMLInputElement> {
  shortcut?: string;
}

export const SearchBar: React.FC<SearchBarProps> = ({
  className,
  placeholder = 'Search anything...',
  shortcut = '⌘ K',
  ...props
}) => {
  return (
    <div
      className={cn(
        'hidden w-72 items-center gap-2 rounded-lg border border-white/[0.08] bg-white/[0.04] px-3 py-1.5 text-xs text-zinc-400 transition-colors focus-within:border-white/20 md:flex lg:w-96',
        className
      )}
    >
      <Search className="h-3.5 w-3.5 shrink-0 text-zinc-400" />
      <input
        type="text"
        placeholder={placeholder}
        className="w-full bg-transparent text-xs text-white placeholder:text-zinc-500 focus:outline-none"
        readOnly
        {...props}
      />
      {shortcut && (
        <kbd className="hidden items-center rounded border border-white/10 bg-white/5 px-1.5 text-[10px] font-medium text-zinc-400 sm:inline-flex">
          {shortcut}
        </kbd>
      )}
    </div>
  );
};
