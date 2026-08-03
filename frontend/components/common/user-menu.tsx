'use client';

import * as React from 'react';
import { User, ChevronDown } from 'lucide-react';

export function UserMenu() {
  const [isOpen, setIsOpen] = React.useState(false);

  return (
    <div className="relative">
      <button
        onClick={() => setIsOpen((prev) => !prev)}
        className="border-border/50 hover:border-border hover:bg-muted/30 flex items-center gap-2 rounded-full border p-1 transition-colors focus:outline-none"
        aria-label="User menu dropdown"
      >
        <div className="bg-muted text-foreground flex h-7 w-7 items-center justify-center rounded-full text-xs font-semibold">
          KS
        </div>
        <ChevronDown className="text-muted-foreground h-3.5 w-3.5 pr-1" />
      </button>

      {/* Dropdown Menu Placeholder */}
      {isOpen && (
        <div className="border-border bg-popover absolute top-11 right-0 z-50 w-48 rounded-lg border p-1.5 shadow-md">
          <div className="border-border/40 border-b px-3 py-2">
            <p className="text-foreground text-xs font-semibold">Admin User</p>
            <p className="text-muted-foreground truncate text-[11px]">admin@keystone.ai</p>
          </div>
          <div className="pt-1 text-xs">
            <div className="text-muted-foreground hover:bg-muted hover:text-foreground flex cursor-pointer items-center gap-2 rounded px-3 py-2">
              <User className="h-3.5 w-3.5" />
              <span>Profile Settings</span>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
