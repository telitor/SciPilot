import { create } from 'zustand';
import { persist } from 'zustand/middleware';
import type { User, AuthState } from '@/types';

interface AuthStore extends AuthState {
  rememberSession: boolean;
  login: (user: User, token: string, rememberSession?: boolean) => void;
  logout: () => void;
  setUser: (user: User | null) => void;
  setLoading: (loading: boolean) => void;
  updateUser: (updates: Partial<User>) => void;
}

export const useAuthStore = create<AuthStore>()(
  persist(
    (set) => ({
      user: null,
      token: null,
      isAuthenticated: false,
      isLoading: false,
      rememberSession: true,

      login: (user, token, rememberSession = true) =>
        set({
          user,
          token,
          isAuthenticated: true,
          isLoading: false,
          rememberSession,
        }),

      logout: () =>
        set({
          user: null,
          token: null,
          isAuthenticated: false,
          isLoading: false,
          rememberSession: true,
        }),

      setUser: (user) => set({ user }),

      setLoading: (isLoading) => set({ isLoading }),

      updateUser: (updates) =>
        set((state) => ({
          user: state.user ? { ...state.user, ...updates } : null,
        })),
    }),
    {
      name: 'scipilot-auth',
      partialize: (state) => ({
        user: state.rememberSession ? state.user : null,
        token: state.rememberSession ? state.token : null,
        isAuthenticated: state.rememberSession ? state.isAuthenticated : false,
        rememberSession: state.rememberSession,
      }),
    }
  )
);
