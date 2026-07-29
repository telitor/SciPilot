import { useState, useRef, useCallback, useEffect } from 'react';
import { Upload, Send, FileText, BookOpen, Quote, Loader2, X } from 'lucide-react';
import AgentKnowledgePanel from '@/components/AgentKnowledgePanel';
import { usePaperStore } from '@/store/paperStore';
import { useUIStore } from '@/store/uiStore';
import { paperAPI } from '@/services/api';
import type { Citation } from '@/types';

interface ChatMessage {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  isStreaming?: boolean;
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
  const { currentPaper, currentReport, setCurrentPaper, setCurrentReport, uploadProgress, setUploadProgress } = usePaperStore();
  const { addNotification } = useUIStore();

  const [input, setInput] = useState('');
  const [chatMessages, setChatMessages] = useState<ChatMessage[]>([]);
  const [isStreaming, setIsStreaming] = useState(false);
  const [streamText, setStreamText] = useState('');
  const [activeSection, setActiveSection] = useState(0);
  const [showCitation, setShowCitation] = useState<Citation | null>(null);
  const [isUploading, setIsUploading] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const chatEndRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [chatMessages, streamText]);

  useEffect(() => {
    if (!currentPaper || currentReport?.paper_id === currentPaper.id) return;
    paperAPI
      .getDeepRead(currentPaper.id)
      .then((response) => setCurrentReport(response.data))
      .catch(() => undefined);
  }, [currentPaper, currentReport?.paper_id, setCurrentReport]);

  const report = currentReport ?? { paper_id: currentPaper?.id ?? '', sections: [] };

  const handleFileUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    if (file.type !== 'application/pdf') {
      addNotification({ type: 'warning', message: '请上传 PDF 文件', duration: 3000 });
      return;
    }

    setIsUploading(true);
    setUploadProgress(0);
    try {
      const uploadResponse = await paperAPI.upload(file, setUploadProgress);
      const paper = uploadResponse.data;
      setCurrentPaper(paper);
      const reportResponse = await paperAPI.getDeepRead(paper.id);
      setCurrentReport(reportResponse.data);
      setUploadProgress(100);
      addNotification({ type: 'success', message: '论文上传成功', duration: 3000 });
    } catch {
      // The shared API interceptor already displays the server error.
    } finally {
      setIsUploading(false);
      if (fileInputRef.current) fileInputRef.current.value = '';
    }
  };

  const handleSendMessage = useCallback(async () => {
    if (!input.trim() || isStreaming) return;

    const userMsg: ChatMessage = {
      id: Date.now().toString(),
      role: 'user',
      content: input,
    };
    setChatMessages((prev) => [...prev, userMsg]);
    setInput('');

    setIsStreaming(true);
    setStreamText('');

    // Simulate streaming response
    const response = '这是一个很好的问题。根据论文内容，Transformer 使用多头注意力机制来捕捉不同子空间的表示。每个注意力头可以关注不同的位置，从而增强模型的表达能力。';

    let index = 0;
    let currentText = '';
    const streamInterval = setInterval(() => {
      if (index < response.length) {
        currentText += response[index];
        setStreamText(currentText);
        index++;
      } else {
        clearInterval(streamInterval);
        setIsStreaming(false);
        setChatMessages((prev) => [
          ...prev,
          { id: (Date.now() + 1).toString(), role: 'assistant', content: currentText },
        ]);
        setStreamText('');
      }
    }, 50);
  }, [input, isStreaming]);

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
                上传中 {uploadProgress}%
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
              {report.sections.map((section, index) => (
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
              <h1 className="text-2xl font-bold mb-2">{currentPaper.title}</h1>
              <div className="flex items-center gap-3">
                <span className="sci-badge-info">PDF</span>
                <span className="text-sm text-sci-muted">{currentPaper.authors.join(', ')}</span>
              </div>
            </div>

            <AgentKnowledgePanel category="paper-reading" className="mb-6" />

            {report.sections.map((section, index) => (
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
