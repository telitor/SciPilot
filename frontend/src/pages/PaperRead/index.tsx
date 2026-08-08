import { useState, useRef, useCallback, useEffect } from 'react';
import { isAxiosError } from 'axios';
import { useNavigate } from 'react-router-dom';
import {
  Upload,
  Send,
  FileText,
  BookOpen,
  Quote,
  Loader2,
  X,
  RefreshCw,
  MessageSquarePlus,
  Trash2,
  ArrowRight,
} from 'lucide-react';
import AgentKnowledgePanel from '@/components/AgentKnowledgePanel';
import ProjectContextBar from '@/components/ProjectContextBar';
import { usePaperStore } from '@/store/paperStore';
import { useAuthStore } from '@/store/authStore';
import { useSelectedProjectId } from '@/store/projectStore';
import { useUIStore } from '@/store/uiStore';
import {
  agentKnowledgeAPI,
  conversationAPI,
  paperAPI,
  researchJobAPI,
} from '@/services/api';
import { getApiErrorMessage } from '@/services/errors';
import type {
  Citation,
  Conversation,
  PaperKnowledgeSync,
  PaperKnowledgeSyncStatus,
} from '@/types';

interface ChatMessage {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  citations?: Citation[];
}

const PAPER_READY_MESSAGE = '论文已解析完成，你可以询问研究背景、核心方法、实验结果、创新点和不足。';

function isTimeoutError(error: unknown) {
  return isAxiosError(error) && (
    error.code === 'ECONNABORTED' || error.message.toLowerCase().includes('timeout')
  );
}

function normalizeChatCitations(value: unknown): Citation[] {
  if (!Array.isArray(value)) return [];
  return value.flatMap((item) => {
    if (!item || typeof item !== 'object') return [];
    const citation = item as Record<string, unknown>;
    const text = String(citation.excerpt || citation.content || '').trim();
    if (!text) return [];
    return [{
      source: String(citation.title || citation.file_name || citation.document_id || '当前论文'),
      text,
    }];
  });
}

function normalizeConversationMessages(value: unknown): ChatMessage[] {
  if (!Array.isArray(value)) return [];
  return value.flatMap((item) => {
    if (!item || typeof item !== 'object') return [];
    const message = item as Record<string, unknown>;
    const role = message.role;
    const content = typeof message.content === 'string' ? message.content.trim() : '';
    if ((role !== 'user' && role !== 'assistant') || !content) return [];
    return [{
      id: String(message.id || `${Date.now()}-${Math.random()}`),
      role,
      content,
      citations: normalizeChatCitations(message.citations),
    }];
  });
}

function knowledgeSyncLabel(status: PaperKnowledgeSyncStatus) {
  const labels: Record<PaperKnowledgeSyncStatus, string> = {
    not_configured: '知识库未配置',
    unavailable: '知识库待迁移',
    not_started: '等待知识库同步',
    pending: '正在提交知识库',
    uploaded: '等待向量化',
    processing: '正在向量化',
    vectored: '知识库已就绪',
    failed: '知识库同步失败',
  };
  return labels[status];
}

// Simple Markdown renderer component
function MarkdownContent({ content }: { content: string }) {
  return (
    <div className="sci-markdown">
      {content.split('\n').map((line, i) => {
        if (line.startsWith('# ')) return <h1 key={i}>{line.slice(2)}</h1>;
        if (line.startsWith('## ')) return <h2 key={i}>{line.slice(3)}</h2>;
        if (line.startsWith('### ')) return <h3 key={i}>{line.slice(4)}</h3>;
        if (line.startsWith('- ')) return <ul key={i}><li>{line.slice(2)}</li></ul>;
        if (line.startsWith('> ')) return <blockquote key={i}>{line.slice(2)}</blockquote>;
        if (line.match(/^\d+\. /)) return <ol key={i}><li>{line.replace(/^\d+\. /, '')}</li></ol>;
        if (line.trim() === '') return <div key={i} className="h-2" />;
        return <p key={i}>{line}</p>;
      })}
    </div>
  );
}

function CitationCard({ citation, onClose }: { citation: Citation; onClose: () => void }) {
  return (
    <div className="fixed z-50 bg-sci-bg2 border border-sci-accent/30 rounded-xl p-4 shadow-xl max-w-sm animate-fade-in" style={{ bottom: '20px', right: '20px' }}>
      <div className="flex items-center justify-between mb-2">
        <span className="text-xs text-sci-accent font-medium">引用来源</span>
        <button onClick={onClose} className="text-sci-muted hover:text-sci-ink"><X size={14} /></button>
      </div>
      <p className="text-sm text-sci-muted">{citation.source}</p>
      <p className="text-sm text-sci-ink mt-2">{citation.text}</p>
      {citation.page && <p className="text-xs text-sci-muted mt-2">第 {citation.page} 页</p>}
    </div>
  );
}

