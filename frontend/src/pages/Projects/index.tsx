import { FormEvent, useCallback, useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Archive,
  ArrowRight,
  BarChart3,
  BookOpen,
  Bot,
  CheckCircle2,
  Code2,
  FileText,
  FolderKanban,
  GitBranch,
  Loader2,
  MessageSquare,
  Plus,
  RotateCcw,
  Route,
  Unlink,
} from 'lucide-react';
import { projectAPI } from '@/services/api';
import ProjectMemoryPanel from '@/components/ProjectMemoryPanel';
import { getApiErrorMessage } from '@/services/errors';
import { useAuthStore } from '@/store/authStore';
import { useProjectStore } from '@/store/projectStore';
import { useUIStore } from '@/store/uiStore';
import type {
  ProjectAsset,
  ResearchProject,
  ResearchProjectDetail,
  ResearchProjectStage,
  UnassignedProjectAssets,
} from '@/types';

const STAGE_LABELS: Record<ResearchProjectStage, string> = {
  discovery: '方向探索',
  literature: '论文调研',
  question: '问题拆解',
  experiment: '实验规划',
  reproduction: '代码复现',
  analysis: '结果分析',
  completed: '研究完成',
};

const WORKFLOW_STAGES: ResearchProjectStage[] = [
  'discovery',
  'literature',
  'question',
  'experiment',
  'reproduction',
  'analysis',
  'completed',
];

const NEXT_ACTIONS: Partial<Record<ResearchProjectStage, { label: string; path: string }>> = {
  discovery: { label: '上传并精读论文', path: '/paper/read' },
  literature: { label: '拆解研究问题', path: '/research/decompose' },
  question: { label: '规划实验路线', path: '/experiment/roadmap' },
  experiment: { label: '分析复现仓库', path: '/code/reproduce' },
  reproduction: { label: '分析实验结果', path: '/result/analyze' },
};

function nextWorkflowPath(detail: ResearchProjectDetail): string | null {
  const fallback = NEXT_ACTIONS[detail.current_stage]?.path || null;
  if (detail.current_stage === 'literature') {
    const paper = detail.assets.papers[0];
    if (!paper) return fallback;
    const params = new URLSearchParams({
      paperId: paper.id,
      direction: `基于《${paper.title}》提出可验证的研究问题`,
    });
    return `/research/decompose?${params.toString()}`;
  }
  const artifactTypeByStage: Partial<Record<ResearchProjectStage, string>> = {
    question: 'research-decomposition',
    experiment: 'experiment-roadmap',
    reproduction: 'code-reproduction',
  };
  const artifactType = artifactTypeByStage[detail.current_stage];
  const artifact = artifactType
    ? detail.assets.artifacts.find((item) => item.artifact_type === artifactType)
    : undefined;
  if (!artifact) return fallback;
  if (detail.current_stage === 'question') {
    const params = new URLSearchParams({
      questionId: artifact.id,
      objective: artifact.title,
    });
    return `/experiment/roadmap?${params.toString()}`;
  }
  if (detail.current_stage === 'experiment') {
    return `/code/reproduce?${new URLSearchParams({ roadmapId: artifact.id }).toString()}`;
  }
  if (detail.current_stage === 'reproduction') {
    return `/result/analyze?${new URLSearchParams({ repoId: artifact.id }).toString()}`;
  }
  return fallback;
}

const ARTIFACT_ROUTES: Record<string, { path: string; storage: string }> = {
  'research-decomposition': { path: '/research/decompose', storage: 'scipilot-current-research' },
  'experiment-roadmap': { path: '/experiment/roadmap', storage: 'scipilot-current-roadmap' },
  'code-reproduction': { path: '/code/reproduce', storage: 'scipilot-current-repository' },
  'result-analysis': { path: '/result/analyze', storage: 'scipilot-current-result-analysis' },
};

function AssetIcon({ asset, type }: { asset: ProjectAsset; type: 'paper' | 'conversation' | 'artifact' }) {
  if (type === 'paper') return <FileText size={15} />;
  if (type === 'conversation') return <MessageSquare size={15} />;
  if (asset.artifact_type === 'experiment-roadmap') return <Route size={15} />;
  if (asset.artifact_type === 'code-reproduction') return <Code2 size={15} />;
  if (asset.artifact_type === 'result-analysis') return <BarChart3 size={15} />;
  return <GitBranch size={15} />;
}

