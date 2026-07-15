import { useEffect, useState } from 'react';
import { Code2, Search, Folder, File, ChevronRight, ChevronDown, Copy, Check, Terminal, AlertCircle, Loader2 } from 'lucide-react';
import { agentAPI, conversationAPI, getErrorMessage } from '@/services/api';
import { useUIStore } from '@/store/uiStore';
import type { CodeReproduction, RepoFile } from '@/types';

type AgentItem = {
  id: string;
  category?: string;
};

type ChatMessage = {
  id: string;
  role: 'user' | 'assistant';
  content: string;
};

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

function extractJsonObject(text: string): unknown | null {
  const start = text.indexOf('{');
  const end = text.lastIndexOf('}');
  if (start === -1 || end === -1 || end <= start) return null;

  try {
    return JSON.parse(text.slice(start, end + 1));
  } catch {
    return null;
  }
}

function normalizeCodeReproduction(value: unknown): CodeReproduction | null {
  if (!value || typeof value !== 'object') return null;
  const data = value as Partial<CodeReproduction>;

  if (typeof data.repo_name !== 'string' && !Array.isArray(data.steps)) {
    return null;
  }

  return {
    repo_name: String(data.repo_name || 'Repository'),
    repo_url: String(data.repo_url || ''),
    language: String(data.language || 'Unknown'),
    stars: typeof data.stars === 'number' ? data.stars : 0,
    description: String(data.description || ''),
    file_tree: Array.isArray(data.file_tree) ? data.file_tree : [],
    dependencies: Array.isArray(data.dependencies) ? data.dependencies : [],
    steps: Array.isArray(data.steps) ? data.steps : [],
  };
}

