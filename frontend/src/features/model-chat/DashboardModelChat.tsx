import { FormEvent, KeyboardEvent, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  AlertCircle,
  Bot,
  Check,
  ChevronDown,
  Database,
  Loader2,
  Maximize2,
  RefreshCw,
  Send,
  Sparkles,
  Trash2,
  X,
} from 'lucide-react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { isAxiosError } from 'axios';
import { conversationAPI, dashboardChatAPI } from '@/services/api';
import { getApiErrorMessage } from '@/services/errors';
import MessageFeedbackControls from '@/components/MessageFeedbackControls';
import { useAuthStore } from '@/store/authStore';
import type {
  AiRunSummary,
  DashboardChatStatus,
  KnowledgeCitation,
  MessageFeedback,
  ModelChatMessage,
} from '@/types';
import './model-chat.css';

interface ViewMessage extends ModelChatMessage {
  id: string;
  citations?: KnowledgeCitation[];
  knowledgeUnavailable?: boolean;
  persistenceUnavailable?: boolean;
  synthetic?: boolean;
  persisted?: boolean;
  run?: AiRunSummary | null;
  feedback?: MessageFeedback | null;
}

const QUICK_PROMPTS = [
  '帮我梳理一个可验证的研究问题',
  '如何设计可靠的消融实验？',
  '总结软件工程论文的复现要点',
];

const WELCOME_MESSAGE: ViewMessage = {
  id: 'welcome',
  role: 'assistant',
  content: '你好，我是 **SciPilot**。我已连接专用微调模型，可以和你一起拆解问题、设计实验，或结合论文知识库核查研究证据。',
  synthetic: true,
};

