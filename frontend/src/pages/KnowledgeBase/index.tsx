import { FormEvent, useCallback, useEffect, useMemo, useState } from 'react';
import axios from 'axios';
import {
  AlertCircle,
  BookOpenCheck,
  CheckCircle2,
  Database,
  FileText,
  Loader2,
  RefreshCw,
  Search,
  Send,
  Server,
  Sparkles,
} from 'lucide-react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { knowledgeAPI } from '@/services/api';
import type {
  KnowledgeAnswerResponse,
  KnowledgeBaseStatus,
  KnowledgeCitation,
  KnowledgeSearchResponse,
} from '@/types';

const QUICK_QUESTIONS = [
  '这些论文中，软件缺陷预测常用哪些评价指标？',
  '总结微服务架构研究中反复出现的主要挑战。',
  '有哪些研究讨论了机器学习系统的测试方法？',
];

function errorMessage(error: unknown, fallback: string) {
  if (axios.isAxiosError(error)) {
    const detail = (error.response?.data as { detail?: string } | undefined)?.detail;
    return detail || fallback;
  }
  return error instanceof Error ? error.message : fallback;
}

function statusLabel(status: string) {
  const labels: Record<string, string> = {
    uploaded: '已上传',
    texted: '已解析',
    spliting: '切分中',
    splited: '已切分',
    vectoring: '向量化中',
    vectored: '可检索',
    failed: '处理失败',
  };
  return labels[status] || status || '未知';
}

function CitationCard({ citation }: { citation: KnowledgeCitation }) {
  return (
    <article className="rounded-xl border border-sci-border bg-sci-bg3/45 p-4 transition-colors hover:border-sci-accent/35">
      <div className="flex items-start gap-3">
        <span className="flex h-7 min-w-7 items-center justify-center rounded-lg border border-sci-accent/30 bg-sci-accent/10 font-mono text-xs font-semibold text-sci-accent">
          {citation.index}
        </span>
        <div className="min-w-0 flex-1">
          <h3 className="truncate text-sm font-semibold text-sci-ink" title={citation.title}>
            {citation.title}
          </h3>
          <p className="mt-2 line-clamp-4 text-xs leading-6 text-sci-muted">
            {citation.excerpt || '星火知识库已返回该文档的匹配片段。'}
          </p>
          <div className="mt-3 flex flex-wrap gap-2 font-mono text-[10px] text-sci-muted">
            {typeof citation.score === 'number' && (
              <span>score {citation.score.toFixed(3)}</span>
            )}
            {typeof citation.rerank_score === 'number' && (
              <span>rank {citation.rerank_score.toFixed(3)}</span>
            )}
            {typeof citation.chunk_index === 'number' && (
              <span>chunk {citation.chunk_index}</span>
            )}
            {citation.file_name && <span className="truncate">{citation.file_name}</span>}
          </div>
        </div>
      </div>
    </article>
  );
}

