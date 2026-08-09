import { useCallback, useEffect, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { Search, ChevronDown, ChevronRight, BookOpen, Database, ArrowRight, Loader2, Plus, Trash2, Combine } from 'lucide-react';
import AgentKnowledgePanel from '@/components/AgentKnowledgePanel';
import ArtifactReviewToolbar, { mergeArtifactDetail } from '@/components/ArtifactReviewToolbar';
import ProjectContextBar from '@/components/ProjectContextBar';
import { useDurableResearchJob } from '@/hooks/useDurableResearchJob';
import { artifactAPI, researchAPI } from '@/services/api';
import { getApiErrorMessage } from '@/services/errors';
import { useAuthStore } from '@/store/authStore';
import { useSelectedProjectId } from '@/store/projectStore';
import { useUIStore } from '@/store/uiStore';
import type { ResearchNode, ResearchTree } from '@/types';

function FeasibilityBadge({ level }: { level: 'high' | 'medium' | 'low' }) {
  const config = {
    high: { class: 'sci-badge-success', label: '可行性高' },
    medium: { class: 'sci-badge-warning', label: '可行性中' },
    low: { class: 'sci-badge-danger', label: '可行性低' },
  };
  const c = config[level];
  return <span className={c.class}>{c.label}</span>;
}

function TreeNode({
  node,
  depth = 0,
}: {
  node: ResearchNode;
  depth?: number;
}) {
  const [expanded, setExpanded] = useState(depth < 1);
  const [showDetail, setShowDetail] = useState(false);

  return (
    <div className="relative">
      {/* Connector lines */}
      {depth > 0 && (
        <div
          className="absolute left-0 top-0 bottom-0 w-px bg-sci-border"
          style={{ left: `${depth * 24 - 12}px` }}
        />
      )}

      <div
        className="flex items-start gap-3 py-2"
        style={{ paddingLeft: `${depth * 24}px` }}
      >
        <button
          onClick={() => setExpanded(!expanded)}
          className="mt-1 p-0.5 rounded hover:bg-sci-bg3 text-sci-muted"
        >
          {node.children && node.children.length > 0 ? (
            expanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />
          ) : (
            <div className="w-3.5 h-3.5" />
          )}
        </button>

        <div
          className="flex-1 sci-card cursor-pointer hover:border-sci-accent/50 transition-colors"
          onClick={() => setShowDetail(!showDetail)}
        >
          <div className="flex items-start justify-between gap-3">
            <div className="flex-1">
              <p className="text-sm font-medium text-sci-ink">{node.question}</p>
              <div className="flex items-center gap-2 mt-2">
                <FeasibilityBadge level={node.feasibility} />
                <span className="text-xs text-sci-muted flex items-center gap-1">
                  <Database size={10} />
                  {node.datasets.length} 个数据集
                </span>
                <span className="text-xs text-sci-muted flex items-center gap-1">
                  <BookOpen size={10} />
                  {node.papers.length} 篇相关论文
                </span>
              </div>
            </div>
          </div>

          {showDetail && (
            <div className="mt-3 pt-3 border-t border-sci-border space-y-2 animate-fade-in">
              <div>
                <p className="text-xs text-sci-muted mb-1">相关数据集</p>
                <div className="flex flex-wrap gap-1">
                  {node.datasets.map((d) => (
                    <span key={d} className="sci-badge-info text-[10px]">{d}</span>
                  ))}
                </div>
              </div>
              <div>
                <p className="text-xs text-sci-muted mb-1">相关论文</p>
                <div className="flex flex-wrap gap-1">
                  {node.papers.map((p) => (
                    <span key={p} className="sci-badge-purple text-[10px]">{p}</span>
                  ))}
                </div>
              </div>
            </div>
          )}
        </div>
      </div>

      {expanded && node.children?.map((child) => (
        <TreeNode key={child.id} node={child} depth={depth + 1} />
      ))}
    </div>
  );
}

function newResearchNode(): ResearchNode {
  return {
    id: `rq-${Date.now()}-${Math.random().toString(16).slice(2)}`,
    question: '新的研究子问题',
    feasibility: 'medium',
    datasets: [],
    papers: [],
    children: [],
  };
}

function mergeNodes(nodes: ResearchNode[], index: number): ResearchNode[] {
  if (index <= 0 || index >= nodes.length) return nodes;
  const previous = nodes[index - 1];
  const current = nodes[index];
  const merged: ResearchNode = {
    ...previous,
    question: `${previous.question}；${current.question}`,
    datasets: [...new Set([...previous.datasets, ...current.datasets])],
    papers: [...new Set([...previous.papers, ...current.papers])],
    children: [...(previous.children || []), ...(current.children || [])],
  };
  return [...nodes.slice(0, index - 1), merged, ...nodes.slice(index + 1)];
}

function EditableTreeNode({
  node,
  onChange,
  onDelete,
  onMerge,
}: {
  node: ResearchNode;
  onChange: (node: ResearchNode) => void;
  onDelete: () => void;
  onMerge?: () => void;
}) {
  const children = node.children || [];
  const updateChildren = (nextChildren: ResearchNode[]) => onChange({ ...node, children: nextChildren });

  return (
    <div className="border-l-2 border-sci-border pl-3 space-y-3">
      <div className="grid md:grid-cols-[1fr_140px_auto] gap-2 items-start">
        <input
          className="sci-input"
          value={node.question}
          onChange={(event) => onChange({ ...node, question: event.target.value })}
          aria-label="研究子问题"
        />
        <select
          className="sci-input"
          value={node.feasibility}
          onChange={(event) => onChange({
            ...node,
            feasibility: event.target.value as ResearchNode['feasibility'],
          })}
          aria-label="可行性"
        >
          <option value="high">可行性高</option>
          <option value="medium">可行性中</option>
          <option value="low">可行性低</option>
        </select>
        <div className="flex gap-1">
          {onMerge && (
            <button type="button" onClick={onMerge} className="p-2 text-sci-muted hover:text-sci-accent" title="与上一节点合并">
              <Combine size={16} />
            </button>
          )}
          <button type="button" onClick={onDelete} className="p-2 text-sci-muted hover:text-sci-danger" title="删除节点">
            <Trash2 size={16} />
          </button>
        </div>
      </div>
      <div className="grid md:grid-cols-2 gap-2">
        <input
          className="sci-input text-sm"
          value={node.datasets.join(', ')}
          onChange={(event) => onChange({
            ...node,
            datasets: event.target.value.split(',').map((item) => item.trim()).filter(Boolean),
          })}
          placeholder="相关数据集，用逗号分隔"
        />
        <input
          className="sci-input text-sm"
          value={node.papers.join(', ')}
          onChange={(event) => onChange({
            ...node,
            papers: event.target.value.split(',').map((item) => item.trim()).filter(Boolean),
          })}
          placeholder="相关论文，用逗号分隔"
        />
      </div>
      <div className="space-y-3 pl-3">
        {children.map((child, index) => (
          <EditableTreeNode
            key={child.id}
            node={child}
            onChange={(nextChild) => updateChildren(children.map((item, childIndex) => childIndex === index ? nextChild : item))}
            onDelete={() => updateChildren(children.filter((_, childIndex) => childIndex !== index))}
            onMerge={index > 0 ? () => updateChildren(mergeNodes(children, index)) : undefined}
          />
        ))}
        <button type="button" onClick={() => updateChildren([...children, newResearchNode()])} className="sci-btn-secondary">
          <Plus size={14} />
          添加子节点
        </button>
      </div>
    </div>
  );
}

function ResearchDecompose() {
  const selectedProjectId = useSelectedProjectId();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const linkedPaperId = searchParams.get('paperId');
  const incomingDirection = searchParams.get('direction') || '';
  const userId = useAuthStore((state) => state.user?.id || 'anonymous');
  const storageKey = `scipilot-current-research:${userId}${selectedProjectId ? `:${selectedProjectId}` : ''}`;
  const sourceStorageKey = `${storageKey}:paper-id`;
  const jobStorageKey = `${storageKey}:job-id`;
  const [direction, setDirection] = useState(incomingDirection);
  const [isAnalyzing, setIsAnalyzing] = useState(false);
  const [tree, setTree] = useState<import('@/types').ResearchTree | null>(null);
  const [draftTree, setDraftTree] = useState<ResearchTree | null>(null);
  const [isEditing, setIsEditing] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
  const { addNotification } = useUIStore();

  const handleJobSucceeded = useCallback((result: ResearchTree) => {
    setTree(result);
    setDraftTree(null);
    setIsEditing(false);
    if (result.id) {
      localStorage.setItem(storageKey, result.id);
      if (linkedPaperId) localStorage.setItem(sourceStorageKey, linkedPaperId);
      else localStorage.removeItem(sourceStorageKey);
    }
    addNotification({ type: 'success', message: '问题拆解完成', duration: 3000 });
  }, [addNotification, linkedPaperId, sourceStorageKey, storageKey]);

  const handleJobFailed = useCallback((message: string) => {
    addNotification({ type: 'error', message, duration: 5000 });
  }, [addNotification]);

  const {
    job,
    isRunning: isJobRunning,
    track: trackJob,
    retry: retryJob,
  } = useDurableResearchJob<ResearchTree>({
    storageKey: jobStorageKey,
    jobType: 'research-decomposition',
    projectId: selectedProjectId,
    onSucceeded: handleJobSucceeded,
    onFailed: handleJobFailed,
  });

  useEffect(() => {
    setTree(null);
    const artifactId = localStorage.getItem(storageKey);
    const storedPaperId = localStorage.getItem(sourceStorageKey);
    if (linkedPaperId && storedPaperId !== linkedPaperId) {
      setDirection(incomingDirection);
      return;
    }
    if (!artifactId) {
      setDirection(incomingDirection);
      return;
    }
    researchAPI.getResearchTree(artifactId)
      .then((response) => {
        setTree(response.data);
        setDirection(response.data.core_question);
      })
      .catch(() => {
        localStorage.removeItem(storageKey);
        localStorage.removeItem(sourceStorageKey);
      });
  }, [incomingDirection, linkedPaperId, sourceStorageKey, storageKey]);

  const handleAnalyze = async () => {
    if (isAnalyzing || isJobRunning) return;
    if (!direction.trim()) {
      addNotification({ type: 'warning', message: '请输入研究方向', duration: 3000 });
      return;
    }
    setIsAnalyzing(true);
    try {
      const response = await researchAPI.decomposeAsync(
        direction.trim(),
        selectedProjectId,
        linkedPaperId,
      );
      trackJob(response.data);
    } catch (error) {
      addNotification({
        type: 'error',
        message: getApiErrorMessage(error, '问题拆解失败，请检查后端智能体配置'),
        duration: 5000,
      });
    } finally {
      setIsAnalyzing(false);
    }
  };

  const handleArtifactChanged = (detail: import('@/types').ArtifactDetail) => {
    const nextTree = mergeArtifactDetail<ResearchTree>(detail);
    setTree(nextTree);
    setDraftTree(null);
    setIsEditing(false);
    localStorage.setItem(storageKey, detail.id);
  };

  const startEditing = () => {
    if (!tree) return;
    setDraftTree(structuredClone(tree));
    setIsEditing(true);
  };

  const saveRevision = async () => {
    if (!tree?.id || !draftTree) return;
    if (!draftTree.core_question.trim()) {
      addNotification({ type: 'warning', message: '核心问题不能为空', duration: 3000 });
      return;
    }
    setIsSaving(true);
    try {
      const response = await artifactAPI.revise(
        tree.id,
        {
          core_question: draftTree.core_question.trim(),
          sub_questions: draftTree.sub_questions,
          generation_mode: draftTree.generation_mode,
        },
        undefined,
        '人工编辑问题树',
      );
      handleArtifactChanged(response.data);
      addNotification({ type: 'success', message: '问题树已保存为新草稿版本', duration: 3000 });
    } catch (error) {
      addNotification({
        type: 'error',
        message: getApiErrorMessage(error, '问题树保存失败'),
        duration: 5000,
      });
    } finally {
      setIsSaving(false);
    }
  };

  return (
    <div className="space-y-6 pb-20 md:pb-0">
      <h1 className="text-2xl font-bold">研究问题拆解</h1>
      <ProjectContextBar />

      {/* Input */}
      <div className="sci-card-glow">
        <label className="block text-sm font-medium text-sci-ink mb-3">
          输入你的研究方向
        </label>
        <div className="flex gap-3">
          <input
            type="text"
            value={direction}
            onChange={(e) => setDirection(e.target.value)}
            placeholder="例如：基于深度学习的代码克隆检测方法研究"
            className="sci-input flex-1"
            onKeyDown={(e) => e.key === 'Enter' && handleAnalyze()}
          />
          <button
            onClick={handleAnalyze}
            disabled={isAnalyzing || isJobRunning}
            className="sci-btn-primary"
          >
            {isAnalyzing || isJobRunning ? (
              <>
                <Loader2 size={16} className="animate-spin" />
                分析中
              </>
            ) : (
              <>
                <Search size={16} />
                开始拆解
              </>
            )}
          </button>
        </div>
        {isJobRunning && (
          <p className="mt-3 text-sm text-sci-muted">
            智能体正在后台拆解，当前进度 {job?.progress ?? 0}%。刷新页面后任务会继续。
          </p>
        )}
        {job?.status === 'failed' && (
          <button type="button" onClick={() => void retryJob()} className="sci-btn-secondary mt-3">
            重试问题拆解
          </button>
        )}
      </div>

      <AgentKnowledgePanel category="problem-decomposition" />

      {/* Result */}
      {tree && (
        <div className="space-y-4">
          <ArtifactReviewToolbar
            artifact={tree}
            isEditing={isEditing}
            isSaving={isSaving}
            onEdit={startEditing}
            onSave={() => void saveRevision()}
            onCancel={() => {
              setDraftTree(null);
              setIsEditing(false);
            }}
            onArtifactChanged={handleArtifactChanged}
          />

          {isEditing && draftTree ? (
            <div className="sci-card space-y-4">
              <div>
                <label className="block text-sm font-medium mb-2">核心问题</label>
                <input
                  className="sci-input w-full"
                  value={draftTree.core_question}
                  onChange={(event) => setDraftTree({
                    ...draftTree,
                    core_question: event.target.value,
                  })}
                />
              </div>
              <div className="space-y-4">
                <h3 className="sci-section-title">编辑子问题树</h3>
                {draftTree.sub_questions.map((node, index) => (
                  <EditableTreeNode
                    key={node.id}
                    node={node}
                    onChange={(nextNode) => setDraftTree({
                      ...draftTree,
                      sub_questions: draftTree.sub_questions.map((item, nodeIndex) => nodeIndex === index ? nextNode : item),
                    })}
                    onDelete={() => setDraftTree({
                      ...draftTree,
                      sub_questions: draftTree.sub_questions.filter((_, nodeIndex) => nodeIndex !== index),
                    })}
                    onMerge={index > 0 ? () => setDraftTree({
                      ...draftTree,
                      sub_questions: mergeNodes(draftTree.sub_questions, index),
                    }) : undefined}
                  />
                ))}
                <button
                  type="button"
                  onClick={() => setDraftTree({
                    ...draftTree,
                    sub_questions: [...draftTree.sub_questions, newResearchNode()],
                  })}
                  className="sci-btn-secondary"
                >
                  <Plus size={15} />
                  添加一级问题
                </button>
              </div>
            </div>
          ) : (
            <>
              <div className="sci-card-glow">
                <h2 className="text-lg font-semibold mb-2">核心问题</h2>
                <p className="text-sci-accent">{tree.core_question}</p>
              </div>

              <div className="sci-card">
                <h3 className="sci-section-title mb-4">子问题树</h3>
                <div className="space-y-1">
                  {tree.sub_questions.map((node) => (
                    <TreeNode key={node.id} node={node} />
                  ))}
                </div>
              </div>
            </>
          )}

          {/* Action Buttons */}
          <div className="flex flex-wrap gap-3">
            <button onClick={() => navigate('/paper/read')} className="sci-btn-secondary">
              <BookOpen size={16} />
              返回论文精读
            </button>
            <button
              onClick={() => {
                const params = new URLSearchParams({ objective: tree.core_question });
                if (tree.id) params.set('questionId', tree.id);
                navigate(`/experiment/roadmap?${params.toString()}`);
              }}
              disabled={tree.review_status !== 'confirmed' || isEditing}
              title={tree.review_status === 'confirmed' ? undefined : '请先确认当前问题树'}
              className="sci-btn-primary"
            >
              生成实验方案
              <ArrowRight size={16} />
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

export default ResearchDecompose;
