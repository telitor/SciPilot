import { FormEvent, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  AlertCircle,
  BookOpenCheck,
  Bot,
  CheckCircle2,
  Loader2,
  MessageSquarePlus,
  RefreshCw,
  Send,
  Sparkles,
  Trash2,
} from 'lucide-react';
import { agentKnowledgeAPI, conversationAPI } from '@/services/api';
import { getApiErrorMessage } from '@/services/errors';
import MessageFeedbackControls from '@/components/MessageFeedbackControls';
import { useAuthStore } from '@/store/authStore';
import { useSelectedProjectId } from '@/store/projectStore';
import type {
  AgentCategory,
  AgentKnowledgeCitation,
  AiRunSummary,
  Conversation,
  MessageFeedback,
  PublicAgent,
} from '@/types';

interface AgentKnowledgePanelProps {
  category: AgentCategory;
  className?: string;
  compact?: boolean;
}

interface PanelMessage {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  citations: AgentKnowledgeCitation[];
  run?: AiRunSummary | null;
  feedback?: MessageFeedback | null;
}

const CATEGORY_LABELS: Record<AgentCategory, string> = {
  'paper-reading': '论文精读',
  'problem-decomposition': '研究问题拆解',
  'project-planning': '实验项目规划',
  'code-reproduction': '代码复现',
  'result-interpretation': '结果解释',
};

const CATEGORY_PLACEHOLDERS: Record<AgentCategory, string> = {
  'paper-reading': '例如：结合知识库文献，解释这个方法的核心贡献与局限。',
  'problem-decomposition': '例如：这个研究方向可以拆成哪些可验证的子问题？',
  'project-planning': '例如：请给出基线、数据集和实验步骤建议。',
  'code-reproduction': '例如：复现这个方法需要哪些依赖、数据和排错步骤？',
  'result-interpretation': '例如：这个实验差异是否显著，应该怎样解释？',
};

