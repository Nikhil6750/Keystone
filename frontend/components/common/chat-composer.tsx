'use client';

import * as React from 'react';
import { Paperclip, SendHorizontal } from 'lucide-react';

export interface ChatComposerProps {
  value: string;
  onChange: (value: string) => void;
  onSubmit?: () => void;
  placeholder?: string;
}

export const ChatComposer: React.FC<ChatComposerProps> = ({
  value,
  onChange,
  onSubmit,
  placeholder = 'Ask Keystone anything...',
}) => {
  return (
    <div className="sticky bottom-0 z-10 bg-[#0B1120] pt-4">
      <div className="rounded-xl border border-white/[0.08] bg-[#0B1120]/90 p-4 shadow-xl backdrop-blur-md transition-colors focus-within:border-white/20">
        <textarea
          value={value}
          onChange={(e) => onChange(e.target.value)}
          placeholder={placeholder}
          rows={2}
          className="w-full resize-none bg-transparent text-sm text-white placeholder:text-zinc-500 focus:outline-none"
        />
        <div className="flex items-center justify-between border-t border-white/[0.08] pt-2">
          {/* Left Attachment Button */}
          <button
            type="button"
            className="flex h-8 w-8 items-center justify-center rounded-lg border border-white/[0.08] bg-white/[0.04] text-zinc-400 transition-colors hover:text-white"
            title="Attach file"
            aria-label="Attach file"
          >
            <Paperclip className="h-4 w-4" />
          </button>

          {/* Right Send Button */}
          <button
            type="button"
            onClick={onSubmit}
            className="flex h-9 w-9 items-center justify-center rounded-lg bg-blue-600 text-white shadow-sm transition-colors hover:bg-blue-500"
            aria-label="Send message"
          >
            <SendHorizontal className="h-4 w-4" />
          </button>
        </div>
      </div>
    </div>
  );
};
