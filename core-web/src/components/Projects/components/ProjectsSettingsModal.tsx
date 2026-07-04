import { useState, useEffect } from "react";
import { createPortal } from "react-dom";
import { motion } from "motion/react";
import { XMarkIcon, ChevronDownIcon } from "@heroicons/react/24/outline";
import {
  createProjectBoardView,
  getProjectBoardRolePresets,
  getProjectBoardViews,
  saveProjectBoardRolePreset,
  updateProjectBoard,
  updateProjectState,
  type ProjectBoardView,
  type ProjectState,
} from "../../../api/client";
import { useProjectsStore } from "../../../stores/projectsStore";

interface ProjectsSettingsModalProps {
  isOpen: boolean;
  onClose: () => void;
  boardId: string | null;
  boardName: string;
  boardDescription?: string;
  states?: ProjectState[];
  initialTab?: "board" | "app";
  onSave: (name: string, description: string) => Promise<void>;
  onDelete?: () => void;
}

export default function ProjectsSettingsModal({
  isOpen,
  onClose,
  boardId: _boardId,
  boardName,
  boardDescription = "",
  states = [],
  initialTab = "board",
  onSave,
  onDelete,
}: ProjectsSettingsModalProps) {
  const [activeTab, setActiveTab] = useState<"board" | "app">("board");
  const [editingName, setEditingName] = useState(boardName);
  const [editingDescription, setEditingDescription] = useState(boardDescription);
  const [showAdvancedOptions, setShowAdvancedOptions] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
  const [roleCapabilities, setRoleCapabilities] = useState<Record<string, boolean>>({});
  const [views, setViews] = useState<ProjectBoardView[]>([]);
  const [viewName, setViewName] = useState("");
  const [enforceColumnLimits, setEnforceColumnLimits] = useState(true);
  const [stateControls, setStateControls] = useState<Record<string, { is_locked: boolean; wip_limit: string }>>({});
  const filters = useProjectsStore((state) => state.filters);

  // Reset form when modal opens or board changes
  useEffect(() => {
    if (isOpen) {
      setEditingName(boardName);
      setEditingDescription(boardDescription);
      setShowAdvancedOptions(false);
      setActiveTab(initialTab);
      setViewName("");
      setStateControls(
        Object.fromEntries(
          states.map((state) => [
            state.id,
            {
              is_locked: !!state.is_locked,
              wip_limit: state.wip_limit == null ? "" : String(state.wip_limit),
            },
          ]),
        ),
      );
      if (_boardId) {
        void Promise.all([
          getProjectBoardRolePresets(_boardId).then((data) => {
            const memberPreset = data.role_presets.find((preset) => preset.role === "member");
            setRoleCapabilities(memberPreset?.capabilities || data.capabilities || {});
          }),
          getProjectBoardViews(_boardId).then(setViews),
        ]).catch((err) => console.error("Failed to load project settings:", err));
      }
    }
  }, [isOpen, boardName, boardDescription, _boardId, initialTab, states]);

  const handleSave = async () => {
    if (!editingName.trim() || isSaving) return;
    setIsSaving(true);
    try {
      await onSave(editingName.trim(), editingDescription.trim());
      if (_boardId) {
        await updateProjectBoard(_boardId, { enforce_column_limits: enforceColumnLimits });
      }
      onClose();
    } catch (err) {
      console.error("Failed to save board settings:", err);
    } finally {
      setIsSaving(false);
    }
  };

  const handleSaveMemberPermissions = async () => {
    if (!_boardId) return;
    await saveProjectBoardRolePreset(_boardId, "member", roleCapabilities);
  };

  const handleSaveColumnControl = async (stateId: string) => {
    const control = stateControls[stateId];
    if (!control) return;
    await updateProjectState(stateId, {
      is_locked: control.is_locked,
      wip_limit: control.wip_limit === "" ? undefined : Number(control.wip_limit),
      clear_wip_limit: control.wip_limit === "",
    });
  };

  const handleCreateView = async () => {
    if (!_boardId || !viewName.trim()) return;
    const view = await createProjectBoardView(_boardId, {
      name: viewName.trim(),
      filters: { ...filters },
      layout: "kanban",
      is_shared: true,
    });
    setViews((prev) => [view, ...prev]);
    setViewName("");
  };

  const handleClose = () => {
    setShowAdvancedOptions(false);
    onClose();
  };

  if (!isOpen) return null;

  return createPortal(
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      transition={{ duration: 0.15 }}
      className="fixed inset-0 bg-black/40 flex items-center justify-center z-[9999]"
      onClick={(e) => {
        if (e.target === e.currentTarget) handleClose();
      }}
    >
      <motion.div
        initial={{ opacity: 0, scale: 0.95, y: 10 }}
        animate={{ opacity: 1, scale: 1, y: 0 }}
        exit={{ opacity: 0, scale: 0.95, y: 10 }}
        transition={{ duration: 0.15, ease: [0.4, 0, 0.2, 1] }}
        className="bg-white rounded-lg shadow-xl w-[520px] max-w-[calc(100%-2rem)] max-h-[80vh] flex flex-col overflow-hidden"
        style={{ minHeight: 400 }}
        onClick={(e) => e.stopPropagation()}
      >
        {/* Modal Header */}
        <div className="flex items-center justify-between px-6 py-5">
          <h2 className="text-lg font-semibold text-gray-900">Projects</h2>
          <button
            onClick={handleClose}
            className="p-1 text-gray-400 hover:text-gray-600 hover:bg-gray-100 rounded-md transition-colors"
          >
            <XMarkIcon className="w-5 h-5" />
          </button>
        </div>

        {/* Tabs */}
        <div className="flex gap-4 px-6 mb-4">
          <button
            onClick={() => setActiveTab("board")}
            className={`pb-2 text-sm font-medium transition-colors relative ${
              activeTab === "board"
                ? "text-gray-900"
                : "text-gray-500 hover:text-gray-700"
            }`}
          >
            Board Settings
            {activeTab === "board" && (
              <div className="absolute bottom-0 left-0 right-0 h-0.5 bg-gray-900 rounded-full" />
            )}
          </button>
          <button
            onClick={() => setActiveTab("app")}
            className={`pb-2 text-sm font-medium transition-colors relative ${
              activeTab === "app"
                ? "text-gray-900"
                : "text-gray-500 hover:text-gray-700"
            }`}
          >
            App Settings
            {activeTab === "app" && (
              <div className="absolute bottom-0 left-0 right-0 h-0.5 bg-gray-900 rounded-full" />
            )}
          </button>
        </div>

        {/* Tab Content */}
        {activeTab === "board" ? (
          <>
            <div className="overflow-y-auto flex-1 px-6 py-3 space-y-4">
              {/* Board Details Section */}
              <div>
                <h3 className="text-xs font-medium text-text-secondary mb-2">
                  Details
                </h3>
                {/* Board Name */}
                <div className="mb-3">
                  <label className="block text-xs text-text-secondary mb-2">
                    Name
                  </label>
                  <input
                    type="text"
                    value={editingName}
                    onChange={(e) => setEditingName(e.target.value)}
                    placeholder="e.g. Product Roadmap"
                    className="w-full px-3 py-2.5 bg-white border border-border-gray rounded-lg text-sm outline-none focus:border-text-tertiary"
                  />
                </div>

                {/* Board Description */}
                <div>
                  <label className="block text-xs text-text-secondary mb-2">
                    Description{" "}
                    <span className="text-text-tertiary">(optional)</span>
                  </label>
                  <textarea
                    value={editingDescription}
                    onChange={(e) => setEditingDescription(e.target.value)}
                    placeholder="What's this board about?"
                    rows={2}
                    className="w-full px-3 py-2.5 bg-white border border-border-gray rounded-lg text-sm outline-none focus:border-text-tertiary resize-none"
                  />
                </div>
              </div>

              {states.length > 0 && (
                <div className="border-t border-border-light pt-4">
                  <div className="flex items-center justify-between mb-3">
                    <div>
                      <h3 className="text-xs font-medium text-text-secondary">
                        Column controls
                      </h3>
                    </div>
                    <label className="flex items-center gap-2 text-xs text-text-secondary">
                      <input
                        type="checkbox"
                        checked={enforceColumnLimits}
                        onChange={(e) => setEnforceColumnLimits(e.target.checked)}
                      />
                      Enforce caps
                    </label>
                  </div>
                  <div className="space-y-2">
                    {states.map((state) => {
                      const control = stateControls[state.id] || { is_locked: false, wip_limit: "" };
                      return (
                        <div key={state.id} className="flex items-center gap-2 p-2 bg-gray-50 rounded-lg">
                          <span className="flex-1 text-sm truncate">{state.name}</span>
                          <label className="flex items-center gap-1 text-xs text-text-secondary">
                            <input
                              type="checkbox"
                              checked={control.is_locked}
                              onChange={(e) =>
                                setStateControls((prev) => ({
                                  ...prev,
                                  [state.id]: { ...control, is_locked: e.target.checked },
                                }))
                              }
                            />
                            Locked
                          </label>
                          <input
                            value={control.wip_limit}
                            onChange={(e) =>
                              setStateControls((prev) => ({
                                ...prev,
                                [state.id]: { ...control, wip_limit: e.target.value.replace(/\D/g, "") },
                              }))
                            }
                            placeholder="Cap"
                            className="w-16 px-2 py-1 bg-white border border-border-gray rounded text-xs"
                          />
                          <button
                            onClick={() => void handleSaveColumnControl(state.id)}
                            className="px-2 py-1 text-xs bg-white border border-border-gray rounded"
                          >
                            Save
                          </button>
                        </div>
                      );
                    })}
                  </div>
                </div>
              )}

              {/* Collapsible Advanced Options */}
              {onDelete && (
                <div className="border-t border-border-light pt-4">
                  <button
                    onClick={() => setShowAdvancedOptions(!showAdvancedOptions)}
                    className="flex items-center gap-2 text-xs text-text-tertiary hover:text-text-secondary transition-colors"
                  >
                    <ChevronDownIcon
                      className="w-3 h-3"
                      style={{
                        transform: showAdvancedOptions ? "rotate(0deg)" : "rotate(-90deg)",
                        transition: "transform 0.15s ease",
                      }}
                    />
                    Advanced options
                  </button>
                  {showAdvancedOptions && (
                    <div className="mt-3">
                      <p className="text-xs text-text-tertiary mb-3">
                        Deleting this board will permanently remove all cards and data. This action cannot be undone.
                      </p>
                      <button
                        onClick={() => {
                          handleClose();
                          onDelete();
                        }}
                        className="px-3 py-1.5 text-xs text-red-600 border border-red-200 rounded-md hover:bg-red-50 transition-colors"
                      >
                        Delete board
                      </button>
                    </div>
                  )}
                </div>
              )}
            </div>

            {/* Board Settings Footer */}
            <div className="flex justify-end gap-2 px-6 py-4 border-t border-border-light">
              <button
                onClick={handleClose}
                className="px-4 py-2 text-sm text-text-secondary hover:bg-bg-gray rounded-lg"
              >
                Cancel
              </button>
              <button
                onClick={handleSave}
                disabled={!editingName.trim() || isSaving}
                className="px-4 py-2 text-sm bg-black text-white rounded-lg disabled:opacity-50"
              >
                {isSaving ? "Saving..." : "Save"}
              </button>
            </div>
          </>
        ) : (
          <>
            {/* App Settings Tab Content */}
            <div className="overflow-y-auto flex-1 px-6 py-4">
              <h3 className="text-sm font-medium text-gray-900 mb-3">Member permissions</h3>
              <div className="space-y-2 mb-5">
                {[
                  ["create_issue", "Create cards"],
                  ["update_issue", "Edit cards"],
                  ["move_issue", "Move cards"],
                  ["assign_issue", "Assign cards"],
                  ["comment_issue", "Comment"],
                  ["delete_issue", "Delete cards"],
                  ["manage_board", "Manage board"],
                ].map(([key, label]) => (
                  <label key={key} className="flex items-center justify-between p-3 bg-gray-50 rounded-lg">
                    <span className="text-sm text-gray-900">{label}</span>
                    <input
                      type="checkbox"
                      checked={!!roleCapabilities[key]}
                      onChange={(e) =>
                        setRoleCapabilities((prev) => ({
                          ...prev,
                          [key]: e.target.checked,
                        }))
                      }
                    />
                  </label>
                ))}
                <button
                  onClick={() => void handleSaveMemberPermissions()}
                  className="px-3 py-2 text-xs bg-black text-white rounded-lg"
                >
                  Save permissions
                </button>
              </div>
              <h3 className="text-sm font-medium text-gray-900 mb-3">Saved views</h3>
              <div className="flex gap-2 mb-3">
                <input
                  value={viewName}
                  onChange={(e) => setViewName(e.target.value)}
                  placeholder="View name"
                  className="flex-1 px-3 py-2 bg-white border border-border-gray rounded-lg text-sm outline-none"
                />
                <button
                  onClick={() => void handleCreateView()}
                  disabled={!viewName.trim()}
                  className="px-3 py-2 text-xs bg-black text-white rounded-lg disabled:opacity-50"
                >
                  Save view
                </button>
              </div>
              <div className="space-y-1">
                {views.length === 0 ? (
                  <p className="text-xs text-text-secondary">No saved views</p>
                ) : views.map((view) => (
                  <div key={view.id} className="flex items-center justify-between p-3 bg-gray-50 rounded-lg">
                    <span className="text-sm text-gray-900">{view.name}</span>
                    <span className="text-[11px] text-gray-500">{view.layout}</span>
                  </div>
                ))}
              </div>
            </div>

            {/* App Settings Footer */}
            <div className="flex justify-end gap-2 px-6 py-4 border-t border-border-light">
              <button
                onClick={handleClose}
                className="px-4 py-2 text-sm text-text-secondary hover:bg-bg-gray rounded-lg"
              >
                Cancel
              </button>
              <button
                disabled
                className="px-4 py-2 text-sm bg-black text-white rounded-lg disabled:opacity-50"
              >
                Save
              </button>
            </div>
          </>
        )}
      </motion.div>
    </motion.div>,
    document.body
  );
}