function PaperRead() {
  const navigate = useNavigate();
  const selectedProjectId = useSelectedProjectId();
  const userId = useAuthStore((state) => state.user?.id || 'anonymous');
  const paperStorageKey = `scipilot-paper-read:${userId}${selectedProjectId ? `:${selectedProjectId}` : ''}:paper-id`;
  const paperJobStorageKey = `scipilot-paper-read:${userId}${selectedProjectId ? `:${selectedProjectId}` : ''}:paper-analysis-job-id`;
  const { currentPaper, currentReport, setCurrentPaper, setCurrentReport, uploadProgress, setUploadProgress } = usePaperStore();
  const { addNotification } = useUIStore();

  const [input, setInput] = useState('');
  const [chatMessages, setChatMessages] = useState<ChatMessage[]>([]);
  const [isSending, setIsSending] = useState(false);
  const [paperAgentId, setPaperAgentId] = useState<string | null>(null);
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [paperConversations, setPaperConversations] = useState<Conversation[]>([]);
  const [isLoadingConversation, setIsLoadingConversation] = useState(false);
  const [isDeletingConversation, setIsDeletingConversation] = useState(false);
  const [isRestoringPaper, setIsRestoringPaper] = useState(
    () => Boolean(localStorage.getItem(paperStorageKey))
  );
  const [knowledgeSync, setKnowledgeSync] = useState<PaperKnowledgeSync | null>(null);
  const [isRetryingKnowledge, setIsRetryingKnowledge] = useState(false);
  const [knowledgeRefreshKey, setKnowledgeRefreshKey] = useState(0);
  const [activeSection, setActiveSection] = useState(0);
  const [showCitation, setShowCitation] = useState<Citation | null>(null);
  const [activeJobId, setActiveJobId] = useState<string | null>(
    () => localStorage.getItem(paperJobStorageKey)
  );
  const [jobProgress, setJobProgress] = useState(0);
  const [jobError, setJobError] = useState<string | null>(null);
  const [jobPollKey, setJobPollKey] = useState(0);
  const [isRetryingAnalysis, setIsRetryingAnalysis] = useState(false);
  const [isUploading, setIsUploading] = useState(
    () => Boolean(localStorage.getItem(paperJobStorageKey))
  );
  const fileInputRef = useRef<HTMLInputElement>(null);
  const chatEndRef = useRef<HTMLDivElement>(null);
  const skipRestoreConversationRef = useRef<string | null>(null);
  const activePaperStorageKeyRef = useRef(paperStorageKey);

  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [chatMessages]);

  useEffect(() => {
    let cancelled = false;
    agentKnowledgeAPI
      .getAgents()
      .then((response) => {
        if (cancelled) return;
        const agent = response.data.find(
          (item) => item.category === 'paper-reading' || item.name === '论文精读助手'
        );
        if (agent) {
          setPaperAgentId(agent.id);
          return;
        }
        addNotification({
          type: 'error',
          message: '没有找到论文精读助手，请检查后端 /agents 或 Supabase agents 表',
          duration: 5000,
        });
      })
      .catch((error: unknown) => {
        if (cancelled) return;
        addNotification({
          type: 'error',
          message: getApiErrorMessage(error, '论文精读助手加载失败，请稍后重试'),
          duration: 5000,
        });
      });
    return () => {
      cancelled = true;
    };
  }, [addNotification]);

  useEffect(() => {
    if (activePaperStorageKeyRef.current !== paperStorageKey) {
      activePaperStorageKeyRef.current = paperStorageKey;
      setCurrentPaper(null);
      setCurrentReport(null);
      setConversationId(null);
      setPaperConversations([]);
      setChatMessages([]);
      setKnowledgeSync(null);
      setInput('');
      setActiveSection(0);
      const storedJobId = localStorage.getItem(paperJobStorageKey);
      setActiveJobId(storedJobId);
      setJobProgress(0);
      setJobError(null);
      setIsUploading(Boolean(storedJobId));
      setIsRestoringPaper(Boolean(localStorage.getItem(paperStorageKey)));
      return;
    }
    if (currentPaper) {
      localStorage.setItem(paperStorageKey, currentPaper.id);
      setIsRestoringPaper(false);
      return;
    }
    const storedPaperId = localStorage.getItem(paperStorageKey);
    if (!storedPaperId) {
      setIsRestoringPaper(false);
      return;
    }
    let cancelled = false;
    setIsRestoringPaper(true);
    Promise.all([
      paperAPI.getPaper(storedPaperId),
      paperAPI.getDeepRead(storedPaperId),
    ])
      .then(([paperResponse, reportResponse]) => {
        if (cancelled) return;
        setCurrentPaper(paperResponse.data);
        setCurrentReport(reportResponse.data);
      })
      .catch(() => {
        localStorage.removeItem(paperStorageKey);
      })
      .finally(() => {
        if (!cancelled) setIsRestoringPaper(false);
      });
    return () => {
      cancelled = true;
    };
  }, [currentPaper, paperJobStorageKey, paperStorageKey, setCurrentPaper, setCurrentReport]);

  useEffect(() => {
    if (!activeJobId) return;
    let cancelled = false;
    let pollTimer: ReturnType<typeof setTimeout> | undefined;
    let pollErrorShown = false;

    const pollJob = async () => {
      try {
        const response = await researchJobAPI.get(activeJobId);
        if (cancelled) return;
        const job = response.data;
        setJobProgress(Number.isFinite(job.progress) ? job.progress : 0);

        if (job.status === 'succeeded') {
          const resultPaperId = typeof job.result?.paper_id === 'string'
            ? job.result.paper_id
            : job.paper_id;
          if (!resultPaperId) throw new Error('论文分析任务没有返回论文编号');
          const [paperResponse, reportResponse] = await Promise.all([
            paperAPI.getPaper(resultPaperId),
            paperAPI.getDeepRead(resultPaperId),
          ]);
          if (cancelled) return;
          setCurrentPaper(paperResponse.data);
          setCurrentReport(reportResponse.data);
          setKnowledgeSync(
            job.result?.knowledge_sync && typeof job.result.knowledge_sync === 'object'
              ? job.result.knowledge_sync as PaperKnowledgeSync
              : null
          );
          localStorage.setItem(paperStorageKey, resultPaperId);
          localStorage.removeItem(paperJobStorageKey);
          setActiveJobId(null);
          setJobError(null);
          setJobProgress(100);
          setUploadProgress(100);
          setIsUploading(false);
          setChatMessages([
            { id: `${Date.now()}-ready`, role: 'assistant', content: PAPER_READY_MESSAGE },
          ]);
          addNotification({ type: 'success', message: '论文解析完成', duration: 3000 });
          return;
        }

        if (job.status === 'failed' || job.status === 'cancelled') {
          const message = job.error_message || '论文分析失败，请稍后重试';
          setJobError(message);
          setIsUploading(false);
          addNotification({ type: 'error', message, duration: 5000 });
          return;
        }

        setJobError(null);
        setIsUploading(true);
        pollTimer = setTimeout(pollJob, 2000);
      } catch (error: unknown) {
        if (cancelled) return;
        const message = getApiErrorMessage(error, '暂时无法读取论文分析进度，正在自动重试');
        setJobError(message);
        if (!pollErrorShown) {
          pollErrorShown = true;
          addNotification({ type: 'warning', message, duration: 4000 });
        }
        pollTimer = setTimeout(pollJob, 5000);
      }
    };

    void pollJob();
    return () => {
      cancelled = true;
      if (pollTimer) clearTimeout(pollTimer);
    };
  }, [
    activeJobId,
    addNotification,
    jobPollKey,
    paperJobStorageKey,
    paperStorageKey,
    setCurrentPaper,
    setCurrentReport,
    setUploadProgress,
  ]);

  useEffect(() => {
    if (!currentPaper || currentReport?.paper_id === currentPaper.id) return;
    paperAPI
      .getDeepRead(currentPaper.id)
      .then((response) => setCurrentReport(response.data))
      .catch(() => undefined);
  }, [currentPaper, currentReport?.paper_id, setCurrentReport]);

  useEffect(() => {
    if (!currentPaper) return;
    let cancelled = false;
    let refreshTimer: ReturnType<typeof setTimeout> | undefined;

    const loadKnowledgeSync = async () => {
      try {
        const response = await paperAPI.getKnowledgeSync(currentPaper.id);
        if (cancelled) return;
        setKnowledgeSync(response.data);
        if (['pending', 'uploaded', 'processing'].includes(response.data.status)) {
          refreshTimer = setTimeout(loadKnowledgeSync, 5000);
        }
      } catch {
        if (!cancelled) {
          setKnowledgeSync((current) => current ?? {
            provider: 'xunfei-chatdoc',
            status: 'unavailable',
            error_message: '暂时无法读取知识库同步状态',
            attempt_count: 0,
          });
        }
      }
    };

    void loadKnowledgeSync();
    return () => {
      cancelled = true;
      if (refreshTimer) clearTimeout(refreshTimer);
    };
  }, [currentPaper, knowledgeRefreshKey]);

  const conversationStorageKey = currentPaper
    ? `scipilot-paper-read:${userId}:${selectedProjectId || 'all'}:${currentPaper.id}:conversation-id`
    : '';

  const loadPaperConversations = useCallback(async () => {
    if (!currentPaper) return;
    const response = await conversationAPI.getConversations({
      module: 'paper',
      project_id: selectedProjectId || undefined,
      limit: 50,
    });
    const items = (Array.isArray(response.data.items) ? response.data.items : []).filter(
      (conversation: Conversation) => conversation.context?.paper_id === currentPaper.id
    );
    setPaperConversations(items);
    const storedId = conversationStorageKey
      ? localStorage.getItem(conversationStorageKey)
      : null;
    if (storedId && items.some((item: Conversation) => item.id === storedId)) {
      setConversationId(storedId);
    } else if (storedId && conversationStorageKey) {
      localStorage.removeItem(conversationStorageKey);
    }
  }, [conversationStorageKey, currentPaper, selectedProjectId]);

  useEffect(() => {
    if (!currentPaper || !paperAgentId) return;
    void loadPaperConversations().catch(() => {
      setPaperConversations([]);
    });
  }, [currentPaper, loadPaperConversations, paperAgentId]);

  useEffect(() => {
    if (!conversationId || !currentPaper) {
      if (conversationStorageKey) localStorage.removeItem(conversationStorageKey);
      return;
    }
    localStorage.setItem(conversationStorageKey, conversationId);
    if (skipRestoreConversationRef.current === conversationId) {
      skipRestoreConversationRef.current = null;
      setIsLoadingConversation(false);
      return;
    }
    let cancelled = false;
    setIsLoadingConversation(true);
    conversationAPI
      .getConversation(conversationId)
      .then((response) => {
        if (cancelled) return;
        if (response.data.context?.paper_id !== currentPaper.id) {
          throw new Error('该历史会话不属于当前论文');
        }
        const restored = normalizeConversationMessages(response.data.messages);
        setChatMessages(restored.length ? restored : [
          { id: `${Date.now()}-ready`, role: 'assistant', content: PAPER_READY_MESSAGE },
        ]);
      })
      .catch((error: unknown) => {
        if (cancelled) return;
        setConversationId(null);
        addNotification({
          type: 'error',
          message: getApiErrorMessage(error, '历史会话恢复失败，请重新选择。'),
          duration: 4000,
        });
      })
      .finally(() => {
        if (!cancelled) setIsLoadingConversation(false);
      });
    return () => {
      cancelled = true;
    };
  }, [addNotification, conversationId, conversationStorageKey, currentPaper]);

  const report = currentReport ?? { paper_id: currentPaper?.id ?? '', sections: [] };
  const safeSections = Array.isArray(report.sections) ? report.sections : [];

  const handleFileUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    if (file.type !== 'application/pdf') {
      addNotification({ type: 'warning', message: '请上传 PDF 文件', duration: 3000 });
      return;
    }

    setIsUploading(true);
    setUploadProgress(0);
    setConversationId(null);
    setPaperConversations([]);
    setChatMessages([]);
    setInput('');
    setActiveSection(0);
    setJobProgress(0);
    setJobError(null);
    let queued = false;
    try {
      const response = await paperAPI.uploadAsync(file, setUploadProgress, selectedProjectId);
      const jobId = String(response.data.job_id);
      if (!jobId) throw new Error('后端没有返回论文分析任务编号');
      queued = true;
      localStorage.setItem(paperJobStorageKey, jobId);
      setActiveJobId(jobId);
      setUploadProgress(100);
      setJobProgress(response.data.progress || 0);
      addNotification({ type: 'success', message: '论文已上传，正在后台解析', duration: 3000 });
    } catch (error: unknown) {
      const message = isTimeoutError(error)
        ? '论文上传超时，请检查网络后重试。'
        : getApiErrorMessage(error, '论文上传失败，请检查后端是否启动或 PDF 是否可读取');
      setJobError(message);
      addNotification({ type: 'error', message, duration: 5000 });
    } finally {
      if (!queued) setIsUploading(false);
      if (fileInputRef.current) fileInputRef.current.value = '';
    }
  };

  const retryPaperAnalysis = useCallback(async () => {
    if (!activeJobId || isRetryingAnalysis) return;
    setIsRetryingAnalysis(true);
    try {
      const response = await researchJobAPI.retry(activeJobId);
      setJobProgress(response.data.progress || 0);
      setJobError(null);
      setIsUploading(true);
      setJobPollKey((value) => value + 1);
      addNotification({ type: 'success', message: '论文分析任务已重新提交', duration: 3000 });
    } catch (error: unknown) {
      const message = getApiErrorMessage(error, '论文分析任务重试失败，请稍后再试');
      setJobError(message);
      addNotification({ type: 'error', message, duration: 5000 });
    } finally {
      setIsRetryingAnalysis(false);
    }
  }, [activeJobId, addNotification, isRetryingAnalysis]);

  const resetPaper = useCallback(() => {
    localStorage.removeItem(paperStorageKey);
    localStorage.removeItem(paperJobStorageKey);
    if (conversationStorageKey) localStorage.removeItem(conversationStorageKey);
    setCurrentPaper(null);
    setCurrentReport(null);
    setUploadProgress(0);
    setIsUploading(false);
    setActiveJobId(null);
    setJobProgress(0);
    setJobError(null);
    setJobPollKey(0);
    setIsRetryingAnalysis(false);
    setConversationId(null);
    setPaperConversations([]);
    setIsLoadingConversation(false);
    setIsDeletingConversation(false);
    setKnowledgeSync(null);
    setIsRetryingKnowledge(false);
    setKnowledgeRefreshKey(0);
    setChatMessages([]);
    setInput('');
    setIsSending(false);
    setActiveSection(0);
    setShowCitation(null);
    if (fileInputRef.current) fileInputRef.current.value = '';
  }, [conversationStorageKey, paperJobStorageKey, paperStorageKey, setCurrentPaper, setCurrentReport, setUploadProgress]);

  const startNewConversation = useCallback(() => {
    if (isSending || isDeletingConversation) return;
    setConversationId(null);
    if (conversationStorageKey) localStorage.removeItem(conversationStorageKey);
    setChatMessages([
      { id: `${Date.now()}-ready`, role: 'assistant', content: PAPER_READY_MESSAGE },
    ]);
    setInput('');
  }, [conversationStorageKey, isDeletingConversation, isSending]);

  const deleteCurrentConversation = useCallback(async () => {
    if (!conversationId || isSending || isDeletingConversation) return;
    if (!window.confirm('确定删除当前论文会话及全部消息吗？此操作无法撤销。')) return;
    setIsDeletingConversation(true);
    try {
      await conversationAPI.deleteConversation(conversationId);
      setPaperConversations((current) => current.filter((item) => item.id !== conversationId));
      setConversationId(null);
      if (conversationStorageKey) localStorage.removeItem(conversationStorageKey);
      setChatMessages([
        { id: `${Date.now()}-ready`, role: 'assistant', content: PAPER_READY_MESSAGE },
      ]);
      addNotification({ type: 'success', message: '会话已删除', duration: 2500 });
    } catch (error: unknown) {
      addNotification({
        type: 'error',
        message: getApiErrorMessage(error, '删除会话失败，请稍后重试。'),
        duration: 4000,
      });
    } finally {
      setIsDeletingConversation(false);
    }
  }, [addNotification, conversationId, conversationStorageKey, isDeletingConversation, isSending]);

  const retryKnowledgeSync = useCallback(async () => {
    if (!currentPaper || isRetryingKnowledge) return;
    setIsRetryingKnowledge(true);
    try {
      const response = await paperAPI.retryKnowledgeSync(currentPaper.id);
      setKnowledgeSync(response.data);
      setKnowledgeRefreshKey((value) => value + 1);
      addNotification({
        type: response.data.status === 'failed' ? 'error' : 'success',
        message: response.data.status === 'failed'
          ? response.data.error_message || '知识库同步失败，请稍后重试'
          : '论文已重新提交到知识库',
        duration: 4000,
      });
    } catch (error: unknown) {
      addNotification({
        type: 'error',
        message: getApiErrorMessage(error, '知识库同步失败，请稍后重试'),
        duration: 5000,
      });
    } finally {
      setIsRetryingKnowledge(false);
    }
  }, [addNotification, currentPaper, isRetryingKnowledge]);

  const handleSendMessage = useCallback(async () => {
    const userInput = input.trim();
    if (!userInput || isSending) return;
    if (!paperAgentId) {
      addNotification({ type: 'warning', message: '论文精读助手正在加载，请稍后再试', duration: 3000 });
      return;
    }
    if (!currentPaper) return;

    const userMsg: ChatMessage = {
      id: `${Date.now()}-user`,
      role: 'user',
      content: userInput,
    };
    setChatMessages((prev) => [...prev, userMsg]);
    setInput('');
    setIsSending(true);

    try {
      let activeConversationId = conversationId;
      if (!activeConversationId) {
        const conversationResponse = await conversationAPI.createConversation({
          agent_id: paperAgentId,
          module: 'paper',
          title: `${currentPaper.title} 论文精读`,
          project_id: selectedProjectId,
          context: { paper_id: currentPaper.id },
        });
        activeConversationId = String(conversationResponse.data.id);
        skipRestoreConversationRef.current = activeConversationId;
        setConversationId(activeConversationId);
        setPaperConversations((current) => [conversationResponse.data, ...current]);
      }

      const chatResponse = await conversationAPI.chat({
        conversation_id: activeConversationId,
        agent_id: paperAgentId,
        message: userInput,
      });
      const reply = String(chatResponse.data.reply || '').trim();
      if (!reply) throw new Error('智能体没有返回有效回复');
      const citations = normalizeChatCitations(chatResponse.data.citations);
      setChatMessages((prev) => [
        ...prev,
        { id: `${Date.now()}-assistant`, role: 'assistant', content: reply, citations },
      ]);
      void loadPaperConversations();
    } catch (error: unknown) {
      const message = isTimeoutError(error)
        ? '智能体响应超时，请稍后重试。首次调用可能需要 1—2 分钟。'
        : getApiErrorMessage(error, '智能体调用失败，请检查后端或 Agent 配置。');
      addNotification({ type: 'error', message, duration: 5000 });
    } finally {
      setIsSending(false);
    }
  }, [addNotification, conversationId, currentPaper, input, isSending, loadPaperConversations, paperAgentId, selectedProjectId]);

  if (!currentPaper && isRestoringPaper) {
    return (
      <div className="h-full flex items-center justify-center text-sci-muted">
        <Loader2 size={20} className="mr-2 animate-spin text-sci-accent" />
        正在恢复上次阅读的论文…
      </div>
    );
  }

  if (!currentPaper) {
    return (
      <div className="h-full flex flex-col">
        <ProjectContextBar className="mb-4" />
        <div className="flex flex-1 items-center justify-center">
        <div className="text-center max-w-md">
          <div className="w-20 h-20 rounded-2xl bg-sci-bg3 border border-sci-border flex items-center justify-center mx-auto mb-6">
            <FileText size={36} className="text-sci-accent" />
          </div>
          <h2 className="text-xl font-bold mb-2">上传论文开始精读</h2>
          <p className="text-sci-muted mb-6">支持 PDF 格式，AI 将自动生成结构化精读报告</p>
          <input
            ref={fileInputRef}
            type="file"
            accept=".pdf"
            onChange={handleFileUpload}
            className="hidden"
          />
          <button
            onClick={() => fileInputRef.current?.click()}
            disabled={isUploading}
            className="sci-btn-primary"
          >
            {isUploading ? (
              <>
                <Loader2 size={18} className="animate-spin" />
                {uploadProgress >= 100
                  ? `智能体正在分析，请稍候… ${jobProgress}%`
                  : `上传中 ${uploadProgress}%`}
              </>
            ) : (
              <>
                <Upload size={18} />
                选择 PDF 文件
              </>
            )}
          </button>
          {jobError && (
            <div className="mt-4">
              <p className="text-sm text-red-400">{jobError}</p>
              {activeJobId && !isUploading && (
                <button
                  type="button"
                  onClick={retryPaperAnalysis}
                  disabled={isRetryingAnalysis}
                  className="sci-btn-secondary mt-3"
                >
                  {isRetryingAnalysis ? (
                    <Loader2 size={16} className="animate-spin" />
                  ) : (
                    <RefreshCw size={16} />
                  )}
                  重新分析
                </button>
              )}
            </div>
          )}
        </div>
        </div>
      </div>
    );
  }

  return (
    <div className="h-full flex flex-col -m-6">
      <div className="px-6 pt-4">
        <ProjectContextBar />
      </div>
      {/* Three-column layout */}
      <div className="flex-1 flex overflow-hidden">
        {/* Left: Section Nav */}
        <div className="w-56 bg-sci-bg2 border-r border-sci-border flex-shrink-0 overflow-y-auto">
          <div className="p-4">
            <h3 className="text-sm font-semibold text-sci-muted mb-3 flex items-center gap-2">
              <BookOpen size={14} />
              章节导航
            </h3>
            <div className="space-y-1">
              {safeSections.map((section, index) => (
                <button
                  key={index}
                  onClick={() => setActiveSection(index)}
                  className={`w-full text-left px-3 py-2 rounded-lg text-sm transition-colors ${
                    activeSection === index
                      ? 'bg-sci-primary/10 text-sci-accent border border-sci-primary/20'
                      : 'text-sci-muted hover:bg-sci-bg3 hover:text-sci-ink'
                  }`}
                >
                  {section.heading}
                </button>
              ))}
            </div>
          </div>
        </div>

        {/* Center: Report */}
        <div className="flex-1 overflow-y-auto p-6">
          <div className="max-w-3xl mx-auto">
            <div className="sci-card-glow mb-6">
              <div className="flex items-start justify-between gap-4 mb-2">
                <h1 className="text-2xl font-bold">{currentPaper.title}</h1>
                <div className="flex flex-shrink-0 flex-wrap justify-end gap-2">
                  <button
                    type="button"
                    onClick={() => {
                      const params = new URLSearchParams({
                        paperId: currentPaper.id,
                        direction: `基于《${currentPaper.title}》提出可验证的研究问题`,
                      });
                      navigate(`/research/decompose?${params.toString()}`);
                    }}
                    className="sci-btn-primary"
                  >
                    拆解研究问题
                    <ArrowRight size={16} />
                  </button>
                  <button
                    type="button"
                    onClick={resetPaper}
                    disabled={isSending || isUploading}
                    className="sci-btn-secondary"
                  >
                    <RefreshCw size={16} />
                    重新上传论文
                  </button>
                </div>
              </div>
              <div className="flex items-center gap-3">
                <span className="sci-badge-info">PDF</span>
                <span className="text-sm text-sci-muted">{currentPaper.authors.join(', ')}</span>
              </div>
              {knowledgeSync && (
                <div className="mt-3 flex flex-wrap items-center gap-2">
                  <span
                    className={`text-xs px-2 py-1 rounded border ${
                      knowledgeSync.status === 'vectored'
                        ? 'text-emerald-400 border-emerald-400/30 bg-emerald-400/10'
                        : knowledgeSync.status === 'failed'
                          ? 'text-red-400 border-red-400/30 bg-red-400/10'
                          : 'text-sci-muted border-sci-border bg-sci-bg3'
                    }`}
                  >
                    {knowledgeSyncLabel(knowledgeSync.status)}
                  </span>
                  {['failed', 'not_started'].includes(knowledgeSync.status) && (
                    <button
                      type="button"
                      onClick={() => void retryKnowledgeSync()}
                      disabled={isRetryingKnowledge}
                      className="text-xs text-sci-accent hover:text-sci-ink inline-flex items-center gap-1"
                    >
                      <RefreshCw size={13} className={isRetryingKnowledge ? 'animate-spin' : ''} />
                      重试同步
                    </button>
                  )}
                  {knowledgeSync.error_message && (
                    <span className="text-xs text-sci-muted w-full">
                      {knowledgeSync.error_message}
                    </span>
                  )}
                </div>
              )}
            </div>

            <AgentKnowledgePanel category="paper-reading" className="mb-6" />

            {safeSections.map((section, index) => (
              <div key={index} id={`section-${index}`} className="mb-8">
                <h2 className="text-xl font-semibold text-sci-accent mb-4 flex items-center gap-2">
                  <span className="w-6 h-6 rounded bg-sci-primary/20 text-sci-accent text-xs flex items-center justify-center">
                    {index + 1}
                  </span>
                  {section.heading}
                </h2>
                <div className="sci-card">
                  <MarkdownContent content={section.content} />
                  {section.citations.length > 0 && (
                    <div className="mt-4 flex items-center gap-2">
                      <Quote size={14} className="text-sci-accent" />
                      <span className="text-xs text-sci-muted">引用:</span>
                      {section.citations.map((cite, ci) => (
                        <button
                          key={ci}
                          onClick={() => setShowCitation(cite)}
                          className="text-xs px-2 py-1 rounded bg-sci-bg3 text-sci-accent hover:bg-sci-primary/20 transition-colors"
                        >
                          [{ci + 1}]
                        </button>
                      ))}
                    </div>
                  )}
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* Right: Chat */}
        <div className="w-80 bg-sci-bg2 border-l border-sci-border flex-shrink-0 flex flex-col">
          <div className="p-3 border-b border-sci-border space-y-2">
            <h3 className="text-sm font-semibold flex items-center gap-2">
              <Send size={14} className="text-sci-accent" />
              论文追问
            </h3>
            <div className="flex items-center gap-1.5">
              <select
                value={conversationId || ''}
                onChange={(event) => {
                  if (event.target.value) setConversationId(event.target.value);
                  else startNewConversation();
                }}
                disabled={isSending || isDeletingConversation}
                className="sci-input min-w-0 flex-1 py-1.5 text-xs"
                aria-label="选择论文历史会话"
              >
                <option value="">新对话</option>
                {paperConversations.map((conversation) => (
                  <option key={conversation.id} value={conversation.id}>
                    {conversation.title || '未命名会话'}
                  </option>
                ))}
              </select>
              <button
                type="button"
                onClick={startNewConversation}
                disabled={isSending || isDeletingConversation}
                className="p-2 rounded-md text-sci-muted hover:bg-sci-bg3 hover:text-sci-accent"
                title="新建会话"
                aria-label="新建论文会话"
              >
                <MessageSquarePlus size={15} />
              </button>
              <button
                type="button"
                onClick={() => void deleteCurrentConversation()}
                disabled={!conversationId || isSending || isDeletingConversation}
                className="p-2 rounded-md text-sci-muted hover:bg-sci-bg3 hover:text-sci-danger disabled:opacity-40"
                title="删除当前会话"
                aria-label="删除当前论文会话"
              >
                {isDeletingConversation
                  ? <Loader2 size={15} className="animate-spin" />
                  : <Trash2 size={15} />}
              </button>
            </div>
          </div>

          <div className="flex-1 overflow-y-auto p-3 space-y-3">
            {isLoadingConversation && (
              <div className="flex items-center justify-center gap-2 py-4 text-xs text-sci-muted">
                <Loader2 size={14} className="animate-spin" />
                正在恢复历史消息…
              </div>
            )}
            {!isLoadingConversation && chatMessages.map((msg) => (
              <div
                key={msg.id}
                className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}
              >
                <div
                  className={`max-w-[90%] px-3 py-2 rounded-xl text-sm ${
                    msg.role === 'user'
                      ? 'bg-sci-primary text-white'
                      : 'bg-sci-bg3 border border-sci-border'
                  }`}
                >
                  {msg.content}
                  {msg.citations && msg.citations.length > 0 && (
                    <div className="mt-2 pt-2 border-t border-sci-border flex flex-wrap items-center gap-1">
                      <Quote size={12} className="text-sci-accent" />
                      {msg.citations.map((citation, index) => (
                        <button
                          key={`${msg.id}-citation-${index}`}
                          type="button"
                          onClick={() => setShowCitation(citation)}
                          className="text-xs text-sci-accent hover:text-sci-ink"
                        >
                          [{index + 1}]
                        </button>
                      ))}
                    </div>
                  )}
                </div>
              </div>
            ))}
            {isSending && (
              <div className="flex justify-start">
                <div className="max-w-[90%] px-3 py-2 rounded-xl text-sm bg-sci-bg3 border border-sci-border">
                  <span className="animate-pulse">智能体正在分析，请稍候……</span>
                </div>
              </div>
            )}
            <div ref={chatEndRef} />
          </div>

          <div className="p-3 border-t border-sci-border">
            <div className="flex gap-2">
              <input
                type="text"
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && handleSendMessage()}
                placeholder="输入问题..."
                className="sci-input flex-1 text-sm"
              />
              <button
                onClick={handleSendMessage}
                disabled={isSending || !input.trim() || !paperAgentId}
                className="sci-btn-primary p-2"
              >
                {isSending ? <Loader2 size={16} className="animate-spin" /> : <Send size={16} />}
              </button>
            </div>
          </div>
        </div>
      </div>

      {showCitation && (
        <CitationCard citation={showCitation} onClose={() => setShowCitation(null)} />
      )}
    </div>
  );
}

export default PaperRead;
