import { useEffect, useRef, useState } from 'react';
import {
  ArrowDownTrayIcon,
  CheckCircleIcon,
  ClockIcon,
  LockClosedIcon,
  PaperClipIcon,
  XCircleIcon,
} from '@heroicons/react/24/outline';
import type { IssueAttachment, ProjectIssue, WorkspaceMember } from '../../../api/client';
import {
  useAttachmentVersionUrl,
  useAttachmentVersions,
  useIssueApprovalActions,
  useIssueAttachments,
  useUploadAttachmentVersion,
} from '../../../hooks/queries/useProjects';
import { formatDateFull } from '../../../utils/dateUtils';
import ApproverPicker from './ApproverPicker';

interface ApprovalPanelProps {
  card: ProjectIssue;
  capabilities: Record<string, boolean>;
  currentUserId?: string;
  members: WorkspaceMember[];
}

const STATUS_LABELS: Record<string, string> = {
  none: 'No approval',
  pending: 'Pending approval',
  approved: 'Approved',
  rejected: 'Changes requested',
};

const memberName = (member?: WorkspaceMember) => member?.name || member?.email || 'Member';

function AttachmentRow({
  attachment,
  disabled,
  onUploadVersion,
}: {
  attachment: IssueAttachment;
  disabled: boolean;
  onUploadVersion: (attachmentId: string, file: File) => void;
}) {
  const [showVersions, setShowVersions] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const { data: versions = [] } = useAttachmentVersions(showVersions ? attachment.id : null);
  const versionUrl = useAttachmentVersionUrl();

  const openVersion = (versionId: string) => {
    versionUrl.mutate(versionId, {
      onSuccess: ({ url }) => window.open(url, '_blank', 'noopener,noreferrer'),
    });
  };

  return (
    <div className="rounded-lg border border-gray-100 px-3 py-2">
      <div className="flex items-center gap-2">
        <PaperClipIcon className="w-4 h-4 text-gray-400 shrink-0" />
        <button
          type="button"
          onClick={() => setShowVersions((value) => !value)}
          className="flex-1 min-w-0 text-left text-[12px] font-medium text-gray-700 truncate"
        >
          {attachment.filename}
        </button>
        <span className="text-[11px] text-gray-400 shrink-0">
          v{Math.max(1, (attachment.next_version_number || 2) - 1)}
        </span>
        <input
          ref={inputRef}
          type="file"
          className="hidden"
          onChange={(event) => {
            const file = event.target.files?.[0];
            if (file) onUploadVersion(attachment.id, file);
            if (inputRef.current) inputRef.current.value = '';
          }}
        />
        <button
          type="button"
          disabled={disabled}
          onClick={() => inputRef.current?.click()}
          className="px-2 py-1 text-[11px] text-gray-500 hover:text-gray-700 hover:bg-gray-50 rounded-md disabled:opacity-40"
        >
          Version
        </button>
      </div>

      {showVersions && (
        <div className="mt-2 space-y-1 border-t border-gray-100 pt-2">
          {versions.map((version) => (
            <button
              key={version.id}
              type="button"
              onClick={() => openVersion(version.id)}
              className="w-full flex items-center gap-2 px-2 py-1.5 text-[11px] text-gray-500 hover:text-gray-700 hover:bg-gray-50 rounded-md"
            >
              <ArrowDownTrayIcon className="w-3.5 h-3.5" />
              <span>Version {version.version_number}</span>
              <span className="ml-auto tabular-nums">{Math.ceil(version.file_size / 1024)} KB</span>
            </button>
          ))}
          {versions.length === 0 && <div className="px-2 py-1 text-[11px] text-gray-400">No versions</div>}
        </div>
      )}
    </div>
  );
}

