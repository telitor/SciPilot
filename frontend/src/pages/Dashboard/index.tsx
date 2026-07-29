import { useCallback, useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  FileText,
  GitBranch,
  Route,
  Clock,
  Star,
  TrendingUp,
} from 'lucide-react';
import { useAuthStore } from '@/store/authStore';
import { dashboardAPI } from '@/services/api';
import { usePaperStore } from '@/store/paperStore';
import type { Paper } from '@/types';
import ResearchLauncher from '@/components/ResearchLauncher';

interface DashboardSummary {
  stats: {
    paper_count: number;
    experiment_count: number;
    code_reproduction_count: number;
  };
  recent_papers: Paper[];
  recent_activities: Array<{
    id: string;
    action: string;
    target: string;
    module: string;
    created_at: string;
  }>;
  trending: Array<{ title: string; papers: number; trend: string }>;
}

function Dashboard() {
  const navigate = useNavigate();
  const { user } = useAuthStore();
  const setCurrentPaper = usePaperStore((state) => state.setCurrentPaper);
  const [summary, setSummary] = useState<DashboardSummary | null>(null);
  const papers = summary?.recent_papers ?? [];
  const handleNavigate = useCallback((path: string) => navigate(path), [navigate]);

  useEffect(() => {
    dashboardAPI
      .getSummary()
      .then((response) => setSummary(response.data))
      .catch(() => undefined);
  }, []);

  return (
    <div className="space-y-6 pb-20 md:pb-0">
      <div className="dashboard-launcher-heading">
        <div>
          <span>研究工作区 / main</span>
          <h1>欢迎回来，{user?.username || '研究者'}</h1>
        </div>
        <p>选择一个模块，继续构建今天的研究提交。</p>
      </div>

      <ResearchLauncher compact initialIndex={2} onNavigate={handleNavigate} />

      <div className="grid lg:grid-cols-3 gap-6">
        {/* Recent Papers */}
        <div className="lg:col-span-2">
          <h2 className="sci-section-title mb-4">最近论文</h2>
          <div className="space-y-3">
            {papers.map((paper) => (
              <div
                key={paper.id}
                onClick={() => {
                  setCurrentPaper(paper);
                  navigate('/paper/read');
                }}
                className="sci-card cursor-pointer group"
              >
                <div className="flex items-start justify-between">
                  <div className="flex-1">
                    <h3 className="font-semibold group-hover:text-sci-accent transition-colors">
                      {paper.title}
                    </h3>
                    <p className="text-sm text-sci-muted mt-1">{paper.authors.join(', ')}</p>
                    <div className="flex items-center gap-3 mt-2">
                      <span className="sci-badge-info">{paper.arxiv_id}</span>
                      <span className="text-xs text-sci-muted flex items-center gap-1">
                        <Clock size={12} />
                        {new Date(paper.uploaded_at).toLocaleDateString('zh-CN')}
                      </span>
                    </div>
                  </div>
                  <Star size={18} className="text-sci-muted hover:text-sci-warning cursor-pointer" />
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* Sidebar Content */}
        <div className="space-y-6">
          {/* Stats */}
          <div>
            <h2 className="sci-section-title mb-4">学习进度</h2>
            <div className="sci-card space-y-4">
              <div>
                <div className="flex items-center justify-between text-sm mb-2">
                  <span className="text-sci-muted">本周论文</span>
                  <span className="text-sci-accent font-semibold">{summary?.stats.paper_count ?? 0}</span>
                </div>
                <div className="h-2 bg-sci-bg3 rounded-full overflow-hidden">
                  <div className="h-full bg-gradient-to-r from-sci-primary to-sci-accent rounded-full" style={{ width: `${Math.min(100, (summary?.stats.paper_count ?? 0) * 10)}%` }} />
                </div>
              </div>
              <div>
                <div className="flex items-center justify-between text-sm mb-2">
                  <span className="text-sci-muted">实验完成度</span>
                  <span className="text-sci-success font-semibold">{summary?.stats.experiment_count ?? 0}</span>
                </div>
                <div className="h-2 bg-sci-bg3 rounded-full overflow-hidden">
                  <div className="h-full bg-gradient-to-r from-sci-success to-emerald-400 rounded-full" style={{ width: `${Math.min(100, (summary?.stats.experiment_count ?? 0) * 20)}%` }} />
                </div>
              </div>
              <div>
                <div className="flex items-center justify-between text-sm mb-2">
                  <span className="text-sci-muted">代码复现</span>
                  <span className="text-sci-warning font-semibold">{summary?.stats.code_reproduction_count ?? 0}</span>
                </div>
                <div className="h-2 bg-sci-bg3 rounded-full overflow-hidden">
                  <div className="h-full bg-gradient-to-r from-sci-warning to-amber-400 rounded-full" style={{ width: `${Math.min(100, (summary?.stats.code_reproduction_count ?? 0) * 20)}%` }} />
                </div>
              </div>
            </div>
          </div>

          {/* Recent Activity */}
          <div>
            <h2 className="sci-section-title mb-4">最近活动</h2>
            <div className="sci-card space-y-4">
              {(summary?.recent_activities ?? []).map((activity) => {
                const Icon = activity.module === 'paper' ? FileText : activity.module === 'experiment' ? Route : GitBranch;
                return (
                  <div key={activity.id} className="flex items-start gap-3">
                    <div className="w-8 h-8 rounded-lg bg-sci-bg3 flex items-center justify-center flex-shrink-0">
                      <Icon size={14} className="text-sci-accent" />
                    </div>
                    <div className="flex-1 min-w-0">
                      <p className="text-sm font-medium">{activity.action}</p>
                      <p className="text-xs text-sci-muted truncate">{activity.target}</p>
                      <p className="text-xs text-sci-muted mt-1">{new Date(activity.created_at).toLocaleString('zh-CN')}</p>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        </div>
      </div>

      {/* Trending */}
      <div>
        <h2 className="sci-section-title mb-4">热门研究方向</h2>
        <div className="grid md:grid-cols-3 gap-4">
          {(summary?.trending ?? []).slice(0, 3).map((item) => (
            <div key={item.title} className="sci-card group cursor-pointer">
              <div className="flex items-center justify-between mb-2">
                <h3 className="font-medium group-hover:text-sci-accent transition-colors">{item.title}</h3>
                <TrendingUp size={16} className="text-sci-success" />
              </div>
              <div className="flex items-center gap-4 text-sm text-sci-muted">
                <span>公开资料 {item.papers} 条</span>
                <span className="text-sci-success">{item.trend}</span>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

export default Dashboard;
