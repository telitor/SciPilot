import { useEffect, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { Clock, GitFork, Database, Wrench, CheckCircle2, Circle, Loader2, Download } from 'lucide-react';
import AgentKnowledgePanel from '@/components/AgentKnowledgePanel';
import ProjectContextBar from '@/components/ProjectContextBar';
import { experimentAPI } from '@/services/api';
import { getApiErrorMessage } from '@/services/errors';
import { useAuthStore } from '@/store/authStore';
import { useSelectedProjectId } from '@/store/projectStore';
import { useUIStore } from '@/store/uiStore';
import type { ExperimentRoadmap as ExperimentRoadmapData } from '@/types';

function ExperimentRoadmap() {
  const selectedProjectId = useSelectedProjectId();
  const [searchParams] = useSearchParams();
  const userId = useAuthStore((state) => state.user?.id || 'anonymous');
  const storageKey = `scipilot-current-roadmap:${userId}${selectedProjectId ? `:${selectedProjectId}` : ''}`;
  const [objective, setObjective] = useState(searchParams.get('objective') || '');
  const [roadmap, setRoadmap] = useState<ExperimentRoadmapData | null>(null);
  const [isGenerating, setIsGenerating] = useState(false);
  const { addNotification } = useUIStore();

  useEffect(() => {
    setRoadmap(null);
    const artifactId = localStorage.getItem(storageKey);
    if (!artifactId) return;
    experimentAPI.getRoadmap(artifactId)
      .then((response) => {
        setRoadmap(response.data);
        if (!searchParams.get('objective')) setObjective(response.data.objective);
      })
      .catch(() => localStorage.removeItem(storageKey));
  }, [searchParams, storageKey]);

  const handleGenerate = async () => {
    if (!objective.trim()) {
      addNotification({ type: 'warning', message: '请输入研究目标', duration: 3000 });
      return;
    }
    setIsGenerating(true);
    try {
      const questionId = searchParams.get('questionId') || 'manual';
      const response = await experimentAPI.generateRoadmap(
        questionId,
        objective.trim(),
        selectedProjectId,
      );
      setRoadmap(response.data);
      if (response.data.id) localStorage.setItem(storageKey, response.data.id);
      addNotification({ type: 'success', message: '实验路线生成完成', duration: 3000 });
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
            disabled={isGenerating}
            className="sci-btn-primary self-end"
          >
            {isGenerating ? <Loader2 size={16} className="animate-spin" /> : <Wrench size={16} />}
            {isGenerating ? '规划中' : '生成路线'}
          </button>
        </div>
      </div>

      <AgentKnowledgePanel category="project-planning" />

      {roadmap && <div className="sci-card-glow">
        <h2 className="text-lg font-semibold mb-2">当前研究目标</h2>
        <p className="text-sci-muted">{roadmap.objective}</p>
      </div>}

      {roadmap && <div className="grid lg:grid-cols-3 gap-6">
        {/* Timeline */}
        <div className="lg:col-span-2 space-y-4">
          <h2 className="sci-section-title">实验步骤</h2>
          <div className="space-y-3">
            {roadmap.steps.map((step, index) => (
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
                  </div>
                </div>
              </div>
            ))}
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
    </div>
  );
}

export default ExperimentRoadmap;
