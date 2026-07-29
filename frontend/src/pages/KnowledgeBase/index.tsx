import { FormEvent, useCallback, useEffect, useRef, useState } from 'react';
import axios from 'axios';
import {
  AlertCircle,
  AlignLeft,
  BookOpen,
  CheckCircle2,
  Database,
  File,
  FileText,
  Folder,
  FolderPlus,
  Loader2,
  MessageSquareText,
  Search,
  Trash2,
  Upload,
} from 'lucide-react';
import { knowledgeAPI } from '@/services/api';
import { useUIStore } from '@/store/uiStore';
import type {
  KnowledgeBaseStatus,
  KnowledgeCitation,
  KnowledgeCollection,
  KnowledgeDocument,
  KnowledgeSearchHit,
} from '@/types';

const acceptedExtensions = ['pdf', 'txt', 'md'];

function errorMessage(error: unknown, fallback: string) {
  if (axios.isAxiosError(error)) {
    const detail = (error.response?.data as { detail?: string } | undefined)?.detail;
    return detail || fallback;
  }
  return fallback;
}

function formatBytes(bytes?: number | null) {
  if (!bytes) return '—';
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

function formatDate(value?: string) {
  if (!value) return '—';
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? '—' : date.toLocaleString('zh-CN');
}

function resultTitle(hit: KnowledgeSearchHit) {
  return hit.document_title || hit.title || hit.file_name || '未命名文档';
}

function KnowledgeBase() {
  const addNotification = useUIStore((state) => state.addNotification);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [status, setStatus] = useState<KnowledgeBaseStatus | null>(null);
  const [collections, setCollections] = useState<KnowledgeCollection[]>([]);
  const [documents, setDocuments] = useState<KnowledgeDocument[]>([]);
  const [selectedCollection, setSelectedCollection] = useState('');
  const [loadingWorkspace, setLoadingWorkspace] = useState(true);
  const [loadingDocuments, setLoadingDocuments] = useState(false);
  const [workspaceError, setWorkspaceError] = useState('');
  const [showCollectionForm, setShowCollectionForm] = useState(false);
  const [collectionName, setCollectionName] = useState('');
  const [collectionDescription, setCollectionDescription] = useState('');
  const [creatingCollection, setCreatingCollection] = useState(false);
  const [showTextForm, setShowTextForm] = useState(false);
  const [textTitle, setTextTitle] = useState('');
  const [textContent, setTextContent] = useState('');
  const [textSourceUrl, setTextSourceUrl] = useState('');
  const [savingText, setSavingText] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [uploadProgress, setUploadProgress] = useState(0);
  const [searchQuery, setSearchQuery] = useState('');
  const [searchMode, setSearchMode] = useState<'search' | 'answer'>('answer');
  const [searching, setSearching] = useState(false);
  const [searchResults, setSearchResults] = useState<KnowledgeSearchHit[]>([]);
  const [answer, setAnswer] = useState<string | null>(null);
  const [citations, setCitations] = useState<KnowledgeCitation[]>([]);
  const [searchMeta, setSearchMeta] = useState<{ total: number; retrieval?: string } | null>(null);
  const [searchError, setSearchError] = useState('');

  const loadStatusAndCollections = useCallback(async () => {
    setLoadingWorkspace(true);
    setWorkspaceError('');
    try {
      const statusResponse = await knowledgeAPI.getStatus();
      setStatus(statusResponse.data);
      if (!statusResponse.data.ready) {
        setCollections([]);
        setDocuments([]);
        return;
      }
      const collectionsResponse = await knowledgeAPI.getCollections();
      setCollections(collectionsResponse.data.items ?? []);
    } catch (error) {
      setWorkspaceError(errorMessage(error, '知识库状态加载失败，请稍后重试。'));
    } finally {
      setLoadingWorkspace(false);
    }
  }, []);

  const loadDocuments = useCallback(async () => {
    if (!status?.ready) return;
    setLoadingDocuments(true);
    setWorkspaceError('');
    try {
      const response = await knowledgeAPI.getDocuments({
        collection_id: selectedCollection || undefined,
        limit: 100,
      });
      setDocuments(response.data.items ?? []);
    } catch (error) {
      setWorkspaceError(errorMessage(error, '文档列表加载失败，请稍后重试。'));
    } finally {
      setLoadingDocuments(false);
    }
  }, [selectedCollection, status?.ready]);

  useEffect(() => {
    void loadStatusAndCollections();
  }, [loadStatusAndCollections]);

  useEffect(() => {
    void loadDocuments();
  }, [loadDocuments]);

  const refreshWorkspace = async () => {
    await loadStatusAndCollections();
    await loadDocuments();
  };

  const handleCreateCollection = async (event: FormEvent) => {
    event.preventDefault();
    const name = collectionName.trim();
    if (!name) return;
    setCreatingCollection(true);
    try {
      const response = await knowledgeAPI.createCollection({
        name,
        description: collectionDescription.trim() || undefined,
      });
      setCollections((current) => [response.data, ...current]);
      setSelectedCollection(response.data.id);
      setCollectionName('');
      setCollectionDescription('');
      setShowCollectionForm(false);
      addNotification({ type: 'success', message: '知识库集合已创建', duration: 3000 });
    } catch (error) {
      setWorkspaceError(errorMessage(error, '创建知识库集合失败。'));
    } finally {
      setCreatingCollection(false);
    }
  };

  const handleFile = async (file?: File) => {
    if (!file) return;
    const extension = file.name.split('.').pop()?.toLowerCase() || '';
    if (!acceptedExtensions.includes(extension)) {
      addNotification({
        type: 'warning',
        message: '仅支持 PDF、TXT 和 Markdown 文件',
        duration: 4000,
      });
      return;
    }
    setUploading(true);
    setUploadProgress(0);
    setWorkspaceError('');
    try {
      const response = await knowledgeAPI.upload(file, {
        collection_id: selectedCollection || undefined,
        onProgress: setUploadProgress,
      });
      addNotification({
        type: 'success',
        message: response.data.duplicate ? '该文档已存在，未重复导入' : '文档已切分并加入知识库',
        duration: 4000,
      });
      await refreshWorkspace();
    } catch (error) {
      setWorkspaceError(errorMessage(error, '文档上传或解析失败。'));
    } finally {
      setUploading(false);
      setUploadProgress(0);
      if (fileInputRef.current) fileInputRef.current.value = '';
    }
  };

  const handleAddText = async (event: FormEvent) => {
    event.preventDefault();
    const title = textTitle.trim();
    const content = textContent.trim();
    if (!title || !content) return;
    setSavingText(true);
    setWorkspaceError('');
    try {
      await knowledgeAPI.addText({
        title,
        content,
        collection_id: selectedCollection || undefined,
        source_url: textSourceUrl.trim() || undefined,
      });
      setTextTitle('');
      setTextContent('');
      setTextSourceUrl('');
      setShowTextForm(false);
      addNotification({ type: 'success', message: '文本已切分并加入知识库', duration: 4000 });
      await refreshWorkspace();
    } catch (error) {
      setWorkspaceError(errorMessage(error, '文本入库失败。'));
    } finally {
      setSavingText(false);
    }
  };

  const handleDeleteDocument = async (document: KnowledgeDocument) => {
    if (!window.confirm(`确定删除“${document.title}”及其知识片段吗？`)) return;
    try {
      await knowledgeAPI.deleteDocument(document.id);
      setDocuments((current) => current.filter((item) => item.id !== document.id));
      setSearchResults((current) =>
        current.filter((item) => item.document_id !== document.id)
      );
      addNotification({ type: 'success', message: '知识文档已删除', duration: 3000 });
      void loadStatusAndCollections();
    } catch (error) {
      setWorkspaceError(errorMessage(error, '删除知识文档失败。'));
    }
  };

  const handleSearch = async (event: FormEvent) => {
    event.preventDefault();
    const query = searchQuery.trim();
    if (!query) return;
    setSearching(true);
    setSearchError('');
    setAnswer(null);
    setCitations([]);
    try {
      if (searchMode === 'answer') {
        const response = await knowledgeAPI.answer({
          query,
          collection_id: selectedCollection || undefined,
          top_k: 10,
          include_answer: true,
        });
        setAnswer(response.data.answer);
        setCitations(response.data.citations ?? []);
        setSearchResults([]);
        setSearchMeta({ total: response.data.citations?.length ?? 0 });
      } else {
        const response = await knowledgeAPI.search({
          query,
          collection_id: selectedCollection || undefined,
          top_k: 10,
        });
        setSearchResults(response.data.items ?? []);
        setSearchMeta({
          total: response.data.total ?? response.data.items?.length ?? 0,
          retrieval: response.data.retrieval,
        });
      }
    } catch (error) {
      setSearchResults([]);
      setAnswer(null);
      setCitations([]);
      setSearchMeta(null);
      setSearchError(errorMessage(error, '知识库检索失败，请稍后重试。'));
    } finally {
      setSearching(false);
    }
  };

  const selectedCollectionName =
    collections.find((item) => item.id === selectedCollection)?.name || '全部集合';

  return (
    <div className="space-y-6 pb-20 md:pb-0">
      <div className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <div className="mb-2 flex items-center gap-2 text-sm text-sci-accent">
            <Database size={16} />
            <span>科研资料检索工作区</span>
          </div>
          <h1 className="text-2xl font-bold">知识库</h1>
          <p className="mt-2 max-w-2xl text-sm text-sci-muted">
            导入论文、笔记和 Markdown 文档，系统会提取文本、切分知识片段，并保留可追溯的来源引用。
          </p>
        </div>
        <div className="flex flex-wrap gap-3">
          <button
            type="button"
            onClick={() => setShowTextForm((value) => !value)}
            className="sci-btn-secondary"
            disabled={!status?.ready}
          >
            <AlignLeft size={16} />
            粘贴文本
          </button>
          <button
            type="button"
            onClick={() => setShowCollectionForm((value) => !value)}
            className="sci-btn-secondary"
            disabled={!status?.ready}
          >
            <FolderPlus size={16} />
            新建集合
          </button>
          <input
            ref={fileInputRef}
            type="file"
            accept=".pdf,.txt,.md,application/pdf,text/plain,text/markdown"
            className="hidden"
            onChange={(event) => void handleFile(event.target.files?.[0])}
          />
          <button
            type="button"
            onClick={() => fileInputRef.current?.click()}
            className="sci-btn-primary"
            disabled={!status?.ready || uploading}
          >
            {uploading ? <Loader2 size={16} className="animate-spin" /> : <Upload size={16} />}
            {uploading ? `上传处理中 ${uploadProgress}%` : '导入文档'}
          </button>
        </div>
      </div>

      {loadingWorkspace && (
        <div className="sci-card flex items-center gap-3 text-sm text-sci-muted">
          <Loader2 size={18} className="animate-spin text-sci-accent" />
          正在检查知识库服务...
        </div>
      )}

      {!loadingWorkspace && status && !status.ready && (
        <div className="rounded-xl border border-amber-500/30 bg-amber-500/10 p-5">
          <div className="flex items-start gap-3">
            <AlertCircle size={20} className="mt-0.5 flex-shrink-0 text-sci-warning" />
            <div>
              <h2 className="font-semibold text-sci-warning">知识库数据层尚未部署</h2>
              <p className="mt-1 text-sm text-sci-muted">
                前端和接口已经就绪。请先在 Supabase SQL Editor 执行
                {' '}<code className="text-sci-ink">{status.migration || '008_knowledge_base.sql'}</code>，
                再刷新本页。
              </p>
              <button
                type="button"
                onClick={() => void loadStatusAndCollections()}
                className="sci-btn-secondary mt-4"
              >
                重新检查
              </button>
            </div>
          </div>
        </div>
      )}

      {workspaceError && (
        <div className="flex items-start gap-3 rounded-xl border border-red-500/30 bg-red-500/10 p-4 text-sm">
          <AlertCircle size={18} className="mt-0.5 flex-shrink-0 text-sci-danger" />
          <span>{workspaceError}</span>
        </div>
      )}

      {status?.ready && (
        <>
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            {[
              { label: '知识集合', value: status.collections, icon: Folder },
              { label: '知识文档', value: status.documents, icon: FileText },
              { label: '可检索片段', value: status.chunks, icon: BookOpen },
              {
                label: '检索模式',
                value: status.retrieval === 'hybrid' ? '混合检索' : '全文检索',
                icon: Search,
              },
            ].map((item) => {
              const Icon = item.icon;
              return (
                <div key={item.label} className="sci-card flex items-center gap-4">
                  <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-sci-bg3">
                    <Icon size={18} className="text-sci-accent" />
                  </div>
                  <div>
                    <p className="text-xs text-sci-muted">{item.label}</p>
                    <p className="mt-1 text-lg font-semibold">{item.value}</p>
                  </div>
                </div>
              );
            })}
          </div>

          {showCollectionForm && (
            <form onSubmit={handleCreateCollection} className="sci-card space-y-4">
              <div>
                <h2 className="font-semibold">新建知识集合</h2>
                <p className="mt-1 text-sm text-sci-muted">可按课题、课程或项目划分资料范围。</p>
              </div>
              <div className="grid gap-3 md:grid-cols-2">
                <input
                  value={collectionName}
                  onChange={(event) => setCollectionName(event.target.value)}
                  className="sci-input"
                  placeholder="集合名称"
                  maxLength={120}
                  required
                />
                <input
                  value={collectionDescription}
                  onChange={(event) => setCollectionDescription(event.target.value)}
                  className="sci-input"
                  placeholder="用途说明（可选）"
                  maxLength={1000}
                />
              </div>
              <div className="flex justify-end gap-3">
                <button
                  type="button"
                  onClick={() => setShowCollectionForm(false)}
                  className="sci-btn-ghost"
                >
                  取消
                </button>
                <button
                  type="submit"
                  className="sci-btn-primary"
                  disabled={creatingCollection || !collectionName.trim()}
                >
                  {creatingCollection && <Loader2 size={16} className="animate-spin" />}
                  创建集合
                </button>
              </div>
            </form>
          )}

          {showTextForm && (
            <form onSubmit={handleAddText} className="sci-card space-y-4">
              <div>
                <h2 className="font-semibold">粘贴文本入库</h2>
                <p className="mt-1 text-sm text-sci-muted">
                  适合导入实验笔记、网页摘录或没有单独文件的研究资料。
                </p>
              </div>
              <div className="grid gap-3 md:grid-cols-2">
                <input
                  value={textTitle}
                  onChange={(event) => setTextTitle(event.target.value)}
                  className="sci-input"
                  placeholder="资料标题"
                  maxLength={500}
                  required
                />
                <input
                  value={textSourceUrl}
                  onChange={(event) => setTextSourceUrl(event.target.value)}
                  className="sci-input"
                  type="url"
                  placeholder="原始来源 URL（可选）"
                />
              </div>
              <textarea
                value={textContent}
                onChange={(event) => setTextContent(event.target.value)}
                className="sci-input min-h-48 w-full resize-y"
                placeholder="粘贴需要检索和问答的正文内容..."
                required
              />
              <div className="flex flex-col justify-between gap-3 text-xs text-sci-muted sm:flex-row sm:items-center">
                <span>
                  将保存到：{selectedCollectionName}
                  {!selectedCollection && '（未指定时自动使用“我的知识库”）'}
                </span>
                <div className="flex justify-end gap-3">
                  <button
                    type="button"
                    onClick={() => setShowTextForm(false)}
                    className="sci-btn-ghost"
                  >
                    取消
                  </button>
                  <button
                    type="submit"
                    className="sci-btn-primary"
                    disabled={savingText || !textTitle.trim() || !textContent.trim()}
                  >
                    {savingText && <Loader2 size={16} className="animate-spin" />}
                    保存并切分
                  </button>
                </div>
              </div>
            </form>
          )}

          <div className="grid gap-6 xl:grid-cols-[280px_minmax(0,1fr)]">
            <aside className="sci-card h-fit">
              <div className="mb-4 flex items-center justify-between">
                <h2 className="font-semibold">集合</h2>
                <span className="text-xs text-sci-muted">{collections.length} 个</span>
              </div>
              <div className="space-y-2">
                <button
                  type="button"
                  onClick={() => setSelectedCollection('')}
                  className={`w-full rounded-lg border px-3 py-3 text-left transition-colors ${
                    !selectedCollection
                      ? 'border-sci-primary/40 bg-sci-primary/10'
                      : 'border-transparent hover:bg-sci-bg3'
                  }`}
                >
                  <div className="flex items-center gap-2">
                    <BookOpen size={15} className="text-sci-accent" />
                    <span className="text-sm font-medium">全部集合</span>
                  </div>
                  <p className="mt-1 text-xs text-sci-muted">{status.documents} 篇文档</p>
                </button>
                {collections.map((collection) => (
                  <button
                    key={collection.id}
                    type="button"
                    onClick={() => setSelectedCollection(collection.id)}
                    className={`w-full rounded-lg border px-3 py-3 text-left transition-colors ${
                      selectedCollection === collection.id
                        ? 'border-sci-primary/40 bg-sci-primary/10'
                        : 'border-transparent hover:bg-sci-bg3'
                    }`}
                  >
                    <div className="flex items-center gap-2">
                      <Folder size={15} className="flex-shrink-0 text-sci-accent" />
                      <span className="truncate text-sm font-medium">{collection.name}</span>
                      {collection.is_public && <span className="sci-badge-info ml-auto">公开</span>}
                    </div>
                    <p className="mt-1 line-clamp-2 text-xs text-sci-muted">
                      {collection.description || `${collection.document_count ?? 0} 篇文档`}
                    </p>
                  </button>
                ))}
                {collections.length === 0 && (
                  <p className="py-6 text-center text-sm text-sci-muted">
                    上传第一份文档时会自动创建“我的知识库”。
                  </p>
                )}
              </div>
            </aside>

            <div className="min-w-0 space-y-6">
              <section className="sci-card">
                <div className="mb-4 flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
                  <div>
                    <h2 className="font-semibold">
                      {searchMode === 'answer' ? '基于知识库问答' : '检索知识片段'}
                    </h2>
                    <p className="mt-1 text-sm text-sci-muted">
                      当前范围：{selectedCollectionName}。回答和命中内容均保留可核查的来源引用。
                    </p>
                  </div>
                  <div className="inline-flex w-fit rounded-lg border border-sci-border bg-sci-bg3 p-1">
                    <button
                      type="button"
                      onClick={() => setSearchMode('answer')}
                      className={`flex items-center gap-2 rounded-md px-3 py-1.5 text-xs transition-colors ${
                        searchMode === 'answer'
                          ? 'bg-sci-primary text-white'
                          : 'text-sci-muted hover:text-sci-ink'
                      }`}
                    >
                      <MessageSquareText size={14} />
                      问答
                    </button>
                    <button
                      type="button"
                      onClick={() => setSearchMode('search')}
                      className={`flex items-center gap-2 rounded-md px-3 py-1.5 text-xs transition-colors ${
                        searchMode === 'search'
                          ? 'bg-sci-primary text-white'
                          : 'text-sci-muted hover:text-sci-ink'
                      }`}
                    >
                      <Search size={14} />
                      原文检索
                    </button>
                  </div>
                </div>
                <form onSubmit={handleSearch} className="flex flex-col gap-3 sm:flex-row">
                  <div className="relative flex-1">
                    <Search
                      size={17}
                      className="absolute left-3 top-1/2 -translate-y-1/2 text-sci-muted"
                    />
                    <input
                      value={searchQuery}
                      onChange={(event) => setSearchQuery(event.target.value)}
                      className="sci-input w-full pl-10"
                      placeholder={
                        searchMode === 'answer'
                          ? '例如：GraphCodeBERT 如何利用数据流？'
                          : '输入论文术语、方法名或关键结论...'
                      }
                      maxLength={2000}
                    />
                  </div>
                  <button
                    type="submit"
                    className="sci-btn-primary"
                    disabled={searching || !searchQuery.trim()}
                  >
                    {searching ? <Loader2 size={16} className="animate-spin" /> : <Search size={16} />}
                    {searchMode === 'answer' ? '生成回答' : '检索'}
                  </button>
                </form>

                {searchError && (
                  <p className="mt-4 rounded-lg bg-red-500/10 p-3 text-sm text-sci-danger">
                    {searchError}
                  </p>
                )}

                {searchMeta && (
                  <div className="mt-5 flex items-center gap-3 text-xs text-sci-muted">
                    <span>
                      {searchMode === 'answer' ? '引用' : '命中'} {searchMeta.total} 个知识片段
                    </span>
                    {searchMode === 'search' && (
                      <span className="sci-badge-info">
                        {searchMeta.retrieval === 'hybrid' ? '向量 + 全文' : '全文检索'}
                      </span>
                    )}
                  </div>
                )}

                {searchMode === 'answer' && answer && (
                  <div className="mt-4 rounded-xl border border-sci-primary/30 bg-sci-primary/5 p-5">
                    <div className="mb-3 flex items-center gap-2">
                      <MessageSquareText size={17} className="text-sci-accent" />
                      <h3 className="text-sm font-semibold">知识库回答</h3>
                    </div>
                    <p className="whitespace-pre-wrap text-sm leading-7 text-sci-ink/90">{answer}</p>
                  </div>
                )}

                {searchMode === 'answer' && citations.length > 0 && (
                  <div className="mt-4 space-y-3">
                    <h3 className="text-sm font-semibold">来源引用</h3>
                    {citations.map((citation) => (
                      <article
                        key={citation.chunk_id || `${citation.document_id}-${citation.index}`}
                        className="rounded-xl border border-sci-border bg-sci-bg3/40 p-4"
                      >
                        <div className="flex flex-wrap items-start justify-between gap-3">
                          <div className="flex min-w-0 items-start gap-3">
                            <span className="flex h-7 w-7 flex-shrink-0 items-center justify-center rounded-md bg-sci-primary/15 text-xs font-semibold text-sci-accent">
                              {citation.index}
                            </span>
                            <div className="min-w-0">
                              <h4 className="truncate text-sm font-semibold">{citation.title}</h4>
                              <p className="mt-1 text-xs text-sci-muted">
                                {citation.file_name || '知识库文档'}
                                {typeof citation.chunk_index === 'number'
                                  ? ` · 片段 ${citation.chunk_index + 1}`
                                  : ''}
                              </p>
                            </div>
                          </div>
                          {typeof citation.score === 'number' && (
                            <span className="sci-badge-success">
                              相关度 {(citation.score * 100).toFixed(0)}%
                            </span>
                          )}
                        </div>
                        <p className="mt-3 whitespace-pre-wrap text-sm leading-7 text-sci-ink/90">
                          {citation.excerpt}
                        </p>
                        {citation.source_url && (
                          <a
                            href={citation.source_url}
                            target="_blank"
                            rel="noreferrer"
                            className="mt-3 inline-block text-xs text-sci-accent hover:underline"
                          >
                            打开原始来源
                          </a>
                        )}
                      </article>
                    ))}
                  </div>
                )}

                {searchResults.length > 0 && (
                  <div className="mt-4 space-y-3">
                    {searchResults.map((hit, index) => (
                      <article
                        key={hit.chunk_id || `${hit.document_id}-${hit.chunk_index ?? index}`}
                        className="rounded-xl border border-sci-border bg-sci-bg3/40 p-4"
                      >
                        <div className="flex flex-wrap items-start justify-between gap-3">
                          <div className="flex min-w-0 items-start gap-3">
                            <span className="flex h-7 w-7 flex-shrink-0 items-center justify-center rounded-md bg-sci-primary/15 text-xs font-semibold text-sci-accent">
                              {index + 1}
                            </span>
                            <div className="min-w-0">
                              <h3 className="truncate text-sm font-semibold">{resultTitle(hit)}</h3>
                              <p className="mt-1 text-xs text-sci-muted">
                                来源：{hit.file_name || '知识库文档'}
                                {typeof hit.chunk_index === 'number'
                                  ? ` · 片段 ${hit.chunk_index + 1}`
                                  : ''}
                              </p>
                            </div>
                          </div>
                          {typeof hit.score === 'number' && (
                            <span className="sci-badge-success">
                              相关度 {(hit.score * 100).toFixed(0)}%
                            </span>
                          )}
                        </div>
                        <p className="mt-3 whitespace-pre-wrap text-sm leading-7 text-sci-ink/90">
                          {hit.content}
                        </p>
                        <div className="mt-3 flex items-center gap-3 text-xs text-sci-muted">
                          <span>引用 [{index + 1}]</span>
                          {hit.source_url && (
                            <a
                              href={hit.source_url}
                              target="_blank"
                              rel="noreferrer"
                              className="text-sci-accent hover:underline"
                            >
                              打开原始来源
                            </a>
                          )}
                        </div>
                      </article>
                    ))}
                  </div>
                )}

                {searchMeta &&
                  (searchMode === 'answer' ? citations.length === 0 : searchResults.length === 0) &&
                  !searching &&
                  !searchError && (
                  <div className="py-10 text-center text-sm text-sci-muted">
                    没有找到足以支撑结果的知识片段。可换用论文中的核心术语重试。
                  </div>
                )}
              </section>

              <section className="sci-card">
                <div className="mb-4 flex items-center justify-between gap-3">
                  <div>
                    <h2 className="font-semibold">文档</h2>
                    <p className="mt-1 text-sm text-sci-muted">
                      {selectedCollectionName} · {documents.length} 篇
                    </p>
                  </div>
                  {loadingDocuments && <Loader2 size={18} className="animate-spin text-sci-accent" />}
                </div>

                <div className="space-y-3">
                  {documents.map((document) => (
                    <div
                      key={document.id}
                      className="flex flex-col gap-4 rounded-xl border border-sci-border p-4 sm:flex-row sm:items-center"
                    >
                      <div className="flex h-10 w-10 flex-shrink-0 items-center justify-center rounded-lg bg-sci-bg3">
                        {document.source_type === 'pdf' ? (
                          <FileText size={18} className="text-sci-accent" />
                        ) : (
                          <File size={18} className="text-sci-accent" />
                        )}
                      </div>
                      <div className="min-w-0 flex-1">
                        <div className="flex flex-wrap items-center gap-2">
                          <h3 className="truncate text-sm font-semibold">{document.title}</h3>
                          <span
                            className={
                              document.status === 'ready'
                                ? 'sci-badge-success'
                                : document.status === 'failed'
                                  ? 'sci-badge-danger'
                                  : 'sci-badge-warning'
                            }
                          >
                            {document.status === 'ready'
                              ? '可检索'
                              : document.status === 'failed'
                                ? '处理失败'
                                : '处理中'}
                          </span>
                        </div>
                        <p className="mt-1 text-xs text-sci-muted">
                          {document.file_name || document.source_type.toUpperCase()} ·{' '}
                          {formatBytes(document.file_size)} · {document.chunk_count ?? 0} 个片段
                        </p>
                        <p className="mt-1 text-xs text-sci-muted">
                          更新于 {formatDate(document.updated_at)}
                        </p>
                      </div>
                      <button
                        type="button"
                        onClick={() => void handleDeleteDocument(document)}
                        className="sci-btn-ghost text-sci-muted hover:text-sci-danger"
                        title="删除文档"
                      >
                        <Trash2 size={15} />
                        删除
                      </button>
                    </div>
                  ))}
                </div>

                {!loadingDocuments && documents.length === 0 && (
                  <div className="py-12 text-center">
                    <CheckCircle2 size={42} className="mx-auto mb-3 text-sci-border" />
                    <p className="text-sm text-sci-muted">当前集合还没有文档</p>
                    <p className="mt-1 text-xs text-sci-muted">可导入 PDF、TXT 或 Markdown 文件。</p>
                  </div>
                )}
              </section>
            </div>
          </div>
        </>
      )}
    </div>
  );
}

export default KnowledgeBase;
