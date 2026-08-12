import { isAxiosError } from 'axios';
import type { Citation, PaperKnowledgeSyncStatus } from '@/types';

export interface PaperChatMessage {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  citations?: Citation[];
}

export function isPaperRequestTimeout(error: unknown) {
  return isAxiosError(error) && (
    error.code === 'ECONNABORTED' || error.message.toLowerCase().includes('timeout')
  );
}

export function normalizeChatCitations(value: unknown): Citation[] {
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

export function normalizeConversationMessages(value: unknown): PaperChatMessage[] {
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

export function knowledgeSyncLabel(status: PaperKnowledgeSyncStatus) {
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
