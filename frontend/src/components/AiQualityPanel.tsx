import { useCallback, useEffect, useState } from 'react';
import { Activity, AlertTriangle, CheckCircle2, Clock3, Coins, Gauge, Play, ShieldCheck, ThumbsDown, ThumbsUp, XCircle } from 'lucide-react';
import { adminQualityAPI } from '@/services/api';
import { getApiErrorMessage } from '@/services/errors';
import { useUIStore } from '@/store/uiStore';
import type { AdminMessageFeedback, AiAlert, AiMetrics, EvaluationRun, EvaluationSuite } from '@/types';

function percent(value: unknown): string {
  const number = typeof value === 'number' ? value : Number(value ?? 0);
  return `${Math.round(number * 100)}%`;
}

function AiQualityPanel() {
  const { addNotification } = useUIStore();
  const [feedback, setFeedback] = useState<AdminMessageFeedback[]>([]);
  const [suites, setSuites] = useState<EvaluationSuite[]>([]);
  const [runs, setRuns] = useState<EvaluationRun[]>([]);
  const [metrics, setMetrics] = useState<AiMetrics | null>(null);
  const [alerts, setAlerts] = useState<AiAlert[]>([]);
  const [loading, setLoading] = useState(true);
  const [running, setRunning] = useState(false);
  const [reviewingId, setReviewingId] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [feedbackResponse, suiteResponse, runResponse, metricsResponse, alertResponse] = await Promise.all([
        adminQualityAPI.getFeedback('pending'),
        adminQualityAPI.getEvaluationSuites(),
        adminQualityAPI.getEvaluationRuns(),
        adminQualityAPI.getAiMetrics(24),
        adminQualityAPI.getAiAlerts('open'),
      ]);
      setFeedback(Array.isArray(feedbackResponse.data.items) ? feedbackResponse.data.items : []);
      setSuites(Array.isArray(suiteResponse.data) ? suiteResponse.data : []);
      setRuns(Array.isArray(runResponse.data.items) ? runResponse.data.items : []);
      setMetrics(metricsResponse.data);
      setAlerts(Array.isArray(alertResponse.data.items) ? alertResponse.data.items : []);
    } catch (error) {
      addNotification({ type: 'error', message: getApiErrorMessage(error, 'AI 质量数据加载失败'), duration: 5000 });
    } finally {
      setLoading(false);
    }
  }, [addNotification]);

  useEffect(() => {
    void load();
  }, [load]);

  const review = async (item: AdminMessageFeedback, status: 'reviewed' | 'rejected') => {
    setReviewingId(item.id);
    try {
      await adminQualityAPI.reviewFeedback(item.id, { review_status: status });
      setFeedback((current) => current.filter((entry) => entry.id !== item.id));
      addNotification({ type: 'success', message: status === 'reviewed' ? '反馈已通过审核' : '反馈已拒绝', duration: 3000 });
    } catch (error) {
      addNotification({ type: 'error', message: getApiErrorMessage(error, '反馈审核失败'), duration: 5000 });
    } finally {
      setReviewingId(null);
    }
  };

  const runOffline = async (suite: EvaluationSuite) => {
    setRunning(true);
    try {
      const response = await adminQualityAPI.runOfflineEvaluation(suite.slug);
      setRuns((current) => [response.data, ...current.filter((item) => item.id !== response.data.id)]);
      addNotification({ type: 'success', message: '离线评测已完成，没有调用真实模型', duration: 4000 });
    } catch (error) {
      addNotification({ type: 'error', message: getApiErrorMessage(error, '离线评测失败'), duration: 5000 });
    } finally {
      setRunning(false);
    }
  };

  const runReal = async (suite: EvaluationSuite) => {
    const confirmed = window.confirm(
      '本次将调用最多 6 次真实讯飞模型，每个模块 1 个短用例，可能产生少量额度消耗。确认继续吗？',
    );
    if (!confirmed) return;
    setRunning(true);
    try {
      const response = await adminQualityAPI.runRealEvaluation(suite.slug);
      setRuns((current) => [response.data, ...current.filter((item) => item.id !== response.data.id)]);
      addNotification({ type: 'success', message: '真实模型冒烟评测已完成', duration: 4000 });
      await load();
    } catch (error) {
      addNotification({ type: 'error', message: getApiErrorMessage(error, '真实模型评测失败'), duration: 5000 });
    } finally {
      setRunning(false);
    }
  };

  const acknowledgeAlert = async (alertId: string) => {
    try {
      await adminQualityAPI.acknowledgeAiAlert(alertId);
      setAlerts((current) => current.filter((item) => item.id !== alertId));
      addNotification({ type: 'success', message: '告警已确认', duration: 3000 });
    } catch (error) {
      addNotification({ type: 'error', message: getApiErrorMessage(error, '告警确认失败'), duration: 5000 });
    }
  };

  if (loading) {
    return <p className="py-8 text-sm text-sci-muted">正在加载 AI 质量数据...</p>;
  }

  return (
    <div className="space-y-6">
      <section className="sci-card">
        <div className="mb-4 flex items-center justify-between gap-4">
          <div>
            <h3 className="flex items-center gap-2 font-semibold"><Activity size={18} />AI 运行概览</h3>
            <p className="mt-1 text-sm text-sci-muted">最近 24 小时，仅统计运行元数据，不保存评测输出正文。</p>
          </div>
          <button type="button" className="sci-btn-secondary" onClick={() => void load()}>刷新</button>
        </div>
        <div className="grid gap-4 border-y border-sci-border py-4 sm:grid-cols-2 xl:grid-cols-4">
          <div><p className="text-sm text-sci-muted">调用量</p><p className="mt-1 text-2xl font-semibold">{metrics?.total_runs ?? 0}</p></div>
          <div><p className="text-sm text-sci-muted">失败 / 降级</p><p className="mt-1 text-2xl font-semibold">{percent(metrics?.failure_rate)} / {percent(metrics?.degraded_rate)}</p></div>
          <div><p className="flex items-center gap-1 text-sm text-sci-muted"><Clock3 size={14} />P95 延迟</p><p className="mt-1 text-2xl font-semibold">{Math.round((metrics?.p95_latency_ms ?? 0) / 1000)} 秒</p></div>
          <div><p className="flex items-center gap-1 text-sm text-sci-muted"><Coins size={14} />已知成本</p><p className="mt-1 text-2xl font-semibold">¥{(metrics?.estimated_cost_cny ?? 0).toFixed(4)}</p><p className="mt-1 text-xs text-sci-muted">{metrics?.unknown_cost_runs ?? 0} 次价格未知</p></div>
        </div>
        <p className="mt-3 text-sm text-sci-muted">Token：输入 {metrics?.input_tokens ?? 0} · 输出 {metrics?.output_tokens ?? 0}</p>
      </section>

      <section className="sci-card">
        <div className="mb-4 flex items-center justify-between gap-4">
          <div>
            <h3 className="flex items-center gap-2 font-semibold"><AlertTriangle size={18} />运行告警</h3>
            <p className="mt-1 text-sm text-sci-muted">监控失败率、降级率、P95 延迟和 24 小时调用量。</p>
          </div>
          <span className="text-sm text-sci-muted">{alerts.length} 条未确认</span>
        </div>
        {alerts.length === 0 ? (
          <p className="border-y border-sci-border py-5 text-sm text-sci-muted">当前没有未确认告警</p>
        ) : (
          <div className="divide-y divide-sci-border border-y border-sci-border">
            {alerts.map((alert) => (
              <div key={alert.id} className="flex flex-col gap-3 py-4 md:flex-row md:items-center">
                <div className="min-w-0 flex-1">
                  <p className="font-medium">{alert.title} · {alert.module}</p>
                  <p className="mt-1 break-words text-sm text-sci-muted">{alert.detail}</p>
                </div>
                <button type="button" className="sci-btn-secondary" onClick={() => void acknowledgeAlert(alert.id)}>
                  <CheckCircle2 size={16} />确认
                </button>
              </div>
            ))}
          </div>
        )}
      </section>

      <section className="sci-card">
        <div className="mb-4 flex items-center justify-between gap-4">
          <div>
            <h3 className="flex items-center gap-2 font-semibold"><ShieldCheck size={18} />待审核反馈</h3>
            <p className="mt-1 text-sm text-sci-muted">用户反馈必须经过人工审核，不会自动进入训练数据。</p>
          </div>
          <span className="text-sm text-sci-muted">{feedback.length} 条</span>
        </div>
        {feedback.length === 0 ? (
          <p className="border-y border-sci-border py-5 text-sm text-sci-muted">当前没有待审核反馈</p>
        ) : (
          <div className="divide-y divide-sci-border border-y border-sci-border">
            {feedback.map((item) => (
              <div key={item.id} className="flex flex-col gap-3 py-4 md:flex-row md:items-center">
                <div className="min-w-0 flex-1">
                  <p className="flex items-center gap-2 text-sm font-medium">
                    {item.rating === 'helpful' ? <ThumbsUp size={15} /> : <ThumbsDown size={15} />}
                    {item.rating === 'helpful' ? '有帮助' : '无帮助'}
                  </p>
                  <p className="mt-1 break-words text-sm text-sci-muted">{item.comment || '用户未填写补充说明'}</p>
                </div>
                <div className="flex gap-2">
                  <button type="button" className="sci-btn-secondary" disabled={reviewingId === item.id} onClick={() => void review(item, 'reviewed')} title="通过审核">
                    <CheckCircle2 size={16} />通过
                  </button>
                  <button type="button" className="sci-btn-secondary" disabled={reviewingId === item.id} onClick={() => void review(item, 'rejected')} title="拒绝反馈">
                    <XCircle size={16} />拒绝
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
      </section>

      <section className="sci-card">
        <div className="mb-4">
          <h3 className="flex items-center gap-2 font-semibold"><Gauge size={18} />质量评测</h3>
          <p className="mt-1 text-sm text-sci-muted">离线检索评测不产生额度消耗；真实冒烟评测最多调用 6 次，每个模块 1 个短用例。</p>
        </div>
        <div className="divide-y divide-sci-border border-y border-sci-border">
          {suites.map((suite) => (
            <div key={suite.id} className="flex flex-col gap-3 py-4 md:flex-row md:items-center">
              <div className="min-w-0 flex-1">
                <p className="font-medium">{suite.name} · v{suite.version}</p>
                <p className="mt-1 text-sm text-sci-muted">{suite.case_count} 个固定用例</p>
              </div>
              {suite.module === 'real-model-smoke' ? (
                <button type="button" className="sci-btn-primary" disabled={running} onClick={() => void runReal(suite)}>
                  <Play size={16} />{running ? '评测中...' : '运行真实冒烟评测'}
                </button>
              ) : (
                <button type="button" className="sci-btn-primary" disabled={running} onClick={() => void runOffline(suite)}>
                  <Play size={16} />{running ? '评测中...' : '运行离线评测'}
                </button>
              )}
            </div>
          ))}
        </div>
      </section>

      <section className="sci-card">
        <h3 className="mb-4 font-semibold">最近评测运行</h3>
        {runs.length === 0 ? (
          <p className="border-y border-sci-border py-5 text-sm text-sci-muted">尚无评测记录</p>
        ) : (
          <div className="divide-y divide-sci-border border-y border-sci-border">
            {runs.map((run) => (
              <div key={run.id} className="grid gap-2 py-4 text-sm md:grid-cols-[1fr_auto_auto_auto] md:items-center">
                <div>
                  <p className="font-medium">{run.provider || '离线评测'}</p>
                  <p className="text-sci-muted">{run.started_at ? new Date(run.started_at).toLocaleString('zh-CN') : '时间未知'}</p>
                </div>
                <span>{run.passed_count}/{run.case_count} 通过</span>
                <span>{run.mode === 'real-model' ? `通过率 ${percent(run.metrics.pass_rate)}` : `Recall@3 ${percent(run.metrics.recall_at_3)}`}</span>
                <span>{run.mode === 'real-model' ? `P95 ${Math.round(Number(run.metrics.p95_latency_ms ?? 0) / 1000)} 秒` : `MRR ${percent(run.metrics.mrr)}`}</span>
              </div>
            ))}
          </div>
        )}
      </section>
    </div>
  );
}

export default AiQualityPanel;
