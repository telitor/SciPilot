import { FormEvent, useCallback, useEffect, useMemo, useState } from 'react';
import {
  Archive,
  Brain,
  Database,
  Loader2,
  Pencil,
  Plus,
  RotateCcw,
  Save,
  X,
} from 'lucide-react';
import { projectAPI } from '@/services/api';
import { getApiErrorMessage } from '@/services/errors';
import { useUIStore } from '@/store/uiStore';
import type { ProjectMemory, ProjectMemoryType } from '@/types';

const MEMORY_TYPE_LABELS: Record<ProjectMemoryType, string> = {
  fact: '项目事实',
  decision: '研究决策',
  constraint: '约束条件',
  preference: '研究偏好',
  lesson: '经验教训',
  'artifact-summary': '确认产物',
};

const MANUAL_MEMORY_TYPES = Object.entries(MEMORY_TYPE_LABELS).filter(
  ([type]) => type !== 'artifact-summary',
) as Array<[ProjectMemoryType, string]>;

interface ProjectMemoryPanelProps {
  projectId: string;
}

export default function ProjectMemoryPanel({ projectId }: ProjectMemoryPanelProps) {
  const { addNotification } = useUIStore();
  const [memories, setMemories] = useState<ProjectMemory[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [showArchived, setShowArchived] = useState(false);
  const [showCreate, setShowCreate] = useState(false);
  const [memoryType, setMemoryType] = useState<ProjectMemoryType>('fact');
  const [title, setTitle] = useState('');
  const [content, setContent] = useState('');
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editType, setEditType] = useState<ProjectMemoryType>('fact');
  const [editTitle, setEditTitle] = useState('');
  const [editContent, setEditContent] = useState('');

  const loadMemories = useCallback(async () => {
    setLoading(true);
    try {
      const response = await projectAPI.getMemories(projectId, true);
      setMemories(Array.isArray(response.data.items) ? response.data.items : []);
    } catch (error) {
      addNotification({
        type: 'error',
        message: getApiErrorMessage(error, '项目记忆加载失败'),
        duration: 5000,
      });
    } finally {
      setLoading(false);
    }
  }, [addNotification, projectId]);

  useEffect(() => {
    setEditingId(null);
    setShowCreate(false);
    void loadMemories();
  }, [loadMemories]);

  const visibleMemories = useMemo(
    () => memories.filter((memory) => showArchived || memory.status === 'active'),
    [memories, showArchived],
  );

  const activeCount = memories.filter((memory) => memory.status === 'active').length;

  const resetCreate = () => {
    setMemoryType('fact');
    setTitle('');
    setContent('');
    setShowCreate(false);
  };

  const handleCreate = async (event: FormEvent) => {
    event.preventDefault();
    if (!title.trim() || !content.trim()) {
      addNotification({ type: 'warning', message: '请填写记忆标题和内容', duration: 3000 });
      return;
    }
    setSaving(true);
    try {
      const response = await projectAPI.createMemory(projectId, {
        memory_type: memoryType,
        title: title.trim(),
        content: content.trim(),
      });
      setMemories((current) => [response.data, ...current]);
      resetCreate();
      addNotification({ type: 'success', message: '项目记忆已保存', duration: 3000 });
    } catch (error) {
      addNotification({
        type: 'error',
        message: getApiErrorMessage(error, '保存项目记忆失败'),
        duration: 5000,
      });
    } finally {
      setSaving(false);
    }
  };

  const startEditing = (memory: ProjectMemory) => {
    setEditingId(memory.id);
    setEditType(memory.memory_type);
    setEditTitle(memory.title);
    setEditContent(memory.content);
  };

  const saveEdit = async (memory: ProjectMemory) => {
    if (!editTitle.trim() || !editContent.trim()) {
      addNotification({ type: 'warning', message: '记忆标题和内容不能为空', duration: 3000 });
      return;
    }
    setSaving(true);
    try {
      const response = await projectAPI.updateMemory(projectId, memory.id, {
        memory_type: editType,
        title: editTitle.trim(),
        content: editContent.trim(),
      });
      setMemories((current) => current.map((item) => (
        item.id === memory.id ? response.data : item
      )));
      setEditingId(null);
      addNotification({ type: 'success', message: '项目记忆已更新', duration: 3000 });
    } catch (error) {
      addNotification({
        type: 'error',
        message: getApiErrorMessage(error, '更新项目记忆失败'),
        duration: 5000,
      });
    } finally {
      setSaving(false);
    }
  };

  const changeStatus = async (memory: ProjectMemory) => {
    const nextStatus = memory.status === 'active' ? 'archived' : 'active';
    if (
      nextStatus === 'archived'
      && !window.confirm('停用后，智能体将不再使用这条项目记忆。确认继续？')
    ) return;
    setSaving(true);
    try {
      const response = await projectAPI.updateMemory(projectId, memory.id, {
        status: nextStatus,
      });
      setMemories((current) => current.map((item) => (
        item.id === memory.id ? response.data : item
      )));
      addNotification({
        type: 'success',
        message: nextStatus === 'active' ? '项目记忆已恢复' : '项目记忆已停用',
        duration: 3000,
      });
    } catch (error) {
      addNotification({
        type: 'error',
        message: getApiErrorMessage(error, '更新项目记忆状态失败'),
        duration: 5000,
      });
    } finally {
      setSaving(false);
    }
  };

  return (
    <section className="border-y border-sci-border py-5">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <div className="flex items-center gap-2">
            <Brain size={19} className="text-sci-accent" />
            <h3 className="sci-section-title">项目记忆</h3>
            <span className="sci-badge-info">{activeCount} 条有效</span>
          </div>
          <p className="mt-1 text-sm text-sci-muted">
            已确认产物会自动沉淀；有效记忆会作为项目事实传给后续智能体。
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-3">
          <label className="flex items-center gap-2 text-sm text-sci-muted">
            <input
              type="checkbox"
              checked={showArchived}
              onChange={(event) => setShowArchived(event.target.checked)}
            />
            显示已停用
          </label>
          <button
            type="button"
            onClick={() => setShowCreate((current) => !current)}
            className="sci-btn-secondary"
          >
            {showCreate ? <X size={15} /> : <Plus size={15} />}
            {showCreate ? '取消' : '新增记忆'}
          </button>
        </div>
      </div>

      {showCreate && (
        <form onSubmit={handleCreate} className="mt-4 grid gap-3 border-t border-sci-border pt-4">
          <div className="grid gap-3 md:grid-cols-[180px_minmax(0,1fr)]">
            <select
              value={memoryType}
              onChange={(event) => setMemoryType(event.target.value as ProjectMemoryType)}
              className="sci-input"
              aria-label="项目记忆类型"
            >
              {MANUAL_MEMORY_TYPES.map(([value, label]) => (
                <option key={value} value={value}>{label}</option>
              ))}
            </select>
            <input
              value={title}
              onChange={(event) => setTitle(event.target.value)}
              placeholder="记忆标题，例如：评测指标选择"
              maxLength={200}
              className="sci-input"
            />
          </div>
          <textarea
            value={content}
            onChange={(event) => setContent(event.target.value)}
            placeholder="记录已经确认的事实、决策、约束或失败经验"
            maxLength={8000}
            rows={3}
            className="sci-input resize-y"
          />
          <div className="flex justify-end">
            <button type="submit" disabled={saving} className="sci-btn-primary">
              {saving ? <Loader2 size={15} className="animate-spin" /> : <Save size={15} />}
              保存记忆
            </button>
          </div>
        </form>
      )}

      <div className="mt-4 divide-y divide-sci-border">
        {loading ? (
          <div className="flex min-h-24 items-center justify-center">
            <Loader2 className="animate-spin text-sci-accent" />
          </div>
        ) : visibleMemories.length === 0 ? (
          <p className="py-6 text-center text-sm text-sci-muted">
            暂无项目记忆。确认研究产物或手动记录一条重要信息后会显示在这里。
          </p>
        ) : visibleMemories.map((memory) => {
          const editing = editingId === memory.id;
          return (
            <article key={memory.id} className={`py-4 ${memory.status === 'archived' ? 'opacity-60' : ''}`}>
              {editing ? (
                <div className="grid gap-3">
                  <div className="grid gap-3 md:grid-cols-[180px_minmax(0,1fr)]">
                    <select
                      value={editType}
                      onChange={(event) => setEditType(event.target.value as ProjectMemoryType)}
                      className="sci-input"
                    >
                      {(memory.source_type === 'artifact'
                        ? [[memory.memory_type, MEMORY_TYPE_LABELS[memory.memory_type]] as [ProjectMemoryType, string]]
                        : MANUAL_MEMORY_TYPES
                      ).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
                    </select>
                    <input
                      value={editTitle}
                      onChange={(event) => setEditTitle(event.target.value)}
                      maxLength={200}
                      className="sci-input"
                    />
                  </div>
                  <textarea
                    value={editContent}
                    onChange={(event) => setEditContent(event.target.value)}
                    maxLength={8000}
                    rows={4}
                    className="sci-input resize-y"
                  />
                  <div className="flex justify-end gap-2">
                    <button type="button" onClick={() => setEditingId(null)} className="sci-btn-secondary">
                      <X size={15} />取消
                    </button>
                    <button type="button" onClick={() => void saveEdit(memory)} disabled={saving} className="sci-btn-primary">
                      {saving ? <Loader2 size={15} className="animate-spin" /> : <Save size={15} />}
                      保存新内容
                    </button>
                  </div>
                </div>
              ) : (
                <div className="flex items-start gap-3">
                  <span className="mt-0.5 text-sci-accent">
                    {memory.source_type === 'artifact' ? <Database size={17} /> : <Brain size={17} />}
                  </span>
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <h4 className="font-medium">{memory.title}</h4>
                      <span className="sci-badge-info">{MEMORY_TYPE_LABELS[memory.memory_type]}</span>
                      {memory.source_type === 'artifact' && (
                        <span className="text-xs text-sci-muted">来自确认产物 v{memory.source_version || 1}</span>
                      )}
                      {memory.status === 'archived' && <span className="sci-badge-warning">已停用</span>}
                    </div>
                    <p className="mt-2 whitespace-pre-wrap text-sm leading-6 text-sci-muted">{memory.content}</p>
                  </div>
                  <div className="flex shrink-0 gap-1">
                    <button
                      type="button"
                      onClick={() => startEditing(memory)}
                      disabled={saving || memory.status === 'archived'}
                      className="p-2 text-sci-muted hover:text-sci-accent disabled:opacity-40"
                      title="编辑记忆"
                    >
                      <Pencil size={15} />
                    </button>
                    <button
                      type="button"
                      onClick={() => void changeStatus(memory)}
                      disabled={saving}
                      className="p-2 text-sci-muted hover:text-sci-accent disabled:opacity-40"
                      title={memory.status === 'active' ? '停用记忆' : '恢复记忆'}
                    >
                      {memory.status === 'active' ? <Archive size={15} /> : <RotateCcw size={15} />}
                    </button>
                  </div>
                </div>
              )}
            </article>
          );
        })}
      </div>
    </section>
  );
}

