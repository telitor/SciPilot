import { useState } from 'react';
import { useNavigate, Link } from 'react-router-dom';
import { Eye, EyeOff, FlaskConical, ArrowLeft, CheckCircle } from 'lucide-react';
import { useAuthStore } from '@/store/authStore';
import { useUIStore } from '@/store/uiStore';
import { authAPI } from '@/services/api';
import { getApiErrorMessage } from '@/services/errors';

function Register() {
  const navigate = useNavigate();
  const { login } = useAuthStore();
  const { addNotification } = useUIStore();

  const [username, setUsername] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [showPassword, setShowPassword] = useState(false);
  const [isLoading, setIsLoading] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    const normalizedUsername = username.trim();
    const normalizedEmail = email.trim().toLowerCase();
    const hasLetter = /\p{L}/u.test(password);
    const hasNumber = /\p{N}/u.test(password);

    if (!normalizedUsername || !normalizedEmail || !password || !confirmPassword) {
      addNotification({ type: 'warning', message: '请填写完整信息', duration: 3000 });
      return;
    }
    if (normalizedUsername.length < 2 || normalizedUsername.length > 50) {
      addNotification({ type: 'warning', message: '用户名需要 2–50 个字符', duration: 3000 });
      return;
    }
    if (password.length < 8 || password.length > 128) {
      addNotification({ type: 'warning', message: '密码需要 8–128 个字符', duration: 3000 });
      return;
    }
    if (!hasLetter || !hasNumber) {
      addNotification({ type: 'warning', message: '密码必须同时包含字母和数字', duration: 3000 });
      return;
    }
    if (password !== confirmPassword) {
      addNotification({ type: 'warning', message: '两次密码输入不一致', duration: 3000 });
      return;
    }

    setIsLoading(true);
    try {
      const response = await authAPI.register(normalizedEmail, password, normalizedUsername);
      const { user, token, requires_email_confirmation } = response.data;
      if (token) {
        login(user, token);
        addNotification({ type: 'success', message: '注册成功', duration: 3000 });
        navigate('/dashboard');
      } else {
        addNotification({
          type: 'success',
          message: requires_email_confirmation
            ? '注册成功，请先查收验证邮件后登录'
            : '注册成功，请登录',
          duration: 5000,
        });
        navigate('/login');
      }
    } catch (error) {
      const message = getApiErrorMessage(error, '注册失败，请重试');
      addNotification({ type: 'error', message, duration: 5000 });
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="min-h-screen bg-sci-bg flex items-center justify-center px-6">
      <div className="absolute inset-0 bg-gradient-tech opacity-20" />
      <div className="absolute top-20 left-1/4 w-96 h-96 bg-sci-primary/5 rounded-full blur-3xl" />
      <div className="absolute bottom-20 right-1/4 w-96 h-96 bg-sci-purple/5 rounded-full blur-3xl" />

      <div className="relative w-full max-w-md">
        <button
          onClick={() => navigate('/')}
          className="flex items-center gap-2 text-sci-muted hover:text-sci-ink transition-colors mb-8"
        >
          <ArrowLeft size={18} />
          <span>返回首页</span>
        </button>

        <div className="sci-card-glow p-8">
          <div className="flex items-center gap-3 mb-8">
            <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-sci-primary to-sci-accent flex items-center justify-center">
              <FlaskConical size={20} className="text-white" />
            </div>
            <div>
              <h1 className="text-xl font-bold">注册 SciCopilot</h1>
              <p className="text-sm text-sci-muted">开启智能科研之旅</p>
            </div>
          </div>

          <form onSubmit={handleSubmit} className="space-y-5">
            <div>
              <label className="block text-sm font-medium text-sci-ink mb-2">用户名</label>
              <input
                type="text"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                placeholder="设置用户名"
                className="sci-input w-full"
                minLength={2}
                maxLength={50}
                autoComplete="username"
                required
              />
            </div>

            <div>
              <label className="block text-sm font-medium text-sci-ink mb-2">邮箱</label>
              <input
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="your@email.com"
                className="sci-input w-full"
                autoComplete="email"
                required
              />
            </div>

            <div>
              <label className="block text-sm font-medium text-sci-ink mb-2">密码</label>
              <div className="relative">
                <input
                  type={showPassword ? 'text' : 'password'}
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  placeholder="设置密码（至少8位）"
                  className="sci-input w-full pr-10"
                  minLength={8}
                  maxLength={128}
                  autoComplete="new-password"
                  aria-describedby="password-requirements"
                  required
                />
                <button
                  type="button"
                  onClick={() => setShowPassword(!showPassword)}
                  className="absolute right-3 top-1/2 -translate-y-1/2 text-sci-muted hover:text-sci-ink"
                >
                  {showPassword ? <EyeOff size={18} /> : <Eye size={18} />}
                </button>
              </div>
            </div>

            <div>
              <label className="block text-sm font-medium text-sci-ink mb-2">确认密码</label>
              <input
                type="password"
                value={confirmPassword}
                onChange={(e) => setConfirmPassword(e.target.value)}
                placeholder="再次输入密码"
                className="sci-input w-full"
                minLength={8}
                maxLength={128}
                autoComplete="new-password"
                required
              />
            </div>

            <div id="password-requirements" className="space-y-2 text-xs text-sci-muted">
              <div className="flex items-center gap-2">
                <CheckCircle
                  size={14}
                  className={password.length >= 8 && password.length <= 128 ? 'text-sci-success' : ''}
                />
                <span>8–128 个字符</span>
              </div>
              <div className="flex items-center gap-2">
                <CheckCircle
                  size={14}
                  className={
                    /\p{L}/u.test(password) && /\p{N}/u.test(password)
                      ? 'text-sci-success'
                      : ''
                  }
                />
                <span>包含字母和数字</span>
              </div>
              <div className="flex items-center gap-2">
                <CheckCircle
                  size={14}
                  className={
                    confirmPassword.length > 0 && password === confirmPassword
                      ? 'text-sci-success'
                      : ''
                  }
                />
                <span>两次密码一致</span>
              </div>
            </div>

            <button
              type="submit"
              disabled={isLoading}
              className="sci-btn-primary w-full"
            >
              {isLoading ? (
                <div className="w-5 h-5 border-2 border-white/30 border-t-white rounded-full animate-spin" />
              ) : (
                '注册'
              )}
            </button>
          </form>

          <div className="mt-6 text-center text-sm text-sci-muted">
            已有账号？
            <Link to="/login" className="text-sci-accent hover:underline ml-1">
              立即登录
            </Link>
          </div>
        </div>
      </div>
    </div>
  );
}

export default Register;
