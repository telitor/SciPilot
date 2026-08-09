import { useEffect, useState } from 'react';
import { Check, Loader2, Save, ThumbsDown, ThumbsUp } from 'lucide-react';
import { feedbackAPI } from '@/services/api';
import { getApiErrorMessage } from '@/services/errors';
import type { MessageFeedback } from '@/types';

interface MessageFeedbackControlsProps {
  messageId: string;
  initialFeedback?: MessageFeedback | null;
  compact?: boolean;
}

export default function MessageFeedbackControls({
  messageId,
  initialFeedback = null,
  compact = false,
}: MessageFeedbackControlsProps) {
  const [feedback, setFeedback] = useState<MessageFeedback | null>(initialFeedback);
  const [comment, setComment] = useState(initialFeedback?.comment || '');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    setFeedback(initialFeedback);
    setComment(initialFeedback?.comment || '');
    setError('');
  }, [initialFeedback, messageId]);

  const save = async (rating: 'helpful' | 'unhelpful', nextComment?: string) => {
    if (saving) return;
    setSaving(true);
    setError('');
    try {
      const response = await feedbackAPI.upsert(messageId, {
        rating,
        comment: (nextComment ?? comment).trim() || null,
      });
      setFeedback(response.data);
      setComment(response.data.comment || '');
    } catch (requestError: unknown) {
      setError(getApiErrorMessage(requestError, '反馈保存失败，请稍后重试。'));
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className={`mt-3 border-t border-sci-border pt-2 ${compact ? 'text-[11px]' : 'text-xs'}`}>
      <div className="flex flex-wrap items-center gap-2 text-sci-muted">
        <span>这个回答有帮助吗？</span>
        <button
          type="button"
          onClick={() => void save('helpful')}
          disabled={saving}
          aria-label="回答有帮助"
          title="有帮助"
          className={`inline-flex h-7 w-7 items-center justify-center rounded-md border ${
            feedback?.rating === 'helpful'
              ? 'border-sci-success/50 bg-sci-success/10 text-sci-success'
              : 'border-sci-border hover:text-sci-ink'
          }`}
        >
          <ThumbsUp size={13} />
        </button>
        <button
          type="button"
          onClick={() => void save('unhelpful')}
          disabled={saving}
          aria-label="回答没有帮助"
          title="没有帮助"
          className={`inline-flex h-7 w-7 items-center justify-center rounded-md border ${
            feedback?.rating === 'unhelpful'
              ? 'border-sci-danger/50 bg-sci-danger/10 text-sci-danger'
              : 'border-sci-border hover:text-sci-ink'
          }`}
        >
          <ThumbsDown size={13} />
        </button>
        {saving && <Loader2 size={13} className="animate-spin" />}
        {!saving && feedback && (
          <span className="inline-flex items-center gap-1 text-sci-success">
            <Check size={12} /> 待审核
          </span>
        )}
      </div>

      {feedback && (
        <div className="mt-2 flex items-center gap-2">
          <input
            value={comment}
            onChange={(event) => setComment(event.target.value)}
            maxLength={1000}
            placeholder="可选：补充具体原因"
            className="sci-input min-w-0 flex-1 py-1.5 text-xs"
          />
          <button
            type="button"
            onClick={() => void save(feedback.rating, comment)}
            disabled={saving}
            aria-label="保存反馈说明"
            title="保存说明"
            className="inline-flex h-8 w-8 items-center justify-center rounded-md border border-sci-border text-sci-muted hover:text-sci-ink"
          >
            <Save size={13} />
          </button>
        </div>
      )}
      {error && <p className="mt-1 text-sci-danger">{error}</p>}
    </div>
  );
}
