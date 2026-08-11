import { useCallback, useEffect, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { Clock, GitFork, Database, Wrench, CheckCircle2, Circle, Loader2, Download, ArrowRight, Code2, ArrowUp, ArrowDown, Plus, Trash2 } from 'lucide-react';
import AgentKnowledgePanel from '@/components/AgentKnowledgePanel';
import ArtifactReviewToolbar, { mergeArtifactDetail } from '@/components/ArtifactReviewToolbar';
import ProjectContextBar from '@/components/ProjectContextBar';
import { useDurableResearchJob } from '@/hooks/useDurableResearchJob';
import { artifactAPI, experimentAPI } from '@/services/api';
import { getApiErrorMessage } from '@/services/errors';
import { useAuthStore } from '@/store/authStore';
import { useSelectedProjectId } from '@/store/projectStore';
import { useUIStore } from '@/store/uiStore';
import type { ExperimentRoadmap as ExperimentRoadmapData, ExperimentStep } from '@/types';

function renumberSteps(steps: ExperimentStep[]) {
  return steps.map((step, index) => ({ ...step, step: index + 1 }));
}

function ExperimentRoadmap() {
  const selectedProjectId = useSelectedProjectId();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const linkedQuestionId = searchParams.get('questionId');
  const incomingObjective = searchParams.get('objective') || '';
  const userId = useAuthStore((state) => state.user?.id || 'anonymous');
  const storageKey = `scipilot-current-roadmap:${userId}${selectedProjectId ? `:${selectedProjectId}` : ''}`;
  const sourceStorageKey = `${storageKey}:question-id`;
  const jobStorageKey = `${storageKey}:job-id`;
  const [objective, setObjective] = useState(incomingObjective);
  const [roadmap, setRoadmap] = useState<ExperimentRoadmapData | null>(null);
  const [draftRoadmap, setDraftRoadmap] = useState<ExperimentRoadmapData | null>(null);
  const [isEditing, setIsEditing] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
  const [isGenerating, setIsGenerating] = useState(false);
  const { addNotification } = useUIStore();

  const handleJobSucceeded = useCallback((result: ExperimentRoadmapData) => {
    setRoadmap(result);
    setDraftRoadmap(null);
    setIsEditing(false);
    if (result.id) {
      localStorage.setItem(storageKey, result.id);
      if (linkedQuestionId) localStorage.setItem(sourceStorageKey, linkedQuestionId);
      else localStorage.removeItem(sourceStorageKey);
    }
    addNotification({ type: 'success', message: '实验路线生成完成', duration: 3000 });
  }, [addNotification, linkedQuestionId, sourceStorageKey, storageKey]);

  const handleJobFailed = useCallback((message: string) => {
    addNotification({ type: 'error', message, duration: 5000 });
  }, [addNotification]);

  const {
    job,
    isRunning: isJobRunning,
    track: trackJob,
    retry: retryJob,
    cancel: cancelJob,
  } = useDurableResearchJob<ExperimentRoadmapData>({
    storageKey: jobStorageKey,
    jobType: 'experiment-roadmap',
    projectId: selectedProjectId,
    onSucceeded: handleJobSucceeded,
    onFailed: handleJobFailed,
  });

  useEffect(() => {
    setRoadmap(null);
    const artifactId = localStorage.getItem(storageKey);
    const storedQuestionId = localStorage.getItem(sourceStorageKey);
    if (linkedQuestionId && storedQuestionId !== linkedQuestionId) {
      setObjective(incomingObjective);
      return;
    }
    if (!artifactId) {
      setObjective(incomingObjective);
      return;
    }
    experimentAPI.getRoadmap(artifactId)
      .then((response) => {
        setRoadmap(response.data);
        if (!incomingObjective) setObjective(response.data.objective);
      })
      .catch(() => {
        localStorage.removeItem(storageKey);
        localStorage.removeItem(sourceStorageKey);
      });
  }, [incomingObjective, linkedQuestionId, sourceStorageKey, storageKey]);

  const handleGenerate = async () => {
    if (isGenerating || isJobRunning) return;
    if (!objective.trim()) {
      addNotification({ type: 'warning', message: '请输入研究目标', duration: 3000 });
      return;
    }
    setIsGenerating(true);
    try {
      const questionId = linkedQuestionId || 'manual';
      const response = await experimentAPI.generateRoadmapAsync(
        questionId,
        objective.trim(),
        selectedProjectId,
      );
      trackJob(response.data);
    } catch (error) {
      addNotification({
        type: 'error',
        message: getApiErrorMessage(error, '实验路线生成失败，请检查项目规划智能体配置'),
        duration: 5000,
      });
    } finally {
      setIsGenerating(false);
    }
  };

  const handleArtifactChanged = (detail: import('@/types').ArtifactDetail) => {
    const nextRoadmap = mergeArtifactDetail<ExperimentRoadmapData>(detail);
    setRoadmap(nextRoadmap);
    setDraftRoadmap(null);
    setIsEditing(false);
    localStorage.setItem(storageKey, detail.id);
  };

  const startEditing = () => {
    if (!roadmap) return;
    setDraftRoadmap(structuredClone(roadmap));
    setIsEditing(true);
  };

  const saveRevision = async () => {
    if (!roadmap?.id || !draftRoadmap) return;
    if (!draftRoadmap.objective.trim() || draftRoadmap.steps.some((step) => !step.task.trim() || !step.details.trim())) {
      addNotification({ type: 'warning', message: '研究目标、步骤名称和步骤说明不能为空', duration: 3000 });
      return;
    }
    setIsSaving(true);
    try {
      const response = await artifactAPI.revise(
        roadmap.id,
        {
          objective: draftRoadmap.objective.trim(),
          steps: renumberSteps(draftRoadmap.steps),
          baselines: draftRoadmap.baselines,
          datasets: draftRoadmap.datasets,
          tools: draftRoadmap.tools || [],
          generation_mode: draftRoadmap.generation_mode,
        },
        undefined,
        '人工编辑实验路线',
      );
      handleArtifactChanged(response.data);
      addNotification({ type: 'success', message: '实验路线已保存为新草稿版本', duration: 3000 });
    } catch (error) {
      addNotification({
        type: 'error',
        message: getApiErrorMessage(error, '实验路线保存失败'),
        duration: 5000,
      });
    } finally {
      setIsSaving(false);
    }
  };

  const updateDraftSteps = (steps: ExperimentStep[]) => {
    if (!draftRoadmap) return;
    setDraftRoadmap({ ...draftRoadmap, steps: renumberSteps(steps) });
  };

  const getStatusIcon = (status?: string) => {
    switch (status) {
      case 'completed':
        return <CheckCircle2 size={18} className="text-sci-success" />;
      case 'in_progress':
        return <Loader2 size={18} className="text-sci-warning animate-spin" />;
      default:
        return <Circle size={18} className="text-sci-muted" />;
    }
  };

  const getStatusClass = (status?: string) => {
    switch (status) {
      case 'completed':
        return 'border-l-sci-success';
      case 'in_progress':
        return 'border-l-sci-warning';
      default:
        return 'border-l-sci-muted';
    }
  };

  return (
    <div className="space-y-6 pb-20 md:pb-0">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold">实验路线</h1>
        <button
          onClick={() => addNotification({ type: 'info', message: '导出功能开发中', duration: 3000 })}
          className="sci-btn-secondary"
        >
          <Download size={16} />
          导出方案
        </button>
      </div>
      <ProjectContextBar />

      <div className="sci-card-glow">
        <label className="block text-sm font-medium text-sci-ink mb-3">研究目标</label>
        <div className="flex gap-3">
          <textarea
            value={objective}
            onChange={(event) => setObjective(event.target.value)}
            placeholder="例如：比较不同代码表征模型在跨项目缺陷预测上的效果"
            rows={3}
            className="sci-input flex-1 resize-none"
          />
          <button
            onClick={handleGenerate}
            disabled={isGenerating || isJobRunning}
            className="sci-btn-primary self-end"
          >
            {isGenerating || isJobRunning ? <Loader2 size={16} className="animate-spin" /> : <Wrench size={16} />}
            {isGenerating || isJobRunning ? '规划中' : '生成路线'}
          </button>
        </div>
        {isJobRunning && (
          <div className="mt-3 flex flex-wrap items-center gap-3 text-sm text-sci-muted">
            <span>智能体正在后台规划，当前进度 {job?.progress ?? 0}%。刷新页面后任务会继续。</span>
            <button type="button" onClick={() => void cancelJob()} className="sci-btn-secondary text-xs">
              取消任务
            </button>
          </div>
        )}
        {job?.status === 'failed' && (
          <button type="button" onClick={() => void retryJob()} className="sci-btn-secondary mt-3">
            重试路线生成
          </button>
        )}
      </div>

      <AgentKnowledgePanel category="project-planning" />

      {roadmap && (
        <ArtifactReviewToolbar
          artifact={roadmap}
          isEditing={isEditing}
          isSaving={isSaving}
          onEdit={startEditing}
          onSave={() => void saveRevision()}
          onCancel={() => {
            setDraftRoadmap(null);
            setIsEditing(false);
          }}
          onArtifactChanged={handleArtifactChanged}
        />
      )}

      {roadmap && <div className="sci-card-glow">
        <h2 className="text-lg font-semibold mb-2">当前研究目标</h2>
        {isEditing && draftRoadmap ? (
          <textarea
            className="sci-input w-full resize-none"
            rows={2}
            value={draftRoadmap.objective}
            onChange={(event) => setDraftRoadmap({ ...draftRoadmap, objective: event.target.value })}
          />
        ) : (
          <p className="text-sci-muted">{roadmap.objective}</p>
        )}
      </div>}

      {roadmap && <div className="grid lg:grid-cols-3 gap-6">
        {/* Timeline */}
        <div className="lg:col-span-2 space-y-4">
          <h2 className="sci-section-title">实验步骤</h2>
          <div className="space-y-3">
            {(isEditing && draftRoadmap ? draftRoadmap.steps : roadmap.steps).map((step, index, steps) => (
              <div
                key={step.step}
                className={`sci-card border-l-4 ${getStatusClass(step.status)}`}
              >
                <div className="flex items-start gap-4">
                  <div className="flex flex-col items-center">
                    {getStatusIcon(step.status)}
                    {index < roadmap.steps.length - 1 && (
                      <div className="w-px h-full min-h-[20px] bg-sci-border mt-1" />
                    )}
                  </div>
                  <div className="flex-1">
                    {isEditing && draftRoadmap ? (
                      <div className="space-y-2">
                        <div className="grid md:grid-cols-[1fr_110px_140px_auto] gap-2">
                          <input
                            className="sci-input"
                            value={step.task}
                            onChange={(event) => updateDraftSteps(steps.map((item, stepIndex) => stepIndex === index ? { ...item, task: event.target.value } : item))}
                            aria-label={`步骤 ${step.step} 名称`}
                          />
                          <input
                            className="sci-input"
                            type="number"
                            min={1}
                            max={90}
                            value={step.estimated_days}
                            onChange={(event) => updateDraftSteps(steps.map((item, stepIndex) => stepIndex === index ? { ...item, estimated_days: Math.max(1, Number(event.target.value) || 1) } : item))}
                            aria-label={`步骤 ${step.step} 天数`}
                          />
                          <select
                            className="sci-input"
                            value={step.status || 'pending'}
                            onChange={(event) => updateDraftSteps(steps.map((item, stepIndex) => stepIndex === index ? { ...item, status: event.target.value as ExperimentStep['status'] } : item))}
                            aria-label={`步骤 ${step.step} 状态`}
                          >
                            <option value="pending">待开始</option>
                            <option value="in_progress">进行中</option>
                            <option value="completed">已完成</option>
                          </select>
                          <div className="flex">
                            <button type="button" disabled={index === 0} onClick={() => updateDraftSteps([...steps.slice(0, index - 1), step, steps[index - 1], ...steps.slice(index + 1)])} className="p-2 text-sci-muted hover:text-sci-accent" title="上移">
                              <ArrowUp size={15} />
                            </button>
                            <button type="button" disabled={index === steps.length - 1} onClick={() => updateDraftSteps([...steps.slice(0, index), steps[index + 1], step, ...steps.slice(index + 2)])} className="p-2 text-sci-muted hover:text-sci-accent" title="下移">
                              <ArrowDown size={15} />
                            </button>
                            <button type="button" onClick={() => updateDraftSteps(steps.filter((_, stepIndex) => stepIndex !== index))} className="p-2 text-sci-muted hover:text-sci-danger" title="删除步骤">
                              <Trash2 size={15} />
                            </button>
                          </div>
                        </div>
                        <textarea
                          className="sci-input w-full resize-none text-sm"
                          rows={2}
                          value={step.details}
                          onChange={(event) => updateDraftSteps(steps.map((item, stepIndex) => stepIndex === index ? { ...item, details: event.target.value } : item))}
                          aria-label={`步骤 ${step.step} 说明`}
                        />
                      </div>
                    ) : (
                      <>
                        <div className="flex items-center justify-between mb-1">
                          <h3 className="font-semibold">
                            Step {step.step}: {step.task}
                          </h3>
                          <span className="text-xs text-sci-muted flex items-center gap-1">
                            <Clock size={12} />
                            {step.estimated_days} 天
                          </span>
                        </div>
                        <p className="text-sm text-sci-muted">{step.details}</p>
                      </>
                    )}
                  </div>
                </div>
              </div>
            ))}
            {isEditing && draftRoadmap && (
              <button
                type="button"
                onClick={() => updateDraftSteps([
                  ...draftRoadmap.steps,
                  {
                    step: draftRoadmap.steps.length + 1,
                    task: '新的实验步骤',
                    details: '填写具体工作与验收标准',
                    estimated_days: 1,
                    status: 'pending',
                  },
                ])}
                className="sci-btn-secondary"
              >
                <Plus size={15} />
                添加步骤
              </button>
            )}
          </div>
        </div>

        {/* Sidebar */}
        <div className="space-y-6">
          {/* Baselines */}
          <div>
            <h2 className="sci-section-title mb-4">Baseline 方法</h2>
            <div className="space-y-3">
              {roadmap.baselines.map((baseline) => (
                <div key={baseline.name} className="sci-card">
                  <div className="flex items-center justify-between mb-2">
                    <h3 className="font-semibold text-sci-accent">{baseline.name}</h3>
                    {typeof baseline.stars === 'number' && (
                      <span className="text-xs text-sci-muted flex items-center gap-1">
                        <GitFork size={12} />
                        {baseline.stars}
                      </span>
                    )}
                  </div>
                  <p className="text-sm text-sci-muted mb-2">{baseline.description}</p>
                  <a
                    href={baseline.github_url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-xs text-sci-accent hover:underline"
                  >
                    {baseline.github_url}
                  </a>
                </div>
              ))}
            </div>
          </div>

          {/* Datasets */}
          <div>
            <h2 className="sci-section-title mb-4">推荐数据集</h2>
            <div className="space-y-3">
              {roadmap.datasets.map((dataset) => (
                <div key={dataset.name} className="sci-card">
                  <div className="flex items-center justify-between mb-1">
                    <h3 className="font-semibold">{dataset.name}</h3>
                    <span className="sci-badge-info text-[10px]">{dataset.language}</span>
                  </div>
                  <p className="text-sm text-sci-muted mb-2">{dataset.description}</p>
                  <div className="flex items-center gap-2">
                    <Database size={12} className="text-sci-muted" />
                    <span className="text-xs text-sci-muted">{dataset.size}</span>
                  </div>
                </div>
              ))}
            </div>
          </div>

          {/* Tools */}
          <div>
            <h2 className="sci-section-title mb-4">推荐工具链</h2>
            <div className="flex flex-wrap gap-2">
              {roadmap.tools?.map((tool) => (
                <span key={tool} className="sci-badge-purple">
                  <Wrench size={10} className="mr-1" />
                  {tool}
                </span>
              ))}
            </div>
          </div>
        </div>
      </div>}

      {roadmap && (
        <div className="flex flex-wrap justify-end gap-3 border-t border-sci-border pt-4">
          <button
            type="button"
            onClick={() => navigate('/research/decompose')}
            className="sci-btn-secondary"
          >
            返回问题拆解
          </button>
          <button
            type="button"
            onClick={() => {
              const params = new URLSearchParams();
              if (roadmap.id) params.set('roadmapId', roadmap.id);
              const suggestedRepo = roadmap.baselines.find(
                (baseline) => baseline.github_url?.startsWith('https://github.com/'),
              )?.github_url;
              if (suggestedRepo) params.set('repoUrl', suggestedRepo);
              navigate(`/code/reproduce${params.size ? `?${params.toString()}` : ''}`);
            }}
            disabled={roadmap.review_status !== 'confirmed' || isEditing}
            title={roadmap.review_status === 'confirmed' ? undefined : '请先确认当前实验路线'}
            className="sci-btn-primary"
          >
            <Code2 size={16} />
            进入代码复现
            <ArrowRight size={16} />
          </button>
        </div>
      )}
    </div>
  );
}

export default ExperimentRoadmap;
