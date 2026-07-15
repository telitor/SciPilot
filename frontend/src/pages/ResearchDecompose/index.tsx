import { useEffect, useState } from 'react';
import { Search, ChevronDown, ChevronRight, BookOpen, Database, ArrowRight, Loader2 } from 'lucide-react';
import { agentAPI, conversationAPI, getErrorMessage } from '@/services/api';
import { useUIStore } from '@/store/uiStore';
import type { ResearchNode, ResearchTree } from '@/types';

type AgentItem = {
  id: string;
  name?: string;
  category?: string;
};

type ChatMessage = {
  id: string;
  role: 'user' | 'assistant';
  content: string;
};

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
                  {node.datasets.map((dataset) => (
                    <span key={dataset} className="sci-badge-info text-[10px]">{dataset}</span>
                  ))}
                </div>
              </div>
              <div>
                <p className="text-xs text-sci-muted mb-1">相关论文</p>
                <div className="flex flex-wrap gap-1">
                  {node.papers.map((paper) => (
                    <span key={paper} className="sci-badge-purple text-[10px]">{paper}</span>
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

function normalizeResearchTree(value: unknown): ResearchTree | null {
  if (!value || typeof value !== 'object') return null;
  const data = value as Partial<ResearchTree>;
  if (typeof data.core_question !== 'string' || !Array.isArray(data.sub_questions)) {
    return null;
  }
  return {
    core_question: data.core_question,
    sub_questions: data.sub_questions,
  };
}

function ResearchDecompose() {
  const [direction, setDirection] = useState('');
  const [isAnalyzing, setIsAnalyzing] = useState(false);
  const [tree, setTree] = useState<ResearchTree | null>(null);
  const [agentId, setAgentId] = useState<string | null>(null);
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const { addNotification } = useUIStore();

  useEffect(() => {
    const loadAgent = async () => {
      try {
        const response = await agentAPI.getAgents();
        const agents = Array.isArray(response.data) ? response.data as AgentItem[] : [];
        const agent = agents.find((item) => item.category === 'problem-decomposition');
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

  const handleAnalyze = async () => {
    if (isAnalyzing) return;

    const userInput = direction.trim();
    if (!userInput) {
      addNotification({ type: 'warning', message: '请输入研究方向', duration: 3000 });
      return;
    }

    if (!agentId) {
      addNotification({
        type: 'warning',
        message: '未找到对应智能体，请检查 Supabase agents 表。',
        duration: 5000,
      });
      return;
    }

    const userMessage: ChatMessage = {
      id: `user-${Date.now()}`,
      role: 'user',
      content: userInput,
    };

    setMessages((prev) => [...prev, userMessage]);
    setIsAnalyzing(true);

    try {
      let currentConversationId = conversationId;
      if (!currentConversationId) {
        const conversationResponse = await conversationAPI.createConversation({
          agent_id: agentId,
          title: '问题拆解对话',
        });
        currentConversationId = String(conversationResponse.data.id);
        setConversationId(currentConversationId);
      }

      const response = await conversationAPI.chat({
        conversation_id: currentConversationId,
        agent_id: agentId,
        message: userInput,
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

      const parsedTree = normalizeResearchTree(extractJsonObject(reply));
      if (parsedTree) {
        setTree(parsedTree);
      }

      addNotification({ type: 'success', message: '问题拆解完成', duration: 3000 });
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

  return (
    <div className="space-y-6 pb-20 md:pb-0">
      <h1 className="text-2xl font-bold">研究问题拆解</h1>

      <div className="sci-card-glow">
        <label className="block text-sm font-medium text-sci-ink mb-3">
          输入你的研究方向
        </label>
        <div className="flex gap-3">
          <input
            type="text"
            value={direction}
            onChange={(event) => setDirection(event.target.value)}
            placeholder="例如：基于深度学习的代码克隆检测方法研究"
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
                开始拆解
              </>
            )}
          </button>
        </div>
      </div>

      {isAnalyzing && (
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

      {tree && (
        <div className="space-y-4">
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

          <div className="flex gap-3">
            <button className="sci-btn-primary">
              <BookOpen size={16} />
              跳转论文精读
            </button>
            <button className="sci-btn-secondary">
              <ArrowRight size={16} />
              生成实验方案
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

export default ResearchDecompose;
