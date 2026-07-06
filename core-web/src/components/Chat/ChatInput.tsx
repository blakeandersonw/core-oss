import { useRef, useState, useEffect, useCallback } from 'react';
import { ArrowUpIcon, StopIcon, XMarkIcon, AtSymbolIcon } from '@heroicons/react/24/solid';
import { PaperClipIcon } from '@heroicons/react/24/outline';
import type { PendingAttachment } from '../../hooks/useChatAttachments';
import type { MentionData } from '../../types/mention';
import { MENTION_ICONS } from '../../types/mention';
import { UniversalMentionAutocomplete } from '../Mentions/UniversalMentionAutocomplete';
import { getTextareaCursorCoords } from '../../lib/textareaCaret';

interface ChatInputProps {
  value: string;
  onChange: (value: string) => void;
  onSubmit: () => void;
  onStop?: () => void;
  disabled?: boolean;
  isStreaming?: boolean;
  placeholder?: string;
  // Attachment props
  pendingAttachments?: PendingAttachment[];
  onAddFiles?: (files: File[]) => void;
  onRemoveAttachment?: (localId: string) => void;
  isUploading?: boolean;
  // Mention props
  mentions?: MentionData[];
  onMentionSelect?: (data: MentionData) => void;
  onRemoveMention?: (entityId: string) => void;
  workspaceId?: string | null;
}

