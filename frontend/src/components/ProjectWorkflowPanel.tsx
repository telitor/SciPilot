import { useCallback, useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  AlertCircle,
  ArrowRight,
  CheckCircle2,
  Circle,
  Clock3,
  GitBranch,
  Loader2,
  Play,
  RefreshCw,
  RotateCcw,
  ShieldCheck,
} from 'lucide-react';
import { projectAPI } from '@/services/api';
import { getApiErrorMessage } from '@/services/errors';
import { useUIStore } from '@/store/uiStore';
import type { AgentTaskStatus, AgentWorkflow, AgentWorkflowTask } from '@/types';

const STATUS_LABELS: Record<AgentTaskStatus, string> = {
  blocked: '等待上游',
  ready: '可以开始',
  in_progress: '进行中',
  awaiting_approval: '等待验收',
  completed: '已完成',
  failed: '执行失败',
};

const STATUS_CLASSES: Record<AgentTaskStatus, string> = {
  blocked: 'text-sci-muted',
  ready: 'text-sci-accent',
  in_progress: 'text-sci-warning',
  awaiting_approval: 'text-sci-warning',
  completed: 'text-sci-success',
  failed: 'text-sci-danger',
};

function TaskStatusIcon({ status }: { status: AgentTaskStatus }) {
  if (status === 'completed') return <CheckCircle2 size={17} />;
  if (status === 'failed') return <AlertCircle size={17} />;
  if (status === 'in_progress') return <Loader2 size={17} className="animate-spin" />;
  if (status === 'awaiting_approval') return <ShieldCheck size={17} />;
  if (status === 'ready') return <Play size={17} />;
  return <Circle size={17} />;
}

interface ProjectWorkflowPanelProps {
  projectId: string;
}

