import { useCallback, useState, useMemo, useEffect } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { BarChart3, TrendingUp, Download, FileSpreadsheet, Loader2, ArrowRight, FolderKanban } from 'lucide-react';
import ReactECharts from 'echarts-for-react';
import * as echarts from 'echarts/core';
import { BarChart, LineChart } from 'echarts/charts';
import {
  GridComponent,
  TooltipComponent,
  LegendComponent,
} from 'echarts/components';
import { CanvasRenderer } from 'echarts/renderers';
import AgentKnowledgePanel from '@/components/AgentKnowledgePanel';
import ProjectContextBar from '@/components/ProjectContextBar';
import { useDurableResearchJob } from '@/hooks/useDurableResearchJob';
import { resultAPI } from '@/services/api';
import { getApiErrorMessage } from '@/services/errors';
import { useAuthStore } from '@/store/authStore';
import { useSelectedProjectId } from '@/store/projectStore';
import { useUIStore } from '@/store/uiStore';
import type { ResultAnalysis } from '@/types';

// Register ECharts modules manually to avoid window.echarts dependency
echarts.use([BarChart, LineChart, GridComponent, TooltipComponent, LegendComponent, CanvasRenderer]);

function ResultAnalyze() {
  const selectedProjectId = useSelectedProjectId();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const linkedRepoId = searchParams.get('repoId');
  const userId = useAuthStore((state) => state.user?.id || 'anonymous');
  const storageKey = `scipilot-current-result-analysis:${userId}${selectedProjectId ? `:${selectedProjectId}` : ''}`;
  const sourceStorageKey = `${storageKey}:repo-id`;
  const jobStorageKey = `${storageKey}:job-id`;
  const [file, setFile] = useState<File | null>(null);
  const [isAnalyzing, setIsAnalyzing] = useState(false);
  const [analysis, setAnalysis] = useState<import('@/types').ResultAnalysis | null>(null);
  const [chartReady, setChartReady] = useState(false);
  const { addNotification } = useUIStore();

  const handleJobSucceeded = useCallback((result: ResultAnalysis) => {
    setAnalysis(result);
    if (result.id) {
      localStorage.setItem(storageKey, result.id);
      if (linkedRepoId) localStorage.setItem(sourceStorageKey, linkedRepoId);
      else localStorage.removeItem(sourceStorageKey);
    }
    setChartReady(true);
    addNotification({ type: 'success', message: '数据分析完成', duration: 3000 });
  }, [addNotification, linkedRepoId, sourceStorageKey, storageKey]);

  const handleJobFailed = useCallback((message: string) => {
    addNotification({ type: 'error', message, duration: 5000 });
  }, [addNotification]);

  const {
    job,
    isRunning: isJobRunning,
    track: trackJob,
    retry: retryJob,
  } = useDurableResearchJob<ResultAnalysis>({
    storageKey: jobStorageKey,
    jobType: 'result-analysis',
    projectId: selectedProjectId,
    onSucceeded: handleJobSucceeded,
    onFailed: handleJobFailed,
  });

  // Ensure echarts is loaded before creating chart options
  useEffect(() => {
    // Small delay to ensure echarts-for-react is ready
    const timer = setTimeout(() => setChartReady(true), 100);
    return () => clearTimeout(timer);
  }, []);

  useEffect(() => {
    setAnalysis(null);
    const artifactId = localStorage.getItem(storageKey);
    const storedRepoId = localStorage.getItem(sourceStorageKey);
    if (linkedRepoId && storedRepoId !== linkedRepoId) return;
    if (!artifactId) return;
    resultAPI.getAnalysis(artifactId)
      .then((response) => setAnalysis(response.data))
      .catch(() => {
        localStorage.removeItem(storageKey);
        localStorage.removeItem(sourceStorageKey);
      });
  }, [linkedRepoId, sourceStorageKey, storageKey]);

  const handleFileUpload = (e: React.ChangeEvent<HTMLInputElement>) => {
    const uploadedFile = e.target.files?.[0];
    if (!uploadedFile) return;
    const validTypes = ['text/csv', 'application/json', 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'];
    const lowerName = uploadedFile.name.toLowerCase();
    if (!validTypes.includes(uploadedFile.type) && !['.csv', '.json', '.xlsx'].some((ext) => lowerName.endsWith(ext))) {
      addNotification({ type: 'warning', message: '请上传 CSV/JSON/Excel 文件', duration: 3000 });
      return;
    }
    setFile(uploadedFile);
  };

  const handleAnalyze = async () => {
    if (isAnalyzing || isJobRunning) return;
    if (!file) {
      addNotification({ type: 'warning', message: '请先上传数据文件', duration: 3000 });
      return;
    }
    setIsAnalyzing(true);
    try {
      const response = await resultAPI.analyzeAsync(
        file,
        undefined,
        selectedProjectId,
        linkedRepoId,
      );
      trackJob(response.data);
    } catch (error) {
      addNotification({
        type: 'error',
        message: getApiErrorMessage(error, '数据分析失败，请检查文件内容或结果分析智能体配置'),
        duration: 5000,
      });
    } finally {
      setIsAnalyzing(false);
    }
  };

  const barChartOption = useMemo(() => {
    if (!chartReady || !analysis?.stats.length) return null;
    const labels = analysis.stats.map((item) => item.metric);
    const values = analysis.stats.map((item) => item.mean);
    return {
      backgroundColor: 'transparent',
      grid: { left: '3%', right: '4%', bottom: '3%', containLabel: true },
      xAxis: {
        type: 'category' as const,
        data: labels,
        axisLine: { lineStyle: { color: '#334155' } },
        axisLabel: { color: '#94a3b8' },
      },
      yAxis: {
        type: 'value' as const,
        axisLine: { lineStyle: { color: '#334155' } },
        axisLabel: { color: '#94a3b8' },
        splitLine: { lineStyle: { color: '#1e293b' } },
      },
      series: [{
        data: values,
        type: 'bar' as const,
        itemStyle: {
          color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
            { offset: 0, color: '#38bdf8' },
            { offset: 1, color: '#2563eb' },
          ]),
          borderRadius: [4, 4, 0, 0],
        },
        barWidth: '40%',
      }],
      tooltip: {
        trigger: 'axis' as const,
        backgroundColor: '#1e293b',
        borderColor: '#334155',
        textStyle: { color: '#f1f5f9' },
      },
    };
  }, [analysis, chartReady]);

  const lineChartOption = useMemo(() => {
    if (!chartReady || !analysis?.stats.length) return null;
    const labels = analysis.stats.map((item) => item.metric);
    return {
      backgroundColor: 'transparent',
      grid: { left: '3%', right: '4%', bottom: '3%', containLabel: true },
      xAxis: {
        type: 'category' as const,
        data: labels,
        axisLine: { lineStyle: { color: '#334155' } },
        axisLabel: { color: '#94a3b8' },
      },
      yAxis: {
        type: 'value' as const,
        axisLine: { lineStyle: { color: '#334155' } },
        axisLabel: { color: '#94a3b8' },
        splitLine: { lineStyle: { color: '#1e293b' } },
      },
      series: [
        {
          name: '最小值',
          data: analysis.stats.map((item) => item.min),
          type: 'line' as const,
          smooth: true,
          lineStyle: { color: '#38bdf8', width: 2 },
          itemStyle: { color: '#38bdf8' },
          areaStyle: {
            color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
              { offset: 0, color: 'rgba(56,189,248,0.2)' },
              { offset: 1, color: 'rgba(56,189,248,0)' },
            ]),
          },
        },
        {
          name: '均值',
          data: analysis.stats.map((item) => item.mean),
          type: 'line' as const,
          smooth: true,
          lineStyle: { color: '#f59e0b', width: 2 },
          itemStyle: { color: '#f59e0b' },
        },
        {
          name: '最大值',
          data: analysis.stats.map((item) => item.max),
          type: 'line' as const,
          smooth: true,
          lineStyle: { color: '#22c55e', width: 2 },
          itemStyle: { color: '#22c55e' },
        },
      ],
      legend: {
        data: ['最小值', '均值', '最大值'],
        textStyle: { color: '#94a3b8' },
        bottom: 0,
      },
      tooltip: {
        trigger: 'axis' as const,
        backgroundColor: '#1e293b',
        borderColor: '#334155',
        textStyle: { color: '#f1f5f9' },
      },
    };
  }, [analysis, chartReady]);

  return (
    <div className="space-y-6 pb-20 md:pb-0">
      <h1 className="text-2xl font-bold">结果分析</h1>
      <ProjectContextBar />

      {/* Upload */}
      <div className="sci-card-glow">
        <div className="flex items-center gap-4">
          <div className="flex-1">
            <label className="block text-sm font-medium text-sci-ink mb-2">
              上传实验数据
            </label>
            <input
              type="file"
              accept=".csv,.json,.xlsx"
              onChange={handleFileUpload}
              className="hidden"
              id="data-upload"
            />
            <label
              htmlFor="data-upload"
              className="flex items-center gap-3 p-4 rounded-xl border-2 border-dashed border-sci-border hover:border-sci-accent/50 cursor-pointer transition-colors"
            >
              <FileSpreadsheet size={24} className="text-sci-accent" />
              <div>
                <p className="text-sm font-medium">
                  {file ? file.name : '点击或拖拽上传 CSV / JSON / Excel'}
                </p>
                <p className="text-xs text-sci-muted">
                  {file ? `${(file.size / 1024).toFixed(1)} KB` : '支持 .csv, .json, .xlsx'}
                </p>
              </div>
            </label>
          </div>
          <button
            onClick={handleAnalyze}
            disabled={isAnalyzing || isJobRunning || !file}
            className="sci-btn-primary self-end"
          >
            {isAnalyzing || isJobRunning ? (
              <>
                <Loader2 size={16} className="animate-spin" />
                分析中
              </>
            ) : (
              <>
                <BarChart3 size={16} />
                开始分析
              </>
            )}
          </button>
        </div>
        {isJobRunning && (
          <p className="mt-3 text-sm text-sci-muted">
            智能体正在后台解释结果，当前进度 {job?.progress ?? 0}%。刷新页面后任务会继续。
          </p>
        )}
        {job?.status === 'failed' && (
          <button type="button" onClick={() => void retryJob()} className="sci-btn-secondary mt-3">
            重试结果分析
          </button>
        )}
      </div>

      <AgentKnowledgePanel category="result-interpretation" />

      {analysis && (
        <div className="space-y-6">
          {/* Charts */}
          <div>
            <h2 className="sci-section-title mb-4">图表分析</h2>
            <div className="grid md:grid-cols-2 gap-4">
              <div className="sci-card">
                <h3 className="text-sm font-medium text-sci-muted mb-4">各数值字段均值</h3>
                {barChartOption ? (
                  <ReactECharts option={barChartOption} style={{ height: 250 }} />
                ) : (
                  <div className="h-[250px] flex items-center justify-center text-sci-muted text-sm">
                    图表加载中...
                  </div>
                )}
              </div>
              <div className="sci-card">
                <h3 className="text-sm font-medium text-sci-muted mb-4">各字段范围与均值</h3>
                {lineChartOption ? (
                  <ReactECharts option={lineChartOption} style={{ height: 250 }} />
                ) : (
                  <div className="h-[250px] flex items-center justify-center text-sci-muted text-sm">
                    图表加载中...
                  </div>
                )}
              </div>
            </div>
          </div>

          {/* Stats */}
          <div>
            <h2 className="sci-section-title mb-4">统计摘要</h2>
            <div className="grid md:grid-cols-3 gap-4">
              {analysis.stats.map((stat) => (
                <div key={stat.metric} className="sci-card">
                  <div className="flex items-center justify-between mb-3">
                    <h3 className="font-semibold">{stat.metric}</h3>
                    {typeof stat.p_value === 'number' && (
                      <span className="text-xs text-sci-muted">p = {stat.p_value}</span>
                    )}
                  </div>
                  <div className="text-3xl font-bold sci-glow-text mb-3">
                    {stat.mean.toFixed(3)}
                  </div>
                  <div className="space-y-1 text-xs text-sci-muted">
                    <div className="flex justify-between">
                      <span>标准差</span>
                      <span>{stat.std.toFixed(3)}</span>
                    </div>
                    <div className="flex justify-between">
                      <span>最小值</span>
                      <span>{stat.min.toFixed(3)}</span>
                    </div>
                    <div className="flex justify-between">
                      <span>最大值</span>
                      <span>{stat.max.toFixed(3)}</span>
                    </div>
                    <div className="flex justify-between">
                      <span>95% CI</span>
                      <span>[{stat.ci95[0].toFixed(3)}, {stat.ci95[1].toFixed(3)}]</span>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </div>

          {/* Interpretation */}
          <div className="grid md:grid-cols-2 gap-4">
            <div className="sci-card">
              <h3 className="sci-section-title mb-3">分析结论</h3>
              <p className="text-sm text-sci-muted leading-relaxed">{analysis.interpretation}</p>
            </div>
            <div className="sci-card">
              <h3 className="sci-section-title mb-3">改进建议</h3>
              <ul className="space-y-2">
                {analysis.suggestions.map((suggestion, index) => (
                  <li key={index} className="flex items-start gap-2 text-sm text-sci-muted">
                    <TrendingUp size={14} className="text-sci-success mt-0.5 flex-shrink-0" />
                    {suggestion}
                  </li>
                ))}
              </ul>
            </div>
          </div>

          {/* Export */}
          <div className="flex flex-wrap justify-end gap-3 border-t border-sci-border pt-4">
            <button
              onClick={() => addNotification({ type: 'info', message: '导出功能开发中', duration: 3000 })}
              className="sci-btn-secondary"
            >
              <Download size={16} />
              导出图表
            </button>
            <button
              type="button"
              onClick={() => navigate('/projects')}
              className="sci-btn-primary"
            >
              <FolderKanban size={16} />
              查看项目进度
              <ArrowRight size={16} />
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

export default ResultAnalyze;