export default function ChatInput({
  value,
  onChange,
  onSubmit,
  onStop,
  disabled = false,
  isStreaming = false,
  placeholder = 'Message StarterStack...',
  pendingAttachments = [],
  onAddFiles,
  onRemoveAttachment,
  isUploading = false,
  mentions = [],
  onMentionSelect,
  onRemoveMention,
  workspaceId,
}: ChatInputProps) {
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const [showMentionAutocomplete, setShowMentionAutocomplete] = useState(false);
  const [mentionQuery, setMentionQuery] = useState('');
  const [mentionCursorCoords, setMentionCursorCoords] = useState<{ top: number; bottom: number; left: number } | null>(null);

  // Auto-resize textarea
  const adjustHeight = useCallback(() => {
    const textarea = textareaRef.current;
    if (!textarea) return;

    textarea.style.height = 'auto';
    const newHeight = Math.min(textarea.scrollHeight, 200);
    textarea.style.height = `${newHeight}px`;
  }, []);

  useEffect(() => {
    adjustHeight();
  }, [value, adjustHeight]);

  // Global keyboard capture - focus textarea when user types anywhere
  useEffect(() => {
    const handleGlobalKeyDown = (e: KeyboardEvent) => {
      if (
        document.activeElement === textareaRef.current ||
        document.activeElement instanceof HTMLInputElement ||
        document.activeElement instanceof HTMLTextAreaElement
      ) {
        return;
      }

      if (e.metaKey || e.ctrlKey || e.altKey) return;
      if (e.key.length !== 1) return;

      textareaRef.current?.focus();
    };

    window.addEventListener('keydown', handleGlobalKeyDown);
    return () => window.removeEventListener('keydown', handleGlobalKeyDown);
  }, []);

  const handleChange = useCallback((e: React.ChangeEvent<HTMLTextAreaElement>) => {
    const newValue = e.target.value;
    onChange(newValue);

    // Detect @ mention trigger
    const cursorPos = e.target.selectionStart ?? 0;
    const textBeforeCursor = newValue.substring(0, cursorPos);
    const mentionMatch = textBeforeCursor.match(/(^|[\s])@(\w*)$/);

    if (mentionMatch) {
      setMentionQuery(mentionMatch[2]);
      setShowMentionAutocomplete(true);
      const coords = getTextareaCursorCoords(e.target);
      setMentionCursorCoords(coords);
    } else {
      setShowMentionAutocomplete(false);
      setMentionQuery('');
    }
  }, [onChange]);

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    // When mention autocomplete is open, let it handle nav keys
    if (showMentionAutocomplete) {
      if (['ArrowDown', 'ArrowUp', 'ArrowRight', 'ArrowLeft', 'Enter', 'Tab', 'Escape'].includes(e.key)) {
        if (e.key === 'Enter' || e.key === 'Tab') {
          e.preventDefault();
        }
        return;
      }
    }

    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      if (canSubmit) {
        onSubmit();
      }
    }
  };

  const handleSubmit = () => {
    if (canSubmit) {
      onSubmit();
    }
  };

  const handleMentionSelect = useCallback((data: MentionData) => {
    const textarea = textareaRef.current;
    if (!textarea) return;

    const cursorPos = textarea.selectionStart ?? 0;
    const textBeforeCursor = value.substring(0, cursorPos);
    const mentionMatch = textBeforeCursor.match(/(^|[\s])@(\w*)$/);

    if (mentionMatch) {
      const prefix = mentionMatch[1]; // leading whitespace or empty (start of string)
      const start = cursorPos - mentionMatch[0].length;
      const icon = data.icon || MENTION_ICONS[data.entityType] || '';
      const insertText = `${prefix}${icon} ${data.displayName} `;
      const newValue = value.substring(0, start) + insertText + value.substring(cursorPos);

      onChange(newValue);
      onMentionSelect?.(data);

      requestAnimationFrame(() => {
        const newPos = start + insertText.length;
        textarea.selectionStart = newPos;
        textarea.selectionEnd = newPos;
        textarea.focus();
      });
    }

    setShowMentionAutocomplete(false);
    setMentionQuery('');
  }, [value, onChange, onMentionSelect]);

  const handleAtButtonClick = useCallback((e: React.MouseEvent) => {
    e.stopPropagation();
    const textarea = textareaRef.current;
    if (!textarea) return;

    const pos = textarea.selectionStart ?? value.length;
    const newValue = value.substring(0, pos) + '@' + value.substring(pos);
    onChange(newValue);

    requestAnimationFrame(() => {
      textarea.selectionStart = pos + 1;
      textarea.selectionEnd = pos + 1;
      textarea.focus();
      setShowMentionAutocomplete(true);
      setMentionQuery('');
      setMentionCursorCoords(getTextareaCursorCoords(textarea));
    });
  }, [value, onChange]);

  const handlePaste = useCallback((e: React.ClipboardEvent) => {
    if (!onAddFiles) return;

    const items = e.clipboardData?.items;
    if (!items) return;

    const imageFiles: File[] = [];
    for (const item of items) {
      if (item.type.startsWith('image/')) {
        const file = item.getAsFile();
        if (file) imageFiles.push(file);
      }
    }

    if (imageFiles.length > 0) {
      e.preventDefault();
      onAddFiles(imageFiles);
    }
  }, [onAddFiles]);

  const handleFileChange = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    if (!onAddFiles || !e.target.files?.length) return;
    onAddFiles(Array.from(e.target.files));
    e.target.value = '';
  }, [onAddFiles]);

  const hasAttachments = pendingAttachments.length > 0;
  const hasMentions = mentions.length > 0;
  const canSubmit = (value.trim().length > 0 || hasAttachments) && !disabled && !isUploading;

  return (
    <div className="relative" ref={containerRef}>
      <div className="bg-white rounded-[26px] p-2.5 shadow-[0_0_0_1px_rgba(0,0,0,0.12),0_1px_3px_rgba(0,0,0,0.06)] cursor-text transition-shadow duration-200 focus-within:shadow-[0_0_0_1px_rgba(0,0,0,0.18),0_2px_6px_rgba(0,0,0,0.08)]"
        onClick={() => textareaRef.current?.focus()}
      >
        {/* Hidden file input */}
        <input
          ref={fileInputRef}
          type="file"
          accept="image/jpeg,image/png,image/heic,image/heif"
          multiple
          onChange={handleFileChange}
          className="hidden"
        />

        {/* Attachment preview strip */}
        {hasAttachments && (
          <div className="flex gap-2 px-2 pb-2 overflow-x-auto">
            {pendingAttachments.map((attachment) => (
              <div key={attachment.id} className="relative flex-shrink-0 group">
                <img
                  src={attachment.preview}
                  alt="Attachment preview"
                  className={`w-16 h-16 rounded-xl object-cover border border-black/5 ${
                    attachment.status === 'uploading' ? 'opacity-50' : ''
                  } ${attachment.status === 'error' ? 'border-red-300' : ''}`}
                />
                {attachment.status === 'uploading' && (
                  <div className="absolute inset-0 flex items-center justify-center">
                    <div className="w-5 h-5 border-2 border-white border-t-transparent rounded-full animate-spin" />
                  </div>
                )}
                {attachment.status === 'error' && (
                  <div className="absolute inset-0 flex items-center justify-center bg-red-500/20 rounded-xl">
                    <span className="text-[10px] text-red-600 font-medium">Error</span>
                  </div>
                )}
                {onRemoveAttachment && attachment.status !== 'uploading' && (
                  <button
                    onClick={(e) => { e.stopPropagation(); onRemoveAttachment(attachment.id); }}
                    className="absolute -top-1.5 -right-1.5 w-5 h-5 bg-white border border-black/10 rounded-full flex items-center justify-center text-text-tertiary hover:text-text-body shadow-sm opacity-0 group-hover:opacity-100 transition-opacity"
                  >
                    <XMarkIcon className="w-3 h-3" />
                  </button>
                )}
              </div>
            ))}
          </div>
        )}

        {/* Mention pills strip */}
        {hasMentions && (
          <div className="flex flex-wrap gap-1.5 px-3 pb-1.5 pt-1">
            {mentions.map((mention) => (
              <span
                key={mention.entityId}
                className="inline-flex items-center gap-1 px-2 py-0.5 bg-blue-50 text-blue-700 text-[13px] rounded-full border border-blue-200"
              >
                <span>{mention.icon || MENTION_ICONS[mention.entityType]}</span>
                <span className="font-medium truncate max-w-[120px]">{mention.displayName}</span>
                {onRemoveMention && (
                  <button
                    onClick={(e) => { e.stopPropagation(); onRemoveMention(mention.entityId); }}
                    className="ml-0.5 text-blue-400 hover:text-blue-600"
                  >
                    <XMarkIcon className="w-3 h-3" />
                  </button>
                )}
              </span>
            ))}
          </div>
        )}

        {/* Textarea */}
        <div className="flex min-h-[44px] items-center px-2">
          <textarea
            ref={textareaRef}
            value={value}
            onChange={handleChange}
            onKeyDown={handleKeyDown}
            onPaste={handlePaste}
            placeholder={placeholder}
            rows={1}
            className="flex-1 bg-transparent resize-none outline-none text-text-body placeholder-text-tertiary/60 text-[15px] leading-6 min-h-[24px] max-h-[200px] py-2"
          />
        </div>

        {/* Footer toolbar */}
        <div className="flex items-center justify-between px-1 pt-0.5">
          {/* Left actions */}
          <div className="flex items-center gap-1.5">
            <button
              type="button"
              onClick={(e) => { e.stopPropagation(); fileInputRef.current?.click(); }}
              className="flex items-center justify-center h-9 rounded-full border border-black/10 text-text-secondary hover:bg-black/5 transition-colors px-2 gap-1.5"
              title="Attach files"
            >
              <PaperClipIcon className="w-[18px] h-[18px]" />
              <span className="text-[13px] font-semibold pr-1">Attach</span>
            </button>
            {workspaceId && (
              <button
                type="button"
                onClick={handleAtButtonClick}
                className="flex items-center justify-center h-9 rounded-full border border-black/10 text-text-secondary hover:bg-black/5 transition-colors px-2 gap-1.5"
                title="Mention a file or person"
              >
                <AtSymbolIcon className="w-[18px] h-[18px]" />
                <span className="text-[13px] font-semibold pr-1">Mention</span>
              </button>
            )}
          </div>

          {/* Right actions */}
          <div className="flex items-center gap-1.5">
            {isStreaming ? (
              <button
                onClick={(e) => { e.stopPropagation(); onStop?.(); }}
                className="w-9 h-9 flex items-center justify-center rounded-full transition-all duration-200 bg-brand-primary text-text-light hover:opacity-90"
                title="Stop generating"
              >
                <StopIcon className="w-4 h-4" />
              </button>
            ) : (
              <button
                onClick={(e) => { e.stopPropagation(); handleSubmit(); }}
                disabled={!canSubmit}
                className={`w-9 h-9 flex items-center justify-center rounded-full transition-all duration-200 ${
                  canSubmit
                    ? 'bg-brand-primary text-text-light hover:opacity-90'
                    : 'bg-black/5 text-text-tertiary cursor-not-allowed'
                }`}
              >
                <ArrowUpIcon className="w-[18px] h-[18px]" />
              </button>
            )}
          </div>
        </div>
      </div>

      {/* Mention autocomplete dropdown */}
      {showMentionAutocomplete && workspaceId && (
        <UniversalMentionAutocomplete
          query={mentionQuery}
          workspaceId={workspaceId}
          onSelect={handleMentionSelect}
          onClose={() => {
            setShowMentionAutocomplete(false);
            setMentionQuery('');
          }}
          anchorRef={containerRef}
          position="above"
          cursorCoords={mentionCursorCoords || undefined}
        />
      )}
    </div>
  );
}