function createId() {
  return typeof crypto !== 'undefined' && 'randomUUID' in crypto
    ? crypto.randomUUID()
    : `${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function readStoredMessages(key: string): ViewMessage[] {
  try {
    const value = JSON.parse(localStorage.getItem(key) || '[]') as ViewMessage[];
    const valid = value.filter(
      (item) => item && ['user', 'assistant'].includes(item.role) && typeof item.content === 'string'
    );
    return valid.length ? valid.slice(-20) : [WELCOME_MESSAGE];
  } catch {
    return [WELCOME_MESSAGE];
  }
}

function DashboardModelChat() {
  const userId = useAuthStore((state) => state.user?.id || 'anonymous');
  const storageKey = `scipilot-dashboard-chat:${userId}`;
  const conversationStorageKey = `${storageKey}:conversation-id`;
  const [open, setOpen] = useState(() => localStorage.getItem('scipilot-dashboard-chat-open') !== 'false');
  const [messages, setMessages] = useState<ViewMessage[]>(() => readStoredMessages(storageKey));
  const [conversationId, setConversationId] = useState<string | null>(
    () => localStorage.getItem(conversationStorageKey)
  );
  const [status, setStatus] = useState<DashboardChatStatus | null>(null);
  const [input, setInput] = useState('');
  const [sending, setSending] = useState(false);
  const [clearing, setClearing] = useState(false);
  const [error, setError] = useState('');
  const [useKnowledgeBase, setUseKnowledgeBase] = useState(true);
  const logRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  const loadStatus = useCallback(async () => {
    try {
      const response = await dashboardChatAPI.getStatus();
      setStatus(response.data);
      if (response.data.knowledge_available === false) setUseKnowledgeBase(false);
    } catch {
      setStatus({ available: false, fine_tuned: false, reason: '无法读取模型状态' });
    }
  }, []);

  useEffect(() => {
    void loadStatus();
  }, [loadStatus]);

  useEffect(() => {
    setMessages(readStoredMessages(storageKey));
    setConversationId(localStorage.getItem(conversationStorageKey));
    setError('');
  }, [conversationStorageKey, storageKey]);

  useEffect(() => {
    if (!conversationId) return;
    let cancelled = false;
    const restoreConversation = async () => {
      try {
        const response = await conversationAPI.getConversation(conversationId);
        const restored = (response.data.messages || [])
          .filter(
            (item: { role?: string; content?: unknown }) =>
              ['user', 'assistant'].includes(item.role || '') &&
              typeof item.content === 'string'
          )
          .map((item: {
            id?: string;
            role: 'user' | 'assistant';
            content: string;
            citations?: KnowledgeCitation[];
            run?: AiRunSummary | null;
            feedback?: MessageFeedback | null;
          }) => ({
            id: item.id || createId(),
            role: item.role,
            content: item.content,
            citations: item.citations,
            persisted: true,
            run: item.run,
            feedback: item.feedback,
          }));
        if (!cancelled && restored.length) {
          setMessages([WELCOME_MESSAGE, ...restored].slice(-20));
        }
      } catch (restoreError) {
        if (isAxiosError(restoreError) && restoreError.response?.status === 404) {
          localStorage.removeItem(conversationStorageKey);
          if (!cancelled) setConversationId(null);
        }
      }
    };
    void restoreConversation();
    return () => {
      cancelled = true;
    };
  }, [conversationId, conversationStorageKey]);

  useEffect(() => {
    localStorage.setItem('scipilot-dashboard-chat-open', String(open));
    if (open) window.setTimeout(() => inputRef.current?.focus(), 160);
  }, [open]);

  useEffect(() => {
    localStorage.setItem(storageKey, JSON.stringify(messages.slice(-20)));
  }, [messages, storageKey]);

  useEffect(() => {
    if (conversationId) {
      localStorage.setItem(conversationStorageKey, conversationId);
    } else {
      localStorage.removeItem(conversationStorageKey);
    }
  }, [conversationId, conversationStorageKey]);

  useEffect(() => {
    const element = logRef.current;
    if (element) element.scrollTo({ top: element.scrollHeight, behavior: 'smooth' });
  }, [messages, sending, open]);

  useEffect(() => {
    const handleEscape = (event: globalThis.KeyboardEvent) => {
      if (event.key === 'Escape' && open) setOpen(false);
    };
    window.addEventListener('keydown', handleEscape);
    return () => window.removeEventListener('keydown', handleEscape);
  }, [open]);

  const requestHistory = useMemo(
    () => messages
      .filter((item) => !item.synthetic)
      .map(({ role, content }) => ({ role, content })),
    [messages]
  );

  const performRequest = async (history: ModelChatMessage[]) => {
    if (!history.length || history[history.length - 1].role !== 'user' || sending) return;
    setSending(true);
    setError('');
    try {
      const response = await dashboardChatAPI.send({
        messages: history.slice(-20),
        use_knowledge_base: useKnowledgeBase,
        conversation_id: conversationId,
      });
      if (response.data.conversation_id) {
        setConversationId(response.data.conversation_id);
      }
      const assistantMessage: ViewMessage = {
        id: response.data.message_id || createId(),
        role: 'assistant',
        content: response.data.reply,
        citations: response.data.citations,
        knowledgeUnavailable: response.data.knowledge_unavailable,
        persistenceUnavailable: response.data.persistence_unavailable,
        persisted: Boolean(response.data.message_id),
        run: response.data.run,
      };
      setMessages((current) => [
        ...current,
        assistantMessage,
      ].slice(-20));
    } catch (requestError) {
      setError(getApiErrorMessage(requestError, '模型暂时没有响应，请稍后重试。'));
    } finally {
      setSending(false);
    }
  };

  const sendMessage = (value: string) => {
    const content = value.trim();
    if (!content || sending || !status?.available) return;
    const userMessage: ViewMessage = { id: createId(), role: 'user', content };
    const history = [...requestHistory, { role: 'user' as const, content }].slice(-20);
    setMessages((current) => [...current, userMessage].slice(-20));
    setInput('');
    void performRequest(history);
  };

  const handleSubmit = (event: FormEvent) => {
    event.preventDefault();
    sendMessage(input);
  };

  const handleInputKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault();
      sendMessage(input);
    }
  };

  const clearConversation = async () => {
    if (sending || clearing) return;
    setClearing(true);
    try {
      if (conversationId) await conversationAPI.deleteConversation(conversationId);
      setConversationId(null);
      setMessages([WELCOME_MESSAGE]);
      setError('');
      setInput('');
    } catch (clearError) {
      setError(getApiErrorMessage(clearError, '清空对话失败，请稍后重试。'));
    } finally {
      setClearing(false);
    }
  };

  const retry = () => {
    const last = requestHistory[requestHistory.length - 1];
    if (last?.role === 'user') void performRequest(requestHistory);
  };

  if (!open) {
    return (
      <button
        type="button"
        className="model-chat-launcher"
        onClick={() => setOpen(true)}
        aria-label="打开 SciPilot 模型对话"
      >
        <span className="model-chat-launcher__pulse" />
        <Bot size={21} />
        <span>
          <strong>SciPilot AI</strong>
          <small>{status?.available ? '微调模型在线' : '检查模型连接'}</small>
        </span>
        <Maximize2 size={15} />
      </button>
    );
  }

  return (
    <aside className="model-chat" aria-label="SciPilot 模型对话">
      <div className="model-chat__ambient" aria-hidden="true" />
      <header className="model-chat__header">
        <div className="model-chat__identity">
          <span className="model-chat__avatar"><Sparkles size={18} /></span>
          <div>
            <div className="model-chat__title-row">
              <strong>SciPilot AI</strong>
              <span className={`model-chat__status-dot ${status?.available ? 'is-online' : ''}`} />
            </div>
            <small>
              {status?.available
                ? `${status.fine_tuned ? 'Fine-tuned' : 'Published'} · ${status.model || 'MaaS'}`
                : status?.reason || '正在检查模型服务…'}
            </small>
          </div>
        </div>
        <div className="model-chat__header-actions">
          <button type="button" onClick={() => void clearConversation()} disabled={sending || clearing} aria-label="清空对话" title="清空对话">
            <Trash2 size={15} />
          </button>
          <button type="button" onClick={() => setOpen(false)} aria-label="最小化对话" title="最小化">
            <ChevronDown size={17} />
          </button>
          <button type="button" onClick={() => setOpen(false)} className="model-chat__close" aria-label="关闭对话">
            <X size={15} />
          </button>
        </div>
      </header>

      <div className="model-chat__capability-bar">
        <span><Check size={12} /> 专用模型</span>
        <button
          type="button"
          className={useKnowledgeBase ? 'is-active' : ''}
          disabled={!status?.knowledge_available}
          onClick={() => setUseKnowledgeBase((value) => !value)}
          aria-pressed={useKnowledgeBase}
          title={status?.knowledge_available ? '切换论文知识增强' : '论文知识库正在构建'}
        >
          <Database size={12} />
          论文增强 {useKnowledgeBase ? 'ON' : 'OFF'}
        </button>
      </div>

      <div ref={logRef} className="model-chat__log" role="log" aria-live="polite" aria-relevant="additions">
        {messages.map((message) => (
          <article key={message.id} className={`model-chat__message is-${message.role}`}>
            <span className="model-chat__message-label">{message.role === 'assistant' ? 'SCIPILOT' : 'YOU'}</span>
            <div className="model-chat__bubble">
              {message.role === 'assistant' ? (
                <div className="model-chat__markdown">
                  <ReactMarkdown remarkPlugins={[remarkGfm]}>{message.content}</ReactMarkdown>
                </div>
              ) : <p>{message.content}</p>}
              {message.citations && message.citations.length > 0 && (
                <div className="model-chat__citations">
                  {message.citations.slice(0, 3).map((citation) => (
                    <span key={`${citation.document_id}-${citation.index}`} title={citation.excerpt}>
                      [{citation.index}] {citation.title}
                    </span>
                  ))}
                </div>
              )}
              {message.knowledgeUnavailable && (
                <div className="model-chat__degraded" role="status">
                  论文增强本轮不可用，已自动切换为纯模型回答
                </div>
              )}
              {message.persistenceUnavailable && (
                <div className="model-chat__degraded" role="status">
                  本轮回答未能保存到历史记录，请检查 Supabase 连接
                </div>
              )}
              {message.role === 'assistant' && message.run && (
                <div className="model-chat__degraded" role="status">
                  {message.run.status === 'degraded' ? '降级响应' : '模型响应'}
                  {' · '}{message.run.latency_ms} ms
                  {message.run.retrieval_count > 0
                    ? ` · ${message.run.retrieval_count} 条证据`
                    : ''}
                </div>
              )}
              {message.role === 'assistant' && message.persisted && !message.synthetic && (
                <MessageFeedbackControls
                  messageId={message.id}
                  initialFeedback={message.feedback}
                  compact
                />
              )}
            </div>
          </article>
        ))}

        {sending && (
          <article className="model-chat__message is-assistant">
            <span className="model-chat__message-label">SCIPILOT</span>
            <div className="model-chat__bubble model-chat__thinking">
              <i /><i /><i />
              <span>正在推理</span>
            </div>
          </article>
        )}
      </div>

      {messages.length === 1 && (
        <div className="model-chat__prompts" aria-label="快捷问题">
          {QUICK_PROMPTS.map((prompt) => (
            <button key={prompt} type="button" onClick={() => sendMessage(prompt)} disabled={!status?.available || sending}>
              {prompt}
            </button>
          ))}
        </div>
      )}

      {error && (
        <div className="model-chat__error" role="alert">
          <AlertCircle size={14} />
          <span>{error}</span>
          <button type="button" onClick={retry} disabled={sending}><RefreshCw size={12} /> 重试</button>
        </div>
      )}

      <form className="model-chat__composer" onSubmit={handleSubmit}>
        <textarea
          ref={inputRef}
          value={input}
          onChange={(event) => setInput(event.target.value)}
          onKeyDown={handleInputKeyDown}
          placeholder={status?.available ? '输入科研问题…' : '模型服务暂不可用'}
          rows={1}
          maxLength={20_000}
          disabled={!status?.available || sending}
          aria-label="对话输入"
        />
        <button type="submit" disabled={!input.trim() || !status?.available || sending} aria-label="发送消息">
          {sending ? <Loader2 size={17} className="animate-spin" /> : <Send size={17} />}
        </button>
        <small>Enter 发送 · Shift + Enter 换行</small>
      </form>
    </aside>
  );
}

export default DashboardModelChat;
