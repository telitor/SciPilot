import { useState, useMemo, useEffect } from 'react';
import { BarChart3, TrendingUp, Download, FileSpreadsheet, Loader2 } from 'lucide-react';
import ReactECharts from 'echarts-for-react';
import * as echarts from 'echarts/core';
import { BarChart, LineChart } from 'echarts/charts';
import {
  GridComponent,
  TooltipComponent,
  LegendComponent,
} from 'echarts/components';
import { CanvasRenderer } from 'echarts/renderers';
import { agentAPI, conversationAPI, getErrorMessage } from '@/services/api';
import { useUIStore } from '@/store/uiStore';
import type { ResultAnalysis } from '@/types';

echarts.use([BarChart, LineChart, GridComponent, TooltipComponent, LegendComponent, CanvasRenderer]);

type AgentItem = {
  id: string;
  category?: string;
};

type ChatMessage = {
  id: string;
  role: 'user' | 'assistant';
  content: string;
};

function extractJsonObject(text: string): unknown | null {
  const start = text.indexOf('{');
  const end = text.lastIndexOf('}');
  if (start === -1 || end === -1 || end <= start) return null;

  try {
    return JSON.parse(text.slice(start, end + 1));
  } catch {
    return null;
  }
}

function normalizeResultAnalysis(value: unknown): ResultAnalysis | null {
  if (!value || typeof value !== 'object') return null;
  const data = value as Partial<ResultAnalysis>;

  if (!Array.isArray(data.stats) && typeof data.interpretation !== 'string') {
    return null;
  }

  return {
    charts: Array.isArray(data.charts) ? data.charts : [],
    stats: Array.isArray(data.stats) ? data.stats : [],
    interpretation: typeof data.interpretation === 'string' ? data.interpretation : '',
    suggestions: Array.isArray(data.suggestions)
      ? data.suggestions.map((item) => String(item))
      : [],
  };
}

async function buildResultMessage(file: File): Promise<string> {
  let preview = '';

  if (
    file.type === 'text/csv'
    || file.type === 'application/json'
    || file.name.endsWith('.csv')
    || file.name.endsWith('.json')
  ) {
    try {
      preview = (await file.text()).slice(0, 8000);
    } catch {
      preview = '';
    }
  }

  return [
    '请分析以下实验结果文件，并解释关键指标、对比现象、可能原因、结论边界和改进建议。',
    '如果可以，请返回结构化 JSON，字段包含 stats、interpretation、suggestions。',
    '',
    `文件名：${file.name}`,
    `文件大小：${(file.size / 1024).toFixed(1)} KB`,
    preview ? `文件内容摘要：\n${preview}` : '文件内容摘要：当前文件无法在浏览器侧直接读取，请基于文件名和用户描述给出分析框架。',
  ].join('\n');
}

