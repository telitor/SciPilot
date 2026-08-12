import { X } from 'lucide-react';
import type { Citation } from '@/types';

export function MarkdownContent({ content }: { content: string }) {
  return (
    <div className="sci-markdown">
      {content.split('\n').map((line, index) => {
        if (line.startsWith('# ')) return <h1 key={index}>{line.slice(2)}</h1>;
        if (line.startsWith('## ')) return <h2 key={index}>{line.slice(3)}</h2>;
        if (line.startsWith('### ')) return <h3 key={index}>{line.slice(4)}</h3>;
        if (line.startsWith('- ')) return <ul key={index}><li>{line.slice(2)}</li></ul>;
        if (line.startsWith('> ')) return <blockquote key={index}>{line.slice(2)}</blockquote>;
        if (line.match(/^\d+\. /)) return <ol key={index}><li>{line.replace(/^\d+\. /, '')}</li></ol>;
        if (line.trim() === '') return <div key={index} className="h-2" />;
        return <p key={index}>{line}</p>;
      })}
    </div>
  );
}

export function CitationCard({ citation, onClose }: { citation: Citation; onClose: () => void }) {
  return (
    <div className="fixed z-50 bg-sci-bg2 border border-sci-accent/30 rounded-xl p-4 shadow-xl max-w-sm animate-fade-in" style={{ bottom: '20px', right: '20px' }}>
      <div className="flex items-center justify-between mb-2">
        <span className="text-xs text-sci-accent font-medium">引用来源</span>
        <button type="button" onClick={onClose} className="text-sci-muted hover:text-sci-ink" aria-label="关闭引用详情">
          <X size={14} />
        </button>
      </div>
      <p className="text-sm text-sci-muted">{citation.source}</p>
      <p className="text-sm text-sci-ink mt-2">{citation.text}</p>
      {citation.page && <p className="text-xs text-sci-muted mt-2">第 {citation.page} 页</p>}
    </div>
  );
}
