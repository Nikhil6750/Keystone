import React, { useRef, useEffect } from 'react';

interface PromptInputProps {
  value: string;
  onChange: (value: string) => void;
}

export const PromptInput: React.FC<PromptInputProps> = ({ value, onChange }) => {
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto';
      textareaRef.current.style.height = `${Math.max(120, textareaRef.current.scrollHeight)}px`;
    }
  }, [value]);

  return (
    <div className="prompt-input-wrapper">
      <label htmlFor="prompt-textarea" className="input-label">
        Task Prompt
      </label>
      <textarea
        id="prompt-textarea"
        ref={textareaRef}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder="Describe what you want Keystone to build..."
        className="prompt-textarea"
        rows={4}
      />
    </div>
  );
};
