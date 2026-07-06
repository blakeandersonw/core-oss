import { useState, useRef, useCallback } from 'react';
import { useEditor, EditorContent, type Editor } from '@tiptap/react';
import StarterKit from '@tiptap/starter-kit';
import Placeholder from '@tiptap/extension-placeholder';
import type { ContentBlock } from '../../../api/client';
import { UniversalMentionMark } from '../../Mentions/MentionMark';
import { UniversalMentionAutocomplete } from '../../Mentions/UniversalMentionAutocomplete';
import { MENTION_ICONS } from '../../../types/mention';
import type { MentionData } from '../../../types/mention';
import { useProjectsStore } from '../../../stores/projectsStore';

interface CommentComposerProps {
  onSend: (blocks: ContentBlock[]) => void;
  disabled?: boolean;
  placeholder?: string;
  initialContent?: string;
  submitLabel?: string;
  onCancel?: () => void;
}

type TipTapJsonNode = {
  type?: string;
  text?: string;
  marks?: Array<{ type?: string; attrs?: Record<string, unknown> }>;
  content?: TipTapJsonNode[];
};

function serializeCommentBlocks(editor: Editor): ContentBlock[] {
  const text = editor.getText().trim();
  const html = editor.getHTML();
  const isFormatted = html !== `<p>${text}</p>`;
  const blocks: ContentBlock[] = [
    {
      type: 'text',
      data: isFormatted ? { content: text, html } : { content: text },
    },
  ];

  const visit = (node: TipTapJsonNode) => {
    if (node.type === 'text' && node.marks) {
      node.marks.forEach((mark) => {
        if (mark.type !== 'mention') return;
        const attrs = mark.attrs || {};
        if (attrs.entityType !== 'person' || typeof attrs.entityId !== 'string') return;
        blocks.push({
          type: 'mention',
          data: {
            entityType: 'person',
            entityId: attrs.entityId,
            displayName: typeof attrs.displayName === 'string' ? attrs.displayName : node.text || 'someone',
            display_name: typeof attrs.displayName === 'string' ? attrs.displayName : node.text || 'someone',
            icon: typeof attrs.icon === 'string' ? attrs.icon : undefined,
          },
        });
      });
    }
    node.content?.forEach(visit);
  };

  visit(editor.getJSON() as TipTapJsonNode);
  return blocks;
}

export default function CommentComposer({
  onSend,
  disabled = false,
  placeholder = 'Add a comment...',
  initialContent,
  submitLabel = 'Post',
  onCancel,
}: CommentComposerProps) {
  const workspaceId = useProjectsStore((s) => s.workspaceId);
  const [showMentionAutocomplete, setShowMentionAutocomplete] = useState(false);
  const [mentionQuery, setMentionQuery] = useState('');
  const [mentionCursorCoords, setMentionCursorCoords] = useState<{ top: number; bottom: number; left: number } | undefined>();
  const [hasContent, setHasContent] = useState(Boolean(initialContent));
  const composerRef = useRef<HTMLDivElement>(null);

  const handleSend = useCallback(() => {
    if (!editor || editor.isEmpty || disabled) return;

    const text = editor.getText();
    if (!text.trim()) return;

    onSend(serializeCommentBlocks(editor));
    editor.commands.clearContent();
    setHasContent(false);
  }, [onSend, disabled]);

  const editor = useEditor({
    extensions: [
      StarterKit.configure({
        heading: false,
        horizontalRule: false,
        dropcursor: false,
        gapcursor: false,
        blockquote: false,
        codeBlock: false,
      }),
      UniversalMentionMark,
      Placeholder.configure({ placeholder }),
    ],
    content: initialContent,
    editorProps: {
      attributes: {
        class: 'outline-none text-[13px] text-gray-700 min-h-[24px] max-h-[120px] overflow-y-auto',
      },
      handleKeyDown: (_view, event) => {
        if (event.key === 'Enter' && !event.shiftKey) {
          event.preventDefault();
          handleSend();
          return true;
        }
        return false;
      },
    },
    onUpdate: ({ editor: ed }) => {
      setHasContent(!ed.isEmpty);

      // Mention detection
      const { from } = ed.state.selection;
      const textBefore = ed.state.doc.textBetween(
        Math.max(0, from - 50),
        from,
        '\n',
      );
      const mentionMatch = textBefore.match(/(^|[\s])@(\w*)$/);
      if (mentionMatch) {
        setMentionQuery(mentionMatch[2]);
        setShowMentionAutocomplete(true);
        try {
          const coords = ed.view.coordsAtPos(from);
          setMentionCursorCoords({ top: coords.top, bottom: coords.bottom, left: coords.left });
        } catch {
          // coordsAtPos can fail if pos is out of view
        }
      } else {
        setShowMentionAutocomplete(false);
        setMentionQuery('');
        if (ed.isActive('mention')) {
          ed.commands.unsetMark('mention');
        }
      }
    },
  });

  const handleMentionSelect = useCallback(
    (data: MentionData) => {
      if (!editor) return;
      const icon = data.icon || MENTION_ICONS[data.entityType] || '';
      const { from } = editor.state.selection;
      const textBefore = editor.state.doc.textBetween(
        Math.max(0, from - 50),
        from,
        '\n',
      );
      const mentionMatch = textBefore.match(/(^|[\s])@(\w*)$/);

      if (mentionMatch) {
        const prefixLen = mentionMatch[1].length; // leading whitespace
        const start = from - mentionMatch[0].length + prefixLen;
        editor
          .chain()
          .focus()
          .deleteRange({ from: start, to: from })
          .insertContent([
            {
              type: 'text',
              text: `${icon} ${data.displayName}`,
              marks: [
                {
                  type: 'mention',
                  attrs: {
                    entityType: data.entityType,
                    entityId: data.entityId,
                    displayName: data.displayName,
                    icon,
                  },
                },
              ],
            },
            { type: 'text', text: ' ' },
          ])
          .run();
      }

      setShowMentionAutocomplete(false);
      setMentionQuery('');
    },
    [editor],
  );

  return (
    <div ref={composerRef} className="py-3 flex-shrink-0">
      <div className="flex gap-3 items-end">
        <div className="flex-1">
          <EditorContent editor={editor} />
        </div>
        {(hasContent || disabled || onCancel) && (
          <div className="flex items-center gap-2">
            {onCancel && (
              <button
                onClick={onCancel}
                disabled={disabled}
                className="px-3 py-2 text-[12px] font-medium text-gray-500 hover:text-gray-700 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
              >
                Cancel
              </button>
            )}
            <button
              onClick={handleSend}
              disabled={disabled || !hasContent}
              className="px-3 py-2 text-[12px] font-medium bg-gray-900 text-white rounded-lg hover:bg-gray-800 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
            >
              {disabled ? 'Posting...' : submitLabel}
            </button>
          </div>
        )}
      </div>
      {showMentionAutocomplete && workspaceId && (
        <UniversalMentionAutocomplete
          query={mentionQuery}
          workspaceId={workspaceId}
          onSelect={handleMentionSelect}
          onClose={() => {
            setShowMentionAutocomplete(false);
            setMentionQuery('');
          }}
          anchorRef={composerRef}
          cursorCoords={mentionCursorCoords}
          position="auto"
        />
      )}
    </div>
  );
}