function KnowledgeBase() {
  const [status, setStatus] = useState<KnowledgeBaseStatus | null>(null);
  const [loadingStatus, setLoadingStatus] = useState(true);
  const [statusError, setStatusError] = useState('');
  const [query, setQuery] = useState('');
  const [mode, setMode] = useState<'answer' | 'search'>('answer');
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState<KnowledgeAnswerResponse | KnowledgeSearchResponse | null>(null);
  const [queryError, setQueryError] = useState('');

  const loadStatus = useCallback(async () => {
    setLoadingStatus(true);
    setStatusError('');
    try {
      const response = await knowledgeAPI.getStatus();
      setStatus(response.data);
    } catch (error) {
      setStatusError(errorMessage(error, '无法读取星火知识库状态。'));
    } finally {
      setLoadingStatus(false);
    }
  }, []);

  useEffect(() => {
    void loadStatus();
  }, [loadStatus]);

  const citations = result?.citations ?? [];
  const answer = result && 'answer' in result ? result.answer : null;
  const readyRatio = useMemo(() => {
    if (!status?.document_count) return 0;
    return Math.round((status.vectored_count / status.document_count) * 100);
  }, [status]);

  const runQuery = async (event?: FormEvent) => {
    event?.preventDefault();
    const value = query.trim();
    if (!value || running || !status?.ready) return;
    setRunning(true);
    setQueryError('');
    setResult(null);
    try {
      const response = mode === 'answer'
        ? await knowledgeAPI.answer({ query: value, top_n: 6 })
        : await knowledgeAPI.search({ query: value, top_n: 8 });
      setResult(response.data);
    } catch (error) {
      setQueryError(errorMessage(error, '星火知识库请求失败，请稍后重试。'));
    } finally {
      setRunning(false);
    }
  };

  return (
    <div className="space-y-6 pb-20 md:pb-0">
      <header className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <div className="mb-2 flex items-center gap-2 font-mono text-[11px] uppercase tracking-[0.18em] text-sci-accent">
            <Database size={14} />
            external knowledge / spark chatdoc
          </div>
          <h1 className="text-3xl font-semibold tracking-tight text-sci-ink">星火论文知识库</h1>
          <p className="mt-2 max-w-2xl text-sm leading-6 text-sci-muted">
            论文原文保存在项目中，检索仅覆盖当前账号已同步的论文，向量数据由讯飞星火知识库托管。浏览器只连接 SciPilot 后端，不接触任何平台密钥。
          </p>
        </div>
        <button type="button" onClick={() => void loadStatus()} disabled={loadingStatus} className="sci-btn-secondary self-start">
          <RefreshCw size={15} className={loadingStatus ? 'animate-spin' : ''} />
          刷新状态
        </button>
      </header>

      {statusError && (
        <div className="flex items-start gap-3 rounded-xl border border-sci-danger/30 bg-sci-danger/5 p-4 text-sm text-sci-danger">
          <AlertCircle size={18} className="mt-0.5 shrink-0" />
          <span>{statusError}</span>
        </div>
      )}

      <section className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4" aria-label="知识库状态">
        {[
          {
            label: '服务提供方',
            value: status?.provider || '星火 ChatDoc',
            note: status?.configured ? '服务端鉴权已配置' : '等待服务端配置',
            icon: Server,
          },
          {
            label: '知识库',
            value: status?.repository_name || (loadingStatus ? '读取中…' : 'SciPilot Papers'),
            note: status?.ready ? '远端仓库连接正常' : status?.reason || '正在确认远端状态',
            icon: Database,
          },
          {
            label: '论文文档',
            value: loadingStatus ? '—' : String(status?.document_count ?? 0),
            note: '当前账号已同步论文',
            icon: FileText,
          },
          {
            label: '向量化进度',
            value: loadingStatus ? '—' : `${readyRatio}%`,
            note: `${status?.vectored_count ?? 0} / ${status?.document_count ?? 0} 篇可检索`,
            icon: BookOpenCheck,
          },
        ].map(({ label, value, note, icon: Icon }) => (
          <article key={label} className="sci-card-glow min-w-0">
            <div className="flex items-center justify-between">
              <span className="text-xs text-sci-muted">{label}</span>
              <Icon size={17} className="text-sci-accent" />
            </div>
            <strong className="mt-3 block truncate text-lg text-sci-ink" title={value}>{value}</strong>
            <p className="mt-1 truncate text-xs text-sci-muted" title={note}>{note}</p>
          </article>
        ))}
      </section>

      <section className="sci-card-glow p-0">
        <div className="border-b border-sci-border px-5 py-4 sm:px-6">
          <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            <div>
              <h2 className="flex items-center gap-2 font-semibold text-sci-ink">
                <Sparkles size={18} className="text-sci-accent" />
                论文知识查询
              </h2>
              <p className="mt-1 text-xs text-sci-muted">回答模式组织结论；检索模式只返回最相关的论文原文片段。</p>
            </div>
            <div className="flex rounded-lg border border-sci-border bg-sci-bg3 p-1" role="group" aria-label="查询模式">
              {(['answer', 'search'] as const).map((item) => (
                <button
                  key={item}
                  type="button"
                  onClick={() => setMode(item)}
                  className={`rounded-md px-3 py-1.5 text-xs font-medium transition-colors ${
                    mode === item ? 'bg-sci-primary text-white' : 'text-sci-muted hover:text-sci-ink'
                  }`}
                >
                  {item === 'answer' ? '知识问答' : '原文检索'}
                </button>
              ))}
            </div>
          </div>
        </div>

        <form onSubmit={runQuery} className="space-y-4 p-5 sm:p-6">
          <textarea
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            rows={4}
            maxLength={5000}
            placeholder="输入想从软件工程论文中核查的问题…"
            className="sci-input w-full resize-y text-sm leading-6"
          />
          <div className="flex flex-wrap gap-2">
            {QUICK_QUESTIONS.map((item) => (
              <button key={item} type="button" onClick={() => setQuery(item)} className="rounded-full border border-sci-border bg-sci-bg3/50 px-3 py-1.5 text-left text-[11px] text-sci-muted transition-colors hover:border-sci-accent/40 hover:text-sci-ink">
                {item}
              </button>
            ))}
          </div>
          <div className="flex flex-wrap items-center justify-between gap-3">
            <p className="flex items-center gap-2 text-xs text-sci-muted">
              {status?.ready ? <CheckCircle2 size={14} className="text-sci-success" /> : <AlertCircle size={14} className="text-sci-warning" />}
              {status?.ready ? '星火知识库在线，仅检索当前账号论文' : '当前账号还没有可检索的已向量化论文'}
            </p>
            <button type="submit" disabled={!query.trim() || running || !status?.ready} className="sci-btn-primary">
              {running ? <Loader2 size={16} className="animate-spin" /> : mode === 'answer' ? <Send size={16} /> : <Search size={16} />}
              {running ? '正在检索…' : mode === 'answer' ? '生成回答' : '检索原文'}
            </button>
          </div>
        </form>
      </section>

      {queryError && (
        <div className="flex items-start gap-3 rounded-xl border border-sci-danger/30 bg-sci-danger/5 p-4 text-sm text-sci-danger">
          <AlertCircle size={18} className="mt-0.5 shrink-0" />
          <span>{queryError}</span>
        </div>
      )}

      {result && (
        <section className="grid gap-6 xl:grid-cols-[minmax(0,1.15fr)_minmax(320px,0.85fr)]">
          <div className="sci-card-glow min-w-0">
            <h2 className="sci-section-title mb-4">{answer ? '知识库回答' : '检索概览'}</h2>
            {result.retrieval_queries && result.retrieval_queries.length > 0 && (
              <div className="mb-4 border-l-2 border-sci-accent pl-3 text-xs leading-5 text-sci-muted">
                <p>
                  {result.retrieval_queries.length} 路查询 · 候选 {result.candidate_count ?? citations.length} · 本地融合重排
                  {result.retrieval_degraded ? ' · 已降级为可用检索结果' : ''}
                </p>
                {result.retrieval_queries.length > 1 && (
                  <p className="mt-1 break-words">改写：{result.retrieval_queries.slice(1).join('；')}</p>
                )}
              </div>
            )}
            {answer ? (
              <div className="sci-markdown break-words text-sm">
                <ReactMarkdown remarkPlugins={[remarkGfm]}>{answer}</ReactMarkdown>
              </div>
            ) : (
              <div className="rounded-xl border border-dashed border-sci-border p-6 text-sm text-sci-muted">
                找到 {citations.length} 个相关论文片段。原文证据显示在右侧或下方。
              </div>
            )}
          </div>
          <div className="min-w-0">
            <h2 className="sci-section-title mb-4">来源证据 · {citations.length}</h2>
            <div className="space-y-3">
              {citations.length > 0 ? citations.map((citation) => (
                <CitationCard key={`${citation.document_id}-${citation.chunk_index}-${citation.index}`} citation={citation} />
              )) : (
                <div className="rounded-xl border border-dashed border-sci-border p-6 text-sm text-sci-muted">没有命中足够相关的论文片段。</div>
              )}
            </div>
          </div>
        </section>
      )}

      {status?.files && status.files.length > 0 && (
        <section>
          <div className="mb-4 flex items-center justify-between gap-3">
            <h2 className="sci-section-title">当前账号论文索引</h2>
            <span className="font-mono text-[11px] text-sci-muted">showing {Math.min(status.files.length, 12)}</span>
          </div>
          <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
            {status.files.slice(0, 12).map((file) => (
              <article key={file.file_id} className="sci-card min-w-0 p-4">
                <div className="flex items-start gap-3">
                  <FileText size={17} className="mt-0.5 shrink-0 text-sci-accent" />
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-sm font-medium text-sci-ink" title={file.file_name}>{file.file_name}</p>
                    <span className={`mt-2 inline-flex rounded-full border px-2 py-0.5 text-[10px] ${file.status === 'vectored' ? 'border-sci-success/30 bg-sci-success/10 text-sci-success' : 'border-sci-warning/30 bg-sci-warning/10 text-sci-warning'}`}>
                      {statusLabel(file.status)}
                    </span>
                  </div>
                </div>
              </article>
            ))}
          </div>
        </section>
      )}
    </div>
  );
}

export default KnowledgeBase;
