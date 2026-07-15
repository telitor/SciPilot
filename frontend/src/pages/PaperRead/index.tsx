import { useState, useRef, useCallback, useEffect } from 'react';
import { Upload, Send, FileText, BookOpen, Quote, Loader2, X } from 'lucide-react';
import { usePaperStore } from '@/store/paperStore';
import { useUIStore } from '@/store/uiStore';
import {
  agentAPI,
  conversationAPI,
  getErrorMessage,
  paperAPI,
  PAPER_ANALYSIS_TIMEOUT_MESSAGE,
} from '@/services/api';
import type { Citation } from '@/types';

interface ChatMessage {
  id: string;
  role: 'user' | 'assistant';
  content: string;
}

interface Agent {
  id: string;
  name: string;
  category?: string;
}

interface PaperAnalysisSection {
  title?: string;
  heading?: string;
  content: string;
  citation?: string;
}

interface PaperAnalysisResponse {
  title: string;
  authors: string | string[];
  sections: PaperAnalysisSection[];
  raw_analysis?: string;
}

function parseJsonLikeText(text?: string): PaperAnalysisResponse | null {
  if (!text || (!text.includes('{') && !text.includes('sections'))) return null;

  let cleaned = text.trim();
  if (cleaned.startsWith('```json')) {
    cleaned = cleaned.slice('```json'.length).trim();
  } else if (cleaned.startsWith('```')) {
    cleaned = cleaned.slice('```'.length).trim();
  }

  if (cleaned.endsWith('```')) {
    cleaned = cleaned.slice(0, -3).trim();
  }

  const start = cleaned.indexOf('{');
  const end = cleaned.lastIndexOf('}');
  const jsonText = start !== -1 && end !== -1 && end > start
    ? cleaned.slice(start, end + 1)
    : cleaned;

  try {
    const parsed = JSON.parse(jsonText);
    if (parsed && typeof parsed === 'object') {
      return parsed as PaperAnalysisResponse;
    }
  } catch {
    return null;
  }

  return null;
}

