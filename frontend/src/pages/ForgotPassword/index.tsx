import { useState } from 'react';
import { ArrowLeft, FlaskConical } from 'lucide-react';
import { Link } from 'react-router-dom';
import { authAPI } from '@/services/api';
import { getApiErrorMessage } from '@/services/errors';

function ForgotPassword() {
  const [email, setEmail] = useState('');
  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');

  const handleSubmit = async (event: React.FormEvent) => {
    event.preventDefault();
    setLoading(true);
    setError('');
    try {
      const response = await authAPI.forgotPassword(email);
      setMessage(response.data.message);
    } catch (requestError) {
      setError(getApiErrorMessage(requestError, '暂时无法发送重置邮件，请稍后重试。'));
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
              <h1 className="text-xl font-bold">找回密码</h1>
              <p className="text-sm text-sci-muted">重置链接将发送到注册邮箱</p>
            </div>
          </div>
          {message ? (
            <div className="space-y-5">
              <p className="rounded border border-sci-success/40 bg-sci-success/10 p-4 text-sm">{message}</p>
              <Link to="/login" className="sci-btn-primary w-full">返回登录</Link>
            </div>
          ) : (
            <form onSubmit={handleSubmit} className="space-y-5">
              <div>
                <label className="mb-2 block text-sm font-medium">邮箱</label>
                <input
                  type="email"
                  value={email}
                  onChange={(event) => setEmail(event.target.value)}
                  className="sci-input w-full"
                  autoComplete="email"
                  required
                />
              </div>
              {error && <p className="text-sm text-sci-danger">{error}</p>}
              <button type="submit" disabled={loading} className="sci-btn-primary w-full">
                {loading ? '正在发送…' : '发送重置邮件'}
              </button>
            </form>
          )}
        </div>
      </div>
    </div>
  );
}

export default ForgotPassword;
