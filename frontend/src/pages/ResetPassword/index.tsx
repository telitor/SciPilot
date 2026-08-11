import { useMemo, useState } from 'react';
import { ArrowLeft, FlaskConical } from 'lucide-react';
import { Link, useNavigate } from 'react-router-dom';
import { authAPI } from '@/services/api';
import { getApiErrorMessage } from '@/services/errors';
import { useUIStore } from '@/store/uiStore';

function ResetPassword() {
  const navigate = useNavigate();
  const addNotification = useUIStore((state) => state.addNotification);
  const recoveryToken = useMemo(() => {
    const hash = new URLSearchParams(window.location.hash.replace(/^#/, ''));
    const query = new URLSearchParams(window.location.search);
    return hash.get('access_token') || query.get('access_token') || '';
  }, []);
  const [password, setPassword] = useState('');
  const [confirmation, setConfirmation] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const handleSubmit = async (event: React.FormEvent) => {
    event.preventDefault();
    if (password !== confirmation) {
      setError('两次输入的密码不一致。');
      return;
    }
    if (!recoveryToken) {
      setError('重置链接无效或已过期，请重新申请。');
      return;
    }
    setLoading(true);
    setError('');
    try {
      await authAPI.resetPassword(password, recoveryToken);
      window.history.replaceState({}, document.title, '/reset-password');
      addNotification({ type: 'success', message: '密码已更新，请使用新密码登录。', duration: 5000 });
      navigate('/login', { replace: true, state: { passwordReset: true } });
    } catch (requestError) {
      setError(getApiErrorMessage(requestError, '密码更新失败，请重新申请重置链接。'));
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="flex min-h-screen items-center justify-center bg-sci-bg px-6">
      <div className="w-full max-w-md">
        <Link to="/login" className="mb-8 flex items-center gap-2 text-sci-muted hover:text-sci-ink">
          <ArrowLeft size={18} /> 返回登录
        </Link>
        <div className="sci-card-glow p-8">
          <div className="mb-8 flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-sci-primary text-white">
              <FlaskConical size={20} />
            </div>
            <div>
              <h1 className="text-xl font-bold">设置新密码</h1>
              <p className="text-sm text-sci-muted">至少 8 位，并同时包含字母和数字</p>
            </div>
          </div>
          <form onSubmit={handleSubmit} className="space-y-5">
            {!recoveryToken && (
              <p className="rounded border border-sci-danger/40 bg-sci-danger/10 p-3 text-sm text-sci-danger">
                重置链接无效或已过期，请返回登录页重新申请。
              </p>
            )}
            <input
              type="password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              placeholder="新密码"
              minLength={8}
              className="sci-input w-full"
              autoComplete="new-password"
              required
            />
            <input
              type="password"
              value={confirmation}
              onChange={(event) => setConfirmation(event.target.value)}
              placeholder="再次输入新密码"
              minLength={8}
              className="sci-input w-full"
              autoComplete="new-password"
              required
            />
            {error && <p className="text-sm text-sci-danger">{error}</p>}
            <button type="submit" disabled={loading || !recoveryToken} className="sci-btn-primary w-full">
              {loading ? '正在更新…' : '更新密码'}
            </button>
          </form>
        </div>
      </div>
    </div>
  );
}

export default ResetPassword;