function ResultAnalyze() {
  const [file, setFile] = useState<File | null>(null);
  const [isAnalyzing, setIsAnalyzing] = useState(false);
  const [analysis, setAnalysis] = useState<ResultAnalysis | null>(null);
  const [chartReady, setChartReady] = useState(false);
  const [agentId, setAgentId] = useState<string | null>(null);
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const { addNotification } = useUIStore();

  useEffect(() => {
    const timer = setTimeout(() => setChartReady(true), 100);
    return () => clearTimeout(timer);
  }, []);

  useEffect(() => {
    const loadAgent = async () => {
      try {
        const response = await agentAPI.getAgents();
        const agents = Array.isArray(response.data) ? response.data as AgentItem[] : [];
        const agent = agents.find((item) => item.category === 'result-interpretation');
        if (!agent) {
          addNotification({
            type: 'warning',
            message: '未找到对应智能体，请检查 Supabase agents 表。',
            duration: 5000,
          });
          return;
        }
        setAgentId(agent.id);
      } catch (error) {
        addNotification({
          type: 'error',
          message: getErrorMessage(error),
          duration: 5000,
        });
      }
    };

    loadAgent();
  }, [addNotification]);

  const handleFileUpload = (event: React.ChangeEvent<HTMLInputElement>) => {
    const uploadedFile = event.target.files?.[0];
    if (!uploadedFile) return;
    const validTypes = ['text/csv', 'application/json', 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'];
    if (!validTypes.includes(uploadedFile.type) && !uploadedFile.name.endsWith('.csv')) {
      addNotification({ type: 'warning', message: '请上传 CSV/JSON/Excel 文件', duration: 3000 });
      return;
    }
    setFile(uploadedFile);
  };

  const handleAnalyze = async () => {
    if (isAnalyzing) return;

    if (!file) {
      addNotification({ type: 'warning', message: '请先上传数据文件', duration: 3000 });
      return;
    }

    if (!agentId) {
      addNotification({
        type: 'warning',
        message: '未找到对应智能体，请检查 Supabase agents 表。',
        duration: 5000,
      });
      return;
    }

    setIsAnalyzing(true);
    const userDisplay = `分析文件：${file.name}`;
    setMessages((prev) => [
      ...prev,
      {
        id: `user-${Date.now()}`,
        role: 'user',
        content: userDisplay,
      },
    ]);

    try {
      let currentConversationId = conversationId;
      if (!currentConversationId) {
        const conversationResponse = await conversationAPI.createConversation({
          agent_id: agentId,
          title: '结果分析对话',
        });
        currentConversationId = String(conversationResponse.data.id);
        setConversationId(currentConversationId);
      }

      const response = await conversationAPI.chat({
        conversation_id: currentConversationId,
        agent_id: agentId,
        message: await buildResultMessage(file),
      });

      const reply = String(response.data?.reply || '');
      setMessages((prev) => [
        ...prev,
        {
          id: `assistant-${Date.now()}`,
          role: 'assistant',
          content: reply,
        },
      ]);

      const parsedAnalysis = normalizeResultAnalysis(extractJsonObject(reply));
      if (parsedAnalysis) {
        setAnalysis(parsedAnalysis);
        setChartReady(true);
      }

      addNotification({ type: 'success', message: '数据分析完成', duration: 3000 });
    } catch (error) {
      addNotification({
        type: 'error',
        message: getErrorMessage(error) || '智能体调用失败，请检查后端或 Agent 配置。',
        duration: 5000,
      });
    } finally {
      setIsAnalyzing(false);
    }
  };

  const barChartOption = useMemo(() => {
    if (!chartReady || !analysis?.stats.length) return null;
    const metrics = analysis.stats.map((stat) => stat.metric);
    const values = analysis.stats.map((stat) => stat.mean);
    return {
      backgroundColor: 'transparent',
      grid: { left: '3%', right: '4%', bottom: '3%', containLabel: true },
      xAxis: {
        type: 'category' as const,
        data: metrics,
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
    return {
      backgroundColor: 'transparent',
      grid: { left: '3%', right: '4%', bottom: '3%', containLabel: true },
      xAxis: {
        type: 'category' as const,
        data: analysis.stats.map((stat) => stat.metric),
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
          name: 'Mean',
          data: analysis.stats.map((stat) => stat.mean),
          type: 'line' as const,
          smooth: true,
          lineStyle: { color: '#38bdf8', width: 2 },
          itemStyle: { color: '#38bdf8' },
        },
      ],
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
            disabled={isAnalyzing || !file}
            className="sci-btn-primary self-end"
          >
            {isAnalyzing ? (
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
      </div>

      {isAnalyzing && (
        <p className="text-sm text-sci-muted">智能体正在分析，请稍候……</p>
      )}

      {messages.length > 0 && (
        <div className="sci-card space-y-3">
          <h2 className="sci-section-title">对话记录</h2>
          {messages.map((message) => (
            <div
              key={message.id}
              className={`rounded-lg p-3 text-sm leading-relaxed whitespace-pre-wrap ${
                message.role === 'user'
                  ? 'bg-sci-primary/10 text-sci-ink'
                  : 'bg-sci-bg3 text-sci-muted'
              }`}
            >
              <p className="mb-1 text-xs font-medium opacity-70">
                {message.role === 'user' ? '你的问题' : '智能体回复'}
              </p>
              {message.content}
            </div>
          ))}
        </div>
      )}

      {analysis && (
        <div className="space-y-6">
          {analysis.stats.length > 0 && (
            <div>
              <h2 className="sci-section-title mb-4">图表分析</h2>
              <div className="grid md:grid-cols-2 gap-4">
                <div className="sci-card">
                  <h3 className="text-sm font-medium text-sci-muted mb-4">指标均值对比</h3>
                  {barChartOption ? (
                    <ReactECharts option={barChartOption} style={{ height: 250 }} />
                  ) : (
                    <div className="h-[250px] flex items-center justify-center text-sci-muted text-sm">
                      图表加载中...
                    </div>
                  )}
                </div>
                <div className="sci-card">
                  <h3 className="text-sm font-medium text-sci-muted mb-4">指标趋势视图</h3>
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
          )}

          {analysis.stats.length > 0 && (
            <div>
              <h2 className="sci-section-title mb-4">统计摘要</h2>
              <div className="grid md:grid-cols-3 gap-4">
                {analysis.stats.map((stat) => (
                  <div key={stat.metric} className="sci-card">
                    <div className="flex items-center justify-between mb-3">
                      <h3 className="font-semibold">{stat.metric}</h3>
                      {stat.p_value !== undefined && (
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
          )}

          <div className="grid md:grid-cols-2 gap-4">
            <div className="sci-card">
              <h3 className="sci-section-title mb-3">分析结论</h3>
              <p className="text-sm text-sci-muted leading-relaxed whitespace-pre-wrap">{analysis.interpretation}</p>
            </div>
            <div className="sci-card">
              <h3 className="sci-section-title mb-3">改进建议</h3>
              <ul className="space-y-2">
                {analysis.suggestions.map((suggestion, index) => (
                  <li key={`${suggestion}-${index}`} className="flex items-start gap-2 text-sm text-sci-muted">
                    <TrendingUp size={14} className="text-sci-success mt-0.5 flex-shrink-0" />
                    {suggestion}
                  </li>
                ))}
              </ul>
            </div>
          </div>

          <div className="flex justify-end gap-3">
            <button
              onClick={() => addNotification({ type: 'info', message: '导出功能开发中', duration: 3000 })}
              className="sci-btn-secondary"
            >
              <Download size={16} />
              导出图表
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

export default ResultAnalyze;