function Projects() {
  const navigate = useNavigate();
  const userId = useAuthStore((state) => state.user?.id || 'anonymous');
  const selectedProjectId = useProjectStore(
    (state) => state.selectedProjectByUser[userId] || null,
  );
  const setSelectedProject = useProjectStore((state) => state.setSelectedProject);
  const { addNotification } = useUIStore();
  const [projects, setProjects] = useState<ResearchProject[]>([]);
  const [detail, setDetail] = useState<ResearchProjectDetail | null>(null);
  const [unassigned, setUnassigned] = useState<UnassignedProjectAssets | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadingDetail, setLoadingDetail] = useState(false);
  const [creating, setCreating] = useState(false);
  const [name, setName] = useState('');
  const [objective, setObjective] = useState('');
  const [assigningKey, setAssigningKey] = useState('');

  const loadProjects = useCallback(async () => {
    const response = await projectAPI.getProjects(true);
    setProjects(Array.isArray(response.data.items) ? response.data.items : []);
  }, []);

  const loadUnassigned = useCallback(async () => {
    const response = await projectAPI.getUnassignedAssets();
    setUnassigned(response.data);
  }, []);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      await Promise.all([loadProjects(), loadUnassigned()]);
    } catch (error) {
      addNotification({
        type: 'error',
        message: getApiErrorMessage(error, '项目工作台加载失败'),
        duration: 5000,
      });
    } finally {
      setLoading(false);
    }
  }, [addNotification, loadProjects, loadUnassigned]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  useEffect(() => {
    if (!selectedProjectId) {
      setDetail(null);
      return;
    }
    setLoadingDetail(true);
    projectAPI.getProject(selectedProjectId)
      .then((response) => setDetail(response.data))
      .catch((error) => {
        setSelectedProject(userId, null);
        addNotification({
          type: 'error',
          message: getApiErrorMessage(error, '项目详情加载失败'),
          duration: 5000,
        });
      })
      .finally(() => setLoadingDetail(false));
  }, [addNotification, selectedProjectId, setSelectedProject, userId]);

  const activeProjects = useMemo(
    () => projects.filter((project) => project.status !== 'archived'),
    [projects],
  );
  const archivedProjects = useMemo(
    () => projects.filter((project) => project.status === 'archived'),
    [projects],
  );
  const currentStageIndex = detail
    ? Math.max(0, WORKFLOW_STAGES.indexOf(detail.current_stage))
    : 0;
  const nextAction = detail ? NEXT_ACTIONS[detail.current_stage] : undefined;
  const nextActionPath = detail ? nextWorkflowPath(detail) : null;

  const handleCreate = async (event: FormEvent) => {
    event.preventDefault();
    if (name.trim().length < 2) {
      addNotification({ type: 'warning', message: '项目名称至少需要 2 个字符', duration: 3000 });
      return;
    }
    setCreating(true);
    try {
      const response = await projectAPI.createProject({
        name: name.trim(),
        objective: objective.trim() || undefined,
      });
      setSelectedProject(userId, response.data.id);
      setName('');
      setObjective('');
      await refresh();
      addNotification({ type: 'success', message: '科研项目已创建', duration: 3000 });
    } catch (error) {
      addNotification({
        type: 'error',
        message: getApiErrorMessage(error, '创建科研项目失败'),
        duration: 5000,
      });
    } finally {
      setCreating(false);
    }
  };

  const handleArchive = async (project: ResearchProject) => {
    if (!window.confirm(`归档“${project.name}”？项目资产会保留，并可随时恢复。`)) return;
    try {
      await projectAPI.archiveProject(project.id);
      if (selectedProjectId === project.id) setSelectedProject(userId, null);
      await refresh();
      addNotification({ type: 'success', message: '项目已归档', duration: 3000 });
    } catch (error) {
      addNotification({ type: 'error', message: getApiErrorMessage(error, '归档失败'), duration: 5000 });
    }
  };

  const handleRestore = async (project: ResearchProject) => {
    try {
      await projectAPI.restoreProject(project.id);
      await refresh();
      addNotification({ type: 'success', message: '项目已恢复', duration: 3000 });
    } catch (error) {
      addNotification({ type: 'error', message: getApiErrorMessage(error, '恢复失败'), duration: 5000 });
    }
  };

  const handleStageChange = async (stage: ResearchProjectStage) => {
    if (!detail) return;
    try {
      const response = await projectAPI.updateProject(detail.id, { current_stage: stage });
      setDetail({ ...detail, ...response.data });
      await loadProjects();
    } catch (error) {
      addNotification({ type: 'error', message: getApiErrorMessage(error, '更新阶段失败'), duration: 5000 });
    }
  };

  const assignAsset = async (
    type: 'paper' | 'conversation' | 'artifact',
    asset: ProjectAsset,
    projectId: string | null,
  ) => {
    const key = `${type}:${asset.id}`;
    setAssigningKey(key);
    try {
      await projectAPI.assignAsset(type, asset.id, projectId);
      await Promise.all([
        loadUnassigned(),
        selectedProjectId
          ? projectAPI.getProject(selectedProjectId).then((response) => setDetail(response.data))
          : Promise.resolve(),
      ]);
      addNotification({
        type: 'success',
        message: projectId ? '资产已加入当前项目' : '资产已移至未归属区域',
        duration: 3000,
      });
    } catch (error) {
      addNotification({ type: 'error', message: getApiErrorMessage(error, '更新资产归属失败'), duration: 5000 });
    } finally {
      setAssigningKey('');
    }
  };

  const openAsset = (type: 'paper' | 'conversation' | 'artifact', asset: ProjectAsset) => {
    if (type === 'paper') {
      const projectSuffix = selectedProjectId ? `:${selectedProjectId}` : '';
      localStorage.setItem(`scipilot-paper-read:${userId}${projectSuffix}:paper-id`, asset.id);
      navigate('/paper/read');
      return;
    }
    if (type === 'artifact' && asset.artifact_type) {
      const target = ARTIFACT_ROUTES[asset.artifact_type];
      if (target) {
        const projectSuffix = selectedProjectId ? `:${selectedProjectId}` : '';
        localStorage.setItem(`${target.storage}:${userId}${projectSuffix}`, asset.id);
        navigate(target.path);
      }
    }
  };

  const renderAssetRows = (
    items: ProjectAsset[],
    type: 'paper' | 'conversation' | 'artifact',
    projectId: string | null,
  ) => items.length === 0 ? (
    <p className="py-3 text-sm text-sci-muted">暂无内容</p>
  ) : (
    <div className="divide-y divide-sci-border">
      {items.map((asset) => {
        const key = `${type}:${asset.id}`;
        return (
          <div key={asset.id} className="flex items-center gap-3 py-3">
            <span className="text-sci-accent"><AssetIcon asset={asset} type={type} /></span>
            <button
              type="button"
              onClick={() => openAsset(type, asset)}
              disabled={type === 'conversation'}
              className={`min-w-0 flex-1 truncate text-left text-sm ${
                type === 'conversation' ? 'cursor-default' : 'hover:text-sci-accent'
              }`}
            >
              {asset.title}
            </button>
            <button
              type="button"
              onClick={() => void assignAsset(type, asset, projectId)}
              disabled={assigningKey === key || (!projectId && !selectedProjectId)}
              className="sci-btn-secondary shrink-0 text-xs"
            >
              {assigningKey === key ? (
                <Loader2 size={14} className="animate-spin" />
              ) : projectId ? (
                <Plus size={14} />
              ) : (
                <Unlink size={14} />
              )}
              {projectId ? '加入' : '移出'}
            </button>
          </div>
        );
      })}
    </div>
  );

  return (
    <div className="space-y-6 pb-20 md:pb-0">
      <div className="flex flex-col gap-2 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <p className="text-xs uppercase text-sci-accent">Research Workspace</p>
          <h1 className="text-2xl font-bold">科研项目</h1>
          <p className="mt-1 text-sm text-sci-muted">把论文、问题、实验、代码和结果组织到同一条研究主线。</p>
        </div>
        {loading && <Loader2 size={20} className="animate-spin text-sci-accent" />}
      </div>

      <form onSubmit={handleCreate} className="sci-card-glow grid gap-3 lg:grid-cols-[minmax(180px,0.7fr)_minmax(280px,1.4fr)_auto]">
        <input
          value={name}
          onChange={(event) => setName(event.target.value)}
          placeholder="项目名称"
          maxLength={120}
          className="sci-input"
        />
        <input
          value={objective}
          onChange={(event) => setObjective(event.target.value)}
          placeholder="研究目标（可选）"
          maxLength={2000}
          className="sci-input"
        />
        <button type="submit" disabled={creating} className="sci-btn-primary">
          {creating ? <Loader2 size={16} className="animate-spin" /> : <Plus size={16} />}
          创建项目
        </button>
      </form>

      <section>
        <h2 className="sci-section-title mb-3">进行中的项目</h2>
        {activeProjects.length === 0 ? (
          <div className="border-y border-sci-border py-8 text-center text-sm text-sci-muted">尚未创建科研项目，现有功能仍可独立使用。</div>
        ) : (
          <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
            {activeProjects.map((project) => (
              <div key={project.id} className={`sci-card ${selectedProjectId === project.id ? 'border-sci-accent' : ''}`}>
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <h3 className="truncate font-semibold">{project.name}</h3>
                    <p className="mt-1 line-clamp-2 text-sm text-sci-muted">{project.objective || '暂未填写研究目标'}</p>
                  </div>
                  {selectedProjectId === project.id && <CheckCircle2 size={18} className="shrink-0 text-sci-success" />}
                </div>
                <div className="mt-4 flex items-center justify-between">
                  <span className="sci-badge-info">{STAGE_LABELS[project.current_stage]}</span>
                  <div className="flex gap-2">
                    <button type="button" onClick={() => void handleArchive(project)} className="p-2 text-sci-muted hover:text-sci-danger" title="归档项目">
                      <Archive size={16} />
                    </button>
                    <button type="button" onClick={() => setSelectedProject(userId, project.id)} className="sci-btn-secondary text-xs">
                      打开 <ArrowRight size={14} />
                    </button>
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}
      </section>

      {selectedProjectId && (
        <section className="space-y-4">
          {loadingDetail || !detail ? (
            <div className="flex min-h-32 items-center justify-center"><Loader2 className="animate-spin text-sci-accent" /></div>
          ) : (
            <>
              <div className="flex flex-col gap-3 border-y border-sci-border py-4 sm:flex-row sm:items-center sm:justify-between">
                <div>
                  <p className="text-xs text-sci-muted">当前项目</p>
                  <h2 className="text-xl font-semibold">{detail.name}</h2>
                </div>
                <select
                  value={detail.current_stage}
                  onChange={(event) => void handleStageChange(event.target.value as ResearchProjectStage)}
                  className="sci-input sm:w-48"
                  aria-label="项目当前阶段"
                >
                  {Object.entries(STAGE_LABELS).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
                </select>
              </div>

              <div className="border-b border-sci-border pb-4">
                <div className="grid grid-cols-2 gap-2 sm:grid-cols-4 xl:grid-cols-7">
                  {WORKFLOW_STAGES.map((stage, index) => {
                    const reached = index <= currentStageIndex;
                    const current = stage === detail.current_stage;
                    return (
                      <div
                        key={stage}
                        className={`flex min-w-0 items-center gap-2 border-l-2 px-2 py-2 text-xs ${
                          current
                            ? 'border-sci-accent text-sci-accent'
                            : reached
                              ? 'border-sci-success text-sci-ink'
                              : 'border-sci-border text-sci-muted'
                        }`}
                      >
                        {reached ? (
                          <CheckCircle2 size={14} className="shrink-0" />
                        ) : (
                          <span className="flex h-3.5 w-3.5 shrink-0 items-center justify-center rounded-full border border-current text-[9px]">
                            {index + 1}
                          </span>
                        )}
                        <span className="truncate">{STAGE_LABELS[stage]}</span>
                      </div>
                    );
                  })}
                </div>
                <div className="mt-4 flex flex-wrap items-center justify-between gap-3">
                  <p className="text-sm text-sci-muted">
                    当前阶段：<span className="font-medium text-sci-ink">{STAGE_LABELS[detail.current_stage]}</span>
                  </p>
                  {nextAction && (
                    <button
                      type="button"
                      onClick={() => navigate(nextActionPath || nextAction.path)}
                      className="sci-btn-primary"
                    >
                      {nextAction.label}
                      <ArrowRight size={15} />
                    </button>
                  )}
                  {detail.current_stage === 'analysis' && (
                    <button
                      type="button"
                      onClick={() => {
                        if (window.confirm('确认当前科研流程已经完成？确认后仍可手动调整项目阶段。')) {
                          void handleStageChange('completed');
                        }
                      }}
                      className="sci-btn-primary"
                    >
                      <CheckCircle2 size={15} />
                      确认研究完成
                    </button>
                  )}
                  {detail.current_stage === 'completed' && (
                    <span className="sci-badge-success">科研流程已完成</span>
                  )}
                </div>
              </div>

              <div className="grid gap-3 sm:grid-cols-3">
                {[
                  { label: '论文', count: detail.counts.papers, icon: BookOpen },
                  { label: '会话', count: detail.counts.conversations, icon: Bot },
                  { label: '研究产物', count: detail.counts.artifacts, icon: FolderKanban },
                ].map(({ label, count, icon: Icon }) => (
                  <div key={label} className="sci-card flex items-center gap-3">
                    <Icon size={20} className="text-sci-accent" />
                    <div><p className="text-xs text-sci-muted">{label}</p><p className="text-xl font-semibold">{count}</p></div>
                  </div>
                ))}
              </div>

              <div className="grid gap-5 lg:grid-cols-3">
                <div><h3 className="sci-section-title">项目论文</h3>{renderAssetRows(detail.assets.papers, 'paper', null)}</div>
                <div><h3 className="sci-section-title">项目会话</h3>{renderAssetRows(detail.assets.conversations, 'conversation', null)}</div>
                <div><h3 className="sci-section-title">研究产物</h3>{renderAssetRows(detail.assets.artifacts, 'artifact', null)}</div>
              </div>

              <ProjectMemoryPanel projectId={detail.id} />
            </>
          )}
        </section>
      )}

      <section>
        <h2 className="sci-section-title mb-1">未归属资产</h2>
        <p className="mb-3 text-sm text-sci-muted">旧数据不会自动合并。选择一个当前项目后，可手动加入。</p>
        <div className="grid gap-5 lg:grid-cols-3">
          <div><h3 className="text-sm font-medium">论文 · {unassigned?.counts.papers ?? 0}</h3>{renderAssetRows(unassigned?.papers ?? [], 'paper', selectedProjectId)}</div>
          <div><h3 className="text-sm font-medium">会话 · {unassigned?.counts.conversations ?? 0}</h3>{renderAssetRows(unassigned?.conversations ?? [], 'conversation', selectedProjectId)}</div>
          <div><h3 className="text-sm font-medium">研究产物 · {unassigned?.counts.artifacts ?? 0}</h3>{renderAssetRows(unassigned?.artifacts ?? [], 'artifact', selectedProjectId)}</div>
        </div>
      </section>

      {archivedProjects.length > 0 && (
        <section>
          <h2 className="sci-section-title mb-3">已归档项目</h2>
          <div className="space-y-2">
            {archivedProjects.map((project) => (
              <div key={project.id} className="flex items-center gap-3 border-y border-sci-border py-3">
                <Archive size={16} className="text-sci-muted" />
                <span className="min-w-0 flex-1 truncate text-sm">{project.name}</span>
                <button type="button" onClick={() => void handleRestore(project)} className="sci-btn-secondary text-xs">
                  <RotateCcw size={14} /> 恢复
                </button>
              </div>
            ))}
          </div>
        </section>
      )}
    </div>
  );
}

export default Projects;