export default function ApprovalPanel({
  card,
  capabilities,
  currentUserId,
  members,
}: ApprovalPanelProps) {
  const [displayCard, setDisplayCard] = useState(card);
  const [requestNote, setRequestNote] = useState('');
  const [rejectNote, setRejectNote] = useState('');
  const [isRejecting, setIsRejecting] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const { requestApproval, approveApproval, rejectApproval, unlockApproval } = useIssueApprovalActions(displayCard.board_id);
  const { data: attachments = [] } = useIssueAttachments(displayCard.id);
  const uploadAttachment = useUploadAttachmentVersion(displayCard.board_id);

  useEffect(() => {
    setDisplayCard(card);
  }, [card]);

  const status = displayCard.approval_status || 'none';
  const canManage = Boolean(capabilities.manage_approval);
  const canAssign = Boolean(capabilities.request_approval) || canManage || displayCard.created_by === currentUserId;
  const canDecide = status === 'pending' && displayCard.approver_id === currentUserId;
  const isLocked = Boolean(displayCard.approval_locked);

  const requester = members.find((member) => member.user_id === displayCard.approval_requested_by);
  const assignedApprover = members.find((member) => member.user_id === displayCard.approver_id);
  const decisionMaker = members.find((member) => member.user_id === displayCard.approved_by);

  const handleSelectApprover = (approverId: string) => {
    requestApproval.mutate(
      { issueId: displayCard.id, approverId, note: requestNote.trim() || undefined },
      {
        onSuccess: (updated) => {
          setDisplayCard(updated);
          setRequestNote('');
        },
      }
    );
  };

  const handleApprove = () => {
    approveApproval.mutate(
      { issueId: displayCard.id },
      { onSuccess: (updated) => setDisplayCard(updated) }
    );
  };

  const handleReject = () => {
    if (!rejectNote.trim()) return;
    rejectApproval.mutate(
      { issueId: displayCard.id, note: rejectNote.trim() },
      {
        onSuccess: (updated) => {
          setDisplayCard(updated);
          setRejectNote('');
          setIsRejecting(false);
        },
      }
    );
  };

  const handleUnlock = () => {
    unlockApproval.mutate(
      { issueId: displayCard.id },
      { onSuccess: (updated) => setDisplayCard(updated) }
    );
  };

  const uploadFile = (file: File, attachmentId?: string) => {
    uploadAttachment.mutate({ issueId: displayCard.id, file, attachmentId });
  };

  return (
    <div className="border-t border-gray-100 pt-5 space-y-4">
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-start gap-2 min-w-0">
          {status === 'approved' ? (
            <CheckCircleIcon className="w-4 h-4 text-emerald-500 mt-0.5" />
          ) : status === 'rejected' ? (
            <XCircleIcon className="w-4 h-4 text-red-500 mt-0.5" />
          ) : (
            <ClockIcon className="w-4 h-4 text-amber-500 mt-0.5" />
          )}
          <div className="min-w-0">
            <div className="flex items-center gap-2 text-[12px] font-medium text-gray-700">
              <span>{STATUS_LABELS[status] || STATUS_LABELS.none}</span>
              {isLocked && (
                <span className="inline-flex items-center gap-1 text-[11px] text-gray-500">
                  <LockClosedIcon className="w-3.5 h-3.5" />
                  Locked
                </span>
              )}
            </div>
            {displayCard.approval_requested_at && (
              <div className="text-[11px] text-gray-400 truncate">
                {memberName(requester)} - {formatDateFull(displayCard.approval_requested_at)}
              </div>
            )}
            {assignedApprover && (
              <div className="text-[11px] text-gray-400 truncate">
                Approver: {memberName(assignedApprover)}
              </div>
            )}
          </div>
        </div>

        <div className="flex items-center gap-2 shrink-0">
          {canDecide && (
            <>
              <button
                onClick={handleApprove}
                disabled={approveApproval.isPending || rejectApproval.isPending}
                className="px-3 py-1.5 text-[12px] font-medium text-emerald-700 bg-emerald-50 hover:bg-emerald-100 rounded-lg disabled:opacity-40"
              >
                Approve
              </button>
              <button
                onClick={() => setIsRejecting((value) => !value)}
                disabled={approveApproval.isPending || rejectApproval.isPending}
                className="px-3 py-1.5 text-[12px] font-medium text-red-600 bg-red-50 hover:bg-red-100 rounded-lg disabled:opacity-40"
              >
                Reject
              </button>
            </>
          )}
          {canManage && isLocked && (
            <button
              onClick={handleUnlock}
              disabled={unlockApproval.isPending}
              className="px-3 py-1.5 text-[12px] font-medium text-gray-600 bg-gray-50 hover:bg-gray-100 rounded-lg disabled:opacity-40"
            >
              Unlock
            </button>
          )}
        </div>
      </div>

      {displayCard.approval_note && (
        <p className="text-[12px] text-gray-500 leading-relaxed whitespace-pre-wrap">
          {displayCard.approval_note}
        </p>
      )}

      {displayCard.approval_decision_note && (
        <p className="text-[12px] text-gray-500 leading-relaxed whitespace-pre-wrap">
          {memberName(decisionMaker)}: {displayCard.approval_decision_note}
        </p>
      )}

      {canAssign && !isLocked && (
        <div className="flex flex-col gap-2">
          <textarea
            value={requestNote}
            onChange={(event) => setRequestNote(event.target.value)}
            rows={2}
            className="w-full px-3 py-2 text-[12px] text-gray-700 border border-gray-200 rounded-lg resize-none focus:outline-none focus:ring-1 focus:ring-gray-300"
            placeholder="Approval note"
          />
          <ApproverPicker
            members={members}
            selectedUserId={displayCard.approver_id}
            excludedUserId={displayCard.created_by}
            disabled={requestApproval.isPending}
            onSelect={handleSelectApprover}
          />
        </div>
      )}

      {isRejecting && canDecide && (
        <div className="flex items-start gap-2">
          <textarea
            value={rejectNote}
            onChange={(event) => setRejectNote(event.target.value)}
            rows={2}
            className="flex-1 min-w-0 px-3 py-2 text-[12px] text-gray-700 border border-gray-200 rounded-lg resize-none focus:outline-none focus:ring-1 focus:ring-gray-300"
            placeholder="Required reason"
          />
          <button
            onClick={handleReject}
            disabled={!rejectNote.trim() || rejectApproval.isPending}
            className="px-3 py-2 text-[12px] font-medium bg-red-500 text-white rounded-lg hover:bg-red-600 disabled:opacity-40"
          >
            Send
          </button>
        </div>
      )}

      <div className="border-t border-gray-100 pt-4">
        <div className="flex items-center justify-between gap-2 mb-3">
          <div className="flex items-center gap-2">
            <PaperClipIcon className="w-4 h-4 text-gray-400" />
            <span className="text-[12px] font-medium text-gray-500">Attachments</span>
          </div>
          <input
            ref={fileInputRef}
            type="file"
            className="hidden"
            onChange={(event) => {
              const file = event.target.files?.[0];
              if (file) uploadFile(file);
              if (fileInputRef.current) fileInputRef.current.value = '';
            }}
          />
          <button
            type="button"
            disabled={isLocked || uploadAttachment.isPending}
            onClick={() => fileInputRef.current?.click()}
            className="px-2.5 py-1.5 text-[11px] font-medium text-gray-600 bg-gray-50 hover:bg-gray-100 rounded-lg disabled:opacity-40"
          >
            Upload
          </button>
        </div>
        <div className="space-y-2">
          {attachments.map((attachment) => (
            <AttachmentRow
              key={attachment.id}
              attachment={attachment}
              disabled={isLocked || uploadAttachment.isPending}
              onUploadVersion={(attachmentId, file) => uploadFile(file, attachmentId)}
            />
          ))}
          {attachments.length === 0 && (
            <div className="text-[12px] text-gray-400">No attachments</div>
          )}
        </div>
      </div>
    </div>
  );
}
