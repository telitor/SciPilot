import { create } from 'zustand';
import { persist } from 'zustand/middleware';
import { useAuthStore } from '@/store/authStore';

interface ProjectState {
  selectedProjectByUser: Record<string, string | null>;
  setSelectedProject: (userId: string, projectId: string | null) => void;
  clearUserProject: (userId: string) => void;
}

export const useProjectStore = create<ProjectState>()(
  persist(
    (set) => ({
      selectedProjectByUser: {},
      setSelectedProject: (userId, projectId) =>
        set((state) => ({
          selectedProjectByUser: {
            ...state.selectedProjectByUser,
            [userId]: projectId,
          },
        })),
      clearUserProject: (userId) =>
        set((state) => {
          const next = { ...state.selectedProjectByUser };
          delete next[userId];
          return { selectedProjectByUser: next };
        }),
    }),
    {
      name: 'scipilot-project-context',
      partialize: (state) => ({
        selectedProjectByUser: state.selectedProjectByUser,
      }),
    },
  ),
);

export function useSelectedProjectId() {
  const userId = useAuthStore((state) => state.user?.id || 'anonymous');
  return useProjectStore((state) => state.selectedProjectByUser[userId] || null);
}
