import { useCallback, useEffect, useRef, useState } from 'react';
import { researchJobAPI } from '@/services/api';
import type { ResearchJob } from '@/types';

interface DurableResearchJobOptions<T> {
  storageKey: string;
  jobType: string;
  projectId?: string | null;
  onSucceeded: (result: T) => void;
  onFailed: (message: string) => void;
}

export function useDurableResearchJob<T>({
  storageKey,
  jobType,
  projectId,
  onSucceeded,
  onFailed,
}: DurableResearchJobOptions<T>) {
  const [job, setJob] = useState<ResearchJob | null>(null);
  const succeededRef = useRef(onSucceeded);
  const failedRef = useRef(onFailed);
  const notifiedFailureRef = useRef<string | null>(null);

  useEffect(() => {
    succeededRef.current = onSucceeded;
    failedRef.current = onFailed;
  }, [onFailed, onSucceeded]);

  const applyJob = useCallback((nextJob: ResearchJob) => {
    setJob(nextJob);
    if (nextJob.status === 'pending' || nextJob.status === 'running') {
      localStorage.setItem(storageKey, nextJob.id);
      return;
    }
    if (nextJob.status === 'succeeded') {
      localStorage.removeItem(storageKey);
      succeededRef.current((nextJob.result || {}) as T);
      return;
    }
    if (nextJob.status === 'failed') {
      localStorage.setItem(storageKey, nextJob.id);
      if (notifiedFailureRef.current !== nextJob.id) {
        notifiedFailureRef.current = nextJob.id;
        failedRef.current(
          nextJob.error_code === 'timeout'
            ? '智能体响应超时，请稍后重试。任务已保留，可直接重试。'
            : nextJob.error_message || '任务执行失败，请稍后重试',
        );
      }
      return;
    }
    if (nextJob.status === 'cancelled') {
      localStorage.removeItem(storageKey);
    }
  }, [storageKey]);

  useEffect(() => {
    let cancelled = false;
    setJob(null);
    notifiedFailureRef.current = null;

    const restore = async () => {
      const storedJobId = localStorage.getItem(storageKey);
      try {
        if (storedJobId) {
          const response = await researchJobAPI.get(storedJobId);
          if (!cancelled) applyJob(response.data);
          return;
        }
        const response = await researchJobAPI.list({
          job_type: jobType,
          project_id: projectId || undefined,
          limit: 10,
        });
        const activeJob = response.data.items.find(
          (item) => item.status === 'pending' || item.status === 'running',
        );
        if (!cancelled && activeJob) applyJob(activeJob);
      } catch {
        localStorage.removeItem(storageKey);
      }
    };

    void restore();
    return () => {
      cancelled = true;
    };
  }, [applyJob, jobType, projectId, storageKey]);

  useEffect(() => {
    if (!job || (job.status !== 'pending' && job.status !== 'running')) return;
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;

    const poll = async () => {
      try {
        const response = await researchJobAPI.get(job.id);
        if (!cancelled) applyJob(response.data);
      } catch {
        if (!cancelled) timer = setTimeout(poll, 5000);
        return;
      }
      if (!cancelled) timer = setTimeout(poll, 2000);
    };

    timer = setTimeout(poll, 1000);
    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
  }, [applyJob, job]);

  const track = useCallback((nextJob: ResearchJob) => {
    notifiedFailureRef.current = null;
    applyJob(nextJob);
  }, [applyJob]);

  const retry = useCallback(async () => {
    if (!job || job.status !== 'failed') return;
    notifiedFailureRef.current = null;
    const response = await researchJobAPI.retry(job.id);
    applyJob(response.data);
  }, [applyJob, job]);

  const cancel = useCallback(async () => {
    if (!job || (job.status !== 'pending' && job.status !== 'running')) return;
    const response = await researchJobAPI.cancel(job.id);
    applyJob(response.data);
  }, [applyJob, job]);

  const clear = useCallback(() => {
    localStorage.removeItem(storageKey);
    notifiedFailureRef.current = null;
    setJob(null);
  }, [storageKey]);

  return {
    job,
    isRunning: job?.status === 'pending' || job?.status === 'running',
    track,
    retry,
    cancel,
    clear,
  };
}
