import { useState, useMemo } from "react";
import {
  DndContext,
  DragOverlay,
  pointerWithin,
  PointerSensor,
  useSensor,
  useSensors,
  type DragStartEvent,
  type DragEndEvent,
  type DragOverEvent,
} from "@dnd-kit/core";
import {
  SortableContext,
  horizontalListSortingStrategy,
  useSortable,
  arrayMove,
} from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import { useQueryClient } from "@tanstack/react-query";
import { useProjectsStore } from "../../../stores/projectsStore";
import {
  useProjectBoard,
  useProjectBoards,
  useCreateState,
  useMoveIssue,
  useReorderIssues,
  useReorderStates,
  type ProjectIssue,
  type ProjectState,
} from "../../../hooks/queries/useProjects";
import { projectKeys } from "../../../hooks/queries/keys";
import KanbanColumn from "./KanbanColumn";
import KanbanCard from "./KanbanCard";
import CardDetailModal from "./CardDetailModal";
import AddColumnForm from "./AddColumnForm";

// Wrapper to make columns sortable
function SortableColumn({
  column,
  children,
}: {
  column: ProjectState;
  children: React.ReactNode;
}) {
  const {
    attributes,
    listeners,
    setNodeRef,
    transform,
    transition,
    isDragging,
  } = useSortable({
    id: column.id,
    data: {
      type: "column",
      column,
    },
  });

  const style = {
    transform: CSS.Transform.toString(transform),
    transition,
  };

  return (
    <div
      ref={setNodeRef}
      style={{ ...style, opacity: isDragging ? 0 : 1 }}
      className="h-full"
      {...attributes}
      {...listeners}
    >
      {children}
    </div>
  );
}

// Module-level flag to suppress card clicks right after a drag ends
export let lastDragEndTime = 0;

interface PreviewPosition {
  columnId: string;
  index: number;
}

