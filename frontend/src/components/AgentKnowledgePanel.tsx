import { FormEvent, useCallback, useEffect, useMemo, useState } from 'react';
import {
  AlertCircle,
  BookOpenCheck,
  Bot,
  CheckCircle2,
  ExternalLink,
  Loader2,
  RefreshCw,
  SearchX,
  Send,
  Sparkles,
} from 'lucide-react';
import { agentKnowledgeAPI } from '@/services/api';
import type {
  AgentCategory,
  AgentKnowledgeAnswerResponse,
  AgentKnowledgeCitation,
  PublicAgent,
} from '@/types';

interface AgentKnowledgePanelProps {
  category: AgentCategory;
  collectionId?: string;
  className?: string;
  compact?: boolean;
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
  'project-planning': '例如：请依据知识库给出基线、数据集和实验步骤建议。',
  'code-reproduction': '例如：复现这个方法需要哪些依赖、数据和排错步骤？',
  'result-interpretation': '例如：这个实验差异是否显著，应该怎样解释？',
};

function errorMessage(error: unknown, fallback: string) {
  if (
    typeof error === 'object' &&
    error !== null &&
    'response' in error
  ) {
    const response = (error as {
      response?: { data?: { detail?: string } };
    }).response;
    if (response?.data?.detail) return response.data.detail;
  }
  return error instanceof Error && error.message ? error.message : fallback;
}

function citationKey(citation: AgentKnowledgeCitation, index: number) {
  return citation.chunk_id || citation.document_id || `${citation.title}-${index}`;
}