export default function ProjectWorkflowPanel({ projectId }: ProjectWorkflowPanelProps) {
  const navigate = useNavigate();
  const { addNotification } = useUIStore();
  const [workflow, setWorkflow] = useState<AgentWorkflow | null>(null);
  const [loading, setLoading] = useState(true);
  const [actionKey, setActionKey] = useState('');

  const loadWorkflow = useCallback(async () => {
    setLoading(true);
    try {
      const response = await projectAPI.getWorkflow(projectId);
      setWorkflow(response.data.workflow || null);
    } catch (error) {
      addNotification({
        type: 'error',
        message: getApiErrorMessage(error, '科研任务流加载失败'),
        duration: 5000,
      });
    } finally {
      setLoading(false);
    }
  }, [addNotification, projectId]);

  useEffect(() => {
    setWorkflow(null);
    void loadWorkflow();
  }, [loadWorkflow]);

  const completedCount = useMemo(
    () => workflow?.tasks.filter((task) => task.status === 'completed').length || 0,
    [workflow],
  );

  const createWorkflow = async () => {
    setActionKey('create');
    try {
      const response = await projectAPI.createWorkflow(projectId);
      setWorkflow(response.data);
      addNotification({ type: 'success', message: '科研任务流已启用', duration: 3000 });
    } catch (error) {
      addNotification({
        type: 'error',
        message: getApiErrorMessage(error, '启用科研任务流失败'),
        duration: 5000,
      });
    } finally {
      setActionKey('');
    }
  };

  const replaceWorkflow = (next: AgentWorkflow) => {
    setWorkflow(next);
    return next;
  };

  const startTask = async (task: AgentWorkflowTask) => {
    setActionKey(`start:${task.id}`);
    try {
      const response = await projectAPI.startWorkflowTask(projectId, task.id);
      const next = replaceWorkflow(response.data);
      const current = next.tasks.find((item) => item.id === task.id) || task;
      navigate(current.launch_path);
    } catch (error) {
      addNotification({
        type: 'error',
        message: getApiErrorMessage(error, '启动科研任务失败'),
        duration: 5000,
      });
    } finally {
      setActionKey('');
    }
  };

  const approveTask = async (task: AgentWorkflowTask) => {
    if (!window.confirm(`确认“${task.title}”的当前产物可以作为下一阶段输入？`)) return;
    setActionKey(`approve:${task.id}`);
    try {
      const response = await projectAPI.approveWorkflowTask(projectId, task.id);
      replaceWorkflow(response.data);
      addNotification({ type: 'success', message: '任务已验收，下一个阶段已解锁', duration: 3500 });
    } catch (error) {
      addNotification({
        type: 'error',
        message: getApiErrorMessage(error, '任务验收失败'),
        duration: 5000,
      });
    } finally {
      setActionKey('');
    }
  };

  const retryTask = async (task: AgentWorkflowTask) => {
    setActionKey(`retry:${task.id}`);
    try {
      const response = await projectAPI.retryWorkflowTask(projectId, task.id);
      replaceWorkflow(response.data);
      addNotification({ type: 'success', message: '仅当前失败任务已进入重试', duration: 3500 });
    } catch (error) {
      addNotification({
        type: 'error',
        message: getApiErrorMessage(error, '重试科研任务失败'),
        duration: 5000,
      });
    } finally {
      setActionKey('');
    }
  };

  const taskAction = (task: AgentWorkflowTask) => {
    const busy = actionKey.endsWith(task.id);
    if (task.status === 'ready') {
      return (
        <button type="button" onClick={() => void startTask(task)} disabled={busy} className="sci-btn-primary text-xs">
          {busy ? <Loader2 size={14} className="animate-spin" /> : <Play size={14} />}
          进入阶段
        </button>
      );
    }
    if (task.status === 'in_progress') {
      return (
        <button type="button" onClick={() => navigate(task.launch_path)} className="sci-btn-secondary text-xs">
          继续处理 <ArrowRight size={14} />
        </button>
      );
    }
    if (task.status === 'awaiting_approval') {
      return (
        <button type="button" onClick={() => void approveTask(task)} disabled={busy} className="sci-btn-primary text-xs">
          {busy ? <Loader2 size={14} className="animate-spin" /> : <ShieldCheck size={14} />}
          验收产物
        </button>
      );
    }
    if (task.status === 'failed') {
      return (
        <button type="button" onClick={() => void retryTask(task)} disabled={busy} className="sci-btn-secondary text-xs">
          {busy ? <Loader2 size={14} className="animate-spin" /> : <RotateCcw size={14} />}
          重试当前节点
        </button>
      );
    }
    return null;
  };

  return (
    <section className="sci-card-glow">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="flex items-center gap-2">
            <GitBranch size={18} className="text-sci-accent" />
            <h3 className="sci-section-title">科研任务流</h3>
            {workflow && <span className="sci-badge-info">{completedCount} / 5</span>}
          </div>
          <p className="mt-1 text-sm text-sci-muted">
            每个阶段由你确认后启动，验收产物后才会解锁下一阶段。
          </p>
        </div>
        {workflow && (
          <button type="button" onClick={() => void loadWorkflow()} disabled={loading} className="sci-btn-secondary text-xs">
            {loading ? <Loader2 size={14} className="animate-spin" /> : <RefreshCw size={14} />}
            刷新状态
          </button>
        )}
      </div>

      {loading ? (
        <div className="flex min-h-28 items-center justify-center">
          <Loader2 className="animate-spin text-sci-accent" />
        </div>
      ) : !workflow ? (
        <div className="mt-5 border-y border-sci-border py-6 text-center">
          <p className="text-sm text-sci-muted">启用后将创建固定五阶段任务，不会自动调用或消耗 Agent 额度。</p>
          <button type="button" onClick={() => void createWorkflow()} disabled={actionKey === 'create'} className="sci-btn-primary mt-4">
            {actionKey === 'create' ? <Loader2 size={15} className="animate-spin" /> : <GitBranch size={15} />}
            启用科研任务流
          </button>
        </div>
      ) : (
        <div className="mt-5 divide-y divide-sci-border border-y border-sci-border">
          {workflow.tasks.map((task) => (
            <article key={task.id} className="grid gap-3 py-4 sm:grid-cols-[32px_minmax(0,1fr)_auto] sm:items-center">
              <div className={`flex h-8 w-8 items-center justify-center ${STATUS_CLASSES[task.status]}`}>
                <TaskStatusIcon status={task.status} />
              </div>
              <div className="min-w-0">
                <div className="flex flex-wrap items-center gap-2">
                  <h4 className="font-medium">{task.position}. {task.title}</h4>
                  <span className={`text-xs ${STATUS_CLASSES[task.status]}`}>{STATUS_LABELS[task.status]}</span>
                </div>
                {task.error_message ? (
                  <p className="mt-1 text-sm text-sci-danger">{task.error_message}</p>
                ) : task.status === 'blocked' ? (
                  <p className="mt-1 flex items-center gap-1 text-xs text-sci-muted"><Clock3 size={12} />等待上一阶段验收</p>
                ) : null}
              </div>
              <div className="sm:justify-self-end">{taskAction(task)}</div>
            </article>
          ))}
        </div>
      )}
    </section>
  );
}
