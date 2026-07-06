import { useMemo, useState } from 'react';
import { CheckIcon, UserIcon } from '@heroicons/react/24/outline';
import type { WorkspaceMember } from '../../../api/client';

interface ApproverPickerProps {
  members: WorkspaceMember[];
  selectedUserId?: string | null;
  excludedUserId?: string | null;
  disabled?: boolean;
  onSelect: (userId: string) => void;
}

const getName = (member: WorkspaceMember) => member.name || member.email || 'Unknown';

export default function ApproverPicker({
  members,
  selectedUserId,
  excludedUserId,
  disabled = false,
  onSelect,
}: ApproverPickerProps) {
  const [isOpen, setIsOpen] = useState(false);
  const [search, setSearch] = useState('');

  const selected = members.find((member) => member.user_id === selectedUserId);
  const filtered = useMemo(() => {
    const term = search.trim().toLowerCase();
    return members
      .filter((member) => member.user_id !== excludedUserId)
      .filter((member) => {
        if (!term) return true;
        return getName(member).toLowerCase().includes(term) || member.email?.toLowerCase().includes(term);
      });
  }, [excludedUserId, members, search]);

  return (
    <div className="relative min-w-[180px]">
      <button
        type="button"
        disabled={disabled}
        onClick={() => setIsOpen((value) => !value)}
        className="w-full flex items-center gap-2 px-3 py-2 text-[12px] text-gray-700 bg-white border border-gray-200 rounded-lg hover:bg-gray-50 disabled:opacity-40 disabled:cursor-not-allowed"
      >
        <UserIcon className="w-4 h-4 text-gray-400 shrink-0" />
        <span className="truncate">{selected ? getName(selected) : 'Choose approver'}</span>
      </button>

      {isOpen && (
        <>
          <div className="fixed inset-0 z-20" onClick={() => setIsOpen(false)} />
          <div className="absolute z-30 mt-1 w-64 bg-white border border-gray-100 rounded-lg shadow-lg overflow-hidden">
            <div className="p-2 border-b border-gray-100">
              <input
                value={search}
                onChange={(event) => setSearch(event.target.value)}
                className="w-full px-2 py-1.5 text-[12px] border-0 rounded-md focus:outline-none placeholder:text-gray-400"
                placeholder="Search members..."
                autoFocus
              />
            </div>
            <div className="max-h-56 overflow-y-auto p-1">
              {filtered.map((member) => (
                <button
                  key={member.user_id}
                  type="button"
                  onClick={() => {
                    onSelect(member.user_id);
                    setIsOpen(false);
                    setSearch('');
                  }}
                  className="w-full flex items-center gap-2 px-2 py-2 text-[12px] text-left rounded-md hover:bg-gray-50"
                >
                  <span className="w-6 h-6 rounded-full bg-gray-100 text-gray-600 flex items-center justify-center text-[10px] font-medium shrink-0">
                    {getName(member).charAt(0).toUpperCase()}
                  </span>
                  <span className="flex-1 min-w-0 truncate">{getName(member)}</span>
                  {member.user_id === selectedUserId && <CheckIcon className="w-4 h-4 text-gray-900 shrink-0" />}
                </button>
              ))}
              {filtered.length === 0 && (
                <div className="px-3 py-3 text-[12px] text-gray-400 text-center">No members found</div>
              )}
            </div>
          </div>
        </>
      )}
    </div>
  );
}
