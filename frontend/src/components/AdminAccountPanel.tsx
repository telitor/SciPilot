import { useCallback, useEffect, useState } from 'react';
import { Check, Shield, UserCog, X } from 'lucide-react';
import { adminAccountAPI } from '@/services/api';
import { getApiErrorMessage } from '@/services/errors';
import { useAuthStore } from '@/store/authStore';
import { useUIStore } from '@/store/uiStore';
import type { AdminRoleAudit, AdminUser } from '@/types';

function shortId(value?: string | null): string {
  return value ? `${value.slice(0, 8)}...` : '系统引导';
}

function AdminAccountPanel() {
  const currentUser = useAuthStore((state) => state.user);
  const { addNotification } = useUIStore();
  const [users, setUsers] = useState<AdminUser[]>([]);
  const [audits, setAudits] = useState<AdminRoleAudit[]>([]);
  const [loading, setLoading] = useState(true);
  const [pendingUser, setPendingUser] = useState<AdminUser | null>(null);
  const [reason, setReason] = useState('');
  const [saving, setSaving] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [userResponse, auditResponse] = await Promise.all([
        adminAccountAPI.getUsers(),
        adminAccountAPI.getRoleAudits(),
      ]);
      setUsers(Array.isArray(userResponse.data.items) ? userResponse.data.items : []);
      setAudits(Array.isArray(auditResponse.data.items) ? auditResponse.data.items : []);
    } catch (error) {
      addNotification({
        type: 'error',
        message: getApiErrorMessage(error, '账号治理数据加载失败'),
        duration: 5000,
      });
    } finally {
      setLoading(false);
    }
  }, [addNotification]);

  useEffect(() => {
    void load();
  }, [load]);

  const submitRoleChange = async () => {
    if (!pendingUser || reason.trim().length < 3) {
      addNotification({ type: 'warning', message: '请填写至少 3 个字符的变更原因', duration: 3000 });
      return;
    }
    const nextRole = pendingUser.role === 'admin' ? 'user' : 'admin';
    setSaving(true);
    try {
      const response = await adminAccountAPI.updateRole(pendingUser.id, {
        role: nextRole,
        reason: reason.trim(),
      });
      setUsers((current) => current.map((item) => (
        item.id === response.data.id ? response.data : item
      )));
      setPendingUser(null);
      setReason('');
      addNotification({ type: 'success', message: '用户角色已更新并记录审计', duration: 3000 });
      await load();
    } catch (error) {
      addNotification({
        type: 'error',
        message: getApiErrorMessage(error, '用户角色更新失败'),
        duration: 5000,
      });
    } finally {
      setSaving(false);
    }
  };

  if (loading) {
    return <p className="py-8 text-sm text-sci-muted">正在加载账号治理数据...</p>;
  }

  return (
    <div className="space-y-6">
      <section className="sci-card">
        <div className="mb-4 flex items-center justify-between gap-4">
          <div>
            <h3 className="flex items-center gap-2 font-semibold"><UserCog size={18} />账号与角色</h3>
            <p className="mt-1 text-sm text-sci-muted">角色由后端统一管理，用户不能修改自己的权限。</p>
          </div>
          <span className="text-sm text-sci-muted">{users.length} 个账号</span>
        </div>
        <div className="divide-y divide-sci-border border-y border-sci-border">
          {users.map((item) => (
            <div key={item.id} className="flex flex-col gap-3 py-4 md:flex-row md:items-center">
              <div className="min-w-0 flex-1">
                <p className="truncate font-medium">{item.username} {item.id === currentUser?.id ? '（当前账号）' : ''}</p>
                <p className="truncate text-sm text-sci-muted">{item.email}</p>
              </div>
              <span className="text-sm text-sci-muted">{item.role === 'admin' ? '管理员' : '普通用户'}</span>
              <button
                type="button"
                className="sci-btn-secondary"
                onClick={() => { setPendingUser(item); setReason(''); }}
              >
                <Shield size={16} />{item.role === 'admin' ? '降为普通用户' : '设为管理员'}
              </button>
            </div>
          ))}
        </div>

        {pendingUser && (
          <div className="mt-4 border-t border-sci-border pt-4">
            <div className="flex items-center justify-between gap-4">
              <p className="font-medium">确认调整 {pendingUser.username} 的角色</p>
              <button type="button" className="sci-icon-button" onClick={() => setPendingUser(null)} title="取消角色调整">
                <X size={17} />
              </button>
            </div>
            <textarea
              value={reason}
              onChange={(event) => setReason(event.target.value)}
              className="sci-input mt-3 min-h-24 w-full resize-y"
              placeholder="填写角色变更原因"
              maxLength={500}
            />
            <button type="button" className="sci-btn-primary mt-3" disabled={saving} onClick={() => void submitRoleChange()}>
              <Check size={16} />{saving ? '正在保存...' : '确认并记录审计'}
            </button>
          </div>
        )}
      </section>

      <section className="sci-card">
        <h3 className="mb-4 font-semibold">最近角色变更</h3>
        {audits.length === 0 ? (
          <p className="border-y border-sci-border py-5 text-sm text-sci-muted">尚无角色变更记录</p>
        ) : (
          <div className="divide-y divide-sci-border border-y border-sci-border">
            {audits.map((audit) => (
              <div key={audit.id} className="grid gap-1 py-4 text-sm md:grid-cols-[1fr_auto]">
                <div>
                  <p className="font-medium">{audit.previous_role} → {audit.new_role} · {shortId(audit.target_user_id)}</p>
                  <p className="mt-1 text-sci-muted">{audit.reason}</p>
                </div>
                <p className="text-sci-muted">{audit.created_at ? new Date(audit.created_at).toLocaleString('zh-CN') : '时间未知'}</p>
              </div>
            ))}
          </div>
        )}
      </section>
    </div>
  );
}

export default AdminAccountPanel;