function createLocalId() {
  return typeof crypto !== 'undefined' && 'randomUUID' in crypto
    ? crypto.randomUUID()
    : `${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function normalizeCitations(value: unknown): AgentKnowledgeCitation[] {
  return Array.isArray(value)
    ? value.filter((item): item is AgentKnowledgeCitation => Boolean(item && typeof item === 'object'))
    : [];
}

function normalizeMessages(value: unknown): PanelMessage[] {
  if (!Array.isArray(value)) return [];
  return value.flatMap((item) => {
    if (!item || typeof item !== 'object') return [];
    const message = item as Record<string, unknown>;
    const role = message.role;
    const content = typeof message.content === 'string' ? message.content.trim() : '';
    if ((role !== 'user' && role !== 'assistant') || !content) return [];
    return [{
      id: String(message.id || createLocalId()),
      role,
      content,
      citations: normalizeCitations(message.citations),
      run: message.run && typeof message.run === 'object'
        ? message.run as unknown as AiRunSummary
        : null,
      feedback: message.feedback && typeof message.feedback === 'object'
        ? message.feedback as unknown as MessageFeedback
        : null,
    }];
  });
}

export default function AgentKnowledgePanel({
  category,
  className = '',
  compact = false,
}: AgentKnowledgePanelProps) {
  const userId = useAuthStore((state) => state.user?.id || 'anonymous');
  const selectedProjectId = useSelectedProjectId();
  const storageKey = `scipilot-agent-chat:${userId}:${category}:${selectedProjectId || 'all'}`;
  const [agent, setAgent] = useState<PublicAgent | null>(null);
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [messages, setMessages] = useState<PanelMessage[]>([]);
  const [loadingAgent, setLoadingAgent] = useState(true);
  const [loadingConversation, setLoadingConversation] = useState(false);
  const [loadError, setLoadError] = useState('');
  const [question, setQuestion] = useState('');
  const [asking, setAsking] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [askError, setAskError] = useState('');
  const [knowledgeUsed, setKnowledgeUsed] = useState<boolean | null>(null);
  const skipRestoreConversationRef = useRef<string | null>(null);

  const label = CATEGORY_LABELS[category];

  const loadConversations = useCallback(async () => {
    const response = await conversationAPI.getConversations({
      module: category,
      project_id: selectedProjectId || undefined,
      limit: 50,
    });
    const items = Array.isArray(response.data.items) ? response.data.items : [];
    setConversations(items);
    const storedId = localStorage.getItem(storageKey);
    if (storedId && items.some((item: Conversation) => item.id === storedId)) {
      setConversationId(storedId);
    } else if (storedId) {
      localStorage.removeItem(storageKey);
    }
  }, [category, selectedProjectId, storageKey]);

  const loadAgent = useCallback(async () => {
    setLoadingAgent(true);
    setLoadError('');
    setAgent(null);
    try {
      const response = await agentKnowledgeAPI.getAgents();
      const matchedAgent = response.data.find(
        (candidate) => candidate.category === category && candidate.is_public !== false
      );
      if (!matchedAgent) {
        setLoadError(`尚未找到“${label}”类别的公开智能体。`);
        return;
      }
      setAgent(matchedAgent);
      await loadConversations();
    } catch (error: unknown) {
      setLoadError(getApiErrorMessage(error, '智能体加载失败，请检查后端服务。'));
    } finally {
      setLoadingAgent(false);
    }
  }, [category, label, loadConversations]);

  useEffect(() => {
    setConversationId(null);
    setMessages([]);
    setKnowledgeUsed(null);
    void loadAgent();
  }, [loadAgent]);

  useEffect(() => {
    if (!conversationId) {
      localStorage.removeItem(storageKey);
      setMessages([]);
      setKnowledgeUsed(null);
      return;
    }
    localStorage.setItem(storageKey, conversationId);
    if (skipRestoreConversationRef.current === conversationId) {
      skipRestoreConversationRef.current = null;
      setLoadingConversation(false);
      return;
    }
    let cancelled = false;
    setLoadingConversation(true);
    setAskError('');
    conversationAPI
      .getConversation(conversationId)
      .then((response) => {
        if (!cancelled) setMessages(normalizeMessages(response.data.messages));
      })
      .catch((error: unknown) => {
        if (cancelled) return;
        setConversationId(null);
        setAskError(getApiErrorMessage(error, '历史会话加载失败，请重新选择。'));
      })
      .finally(() => {
        if (!cancelled) setLoadingConversation(false);
      });
    return () => {
      cancelled = true;
    };
  }, [conversationId, storageKey]);

  const latestAssistant = useMemo(
    () => [...messages].reverse().find((message) => message.role === 'assistant'),
    [messages]
  );

  const startNewConversation = () => {
    if (asking || deleting) return;
    setConversationId(null);
    setMessages([]);
    setQuestion('');
    setAskError('');
    setKnowledgeUsed(null);
  };

  const deleteCurrentConversation = async () => {
    if (!conversationId || asking || deleting) return;
    if (!window.confirm('确定删除当前会话及全部消息吗？此操作无法撤销。')) return;
    setDeleting(true);
    setAskError('');
    try {
      await conversationAPI.deleteConversation(conversationId);
      setConversations((current) => current.filter((item) => item.id !== conversationId));
      setConversationId(null);
      setMessages([]);
      setQuestion('');
      setKnowledgeUsed(null);
    } catch (error: unknown) {
      setAskError(getApiErrorMessage(error, '删除会话失败，请稍后重试。'));
    } finally {
      setDeleting(false);
    }
  };

  const handleAsk = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const content = question.trim();
    if (!agent || !content || asking) return;

    const optimisticUser: PanelMessage = {
      id: createLocalId(),
      role: 'user',
      content,
      citations: [],
    };
    setMessages((current) => [...current, optimisticUser]);
    setQuestion('');
    setAsking(true);
    setAskError('');
    try {
      let activeConversationId = conversationId;
      if (!activeConversationId) {
        const created = await conversationAPI.createConversation({
          agent_id: agent.id,
          module: category,
          title: content.slice(0, 60),
          project_id: selectedProjectId,
        });
        activeConversationId = String(created.data.id);
        skipRestoreConversationRef.current = activeConversationId;
        setConversationId(activeConversationId);
        setConversations((current) => [created.data, ...current]);
      }
      const response = await conversationAPI.chat({
        conversation_id: activeConversationId,
        agent_id: agent.id,
        message: content,
      });
      const reply = String(response.data.reply || '').trim();
      if (!reply) throw new Error('智能体没有返回有效回答。');
      setMessages((current) => [
        ...current,
        {
          id: String(response.data.message?.id || createLocalId()),
          role: 'assistant',
          content: reply,
          citations: normalizeCitations(response.data.citations),
          run: response.data.run || null,
          feedback: null,
        },
      ]);
      setKnowledgeUsed(Boolean(response.data.knowledge_used));
      void loadConversations();
    } catch (error: unknown) {
      setAskError(getApiErrorMessage(error, '智能体调用失败，请检查后端或 Agent 配置。'));
    } finally {
      setAsking(false);
    }
  };

  return (
    <section className={`sci-card-glow overflow-hidden ${className}`}>
      <div className={`flex flex-wrap items-start justify-between gap-3 ${compact ? 'mb-3' : 'mb-5'}`}>
        <div className="flex min-w-0 items-start gap-3">
          <div className="flex h-10 w-10 flex-shrink-0 items-center justify-center rounded-xl bg-sci-primary/15">
            <Bot size={20} className="text-sci-accent" />
          </div>
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <h2 className="font-semibold">智能体对话</h2>
              <span className="sci-badge-purple">{label}</span>
            </div>
            <p className="mt-1 text-xs text-sci-muted">
              {agent
                ? `${agent.name}${agent.description ? ` · ${agent.description}` : ''}`
                : '正在匹配当前模块的智能体…'}
            </p>
          </div>
        </div>
        {agent && (
          <span className="sci-badge-success flex items-center gap-1">
            <CheckCircle2 size={11} />
            已连接
          </span>
        )}
      </div>

      {loadingAgent && (
        <div className="flex items-center justify-center gap-2 rounded-xl border border-sci-border bg-sci-bg3/40 px-4 py-8 text-sm text-sci-muted">
          <Loader2 size={17} className="animate-spin text-sci-accent" />
          正在加载智能体…
        </div>
      )}

      {!loadingAgent && loadError && (
        <div className="rounded-xl border border-sci-danger/30 bg-sci-danger/5 p-4">
          <div className="flex items-start gap-2 text-sm text-sci-danger">
            <AlertCircle size={17} className="mt-0.5 flex-shrink-0" />
            <span>{loadError}</span>
          </div>
          <button type="button" onClick={() => void loadAgent()} className="sci-btn-secondary mt-3 text-xs">
            <RefreshCw size={14} />
            重新加载
          </button>
        </div>
      )}

      {!loadingAgent && agent && (
        <>
          <div className="mb-4 flex flex-wrap items-center gap-2 rounded-lg border border-sci-border bg-sci-bg3/40 p-2">
            <select
              value={conversationId || ''}
              onChange={(event) => setConversationId(event.target.value || null)}
              disabled={asking || deleting}
              className="sci-input min-w-0 flex-1 text-sm"
              aria-label="选择历史会话"
            >
              <option value="">新对话</option>
              {conversations.map((conversation) => (
                <option key={conversation.id} value={conversation.id}>
                  {conversation.title || '未命名会话'}
                </option>
              ))}
            </select>
            <button
              type="button"
              onClick={startNewConversation}
              disabled={asking || deleting}
              className="sci-btn-secondary px-3"
              title="新建会话"
            >
              <MessageSquarePlus size={15} />
              新建
            </button>
            <button
              type="button"
              onClick={() => void deleteCurrentConversation()}
              disabled={!conversationId || asking || deleting}
              className="sci-btn-secondary px-3 text-sci-danger"
              title="删除当前会话"
            >
              {deleting ? <Loader2 size={15} className="animate-spin" /> : <Trash2 size={15} />}
              删除
            </button>
          </div>

          <div className="mb-4 max-h-[28rem] space-y-3 overflow-y-auto rounded-xl border border-sci-border p-3">
            {loadingConversation && (
              <div className="flex items-center justify-center gap-2 py-6 text-sm text-sci-muted">
                <Loader2 size={16} className="animate-spin" />
                正在恢复历史消息…
              </div>
            )}
            {!loadingConversation && messages.length === 0 && (
              <div className="flex items-center gap-3 py-3 text-sm text-sci-muted">
                <Sparkles size={17} className="flex-shrink-0 text-sci-accent" />
                输入问题开始新对话，消息将自动保存并可在这里恢复。
              </div>
            )}
            {!loadingConversation && messages.map((message) => (
              <article
                key={message.id}
                className={`rounded-xl border p-4 ${
                  message.role === 'assistant'
                    ? 'border-sci-primary/25 bg-sci-primary/5'
                    : 'border-sci-border bg-sci-bg3/50'
                }`}
              >
                <p className="mb-2 text-xs font-medium text-sci-muted">
                  {message.role === 'assistant' ? agent.name : '你'}
                </p>
                <p className="whitespace-pre-wrap text-sm leading-7 text-sci-ink/90">
                  {message.content}
                </p>
                {message.citations.length > 0 && (
                  <div className="mt-3 space-y-2 border-t border-sci-border pt-3">
                    <p className="flex items-center gap-1.5 text-xs font-medium text-sci-muted">
                      <BookOpenCheck size={13} className="text-sci-accent" />
                      来源引用（{message.citations.length}）
                    </p>
                    {message.citations.slice(0, 4).map((citation, index) => (
                      <div key={citation.chunk_id || citation.document_id || `${message.id}-${index}`} className="text-xs text-sci-muted">
                        [{citation.index ?? index + 1}] {citation.title}：
                        {citation.excerpt || citation.content || '未返回文本片段'}
                      </div>
                    ))}
                  </div>
                )}
                {message.role === 'assistant' && message.run && (
                  <p className="mt-2 text-xs text-sci-muted">
                    {message.run.status === 'degraded' ? '降级响应' : '模型响应'}
                    {' · '}{message.run.latency_ms} ms
                    {message.run.retrieval_count > 0
                      ? ` · ${message.run.retrieval_count} 条证据`
                      : ''}
                  </p>
                )}
                {message.role === 'assistant' && (
                  <MessageFeedbackControls
                    messageId={message.id}
                    initialFeedback={message.feedback}
                  />
                )}
              </article>
            ))}
            {asking && (
              <div className="flex items-center gap-2 px-2 py-3 text-sm text-sci-muted">
                <Loader2 size={16} className="animate-spin text-sci-accent" />
                智能体正在分析，请稍候…
              </div>
            )}
          </div>

          {knowledgeUsed !== null && latestAssistant && (
            <div className="mb-3 flex items-center gap-2">
              <span className={knowledgeUsed ? 'sci-badge-success' : 'sci-badge-warning'}>
                {knowledgeUsed ? '已命中知识库' : '本轮未命中知识库'}
              </span>
              <span className="text-xs text-sci-muted">回答已保存到当前会话</span>
            </div>
          )}

          {askError && (
            <div className="mb-4 flex items-start gap-2 rounded-xl border border-sci-danger/30 bg-sci-danger/5 p-4 text-sm text-sci-danger">
              <AlertCircle size={17} className="mt-0.5 flex-shrink-0" />
              <span>{askError}</span>
            </div>
          )}

          <form onSubmit={handleAsk} className="space-y-3">
            <textarea
              value={question}
              onChange={(event) => setQuestion(event.target.value)}
              placeholder={CATEGORY_PLACEHOLDERS[category]}
              rows={compact ? 3 : 4}
              maxLength={4000}
              disabled={asking || loadingConversation}
              className="sci-input w-full resize-y text-sm"
            />
            <div className="flex flex-wrap items-center justify-between gap-3">
              <p className="flex items-center gap-1.5 text-xs text-sci-muted">
                <BookOpenCheck size={13} className="text-sci-accent" />
                当前会话会保留上下文、回答和可核查引用
              </p>
              <button
                type="submit"
                disabled={asking || loadingConversation || !question.trim()}
                className="sci-btn-primary"
              >
                {asking ? <Loader2 size={16} className="animate-spin" /> : <Send size={16} />}
                {asking ? '智能体分析中…' : '发送问题'}
              </button>
            </div>
          </form>
        </>
      )}
    </section>
  );
}
