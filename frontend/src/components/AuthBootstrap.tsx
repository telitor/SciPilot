import { useEffect, useState } from 'react';
import { FlaskConical } from 'lucide-react';
import { authAPI } from '@/services/api';
import { useAuthStore } from '@/store/authStore';

function AuthBootstrap({ children }: { children: React.ReactNode }) {
  const token = useAuthStore((state) => state.token);
  const isAuthenticated = useAuthStore((state) => state.isAuthenticated);
  const login = useAuthStore((state) => state.login);
  const logout = useAuthStore((state) => state.logout);
  const rememberSession = useAuthStore((state) => state.rememberSession);
  const [checking, setChecking] = useState(Boolean(token && isAuthenticated));

  useEffect(() => {
    let active = true;
    if (!token || !isAuthenticated) {
      if (isAuthenticated || token) logout();
      setChecking(false);
      return () => {
        active = false;
      };
    }

    setChecking(true);
    authAPI.getMe()
      .then((response) => {
        if (active) login(response.data, token, rememberSession);
      })
      .catch(() => {
        if (active) logout();
      })
      .finally(() => {
        if (active) setChecking(false);
      });

    return () => {
      active = false;
    };
  }, [isAuthenticated, login, logout, rememberSession, token]);

  if (!checking) return <>{children}</>;

  return (
    <div className="flex min-h-screen items-center justify-center bg-sci-bg text-sci-muted">
      <div className="flex items-center gap-3 text-sm">
        <FlaskConical size={20} className="animate-pulse text-sci-accent" />
        正在恢复科研工作台…
      </div>
    </div>
  );
}

export default AuthBootstrap;
