import { useState } from 'react';
import {
  Archive,
  CheckCircle2,
  ChevronDown,
  ChevronUp,
  History,
  Loader2,
  Pencil,
  RotateCcw,
  Save,
  X,
} from 'lucide-react';
import { artifactAPI } from '@/services/api';
import { getApiErrorMessage } from '@/services/errors';
import { useUIStore } from '@/store/uiStore';
import type {
  ArtifactDetail,
  ArtifactVersionList,
  ArtifactVersionMetadata,
  ArtifactVersionSummary,
} from '@/types';

export function mergeArtifactDetail<T extends ArtifactVersionMetadata>(
  detail: ArtifactDetail,
): T {
  return {
    ...detail.content,
    id: detail.id,
    project_id: detail.project_id,
    review_status: detail.review_status,
    version_group_id: detail.version_group_id,
    version: detail.version,
    parent_version_id: detail.parent_version_id,
    confirmed_at: detail.confirmed_at,
    created_at: detail.created_at,
    updated_at: detail.updated_at,
  } as T;
}

interface ArtifactReviewToolbarProps {
  artifact: ArtifactVersionMetadata;
  isEditing: boolean;
  isSaving?: boolean;
  onEdit: () => void;
  onSave: () => void;
  onCancel: () => void;
  onArtifactChanged: (artifact: ArtifactDetail) => void;
}

const statusConfig = {
  draft: { label: '草稿', className: 'sci-badge-warning' },
  confirmed: { label: '已确认', className: 'sci-badge-success' },
  deprecated: { label: '已废弃', className: 'sci-badge-danger' },
} as const;

function formatTime(value?: string | null) {
  if (!value) return '时间未知';
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? '时间未知' : date.toLocaleString('zh-CN');
}

function ArtifactReviewToolbar({
  artifact,
  isEditing,
  isSaving = false,
  onEdit,
  onSave,
  onCancel,
  onArtifactChanged,
}: ArtifactReviewToolbarProps) {
  const artifactId = artifact.id;
  const status = artifact.review_status || 'draft';
  const config = statusConfig[status];
  const [isWorking, setIsWorking] = useState(false);
  const [showHistory, setShowHistory] = useState(false);
  const [history, setHistory] = useState<ArtifactVersionList | null>(null);
  const [confirmDeprecate, setConfirmDeprecate] = useState(false);
  const { addNotification } = useUIStore();

  if (!artifactId) return null;

  const loadHistory = async () => {
    const nextOpen = !showHistory;
    setShowHistory(nextOpen);
    if (!nextOpen || history) return;
    try {
      const response = await artifactAPI.getVersions(artifactId);
      setHistory(response.data);
    } catch (error) {
      addNotification({
        type: 'error',
        message: getApiErrorMessage(error, '版本历史加载失败'),
        duration: 5000,
      });
    }
  };

  const runAction = async (
    action: () => Promise<{ data: ArtifactDetail }>,
    successMessage: string,
  ) => {
    if (isWorking) return;
    setIsWorking(true);
    try {
      const response = await action();
      onArtifactChanged(response.data);
      const versions = await artifactAPI.getVersions(response.data.id);
      setHistory(versions.data);
      setConfirmDeprecate(false);
      addNotification({ type: 'success', message: successMessage, duration: 3000 });
    } catch (error) {
      addNotification({
        type: 'error',
        message: getApiErrorMessage(error, '产物状态更新失败'),
        duration: 5000,
      });
    } finally {
      setIsWorking(false);
    }
  };

  const handleRestore = (version: ArtifactVersionSummary) => runAction(
    () => artifactAPI.restore(version.id, `恢复版本 v${version.version}`),
    `已从 v${version.version} 创建新草稿`,
  );

  return (
    <div className="sci-card">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-wrap items-center gap-2">
          <span className={config.className}>{config.label}</span>
          <span className="text-sm font-medium text-sci-ink">v{artifact.version || 1}</span>
          <span className="text-xs text-sci-muted">
            更新于 {formatTime(artifact.updated_at || artifact.created_at)}
          </span>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          {isEditing ? (
            <>
              <button type="button" onClick={onCancel} disabled={isSaving} className="sci-btn-secondary">
                <X size={15} />
                取消
              </button>
              <button type="button" onClick={onSave} disabled={isSaving} className="sci-btn-primary">
                {isSaving ? <Loader2 size={15} className="animate-spin" /> : <Save size={15} />}
                {isSaving ? '保存中' : '保存新版本'}
              </button>
            </>
          ) : (
            <button
              type="button"
              onClick={onEdit}
              disabled={status === 'deprecated' || isWorking}
              className="sci-btn-secondary"
            >
              <Pencil size={15} />
              编辑
            </button>
          )}

          <button
            type="button"
            onClick={() => void runAction(
              () => artifactAPI.confirm(artifactId),
              '产物已确认，下游将使用此版本',
            )}
            disabled={status !== 'draft' || isEditing || isWorking}
            className="sci-btn-primary"
          >
            {isWorking ? <Loader2 size={15} className="animate-spin" /> : <CheckCircle2 size={15} />}
            确认版本
          </button>

          <button type="button" onClick={() => void loadHistory()} className="sci-btn-secondary">
            <History size={15} />
            历史
            {showHistory ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
          </button>

          {status !== 'deprecated' && !isEditing && (
            confirmDeprecate ? (
              <button
                type="button"
                onClick={() => void runAction(
                  () => artifactAPI.deprecate(artifactId),
                  '当前版本已标记为废弃',
                )}
                disabled={isWorking}
                className="sci-btn-secondary text-sci-danger"
              >
                <Archive size={15} />
                确认废弃
              </button>
            ) : (
              <button
                type="button"
                onClick={() => setConfirmDeprecate(true)}
                className="sci-btn-secondary"
              >
                <Archive size={15} />
                废弃
              </button>
            )
          )}
        </div>
      </div>

      {status === 'draft' && !isEditing && (
        <p className="mt-3 text-xs text-sci-muted">
          当前是草稿。确认后才会作为后续科研阶段的默认输入。
        </p>
      )}

      {showHistory && (
        <div className="mt-4 border-t border-sci-border pt-3 space-y-2">
          {history?.items.map((version) => (
            <div
              key={version.id}
              className="flex flex-wrap items-center justify-between gap-3 py-2 border-b border-sci-border/60 last:border-0"
            >
              <div className="flex items-center gap-3">
                <span className="text-sm font-semibold">v{version.version}</span>
                <span className={statusConfig[version.review_status].className}>
                  {statusConfig[version.review_status].label}
                </span>
                <span className="text-xs text-sci-muted">{formatTime(version.updated_at || version.created_at)}</span>
              </div>
              {version.id !== artifactId && (
                <button
                  type="button"
                  onClick={() => void handleRestore(version)}
                  disabled={isWorking || isEditing}
                  className="sci-btn-secondary"
                >
                  <RotateCcw size={14} />
                  恢复为新草稿
                </button>
              )}
            </div>
          ))}
          {!history && <p className="text-sm text-sci-muted">正在加载版本历史...</p>}
        </div>
      )}
    </div>
  );
}

export default ArtifactReviewToolbar;
