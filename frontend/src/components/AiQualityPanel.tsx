import { useCallback, useEffect, useState } from 'react';
import { CheckCircle2, Gauge, Play, ShieldCheck, ThumbsDown, ThumbsUp, XCircle } from 'lucide-react';
import { adminQualityAPI } from '@/services/api';
import { getApiErrorMessage } from '@/services/errors';
import { useUIStore } from '@/store/uiStore';
import type { AdminMessageFeedback, EvaluationRun, EvaluationSuite } from '@/types';

function percent(value: unknown): string {
  const number = typeof value === 'number' ? value : Number(value ?? 0);
  return `${Math.round(number * 100)}%`;
}

function AiQualityPanel() {
  const { addNotification } = useUIStore();
  const [feedback, setFeedback] = useState<AdminMessageFeedback[]>([]);
  const [suites, setSuites] = useState<EvaluationSuite[]>([]);
  const [runs, setRuns] = useState<EvaluationRun[]>([]);
  const [loading, setLoading] = useState(true);
  const [running, setRunning] = useState(false);
  const [reviewingId, setReviewingId] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [feedbackResponse, suiteResponse, runResponse] = await Promise.all([
        adminQualityAPI.getFeedback('pending'),
        adminQualityAPI.getEvaluationSuites(),
        adminQualityAPI.getEvaluationRuns(),
      ]);
      setFeedback(Array.isArray(feedbackResponse.data.items) ? feedbackResponse.data.items : []);
      setSuites(Array.isArray(suiteResponse.data) ? suiteResponse.data : []);
      setRuns(Array.isArray(runResponse.data.items) ? runResponse.data.items : []);
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

  if (loading) {
    return <p className="py-8 text-sm text-sci-muted">正在加载 AI 质量数据...</p>;
  }

  return (
    <div className="space-y-6">
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
          <h3 className="flex items-center gap-2 font-semibold"><Gauge size={18} />固定离线评测</h3>
          <p className="mt-1 text-sm text-sci-muted">仅运行本地确定性检索评测。真实模型评测保持关闭。</p>
        </div>
        <div className="divide-y divide-sci-border border-y border-sci-border">
          {suites.map((suite) => (
            <div key={suite.id} className="flex flex-col gap-3 py-4 md:flex-row md:items-center">
              <div className="min-w-0 flex-1">
                <p className="font-medium">{suite.name} · v{suite.version}</p>
                <p className="mt-1 text-sm text-sci-muted">{suite.case_count} 个固定用例</p>
              </div>
              <button type="button" className="sci-btn-primary" disabled={running} onClick={() => void runOffline(suite)}>
                <Play size={16} />{running ? '评测中...' : '运行离线评测'}
              </button>
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
                <span>Recall@3 {percent(run.metrics.recall_at_3)}</span>
                <span>MRR {percent(run.metrics.mrr)}</span>
              </div>
            ))}
          </div>
        )}
      </section>
    </div>
  );
}

export default AiQualityPanel;