function normalizeAnalysisSections(analysis: PaperAnalysisResponse) {
  const parsedRaw = parseJsonLikeText(analysis.raw_analysis);
  const rawSections = Array.isArray(analysis.sections) ? analysis.sections : [];
  const parsedFromContent = rawSections.length === 1
    ? parseJsonLikeText(rawSections[0]?.content)
    : null;
  const source = parsedRaw || parsedFromContent || analysis;
  const sourceSections = Array.isArray(source.sections) ? source.sections : [];

  if (sourceSections.length === 0) {
    return [
      {
        heading: '论文精读结果',
        content: analysis.raw_analysis || '论文解析完成，但没有返回结构化章节。',
        citations: [{ source: '[1]', text: analysis.raw_analysis || '' }],
      },
    ];
  }

  return sourceSections
    .filter((section) => section && typeof section === 'object')
    .map((section, index) => ({
      heading: String(section.title || section.heading || `章节 ${index + 1}`),
      content: String(section.content || ''),
      citations: section.citation
        ? [{ source: String(section.citation), text: String(section.content || '') }]
        : [],
    }));
}

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
  const {
    currentPaper,
    currentReport,
    setCurrentPaper,
    setCurrentReport,
    uploadProgress,
    setUploadProgress,
  } = usePaperStore();
  const { addNotification } = useUIStore();

  const [input, setInput] = useState('');
  const [chatMessages, setChatMessages] = useState<ChatMessage[]>([]);
  const [isStreaming, setIsStreaming] = useState(false);
  const [streamText, setStreamText] = useState('');
  const [activeSection, setActiveSection] = useState(0);
  const [showCitation, setShowCitation] = useState<Citation | null>(null);
  const [isUploading, setIsUploading] = useState(false);
  const [paperAgentId, setPaperAgentId] = useState<string | null>(null);
  const [conversationId, setConversationId] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const chatEndRef = useRef<HTMLDivElement>(null);

  const reportSections = currentReport?.sections ?? [];

  const resetPaper = useCallback(() => {
    setCurrentPaper(null);
    setCurrentReport(null);
    setUploadProgress(0);
    setIsUploading(false);
    setConversationId(null);
    setChatMessages([]);
    setStreamText('');
    setInput('');
    setActiveSection(0);
    setShowCitation(null);
    if (fileInputRef.current) {
      fileInputRef.current.value = '';
    }
  }, [setCurrentPaper, setCurrentReport, setUploadProgress]);

  useEffect(() => {
    const loadPaperAgent = async () => {
      try {
        const response = await agentAPI.getAgents();
        const agents = response.data as Agent[];
        const paperAgent = agents.find(
          (agent) => agent.category === 'paper-reading' || agent.name === '论文精读助手'
        );

        if (!paperAgent) {
          addNotification({
            type: 'warning',
            message: '没有找到论文精读助手，请检查后端 /agents 或 Supabase agents 表',
            duration: 5000,
          });
          return;
        }

        setPaperAgentId(paperAgent.id);
      } catch {
        addNotification({
          type: 'error',
          message: '获取论文精读助手失败，请检查后端 /agents',
          duration: 5000,
        });
      }
    };

    loadPaperAgent();
  }, [addNotification]);

  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [chatMessages, streamText]);

  const handleFileUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;

    if (file.type !== 'application/pdf' && !file.name.toLowerCase().endsWith('.pdf')) {
      addNotification({ type: 'warning', message: '请上传 PDF 文件', duration: 3000 });
      return;
    }

    setIsUploading(true);
    setUploadProgress(20);
    setCurrentPaper(null);
    setCurrentReport(null);

    try {
      const response = await paperAPI.analyzePaper(file);
      const analysis = response.data as PaperAnalysisResponse;
      const parsedAnalysis = parseJsonLikeText(analysis.raw_analysis) || analysis;
      const paperId = `${Date.now()}`;
      const authors = Array.isArray(parsedAnalysis.authors)
        ? parsedAnalysis.authors
        : [parsedAnalysis.authors || 'Unknown'];
      const sections = normalizeAnalysisSections(analysis);

      setCurrentPaper({
        id: paperId,
        title: parsedAnalysis.title || file.name.replace(/\.pdf$/i, ''),
        authors,
        abstract: 'Uploaded paper',
        uploaded_at: new Date().toISOString(),
        status: 'completed',
      });
      setCurrentReport({
        paper_id: paperId,
        sections,
      });
      setActiveSection(0);
      setConversationId(null);
      setChatMessages([
        {
          id: `${Date.now()}-ready`,
          role: 'assistant',
          content: '论文已解析完成，你可以询问研究背景、核心方法、实验结果、创新点和不足。',
        },
      ]);
      setInput('');
      setStreamText('');
      setUploadProgress(100);
      addNotification({ type: 'success', message: '论文解析完成', duration: 3000 });
    } catch (error) {
      const errorMessage = getErrorMessage(error, PAPER_ANALYSIS_TIMEOUT_MESSAGE);
      addNotification({
        type: 'error',
        message: errorMessage.includes('论文解析超时')
          ? errorMessage
          : `论文解析失败，请检查后端是否启动或 PDF 是否可读取：${errorMessage}`,
        duration: 5000,
      });
    } finally {
      setIsUploading(false);
      if (fileInputRef.current) {
        fileInputRef.current.value = '';
      }
    }
  };

  const handleSendMessage = useCallback(async () => {
    if (!input.trim() || isStreaming) return;

    if (!paperAgentId) {
      addNotification({ type: 'warning', message: '论文精读助手还在加载，请稍后再试', duration: 3000 });
      return;
    }

    const userInput = input.trim();
    const userMsg: ChatMessage = {
      id: Date.now().toString(),
      role: 'user',
      content: userInput,
    };
    setChatMessages((prev) => [...prev, userMsg]);
    setInput('');

    setIsStreaming(true);
    setStreamText('正在思考...');

    try {
      const safeSections = Array.isArray(reportSections) ? reportSections : [];
      const paperContext = currentPaper && safeSections.length > 0
        ? `
【当前论文信息】
标题：${currentPaper.title || 'Unknown'}
作者：${currentPaper.authors?.join(', ') || 'Unknown'}

【论文结构化精读报告】
${safeSections.map((section, index) => `
${index + 1}. ${section.heading}
${section.content}
引用：${section.citations?.map((citation) => citation.source).join(', ') || ''}
`).join('\n')}

请你基于以上论文信息回答用户问题，不要声称自己没有看到论文或无法访问论文。
`.trim()
        : '';
      const messageForAgent = paperContext
        ? `${paperContext}\n\n【用户问题】\n${userInput}`
        : userInput;
      let currentConversationId = conversationId;

      if (!currentConversationId) {
        const conversationResponse = await conversationAPI.createConversation({
          agent_id: paperAgentId,
          title: currentPaper ? `${currentPaper.title} 论文精读` : '论文精读对话',
        });
        currentConversationId = conversationResponse.data.id;

        if (!currentConversationId) {
          throw new Error('Create conversation response missing id');
        }

        setConversationId(currentConversationId);
      }

      const chatResponse = await conversationAPI.chat({
        conversation_id: currentConversationId,
        agent_id: paperAgentId,
        message: messageForAgent,
      });
      const reply = chatResponse.data.reply;

      if (!reply) {
        throw new Error('Chat response missing reply');
      }

      setChatMessages((prev) => [
        ...prev,
        { id: (Date.now() + 1).toString(), role: 'assistant', content: reply },
      ]);
    } catch (error) {
      addNotification({
        type: 'error',
        message: `论文精读回复失败，请稍后重试：${getErrorMessage(error)}`,
        duration: 5000,
      });
      setChatMessages((prev) => [
        ...prev,
        {
          id: (Date.now() + 1).toString(),
          role: 'assistant',
          content: '论文精读助手暂时没有成功回复，请稍后再试。',
        },
      ]);
    } finally {
      setIsStreaming(false);
      setStreamText('');
    }
  }, [addNotification, conversationId, currentPaper, input, isStreaming, paperAgentId, reportSections]);

  if (!currentPaper) {
    return (
      <div className="h-full flex items-center justify-center">
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
                正在解析论文，首次分析可能需要 1-3 分钟... {uploadProgress}%
              </>
            ) : (
              <>
                <Upload size={18} />
                选择 PDF 文件
              </>
            )}
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="h-full flex flex-col -m-6">
      <div className="flex-1 flex overflow-hidden">
        <div className="w-56 bg-sci-bg2 border-r border-sci-border flex-shrink-0 overflow-y-auto">
          <div className="p-4">
            <h3 className="text-sm font-semibold text-sci-muted mb-3 flex items-center gap-2">
              <BookOpen size={14} />
              章节导航
            </h3>
            <div className="space-y-1">
              {reportSections.map((section, index) => (
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

        <div className="flex-1 overflow-y-auto p-6">
          <div className="max-w-3xl mx-auto">
            <div className="sci-card-glow mb-6">
              <div className="flex items-start justify-between gap-4">
                <div>
                  <h1 className="text-2xl font-bold mb-2">{currentPaper.title}</h1>
                  <div className="flex items-center gap-3">
                    <span className="sci-badge-info">PDF</span>
                    <span className="text-sm text-sci-muted">{currentPaper.authors.join(', ')}</span>
                  </div>
                </div>
                <button
                  type="button"
                  onClick={resetPaper}
                  className="sci-btn-secondary flex-shrink-0 text-sm"
                >
                  <Upload size={16} />
                  重新上传论文
                </button>
              </div>
            </div>

            {reportSections.map((section, index) => (
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

        <div className="w-80 bg-sci-bg2 border-l border-sci-border flex-shrink-0 flex flex-col">
          <div className="p-3 border-b border-sci-border">
            <h3 className="text-sm font-semibold flex items-center gap-2">
              <Send size={14} className="text-sci-accent" />
              论文追问
            </h3>
          </div>

          <div className="flex-1 overflow-y-auto p-3 space-y-3">
            {chatMessages.map((msg) => (
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
                </div>
              </div>
            ))}
            {isStreaming && (
              <div className="flex justify-start">
                <div className="max-w-[90%] px-3 py-2 rounded-xl text-sm bg-sci-bg3 border border-sci-border">
                  <span className="animate-pulse">{streamText}▌</span>
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
                disabled={isStreaming || !input.trim()}
                className="sci-btn-primary p-2"
              >
                {isStreaming ? <Loader2 size={16} className="animate-spin" /> : <Send size={16} />}
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