export default function KanbanBoard() {
  // UI state from store
  const activeProjectId = useProjectsStore((state) => state.activeProjectId);
  const workspaceAppId = useProjectsStore((state) => state.workspaceAppId);
  const filters = useProjectsStore((state) => state.filters);
  const selectedCardId = useProjectsStore((state) => state.selectedCardId);
  const setSelectedCard = useProjectsStore((state) => state.setSelectedCard);

  // React Query
  const queryClient = useQueryClient();
  const { data: boards = [] } = useProjectBoards(workspaceAppId);
  const { data: boardData, isLoading: isBoardLoading } = useProjectBoard(activeProjectId);

  // React Query mutations
  const createState = useCreateState(activeProjectId);
  const moveIssue = useMoveIssue(activeProjectId);
  const reorderIssues = useReorderIssues(activeProjectId);
  const reorderStates = useReorderStates(activeProjectId);

  // Cache key for synchronous updates
  const boardDataKey = projectKeys.boardData(activeProjectId ?? '');

  const [activeCard, setActiveCard] = useState<ProjectIssue | null>(null);
  const [activeColumn, setActiveColumn] = useState<ProjectState | null>(null);
  const [previewPosition, setPreviewPosition] =
    useState<PreviewPosition | null>(null);

  // Derive data from React Query
  const project = boards.find((b) => b.id === activeProjectId) ?? null;
  const allColumns = useMemo(() => {
    if (!boardData?.states) return [];
    return [...boardData.states].sort((a, b) => a.position - b.position);
  }, [boardData?.states]);

  // Helper to check if a column is a "done" column
  const isDoneColumn = (col: ProjectState) => {
    const name = col.name.toLowerCase();
    return name === 'done' || name === 'completed';
  };

  // No longer filter out Done columns - we show all columns but mark Done as collapsed
  const columns = allColumns;

  const issues = boardData?.issues ?? [];

  // Helper to get sorted cards for a column (used in drag handlers)
  const getColumnCards = (stateId: string) => {
    return issues
      .filter((i) => i.state_id === stateId)
      .sort((a, b) => a.position - b.position);
  };

  // Filter logic
  const hasActiveFilters =
    filters.search.trim().length > 0 ||
    filters.statusIds.length > 0 ||
    filters.assigneeIds.length > 0 ||
    filters.labelIds.length > 0 ||
    filters.priorities.length > 0 ||
    filters.types.length > 0 ||
    filters.tags.length > 0 ||
    filters.createdByIds.length > 0 ||
    filters.lastEditedByIds.length > 0 ||
    filters.complexities.length > 0 ||
    !!filters.dueFrom ||
    !!filters.dueTo ||
    !!filters.targetDueFrom ||
    !!filters.targetDueTo;

  const filteredIssues = useMemo(() => {
    if (!issues.length) return [];
    const searchLower = filters.search.trim().toLowerCase();
    const hasStatusFilter = filters.statusIds.length > 0;
    const hasAssigneeFilter = filters.assigneeIds.length > 0;
    const hasLabelFilter = filters.labelIds.length > 0;
    const hasPriorityFilter = filters.priorities.length > 0;
    const hasTypeFilter = filters.types.length > 0;
    const hasTagFilter = filters.tags.length > 0;
    const hasCreatedByFilter = filters.createdByIds.length > 0;
    const hasLastEditedByFilter = filters.lastEditedByIds.length > 0;
    const hasComplexityFilter = filters.complexities.length > 0;
    const dueFrom = filters.dueFrom ? new Date(filters.dueFrom) : null;
    const dueTo = filters.dueTo ? new Date(filters.dueTo) : null;
    const targetDueFrom = filters.targetDueFrom ? new Date(filters.targetDueFrom) : null;
    const targetDueTo = filters.targetDueTo ? new Date(filters.targetDueTo) : null;
    if (dueFrom) dueFrom.setHours(0, 0, 0, 0);
    if (dueTo) dueTo.setHours(23, 59, 59, 999);
    if (targetDueFrom) targetDueFrom.setHours(0, 0, 0, 0);
    if (targetDueTo) targetDueTo.setHours(23, 59, 59, 999);

    return issues.filter((issue) => {
      if (searchLower) {
        const title = issue.title?.toLowerCase() || '';
        const description = issue.description?.toLowerCase() || '';
        const type = issue.type?.toLowerCase() || '';
        const tags = (issue.tags || []).join(' ').toLowerCase();
        if (!title.includes(searchLower) && !description.includes(searchLower) && !type.includes(searchLower) && !tags.includes(searchLower)) {
          return false;
        }
      }
      if (hasStatusFilter && !filters.statusIds.includes(issue.state_id)) {
        return false;
      }
      if (hasAssigneeFilter) {
        const assignees = issue.assignees || [];
        const match = assignees.some((a) => filters.assigneeIds.includes(a.user_id));
        if (!match) return false;
      }
      if (hasLabelFilter) {
        const labels = issue.label_objects || [];
        const match = labels.some((l) => filters.labelIds.includes(l.id));
        if (!match) return false;
      }
      if (hasPriorityFilter && !filters.priorities.includes(issue.priority || 0)) {
        return false;
      }
      if (hasTypeFilter && !filters.types.includes(issue.type || '')) {
        return false;
      }
      if (hasTagFilter) {
        const issueTags = issue.tags || [];
        if (!issueTags.some((tag) => filters.tags.includes(tag))) return false;
      }
      if (hasCreatedByFilter && (!issue.created_by || !filters.createdByIds.includes(issue.created_by))) {
        return false;
      }
      if (hasLastEditedByFilter && (!issue.last_edited_by || !filters.lastEditedByIds.includes(issue.last_edited_by))) {
        return false;
      }
      if (hasComplexityFilter && !filters.complexities.includes(issue.complexity ?? -1)) {
        return false;
      }
      if (dueFrom || dueTo) {
        if (!issue.due_at) return false;
        const dueDate = new Date(issue.due_at);
        if (dueFrom && dueDate < dueFrom) return false;
        if (dueTo && dueDate > dueTo) return false;
      }
      if (targetDueFrom || targetDueTo) {
        if (!issue.target_due_at) return false;
        const targetDueDate = new Date(issue.target_due_at);
        if (targetDueFrom && targetDueDate < targetDueFrom) return false;
        if (targetDueTo && targetDueDate > targetDueTo) return false;
      }
      return true;
    });
  }, [issues, filters]);

  const filteredIssueIds = useMemo(() => new Set(filteredIssues.map((i) => i.id)), [filteredIssues]);

  // Memoize cards per column to prevent KanbanColumn re-renders during drag
  // Without this, each column gets a new array reference on every KanbanBoard render
  const columnCardsMap = useMemo(() => {
    const map = new Map<string, ProjectIssue[]>();
    for (const column of columns) {
      const cards = issues
        .filter((i) => i.state_id === column.id && filteredIssueIds.has(i.id))
        .sort((a, b) => a.position - b.position);
      map.set(column.id, cards);
    }
    return map;
  }, [columns, issues, filteredIssueIds]);

  const selectedCard = selectedCardId
    ? (issues.find((i) => i.id === selectedCardId) ?? null)
    : null;

  const sensors = useSensors(
    useSensor(PointerSensor, {
      activationConstraint: {
        distance: 8,
      },
    }),
  );

  if (!project) {
    return (
      <div className="flex items-center justify-center h-full">
        <p className="text-text-tertiary">Select a project to view the board</p>
      </div>
    );
  }

  // Show loading state while fetching board data
  if (isBoardLoading) {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="flex items-center gap-2 text-text-tertiary">
          <div className="w-4 h-4 border-2 border-current border-t-transparent rounded-full animate-spin" />
          <span>Loading board...</span>
        </div>
      </div>
    );
  }

  const handleAddColumn = (name: string, color?: string) => {
    createState.mutate({ name, color });
  };

  const handleDragStart = (event: DragStartEvent) => {
    const { active } = event;
    const activeType = active.data?.current?.type;

    if (activeType === "column") {
      const column = active.data?.current?.column as ProjectState;
      if (column) {
        setActiveColumn(column);
      }
    } else {
      const card = issues.find((i) => i.id === String(active.id));
      if (card) {
        setActiveCard(card);
      }
    }
  };

  const handleDragOver = (event: DragOverEvent) => {
    const { active, over } = event;

    if (!over) {
      setPreviewPosition(null);
      return;
    }

    // Ignore column drags for preview
    if (active.data?.current?.type === "column") return;

    const draggedCard = issues.find((i) => i.id === String(active.id));
    if (!draggedCard) return;

    const overType = over.data?.current?.type;

    if (overType === "card") {
      // Hovering over another card - show insertion point
      const overCard = over.data?.current?.card as ProjectIssue;
      if (overCard) {
        const targetColumnCards = getColumnCards(overCard.state_id);
        const overCardIndex = targetColumnCards.findIndex(
          (c) => c.id === overCard.id,
        );
        setPreviewPosition({
          columnId: overCard.state_id,
          index: overCardIndex,
        });
      }
    } else if (overType === "column") {
      // Hovering over column (empty area) - show at end
      const columnId = String(over.id);
      const targetColumnCards = getColumnCards(columnId);
      setPreviewPosition({
        columnId,
        index: targetColumnCards.length,
      });
    }
  };

  const handleDragEnd = (event: DragEndEvent) => {
    const { active, over } = event;

    // Mark drag end time immediately
    lastDragEndTime = Date.now();

    // Clear preview position
    setPreviewPosition(null);

    // Helper to clear drag state after mutation is queued
    const clearDragState = () => {
      setActiveCard(null);
      setActiveColumn(null);
    };

    if (!over) {
      clearDragState();
      return;
    }

    // Handle column reordering
    if (active.data?.current?.type === "column") {
      if (active.id !== over.id && activeProjectId) {
        const oldIndex = columns.findIndex((col) => col.id === active.id);
        const newIndex = columns.findIndex((col) => col.id === over.id);
        if (oldIndex !== -1 && newIndex !== -1) {
          const reordered = arrayMove(columns, oldIndex, newIndex);
          const items = reordered.map((col, idx) => ({
            id: col.id,
            position: idx,
          }));
          // Mutation fires first (optimistic update), then clear state
          reorderStates.mutate(items);
        }
      }
      clearDragState();
      return;
    }

    const draggedCard = issues.find((i) => i.id === String(active.id));
    if (!draggedCard) {
      clearDragState();
      return;
    }

    const overType = over.data?.current?.type;
    let targetColumnId: string;
    let newPosition: number;

    if (overType === "card") {
      // Dropped on a card - insert at that card's position
      const overCard = over.data?.current?.card as ProjectIssue;
      if (!overCard) {
        clearDragState();
        return;
      }

      targetColumnId = overCard.state_id;
      const targetColumnCards = getColumnCards(targetColumnId);
      const overCardIndex = targetColumnCards.findIndex(
        (c) => c.id === overCard.id,
      );

      // Determine insertion position
      if (draggedCard.state_id === targetColumnId) {
        // Same column: if dragging down, insert at overCard's position
        // if dragging up, also insert at overCard's position (it will shift down)
        const draggedIndex = targetColumnCards.findIndex(
          (c) => c.id === draggedCard.id,
        );
        if (draggedIndex < overCardIndex) {
          newPosition = overCard.position;
        } else {
          newPosition = overCard.position;
        }
      } else {
        // Different column: insert at overCard's position
        newPosition = overCard.position;
      }
    } else if (overType === "column") {
      // Dropped on column (empty area) - add to end
      targetColumnId = String(over.id);
      const targetColumnCards = getColumnCards(targetColumnId);
      newPosition = targetColumnCards.length;
    } else {
      // Fallback - shouldn't happen but handle gracefully
      clearDragState();
      return;
    }

    // Only act if something changed
    if (
      draggedCard.state_id !== targetColumnId ||
      draggedCard.position !== newPosition
    ) {
      // SYNCHRONOUSLY update the cache before clearing drag state
      // This prevents the visual "flash back" glitch
      type BoardData = { states: ProjectState[]; issues: ProjectIssue[]; labels: unknown[] };

      if (draggedCard.state_id === targetColumnId) {
        // Same column reorder
        const columnCards = getColumnCards(targetColumnId);
        const filtered = columnCards.filter((c) => c.id !== draggedCard.id);
        filtered.splice(
          newPosition > draggedCard.position ? newPosition - 1 : newPosition,
          0,
          draggedCard,
        );
        const items = filtered.map((c, idx) => ({ id: c.id, position: idx }));

        // Synchronous cache update
        queryClient.setQueryData<BoardData>(boardDataKey, (old) => {
          if (!old) return old;
          const positionMap = new Map(items.map((item) => [item.id, item.position]));
          return {
            ...old,
            issues: old.issues.map((issue) => {
              const newPos = positionMap.get(issue.id);
              return newPos !== undefined ? { ...issue, position: newPos } : issue;
            }),
          };
        });

        // Then fire mutation for server sync
        reorderIssues.mutate({ stateId: targetColumnId, items });
      } else {
        // Cross-column move - synchronous cache update
        const sourceStateId = draggedCard.state_id;
        const oldPosition = draggedCard.position;

        queryClient.setQueryData<BoardData>(boardDataKey, (old) => {
          if (!old) return old;
          return {
            ...old,
            issues: old.issues.map((issue) => {
              if (issue.id === draggedCard.id) {
                return { ...issue, state_id: targetColumnId, position: newPosition };
              }
              // Shift positions in source column
              if (issue.state_id === sourceStateId && issue.position > oldPosition) {
                return { ...issue, position: issue.position - 1 };
              }
              // Shift positions in target column
              if (issue.state_id === targetColumnId && issue.position >= newPosition) {
                return { ...issue, position: issue.position + 1 };
              }
              return issue;
            }),
          };
        });

        // Then fire mutation for server sync
        moveIssue.mutate({
          issueId: draggedCard.id,
          targetStateId: targetColumnId,
          position: newPosition,
        });
      }
    }

    // Now safe to clear drag state - cache is already updated
    clearDragState();
  };

  const handleDragCancel = () => {
    setActiveCard(null);
    setActiveColumn(null);
    setPreviewPosition(null);
    lastDragEndTime = Date.now();
  };

  return (
    <DndContext
      sensors={sensors}
      collisionDetection={pointerWithin}
      onDragStart={handleDragStart}
      onDragOver={handleDragOver}
      onDragEnd={handleDragEnd}
      onDragCancel={handleDragCancel}
    >
      <div className="flex flex-col flex-1 min-h-0 h-full">
        {/* Board Content */}
        <div className="flex-1 min-h-0 h-full overflow-auto px-2 pt-2 pb-8">
          {filteredIssues.length === 0 && columns.length > 0 && (
            <div className="px-1 pb-4 text-sm text-gray-400">
              {hasActiveFilters ? "No matching results" : "No cards yet"}
            </div>
          )}
          <div className="grid grid-flow-col auto-cols-max gap-2">
            {/* Columns */}
            {columns.length === 0 ? (
              <div className="flex items-center justify-center flex-1">
                <AddColumnForm onAdd={handleAddColumn} />
              </div>
            ) : (
              <>
                <SortableContext
                  items={columns.map((col) => col.id)}
                  strategy={horizontalListSortingStrategy}
                >
                  {columns.map((column) => (
                    <SortableColumn key={column.id} column={column}>
                      <KanbanColumn
                        column={column}
                        boardId={project.id}
                        cardsOverride={columnCardsMap.get(column.id) ?? []}
                        previewIndex={
                          previewPosition?.columnId === column.id
                            ? previewPosition.index
                            : null
                        }
                        activeCardId={activeCard?.id}
                        isDragActive={!!activeCard}
                        isCollapsed={filters.showActiveOnly && isDoneColumn(column)}
                      />
                    </SortableColumn>
                  ))}
                </SortableContext>

                {/* Add Column Form */}
                <AddColumnForm onAdd={handleAddColumn} />
              </>
            )}
          </div>
        </div>
      </div>

      {/* Drag Overlay */}
      <DragOverlay
        dropAnimation={{
          duration: 200,
          easing: "cubic-bezier(0.18, 0.67, 0.6, 1.22)",
        }}
      >
        {activeCard && <KanbanCard card={activeCard} isOverlay />}
        {activeColumn && (
          <div className="opacity-90">
            <KanbanColumn
              column={activeColumn}
              boardId={project?.id ?? ""}
              cardsOverride={columnCardsMap.get(activeColumn.id) ?? []}
            />
          </div>
        )}
      </DragOverlay>

      {/* Card Detail Modal */}
      {selectedCard && (
        <CardDetailModal
          card={selectedCard}
          initialEdit={true}
          onClose={() => {
            setSelectedCard(null);
          }}
        />
      )}
    </DndContext>
  );
}
