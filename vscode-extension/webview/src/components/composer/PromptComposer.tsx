import React, { useCallback, useRef, useState } from 'react';
import { ArrowUp, Paperclip } from 'lucide-react';

export interface PromptComposerProps {
  disabled?: boolean;
  placeholder?: string;
  onSubmit: (goal: string) => void;
}

/**
 * The single compact prompt composer, docked at the bottom of the screen.
 * Enter sends; Shift+Enter inserts a newline. Deliberately has no agent
 * picker, template grid, or workflow editor -- the user only ever
 * describes what they want; Keystone decides how to route it.
 */
export const PromptComposer: React.FC<PromptComposerProps> = ({
  disabled = false,
  placeholder = 'Ask Keystone anything...',
  onSubmit,
}) => {
  const [value, setValue] = useState('');
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const submit = useCallback(() => {
    const trimmed = value.trim();
    if (!trimmed || disabled) return;
    onSubmit(trimmed);
    setValue('');
  }, [value, disabled, onSubmit]);

  const handleKeyDown = useCallback(
    (event: React.KeyboardEvent<HTMLTextAreaElement>) => {
      if (event.key === 'Enter' && !event.shiftKey) {
        event.preventDefault();
        submit();
      }
    },
    [submit]
  );

  const handleChange = useCallback((event: React.ChangeEvent<HTMLTextAreaElement>) => {
    setValue(event.target.value);
    const el = textareaRef.current;
    if (el) {
      el.style.height = 'auto';
      el.style.height = `${Math.min(el.scrollHeight, 140)}px`;
    }
  }, []);

  return (
    <div className="prompt-composer">
      <button
        type="button"
        className="prompt-composer-attach-btn"
        aria-disabled="true"
        title="Attachments coming soon"
        disabled
      >
        <Paperclip size={15} />
      </button>
      <textarea
        ref={textareaRef}
        className="prompt-composer-input"
        rows={1}
        value={value}
        placeholder={placeholder}
        disabled={disabled}
        onChange={handleChange}
        onKeyDown={handleKeyDown}
        aria-label="Ask Keystone"
      />
      <button
        type="button"
        className="prompt-composer-send-btn"
        onClick={submit}
        disabled={disabled || !value.trim()}
        aria-label="Send"
      >
        <ArrowUp size={15} />
      </button>
    </div>
  );
};
