import { create } from 'zustand';
import { persist } from 'zustand/middleware';
import {
  getAgentConversations,
  createAgentConversation,
  deleteAgentConversation,
  renameAgentConversation,
  type AgentConversation,
} from '../api/client';

interface AgentConversationState {
  conversations: AgentConversation[];
  activeConversationId: string | null;
  currentAgentId: string | null;
  isLoading: boolean;
  isRevalidating: boolean;
  lastFetched: number | null;

  fetchConversations: (agentId: string) => Promise<void>;
  addConversation: (agentId: string, title?: string) => Promise<AgentConversation>;
  removeConversation: (agentId: string, conversationId: string) => Promise<void>;
  updateTitle: (agentId: string, conversationId: string, title: string) => Promise<void>;
  setActiveConversationId: (id: string | null) => void;
  setCurrentAgentId: (agentId: string | null) => void;
  handleRealtimeInsert: (conversation: AgentConversation) => void;
  handleRealtimeUpdate: (conversation: AgentConversation) => void;
  handleRealtimeDelete: (conversationId: string) => void;
}

export const useAgentConversationStore = create<AgentConversationState>()(
  persist(
    (set, get) => ({
      conversations: [],
      activeConversationId: null,
      currentAgentId: null,
      isLoading: false,
      isRevalidating: false,
      lastFetched: null,

      fetchConversations: async (agentId: string) => {
        const { conversations: cached, lastFetched, currentAgentId } = get();
        const isSameAgent = currentAgentId === agentId;
        const hasCachedData = isSameAgent && cached.length > 0 && lastFetched;

        if (hasCachedData) {
          set({ isRevalidating: true });
        } else {
          set({ isLoading: true, conversations: [], activeConversationId: null });
        }

        set({ currentAgentId: agentId });

        try {
          const data = await getAgentConversations(agentId);
          // Discard stale response if agent changed while fetching
          if (get().currentAgentId !== agentId) return;
          const convos = data.conversations || [];
          const { activeConversationId } = get();
          set({
            conversations: convos,
            lastFetched: Date.now(),
            // Auto-select most recent conversation when switching agents
            ...(!activeConversationId && convos.length > 0
              ? { activeConversationId: convos[0].id }
              : {}),
          });
        } catch (err) {
          console.error('Failed to fetch agent conversations:', err);
        } finally {
          if (get().currentAgentId === agentId) {
            set({ isLoading: false, isRevalidating: false });
          }
        }
      },

      addConversation: async (agentId: string, title?: string) => {
        const conversation = await createAgentConversation(agentId, title);
        const { conversations } = get();
        set({
          conversations: [conversation, ...conversations],
          activeConversationId: conversation.id,
        });
        return conversation;
      },

      removeConversation: async (agentId: string, conversationId: string) => {
        await deleteAgentConversation(agentId, conversationId);
        const { conversations, activeConversationId } = get();
        const filtered = conversations.filter((c) => c.id !== conversationId);
        set({
          conversations: filtered,
          activeConversationId:
            activeConversationId === conversationId
              ? filtered[0]?.id ?? null
              : activeConversationId,
        });
      },

      updateTitle: async (agentId: string, conversationId: string, title: string) => {
        await renameAgentConversation(agentId, conversationId, title);
        const { conversations } = get();
        set({
          conversations: conversations.map((c) =>
            c.id === conversationId ? { ...c, title } : c,
          ),
        });
      },

      setActiveConversationId: (id: string | null) => {
        set({ activeConversationId: id });
      },

      setCurrentAgentId: (agentId: string | null) => {
        set({ currentAgentId: agentId });
      },

      handleRealtimeInsert: (conversation: AgentConversation) => {
        const { conversations } = get();
        if (conversations.some((c) => c.id === conversation.id)) return;
        set({ conversations: [conversation, ...conversations] });
      },

      handleRealtimeUpdate: (conversation: AgentConversation) => {
        const { conversations } = get();
        set({
          conversations: conversations.map((c) =>
            c.id === conversation.id ? { ...c, ...conversation } : c,
          ),
        });
      },

      handleRealtimeDelete: (conversationId: string) => {
        const { conversations, activeConversationId } = get();
        const filtered = conversations.filter((c) => c.id !== conversationId);
        set({
          conversations: filtered,
          activeConversationId:
            activeConversationId === conversationId
              ? filtered[0]?.id ?? null
              : activeConversationId,
        });
      },
    }),
    {
      name: 'starterstack-agent-conversation-storage-v1',
      partialize: (state) => ({
        currentAgentId: state.currentAgentId,
      }),
    },
  ),
);
