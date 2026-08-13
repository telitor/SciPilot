import { useCallback, useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { CheckCircle2, ClipboardCheck, Loader2, Play, Plus, ShieldCheck, XCircle } from 'lucide-react';
import { experimentRunAPI } from '@/services/api';
import { getApiErrorMessage } from '@/services/errors';
import { useUIStore } from '@/store/uiStore';
import type { ExperimentRun, ExperimentRunStatus } from '@/types';

const STATUS_LABELS: Record<ExperimentRunStatus, string> = {
  planned: '待运行',
  running: '运行中',
  succeeded: '成功',
  failed: '失败',
  cancelled: '已取消',
};

interface ExperimentRunPanelProps {
  codeArtifactId: string;
  projectId?: string | null;
}

export default function ExperimentRunPanel({
  codeArtifactId,
  projectId,
}: ExperimentRunPanelProps) {
  const navigate = useNavigate();
  const { addNotification } = useUIStore();
  const [runs, setRuns] = useState<ExperimentRun[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [isSaving, setIsSaving] = useState(false);
  const [executionMode, setExecutionMode] = useState<'manual-evidence' | 'sandboxed-docker'>('manual-evidence');
  const [executionApproved, setExecutionApproved] = useState(false);
  const [commitSha, setCommitSha] = useState('');
  const [command, setCommand] = useState('');
  const [runtime, setRuntime] = useState('');
  const [operatingSystem, setOperatingSystem] = useState('');
  const [notes, setNotes] = useState('');
  const [activeRunId, setActiveRunId] = useState<string | null>(null);
  const [exitCode, setExitCode] = useState('0');
  const [stdoutExcerpt, setStdoutExcerpt] = useState('');
  const [stderrExcerpt, setStderrExcerpt] = useState('');
  const [outputFileNames, setOutputFileNames] = useState('');

  const loadRuns = useCallback(async (showLoading = true) => {
    if (showLoading) setIsLoading(true);
    try {
      const response = await experimentRunAPI.list({
        code_artifact_id: codeArtifactId,
        project_id: projectId || undefined,
      });
      setRuns(Array.isArray(response.data.items) ? response.data.items : []);
    } catch (error) {
      if (showLoading) {
        addNotification({
          type: 'error',
          message: getApiErrorMessage(error, '实验运行记录加载失败'),
          duration: 5000,
        });
      }
    } finally {
      if (showLoading) setIsLoading(false);
    }
  }, [addNotification, codeArtifactId, projectId]);

  useEffect(() => {
    void loadRuns();
  }, [loadRuns]);

  useEffect(() => {
    const hasActiveSandboxRun = runs.some(
      (run) => run.execution_mode === 'sandboxed-docker'
        && Boolean(run.execution_job_id)
        && (run.status === 'planned' || run.status === 'running'),
    );
    if (!hasActiveSandboxRun) return undefined;
    const timer = window.setInterval(() => void loadRuns(false), 3000);
    return () => window.clearInterval(timer);
  }, [loadRuns, runs]);

  const createRun = async () => {
    if (!/^[0-9a-fA-F]{7,64}$/.test(commitSha.trim())) {
      addNotification({ type: 'warning', message: '请输入 7 至 64 位十六进制 commit SHA', duration: 3500 });
      return;
    }
    if (!command.trim()) {
      addNotification({ type: 'warning', message: '请输入本次实验的运行命令', duration: 3500 });
      return;
    }
    if (executionMode === 'sandboxed-docker' && !executionApproved) {
      addNotification({ type: 'warning', message: '请先检查命令并确认受控执行', duration: 3500 });
      return;
    }
    setIsSaving(true);
    try {
      const response = await experimentRunAPI.create({
        code_artifact_id: codeArtifactId,
        execution_mode: executionMode,
        commit_sha: commitSha.trim(),
        command: command.trim(),
        environment: {
          ...(operatingSystem.trim() ? { os: operatingSystem.trim() } : {}),
          ...(runtime.trim() ? { runtime: runtime.trim() } : {}),
        },
        notes: notes.trim() || undefined,
      });
      if (executionMode === 'sandboxed-docker') {
        await experimentRunAPI.execute(response.data.id);
        await loadRuns(false);
      } else {
        setRuns((current) => [response.data, ...current]);
      }
      setCommitSha('');
      setCommand('');
      setRuntime('');
      setOperatingSystem('');
      setNotes('');
      setExecutionApproved(false);
      addNotification({
        type: 'success',
        message: executionMode === 'sandboxed-docker' ? '受控执行已进入队列' : '实验运行记录已创建',
        duration: 3000,
      });
    } catch (error) {
      addNotification({
        type: 'error',
        message: getApiErrorMessage(error, '实验运行记录创建失败'),
        duration: 5000,
      });
    } finally {
      setIsSaving(false);
    }
  };

  const replaceRun = (updated: ExperimentRun) => {
    setRuns((current) => current.map((item) => (item.id === updated.id ? updated : item)));
  };

  const updateStatus = async (
    run: ExperimentRun,
    status: 'running' | 'succeeded' | 'failed' | 'cancelled',
  ) => {
    setActiveRunId(run.id);
    try {
      const parsedExitCode = Number.parseInt(exitCode, 10);
      const response = await experimentRunAPI.update(run.id, {
        status,
        ...(status === 'succeeded' || status === 'failed'
          ? {
              exit_code: status === 'succeeded' ? 0 : (Number.isFinite(parsedExitCode) ? parsedExitCode : 1),
              stdout_excerpt: stdoutExcerpt.trim() || undefined,
              stderr_excerpt: stderrExcerpt.trim() || undefined,
              output_files: outputFileNames
                .split(/[,\n]/)
                .map((name) => name.trim())
                .filter(Boolean)
                .slice(0, 50)
                .map((name) => ({ name })),
            }
          : {}),
      });
      replaceRun(response.data);
      if (status !== 'running') {
        setExitCode('0');
        setStdoutExcerpt('');
        setStderrExcerpt('');
        setOutputFileNames('');
      }
      addNotification({ type: 'success', message: `实验运行已更新为${STATUS_LABELS[status]}`, duration: 3000 });
    } catch (error) {
      addNotification({
        type: 'error',
        message: getApiErrorMessage(error, '实验运行状态更新失败'),
        duration: 5000,
      });
    } finally {
      setActiveRunId(null);
    }
  };

  return (
    <div className="sci-card">
      <div className="mb-4 flex items-center justify-between gap-3">
        <div>
          <h3 className="sci-section-title">实验运行证据</h3>
          <p className="mt-1 text-xs text-sci-muted">固定 Commit · 不保存密钥 · 运行证据可追溯</p>
        </div>
        {isLoading && <Loader2 size={16} className="animate-spin text-sci-accent" />}
      </div>

      <div className="mb-4 inline-flex rounded-md border border-sci-border bg-sci-bg3 p-1">
        <button
          type="button"
          onClick={() => {
            setExecutionMode('manual-evidence');
            setExecutionApproved(false);
          }}
          className={`px-3 py-1.5 text-xs ${executionMode === 'manual-evidence' ? 'rounded bg-sci-primary text-white' : 'text-sci-muted'}`}
        >
          手动证据
        </button>
        <button
          type="button"
          onClick={() => setExecutionMode('sandboxed-docker')}
          className={`inline-flex items-center gap-1 px-3 py-1.5 text-xs ${executionMode === 'sandboxed-docker' ? 'rounded bg-sci-primary text-white' : 'text-sci-muted'}`}
        >
          <ShieldCheck size={13} />Docker 受控执行
        </button>
      </div>

      <div className="grid gap-3 md:grid-cols-2">
        <label className="text-xs text-sci-muted">
          Commit SHA
          <input className="sci-input mt-1 w-full font-mono" value={commitSha} onChange={(event) => setCommitSha(event.target.value)} placeholder="例如 4f8a6d2" />
        </label>
        <label className="text-xs text-sci-muted">
          运行命令
          <input className="sci-input mt-1 w-full font-mono" value={command} onChange={(event) => setCommand(event.target.value)} placeholder="例如 python train.py --config config.yaml" />
        </label>
        <label className="text-xs text-sci-muted">
          操作系统
          <input className="sci-input mt-1 w-full" value={operatingSystem} onChange={(event) => setOperatingSystem(event.target.value)} placeholder="例如 Windows 11" />
        </label>
        <label className="text-xs text-sci-muted">
          运行环境
          <input className="sci-input mt-1 w-full" value={runtime} onChange={(event) => setRuntime(event.target.value)} placeholder="例如 Python 3.11 / CUDA 12.1" />
        </label>
      </div>
      <label className="mt-3 block text-xs text-sci-muted">
        备注
        <textarea className="sci-input mt-1 w-full resize-none" rows={2} value={notes} onChange={(event) => setNotes(event.target.value)} placeholder="数据集版本、随机种子或硬件信息" />
      </label>
      {executionMode === 'sandboxed-docker' && (
        <label className="mt-3 flex items-start gap-2 rounded-md border border-sci-border bg-sci-bg3 p-3 text-xs text-sci-muted">
          <input
            type="checkbox"
            checked={executionApproved}
            onChange={(event) => setExecutionApproved(event.target.checked)}
            className="mt-0.5"
          />
          <span>我已检查并批准该命令。依赖准备阶段可访问网络，正式运行阶段将关闭网络并限制 CPU、内存、进程数和执行时间。</span>
        </label>
      )}
      <div className="mt-3 flex justify-end">
        <button
          type="button"
          onClick={() => void createRun()}
          disabled={isSaving || (executionMode === 'sandboxed-docker' && !executionApproved)}
          className="sci-btn-primary"
        >
          {isSaving ? <Loader2 size={16} className="animate-spin" /> : <Plus size={16} />}
          {executionMode === 'sandboxed-docker' ? '确认并执行' : '创建运行记录'}
        </button>
      </div>

      <div className="mt-5 divide-y divide-sci-border border-t border-sci-border">
        {!isLoading && runs.length === 0 && (
          <p className="py-5 text-sm text-sci-muted">暂无实验运行记录</p>
        )}
        {runs.map((run) => (
          <div key={run.id} className="py-4">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div>
                <div className="flex items-center gap-2">
                  <span className="font-mono text-sm text-sci-accent">{run.commit_sha.slice(0, 12)}</span>
                  <span className="sci-badge-info">{STATUS_LABELS[run.status]}</span>
                  <span className="text-xs text-sci-muted">
                    {run.execution_mode === 'sandboxed-docker' ? 'Docker 受控执行' : '手动证据'}
                  </span>
                </div>
                <code className="mt-2 block max-w-3xl break-all text-xs text-sci-muted">{run.command}</code>
              </div>
              <div className="flex flex-wrap gap-2">
                {run.status === 'planned' && run.execution_mode === 'manual-evidence' && (
                  <>
                    <button type="button" onClick={() => void updateStatus(run, 'running')} disabled={activeRunId === run.id} className="sci-btn-secondary">
                      <Play size={14} />开始记录
                    </button>
                    <button type="button" onClick={() => void updateStatus(run, 'cancelled')} disabled={activeRunId === run.id} className="sci-btn-secondary">
                      <XCircle size={14} />取消
                    </button>
                  </>
                )}
                {run.execution_mode === 'sandboxed-docker'
                  && (run.status === 'planned' || run.status === 'running') && (
                    <span className="inline-flex items-center gap-1 text-xs text-sci-muted">
                      <Loader2 size={14} className="animate-spin" />隔离环境正在执行
                    </span>
                  )}
                {run.status === 'succeeded' && !run.result_artifact_id && (
                  <button type="button" onClick={() => navigate(`/result/analyze?repoId=${encodeURIComponent(codeArtifactId)}&runId=${encodeURIComponent(run.id)}`)} className="sci-btn-primary">
                    <ClipboardCheck size={14} />分析结果
                  </button>
                )}
                {run.result_artifact_id && (
                  <span className="inline-flex items-center gap-1 text-xs text-sci-success"><CheckCircle2 size={14} />已关联结果分析</span>
                )}
              </div>
            </div>

            {run.status === 'running' && run.execution_mode === 'manual-evidence' && (
              <div className="mt-4 grid gap-3 border-l-2 border-sci-accent/40 pl-4 md:grid-cols-2">
                <label className="text-xs text-sci-muted">
                  失败退出码
                  <input type="number" className="sci-input mt-1 w-full" value={exitCode} onChange={(event) => setExitCode(event.target.value)} />
                </label>
                <label className="text-xs text-sci-muted">
                  输出文件名
                  <input className="sci-input mt-1 w-full" value={outputFileNames} onChange={(event) => setOutputFileNames(event.target.value)} placeholder="metrics.csv, model.json" />
                </label>
                <label className="text-xs text-sci-muted">
                  标准输出摘要
                  <textarea className="sci-input mt-1 w-full resize-none font-mono" rows={3} value={stdoutExcerpt} onChange={(event) => setStdoutExcerpt(event.target.value)} />
                </label>
                <label className="text-xs text-sci-muted">
                  错误输出摘要
                  <textarea className="sci-input mt-1 w-full resize-none font-mono" rows={3} value={stderrExcerpt} onChange={(event) => setStderrExcerpt(event.target.value)} />
                </label>
                <div className="flex flex-wrap gap-2 md:col-span-2">
                  <button type="button" onClick={() => void updateStatus(run, 'succeeded')} disabled={activeRunId === run.id} className="sci-btn-primary">
                    <CheckCircle2 size={14} />记录成功
                  </button>
                  <button type="button" onClick={() => void updateStatus(run, 'failed')} disabled={activeRunId === run.id} className="sci-btn-secondary">
                    <XCircle size={14} />记录失败
                  </button>
                  <button type="button" onClick={() => void updateStatus(run, 'cancelled')} disabled={activeRunId === run.id} className="sci-btn-secondary">
                    取消运行
                  </button>
                </div>
              </div>
            )}

            {run.execution_mode === 'sandboxed-docker'
              && (run.status === 'succeeded' || run.status === 'failed') && (
                <div className="mt-4 space-y-3 border-l-2 border-sci-accent/40 pl-4">
                  <div className="flex flex-wrap gap-4 text-xs text-sci-muted">
                    <span>退出码：{run.exit_code ?? 'Unknown'}</span>
                    {typeof run.environment.image === 'string' && <span>镜像：{run.environment.image}</span>}
                    {typeof run.environment.duration_seconds === 'number' && <span>耗时：{run.environment.duration_seconds} 秒</span>}
                  </div>
                  {run.stdout_excerpt && (
                    <div>
                      <p className="mb-1 text-xs text-sci-muted">标准输出</p>
                      <pre className="max-h-48 overflow-auto whitespace-pre-wrap rounded-md bg-sci-bg3 p-3 text-xs">{run.stdout_excerpt}</pre>
                    </div>
                  )}
                  {run.stderr_excerpt && (
                    <div>
                      <p className="mb-1 text-xs text-sci-muted">错误输出</p>
                      <pre className="max-h-48 overflow-auto whitespace-pre-wrap rounded-md bg-sci-bg3 p-3 text-xs text-sci-danger">{run.stderr_excerpt}</pre>
                    </div>
                  )}
                  {run.output_files.length > 0 && (
                    <div>
                      <p className="mb-1 text-xs text-sci-muted">自动采集的输出文件</p>
                      <div className="flex flex-wrap gap-2">
                        {run.output_files.map((file) => (
                          <span key={`${file.relative_path || file.name}-${file.sha256 || ''}`} className="sci-badge-info">
                            {file.relative_path || file.name}
                          </span>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              )}
          </div>
        ))}
      </div>
    </div>
  );
}