function CodeReproduce() {
  const [repoUrl, setRepoUrl] = useState('');
  const [isAnalyzing, setIsAnalyzing] = useState(false);
  const [isDiagnosing, setIsDiagnosing] = useState(false);
  const [reproduction, setReproduction] = useState<CodeReproduction | null>(null);
  const [copiedCommand, setCopiedCommand] = useState<string | null>(null);
  const [errorLog, setErrorLog] = useState('');
  const [agentId, setAgentId] = useState<string | null>(null);
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const { addNotification } = useUIStore();

  useEffect(() => {
    const loadAgent = async () => {
      try {
        const response = await agentAPI.getAgents();
        const agents = Array.isArray(response.data) ? response.data as AgentItem[] : [];
        const agent = agents.find((item) => item.category === 'code-reproduction');
        if (!agent) {
          addNotification({
            type: 'warning',
            message: '未找到对应智能体，请检查 Supabase agents 表。',
            duration: 5000,
          });
          return;
        }
        setAgentId(agent.id);
      } catch (error) {
        addNotification({
          type: 'error',
          message: getErrorMessage(error),
          duration: 5000,
        });
      }
    };

    loadAgent();
  }, [addNotification]);

  const sendToAgent = async (displayMessage: string, agentMessage: string) => {
    if (!agentId) {
      addNotification({
        type: 'warning',
        message: '未找到对应智能体，请检查 Supabase agents 表。',
        duration: 5000,
      });
      return null;
    }

    setMessages((prev) => [
      ...prev,
      {
        id: `user-${Date.now()}`,
        role: 'user',
        content: displayMessage,
      },
    ]);

    let currentConversationId = conversationId;
    if (!currentConversationId) {
      const conversationResponse = await conversationAPI.createConversation({
        agent_id: agentId,
        title: '代码复现对话',
      });
      currentConversationId = String(conversationResponse.data.id);
      setConversationId(currentConversationId);
    }

    const response = await conversationAPI.chat({
      conversation_id: currentConversationId,
      agent_id: agentId,
      message: agentMessage,
    });

    const reply = String(response.data?.reply || '');
    setMessages((prev) => [
      ...prev,
      {
        id: `assistant-${Date.now()}`,
        role: 'assistant',
        content: reply,
      },
    ]);

    return reply;
  };

  const handleAnalyze = async () => {
    if (isAnalyzing) return;

    const userInput = repoUrl.trim();
    if (!userInput) {
      addNotification({ type: 'warning', message: '请输入 GitHub 仓库地址', duration: 3000 });
      return;
    }

    setIsAnalyzing(true);

    try {
      const reply = await sendToAgent(
        userInput,
        [
          '请分析这个论文或科研项目代码仓库，给出仓库功能、主要语言、目录结构、依赖、复现步骤和注意事项。',
          '如果可以，请返回结构化 JSON，字段包含 repo_name、repo_url、language、stars、description、file_tree、dependencies、steps。',
          `仓库地址：${userInput}`,
        ].join('\n')
      );

      if (reply) {
        const parsedReproduction = normalizeCodeReproduction(extractJsonObject(reply));
        if (parsedReproduction) {
          setReproduction(parsedReproduction);
        }
        addNotification({ type: 'success', message: '仓库分析完成', duration: 3000 });
      }
    } catch (error) {
      addNotification({
        type: 'error',
        message: getErrorMessage(error) || '智能体调用失败，请检查后端或 Agent 配置。',
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
    if (isDiagnosing) return;

    const log = errorLog.trim();
    if (!log) {
      addNotification({ type: 'warning', message: '请粘贴错误日志', duration: 3000 });
      return;
    }

    setIsDiagnosing(true);
    try {
      await sendToAgent(
        '诊断错误日志',
        [
          '请诊断下面的代码复现报错，说明可能原因、定位步骤和修复命令。',
          repoUrl.trim() ? `相关仓库：${repoUrl.trim()}` : '',
          `错误日志：\n${log}`,
        ].filter(Boolean).join('\n')
      );
      addNotification({ type: 'success', message: '错误诊断完成', duration: 3000 });
    } catch (error) {
      addNotification({
        type: 'error',
        message: getErrorMessage(error) || '智能体调用失败，请检查后端或 Agent 配置。',
        duration: 5000,
      });
    } finally {
      setIsDiagnosing(false);
    }
  };

  return (
    <div className="space-y-6 pb-20 md:pb-0">
      <h1 className="text-2xl font-bold">代码复现辅助</h1>

      <div className="sci-card-glow">
        <label className="block text-sm font-medium text-sci-ink mb-3">
          输入 GitHub 仓库地址
        </label>
        <div className="flex gap-3">
          <input
            type="text"
            value={repoUrl}
            onChange={(event) => setRepoUrl(event.target.value)}
            placeholder="https://github.com/username/repo"
            className="sci-input flex-1"
            onKeyDown={(event) => event.key === 'Enter' && handleAnalyze()}
          />
          <button
            onClick={handleAnalyze}
            disabled={isAnalyzing}
            className="sci-btn-primary"
          >
            {isAnalyzing ? (
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
      </div>

      {(isAnalyzing || isDiagnosing) && (
        <p className="text-sm text-sci-muted">智能体正在分析，请稍候……</p>
      )}

      {messages.length > 0 && (
        <div className="sci-card space-y-3">
          <h2 className="sci-section-title">对话记录</h2>
          {messages.map((message) => (
            <div
              key={message.id}
              className={`rounded-lg p-3 text-sm leading-relaxed whitespace-pre-wrap ${
                message.role === 'user'
                  ? 'bg-sci-primary/10 text-sci-ink'
                  : 'bg-sci-bg3 text-sci-muted'
              }`}
            >
              <p className="mb-1 text-xs font-medium opacity-70">
                {message.role === 'user' ? '你的问题' : '智能体回复'}
              </p>
              {message.content}
            </div>
          ))}
        </div>
      )}

      {reproduction && (
        <div className="space-y-6">
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
            <div className="sci-card">
              <h3 className="sci-section-title mb-3">文件结构</h3>
              <div className="bg-sci-bg3 rounded-lg p-2 overflow-auto max-h-96">
                <FileTree files={reproduction.file_tree} />
              </div>
            </div>

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
        </div>
      )}

      <div className="sci-card">
        <h3 className="sci-section-title mb-3 flex items-center gap-2">
          <AlertCircle size={16} className="text-sci-danger" />
          错误诊断
        </h3>
        <p className="text-sm text-sci-muted mb-3">遇到报错？粘贴错误日志获取修复建议</p>
        <div className="flex gap-3">
          <textarea
            value={errorLog}
            onChange={(event) => setErrorLog(event.target.value)}
            placeholder="粘贴错误日志..."
            rows={3}
            className="sci-input flex-1 font-mono text-sm resize-none"
          />
          <button
            onClick={handleDiagnose}
            disabled={isDiagnosing}
            className="sci-btn-primary self-end"
          >
            {isDiagnosing ? (
              <Loader2 size={16} className="animate-spin" />
            ) : (
              <Terminal size={16} />
            )}
            诊断
          </button>
        </div>
      </div>
    </div>
  );
}

export default CodeReproduce;
