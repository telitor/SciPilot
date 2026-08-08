import { useCallback, useEffect, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { Code2, Search, Folder, File, ChevronRight, ChevronDown, Copy, Check, Terminal, AlertCircle, Loader2, ArrowRight, BarChart3 } from 'lucide-react';
import AgentKnowledgePanel from '@/components/AgentKnowledgePanel';
import ProjectContextBar from '@/components/ProjectContextBar';
import { useDurableResearchJob } from '@/hooks/useDurableResearchJob';
import { codeAPI } from '@/services/api';
import { getApiErrorMessage } from '@/services/errors';
import { useAuthStore } from '@/store/authStore';
import { useSelectedProjectId } from '@/store/projectStore';
import { useUIStore } from '@/store/uiStore';
import type { CodeReproduction, RepoFile } from '@/types';

function FileTree({ files, depth = 0 }: { files: RepoFile[]; depth?: number }) {
  return (
    <div className="space-y-0.5">
      {files.map((file) => (
        <FileTreeItem key={file.path} file={file} depth={depth} />
      ))}
    </div>
  );
}

function FileTreeItem({ file, depth }: { file: RepoFile; depth: number }) {
  const [expanded, setExpanded] = useState(true);

  if (file.type === 'directory') {
    return (
      <div>
        <button
          onClick={() => setExpanded(!expanded)}
          className="flex items-center gap-1.5 py-1 px-2 rounded hover:bg-sci-bg3 w-full text-left text-sm"
          style={{ paddingLeft: `${depth * 16 + 8}px` }}
        >
          {expanded ? <ChevronDown size={14} className="text-sci-muted" /> : <ChevronRight size={14} className="text-sci-muted" />}
          <Folder size={14} className="text-sci-warning" />
          <span className="text-sci-ink">{file.name}</span>
        </button>
        {expanded && file.children && (
          <FileTree files={file.children} depth={depth + 1} />
        )}
      </div>
    );
  }

  return (
    <button
      className="flex items-center gap-1.5 py-1 px-2 rounded hover:bg-sci-bg3 w-full text-left text-sm"
      style={{ paddingLeft: `${depth * 16 + 8}px` }}
    >
      <div className="w-3.5" />
      <File size={14} className="text-sci-accent" />
      <span className="text-sci-muted">{file.name}</span>
    </button>
  );
}

function CodeReproduce() {
  const selectedProjectId = useSelectedProjectId();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const linkedRoadmapId = searchParams.get('roadmapId');
  const incomingRepoUrl = searchParams.get('repoUrl') || '';
  const userId = useAuthStore((state) => state.user?.id || 'anonymous');
  const storageKey = `scipilot-current-repository:${userId}${selectedProjectId ? `:${selectedProjectId}` : ''}`;
  const sourceStorageKey = `${storageKey}:roadmap-id`;
  const jobStorageKey = `${storageKey}:job-id`;
  const [repoUrl, setRepoUrl] = useState(incomingRepoUrl);
  const [isAnalyzing, setIsAnalyzing] = useState(false);
  const [reproduction, setReproduction] = useState<import('@/types').CodeReproduction | null>(null);
  const [copiedCommand, setCopiedCommand] = useState<string | null>(null);
  const [errorLog, setErrorLog] = useState('');
  const [isDiagnosing, setIsDiagnosing] = useState(false);
  const [diagnosis, setDiagnosis] = useState('');
  const { addNotification } = useUIStore();

  const handleJobSucceeded = useCallback((result: CodeReproduction) => {
    setReproduction(result);
    setRepoUrl(result.repo_url);
    if (result.id) {
      localStorage.setItem(storageKey, result.id);
      if (linkedRoadmapId) localStorage.setItem(sourceStorageKey, linkedRoadmapId);
      else localStorage.removeItem(sourceStorageKey);
    }
    addNotification({ type: 'success', message: '仓库分析完成', duration: 3000 });
  }, [addNotification, linkedRoadmapId, sourceStorageKey, storageKey]);

  const handleJobFailed = useCallback((message: string) => {
    addNotification({ type: 'error', message, duration: 5000 });
  }, [addNotification]);

  const {
    job,
    isRunning: isJobRunning,
    track: trackJob,
    retry: retryJob,
  } = useDurableResearchJob<CodeReproduction>({
    storageKey: jobStorageKey,
    jobType: 'code-reproduction',
    projectId: selectedProjectId,
    onSucceeded: handleJobSucceeded,
    onFailed: handleJobFailed,
  });

  useEffect(() => {
    setReproduction(null);
    setDiagnosis('');
    const artifactId = localStorage.getItem(storageKey);
    const storedRoadmapId = localStorage.getItem(sourceStorageKey);
    if (linkedRoadmapId && storedRoadmapId !== linkedRoadmapId) {
      setRepoUrl(incomingRepoUrl);
      return;
    }
    if (!artifactId) {
      setRepoUrl(incomingRepoUrl);
      return;
    }
    codeAPI.getRepoAnalysis(artifactId)
      .then((response) => {
        setReproduction(response.data);
        setRepoUrl(response.data.repo_url);
      })
      .catch(() => {
        localStorage.removeItem(storageKey);
        localStorage.removeItem(sourceStorageKey);
      });
  }, [incomingRepoUrl, linkedRoadmapId, sourceStorageKey, storageKey]);

  const handleAnalyze = async () => {
    if (isAnalyzing || isJobRunning) return;
    if (!repoUrl.trim()) {
      addNotification({ type: 'warning', message: '请输入 GitHub 仓库地址', duration: 3000 });
      return;
    }
    setIsAnalyzing(true);
    setDiagnosis('');
    try {
      const response = await codeAPI.analyzeRepoAsync(
        repoUrl.trim(),
        selectedProjectId,
        linkedRoadmapId,
      );
      trackJob(response.data);
    } catch (error) {
      addNotification({
        type: 'error',
        message: getApiErrorMessage(error, '仓库分析失败，请检查 GitHub 地址或代码复现智能体配置'),
        duration: 5000,
      });
    } finally {
      setIsAnalyzing(false);
    }
  };

  const copyCommand = (command: string) => {
    navigator.clipboard.writeText(command);
    setCopiedCommand(command);
    setTimeout(() => setCopiedCommand(null), 2000);
  };

  const handleDiagnose = async () => {
    if (!errorLog.trim()) {
      addNotification({ type: 'warning', message: '请粘贴错误日志', duration: 3000 });
      return;
    }
    if (!reproduction?.id) {
      addNotification({ type: 'warning', message: '请先完成仓库分析', duration: 3000 });
      return;
    }
    setIsDiagnosing(true);
    try {
      const response = await codeAPI.diagnoseError(errorLog.trim(), reproduction.id);
      setDiagnosis(response.data.diagnosis);
      addNotification({ type: 'success', message: '错误诊断完成', duration: 3000 });
    } catch (error) {
      addNotification({
        type: 'error',
        message: getApiErrorMessage(error, '错误诊断失败，请检查代码复现智能体配置'),
        duration: 5000,
      });
    } finally {
      setIsDiagnosing(false);
    }
  };

  return (
    <div className="space-y-6 pb-20 md:pb-0">
      <h1 className="text-2xl font-bold">代码复现辅助</h1>
      <ProjectContextBar />

      {/* Input */}
      <div className="sci-card-glow">
        <label className="block text-sm font-medium text-sci-ink mb-3">
          输入 GitHub 仓库地址
        </label>
        <div className="flex gap-3">
          <input
            type="text"
            value={repoUrl}
            onChange={(e) => setRepoUrl(e.target.value)}
            placeholder="https://github.com/username/repo"
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
                分析仓库
              </>
            )}
          </button>
        </div>
        {isJobRunning && (
          <p className="mt-3 text-sm text-sci-muted">
            智能体正在后台分析仓库，当前进度 {job?.progress ?? 0}%。刷新页面后任务会继续。
          </p>
        )}
        {job?.status === 'failed' && (
          <button type="button" onClick={() => void retryJob()} className="sci-btn-secondary mt-3">
            重试仓库分析
          </button>
        )}
      </div>

      <AgentKnowledgePanel category="code-reproduction" />

      {reproduction && (
        <div className="space-y-6">
          {/* Repo Info */}
          <div className="sci-card-glow">
            <div className="flex items-start justify-between">
              <div>
                <h2 className="text-xl font-semibold text-sci-accent">{reproduction.repo_name}</h2>
                <p className="text-sm text-sci-muted mt-1">{reproduction.description}</p>
                <div className="flex items-center gap-4 mt-3">
                  <span className="sci-badge-info">{reproduction.language}</span>
                  <span className="text-sm text-sci-muted flex items-center gap-1">
                    <Code2 size={14} />
                    {reproduction.stars} stars
                  </span>
                </div>
              </div>
            </div>
          </div>

          <div className="grid lg:grid-cols-3 gap-6">
            {/* File Tree */}
            <div className="sci-card">
              <h3 className="sci-section-title mb-3">文件结构</h3>
              <div className="bg-sci-bg3 rounded-lg p-2 overflow-auto max-h-96">
                <FileTree files={reproduction.file_tree} />
              </div>
            </div>

            {/* Dependencies */}
            <div className="sci-card">
              <h3 className="sci-section-title mb-3">依赖列表</h3>
              <div className="space-y-2">
                {reproduction.dependencies.map((dep) => (
                  <div
                    key={dep.name}
                    className="flex items-center justify-between p-3 rounded-lg bg-sci-bg3 border border-sci-border"
                  >
                    <div>
                      <span className="font-mono text-sm text-sci-accent">{dep.name}</span>
                      <span className="text-xs text-sci-muted ml-2">{dep.version}</span>
                    </div>
                    <span className="text-xs text-sci-muted">{dep.purpose}</span>
                  </div>
                ))}
              </div>
            </div>

            {/* Reproduction Steps */}
            <div className="sci-card">
              <h3 className="sci-section-title mb-3">复现步骤</h3>
              <div className="space-y-3">
                {reproduction.steps.map((step) => (
                  <div key={step.step} className="flex items-start gap-3">
                    <div className="w-6 h-6 rounded-full bg-sci-primary/20 text-sci-accent text-xs flex items-center justify-center flex-shrink-0 mt-0.5">
                      {step.step}
                    </div>
                    <div className="flex-1">
                      <p className="text-sm">{step.instruction}</p>
                      {step.command && (
                        <div className="mt-2 flex items-center gap-2">
                          <code className="flex-1 bg-sci-bg3 px-3 py-1.5 rounded text-xs font-mono text-sci-accent">
                            {step.command}
                          </code>
                          <button
                            onClick={() => copyCommand(step.command!)}
                            className="p-1.5 rounded hover:bg-sci-bg3 text-sci-muted"
                          >
                            {copiedCommand === step.command ? <Check size={14} className="text-sci-success" /> : <Copy size={14} />}
                          </button>
                        </div>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </div>

          {/* Error Diagnosis */}
          <div className="sci-card">
            <h3 className="sci-section-title mb-3 flex items-center gap-2">
              <AlertCircle size={16} className="text-sci-danger" />
              错误诊断
            </h3>
            <p className="text-sm text-sci-muted mb-3">遇到报错？粘贴错误日志获取修复建议</p>
            <div className="flex gap-3">
              <textarea
                value={errorLog}
                onChange={(e) => setErrorLog(e.target.value)}
                placeholder="粘贴错误日志..."
                rows={3}
                className="sci-input flex-1 font-mono text-sm resize-none"
              />
              <button
                onClick={handleDiagnose}
                disabled={isDiagnosing}
                className="sci-btn-primary self-end"
              >
                {isDiagnosing ? <Loader2 size={16} className="animate-spin" /> : <Terminal size={16} />}
                {isDiagnosing ? '诊断中' : '诊断'}
              </button>
            </div>
            {diagnosis && (
              <div className="mt-4 rounded-lg border border-sci-border bg-sci-bg3 p-4">
                <h4 className="text-sm font-semibold mb-2">诊断结果</h4>
                <p className="text-sm text-sci-muted whitespace-pre-wrap leading-relaxed">{diagnosis}</p>
              </div>
            )}
          </div>

          <div className="flex flex-wrap justify-end gap-3 border-t border-sci-border pt-4">
            <button
              type="button"
              onClick={() => navigate('/experiment/roadmap')}
              className="sci-btn-secondary"
            >
              返回实验路线
            </button>
            <button
              type="button"
              onClick={() => {
                const params = new URLSearchParams();
                if (reproduction.id) params.set('repoId', reproduction.id);
                navigate(`/result/analyze${params.toString() ? `?${params.toString()}` : ''}`);
              }}
              className="sci-btn-primary"
            >
              <BarChart3 size={16} />
              进入结果分析
              <ArrowRight size={16} />
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

export default CodeReproduce;
