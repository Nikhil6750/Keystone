'use client';

import * as React from 'react';
import { Header } from './header';
import { Sidebar } from './sidebar';

export interface AppLayoutProps {
  children: React.ReactNode;
  showSidebar?: boolean;
}

export const AppLayout: React.FC<AppLayoutProps> = ({ children, showSidebar = true }) => {
  return (
    <div className="flex min-h-screen flex-col bg-[#0B1120] font-sans text-white">
      <Header />
      <div className="flex flex-1 overflow-hidden">
        {showSidebar && <Sidebar />}
        <div className="flex flex-1 overflow-hidden">{children}</div>
      </div>
    </div>
  );
};