export default function AgentKnowledgePanel({
  category,
  collectionId,
  className = '',
  compact = false,
}: AgentKnowledgePanelProps) {
  const [agent, setAgent] = useState<PublicAgent | null>(null);
  const [loadingAgent, setLoadingAgent] = useState(true);
  const [loadError, setLoadError] = useState('');
  const [question, setQuestion] = useState('');
  const [answer, setAnswer] = useState<AgentKnowledgeAnswerResponse | null>(null);
  const [asking, setAsking] = useState(false);
  const [askError, setAskError] = useState('');

  const label = CATEGORY_LABELS[category];

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
    } catch (error) {
      setLoadError(errorMessage(error, '智能体加载失败，请检查后端服务。'));
    } finally {
      setLoadingAgent(false);
    }
  }, [category, label]);

  useEffect(() => {
    void loadAgent();
  }, [loadAgent]);

  const citations = useMemo(() => answer?.citations ?? [], [answer]);

  const handleAsk = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const message = question.trim();
    if (!agent || !message || asking) return;

    setAsking(true);
    setAskError('');
    setAnswer(null);
    try {
      const response = await agentKnowledgeAPI.ask(agent.id, {
        message,
        collection_id: collectionId,
        top_k: 6,
      });
      setAnswer(response.data);
    } catch (error) {
      setAskError(errorMessage(error, '知识库问答失败，请稍后重试。'));
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
              <h2 className="font-semibold">知识库智能体</h2>
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
          <button
            type="button"
            onClick={() => void loadAgent()}
            className="sci-btn-secondary mt-3 text-xs"
          >
            <RefreshCw size={14} />
            重新加载
          </button>
        </div>
      )}

      {!loadingAgent && agent && (
        <>
          <form onSubmit={handleAsk} className="space-y-3">
            <textarea
              value={question}
              onChange={(event) => setQuestion(event.target.value)}
              placeholder={CATEGORY_PLACEHOLDERS[category]}
              rows={compact ? 3 : 4}
              maxLength={4000}
              className="sci-input w-full resize-y text-sm"
            />
            <div className="flex flex-wrap items-center justify-between gap-3">
              <p className="flex items-center gap-1.5 text-xs text-sci-muted">
                <BookOpenCheck size={13} className="text-sci-accent" />
                回答会检索已授权的知识库文档，并保留可核查引用
              </p>
              <button
                type="submit"
                disabled={asking || !question.trim()}
                className="sci-btn-primary"
              >
                {asking ? <Loader2 size={16} className="animate-spin" /> : <Send size={16} />}
                {asking ? '检索并生成…' : '询问智能体'}
              </button>
            </div>
          </form>

          {askError && (
            <div className="mt-4 flex items-start gap-2 rounded-xl border border-sci-danger/30 bg-sci-danger/5 p-4 text-sm text-sci-danger">
              <AlertCircle size={17} className="mt-0.5 flex-shrink-0" />
              <span>{askError}</span>
            </div>
          )}

          {!answer && !askError && !asking && (
            <div className="mt-4 flex items-center gap-3 rounded-xl border border-dashed border-sci-border px-4 py-4 text-sm text-sci-muted">
              <Sparkles size={17} className="flex-shrink-0 text-sci-accent" />
              输入问题后，这里会显示智能体回答、知识命中状态和原文引用。
            </div>
          )}

          {answer && (
            <div className="mt-5 space-y-4 animate-fade-in">
              <div className="flex flex-wrap items-center gap-2">
                <span
                  className={
                    answer.knowledge_used ? 'sci-badge-success' : 'sci-badge-warning'
                  }
                >
                  {answer.knowledge_used ? '已命中知识库' : '未命中知识库'}
                </span>
                <span className="text-xs text-sci-muted">
                  回答智能体：{answer.agent?.name || agent.name}
                </span>
                {answer.retrieval_id && (
                  <span className="text-xs text-sci-muted" title={answer.retrieval_id}>
                    检索记录 {answer.retrieval_id.slice(0, 8)}
                  </span>
                )}
              </div>

              <div className="rounded-xl border border-sci-primary/25 bg-sci-primary/5 p-4">
                <p className="whitespace-pre-wrap text-sm leading-7 text-sci-ink/90">
                  {answer.reply}
                </p>
              </div>

              {citations.length > 0 ? (
                <div className="space-y-3">
                  <h3 className="flex items-center gap-2 text-sm font-semibold">
                    <BookOpenCheck size={15} className="text-sci-accent" />
                    来源引用（{citations.length}）
                  </h3>
                  {citations.map((citation, index) => (
                    <article
                      key={citationKey(citation, index)}
                      className="rounded-xl border border-sci-border bg-sci-bg3/40 p-4"
                    >
                      <div className="flex flex-wrap items-start justify-between gap-2">
                        <div className="flex min-w-0 items-start gap-2">
                          <span className="flex h-6 w-6 flex-shrink-0 items-center justify-center rounded-md bg-sci-primary/15 text-xs font-semibold text-sci-accent">
                            {citation.index ?? index + 1}
                          </span>
                          <div className="min-w-0">
                            <h4 className="text-sm font-semibold">{citation.title}</h4>
                            {citation.file_name && (
                              <p className="mt-0.5 text-xs text-sci-muted">{citation.file_name}</p>
                            )}
                          </div>
                        </div>
                        {typeof citation.score === 'number' && (
                          <span className="sci-badge-info">
                            相关度 {(citation.score * 100).toFixed(0)}%
                          </span>
                        )}
                      </div>
                      <p className="mt-3 whitespace-pre-wrap text-sm leading-6 text-sci-muted">
                        {citation.excerpt || citation.content || '该引用未返回文本片段。'}
                      </p>
                      {citation.source_url && (
                        <a
                          href={citation.source_url}
                          target="_blank"
                          rel="noreferrer"
                          className="mt-3 inline-flex items-center gap-1 text-xs text-sci-accent hover:underline"
                        >
                          查看原始来源
                          <ExternalLink size={12} />
                        </a>
                      )}
                    </article>
                  ))}
                </div>
              ) : (
                <div className="flex items-center gap-2 rounded-xl border border-sci-border px-4 py-3 text-xs text-sci-muted">
                  <SearchX size={15} />
                  本次回答没有返回可展示的知识引用。
                </div>
              )}
            </div>
          )}
        </>
      )}
    </section>
  );
}
