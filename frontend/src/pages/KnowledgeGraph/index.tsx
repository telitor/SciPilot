import { FormEvent, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import axios from 'axios';
import {
  AlertCircle,
  Info,
  Loader2,
  Maximize2,
  RefreshCw,
  Search,
  Share2,
  ZoomIn,
  ZoomOut,
} from 'lucide-react';
import { kgAPI } from '@/services/api';
import type { KGEdge, KGNode, KnowledgeGraph as KnowledgeGraphData } from '@/types';

const categoryColors: Record<string, string> = {
  concept: '#38bdf8',
  technique: '#8b5cf6',
  dataset: '#10b981',
  paper: '#f59e0b',
  tool: '#ef4444',
};

const categoryLabels: Record<string, string> = {
  concept: '概念',
  technique: '技术',
  dataset: '数据集',
  paper: '论文',
  tool: '工具',
};

function getErrorMessage(error: unknown) {
  if (axios.isAxiosError(error)) {
    return (
      (error.response?.data as { detail?: string } | undefined)?.detail ||
      '知识图谱加载失败，请检查数据库迁移和后端服务。'
    );
  }
  return '知识图谱加载失败，请检查数据库迁移和后端服务。';
}

function KnowledgeGraphCanvas({
  graph,
}: {
  graph: KnowledgeGraphData;
}) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [nodes, setNodes] = useState<KGNode[]>([]);
  const [scale, setScale] = useState(1);
  const [offset, setOffset] = useState({ x: 0, y: 0 });
  const [dragging, setDragging] = useState<string | null>(null);
  const [hoveredNode, setHoveredNode] = useState<KGNode | null>(null);
  const [isPanning, setIsPanning] = useState(false);
  const [panStart, setPanStart] = useState({ x: 0, y: 0 });

  useEffect(() => {
    setNodes((previous) =>
      graph.nodes.map((node, index) => {
        const existing = previous.find((item) => item.id === node.id);
        if (existing?.x != null && existing.y != null) {
          return { ...node, x: existing.x, y: existing.y };
        }
        const angle = (index / Math.max(graph.nodes.length, 1)) * Math.PI * 2;
        const ring = graph.nodes.length > 14 ? 225 : 190;
        return {
          ...node,
          x: 400 + Math.cos(angle) * ring,
          y: 300 + Math.sin(angle) * ring,
        };
      })
    );
    setHoveredNode(null);
  }, [graph.nodes]);

  const draw = useCallback(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const context = canvas.getContext('2d');
    if (!context) return;

    context.clearRect(0, 0, canvas.width, canvas.height);

    graph.edges.forEach((edge) => {
      const source = nodes.find((node) => node.id === edge.source);
      const target = nodes.find((node) => node.id === edge.target);
      if (
        !source ||
        !target ||
        source.x == null ||
        source.y == null ||
        target.x == null ||
        target.y == null
      ) {
        return;
      }

      context.beginPath();
      context.moveTo((source.x + offset.x) * scale, (source.y + offset.y) * scale);
      context.lineTo((target.x + offset.x) * scale, (target.y + offset.y) * scale);
      context.strokeStyle = `rgba(100, 116, 139, ${edge.strength || 0.5})`;
      context.lineWidth = (edge.strength || 0.5) * 2;
      context.stroke();

      const midX = ((source.x + target.x) / 2 + offset.x) * scale;
      const midY = ((source.y + target.y) / 2 + offset.y) * scale;
      context.fillStyle = '#64748b';
      context.font = '10px Inter';
      context.textAlign = 'center';
      context.fillText(edge.relation, midX, midY);
    });

    nodes.forEach((node) => {
      if (node.x == null || node.y == null) return;
      const x = (node.x + offset.x) * scale;
      const y = (node.y + offset.y) * scale;
      const radius = 30 * scale;
      const color = categoryColors[node.category] || '#38bdf8';

      context.beginPath();
      context.arc(x, y, radius, 0, Math.PI * 2);
      context.fillStyle = '#0f172a';
      context.fill();
      context.strokeStyle = color;
      context.lineWidth = 2;
      context.stroke();

      context.beginPath();
      context.arc(x, y, radius + 4, 0, Math.PI * 2);
      context.strokeStyle = `${color}33`;
      context.lineWidth = 4;
      context.stroke();

      context.fillStyle = '#f1f5f9';
      context.font = `bold ${12 * scale}px Inter`;
      context.textAlign = 'center';
      context.textBaseline = 'middle';
      const label = node.label.length > 16 ? `${node.label.slice(0, 14)}…` : node.label;
      context.fillText(label, x, y);

      context.beginPath();
      context.arc(x + radius * 0.7, y - radius * 0.7, 5 * scale, 0, Math.PI * 2);
      context.fillStyle = color;
      context.fill();
    });
  }, [graph.edges, nodes, offset, scale]);

  useEffect(() => {
    draw();
  }, [draw]);

  const canvasPoint = (event: React.MouseEvent) => {
    const canvas = canvasRef.current;
    const rect = canvas?.getBoundingClientRect();
    if (!canvas || !rect) return null;
    return {
      x: (event.clientX - rect.left) * (canvas.width / rect.width),
      y: (event.clientY - rect.top) * (canvas.height / rect.height),
    };
  };

  const handleMouseDown = (event: React.MouseEvent) => {
    const point = canvasPoint(event);
    if (!point) return;
    const x = point.x / scale - offset.x;
    const y = point.y / scale - offset.y;
    const clickedNode = nodes.find((node) => {
      if (node.x == null || node.y == null) return false;
      return Math.hypot(node.x - x, node.y - y) < 30;
    });

    if (clickedNode) {
      setDragging(clickedNode.id);
      return;
    }
    setIsPanning(true);
    setPanStart({
      x: point.x - offset.x * scale,
      y: point.y - offset.y * scale,
    });
  };

  const handleMouseMove = (event: React.MouseEvent) => {
    const point = canvasPoint(event);
    if (!point) return;
    const graphX = point.x / scale - offset.x;
    const graphY = point.y / scale - offset.y;
    const hovered = nodes.find((node) => {
      if (node.x == null || node.y == null) return false;
      return Math.hypot(node.x - graphX, node.y - graphY) < 30;
    });
    setHoveredNode(hovered || null);

    if (dragging) {
      setNodes((current) =>
        current.map((node) =>
          node.id === dragging ? { ...node, x: graphX, y: graphY } : node
        )
      );
    } else if (isPanning) {
      setOffset({
        x: (point.x - panStart.x) / scale,
        y: (point.y - panStart.y) / scale,
      });
    }
  };

  const handleMouseUp = () => {
    setDragging(null);
    setIsPanning(false);
  };

  const handleWheel = (event: React.WheelEvent) => {
    event.preventDefault();
    setScale((current) => Math.max(0.5, Math.min(2, current - event.deltaY * 0.001)));
  };

  return (
    <div className="relative">
      <canvas
        ref={canvasRef}
        width={800}
        height={600}
        className="w-full rounded-xl border border-sci-border bg-sci-bg2 cursor-grab active:cursor-grabbing"
        onMouseDown={handleMouseDown}
        onMouseMove={handleMouseMove}
        onMouseUp={handleMouseUp}
        onMouseLeave={handleMouseUp}
        onWheel={handleWheel}
      />

      {nodes.length === 0 && (
        <div className="pointer-events-none absolute inset-0 flex items-center justify-center">
          <div className="max-w-sm rounded-xl border border-sci-border bg-sci-bg2/95 p-5 text-center">
            <Share2 size={32} className="mx-auto mb-3 text-sci-border" />
            <p className="font-medium">暂无可显示的知识节点</p>
            <p className="mt-1 text-sm text-sci-muted">
              可清除搜索条件，或先导入并整理知识库资料。
            </p>
          </div>
        </div>
      )}

      <div className="absolute right-4 top-4 flex flex-col gap-2">
        <button
          type="button"
          onClick={() => setScale((current) => Math.min(2, current + 0.1))}
          className="rounded-lg border border-sci-border bg-sci-bg2 p-2 text-sci-muted hover:bg-sci-bg3"
          title="放大"
        >
          <ZoomIn size={16} />
        </button>
        <button
          type="button"
          onClick={() => setScale((current) => Math.max(0.5, current - 0.1))}
          className="rounded-lg border border-sci-border bg-sci-bg2 p-2 text-sci-muted hover:bg-sci-bg3"
          title="缩小"
        >
          <ZoomOut size={16} />
        </button>
        <button
          type="button"
          onClick={() => {
            setScale(1);
            setOffset({ x: 0, y: 0 });
          }}
          className="rounded-lg border border-sci-border bg-sci-bg2 p-2 text-sci-muted hover:bg-sci-bg3"
          title="重置视图"
        >
          <Maximize2 size={16} />
        </button>
      </div>

      {hoveredNode && (
        <div className="sci-card absolute bottom-4 left-4 max-w-xs animate-fade-in">
          <div className="mb-2 flex items-center gap-2">
            <div
              className="h-3 w-3 rounded-full"
              style={{ backgroundColor: categoryColors[hoveredNode.category] || '#38bdf8' }}
            />
            <span className="font-semibold">{hoveredNode.label}</span>
          </div>
          <p className="text-sm text-sci-muted">{hoveredNode.description || '暂无节点说明'}</p>
        </div>
      )}
    </div>
  );
}

function KnowledgeGraph() {
  const [searchQuery, setSearchQuery] = useState('');
  const [fullGraph, setFullGraph] = useState<KnowledgeGraphData>({ nodes: [], edges: [] });
  const [visibleGraph, setVisibleGraph] = useState<KnowledgeGraphData>({ nodes: [], edges: [] });
  const [loading, setLoading] = useState(true);
  const [searching, setSearching] = useState(false);
  const [error, setError] = useState('');
  const [hasSearched, setHasSearched] = useState(false);

  const loadGraph = useCallback(async () => {
    setLoading(true);
    setError('');
    setHasSearched(false);
    try {
      const response = await kgAPI.getGraph({ limit: 500 });
      const graph: KnowledgeGraphData = {
        nodes: response.data.nodes ?? [],
        edges: response.data.edges ?? [],
      };
      setFullGraph(graph);
      setVisibleGraph(graph);
    } catch (requestError) {
      setFullGraph({ nodes: [], edges: [] });
      setVisibleGraph({ nodes: [], edges: [] });
      setError(getErrorMessage(requestError));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadGraph();
  }, [loadGraph]);

  const handleSearch = async (event: FormEvent) => {
    event.preventDefault();
    const query = searchQuery.trim();
    if (!query) {
      setVisibleGraph(fullGraph);
      setHasSearched(false);
      setError('');
      return;
    }

    setSearching(true);
    setError('');
    try {
      const response = await kgAPI.searchNodes(query);
      const matchedNodes = (Array.isArray(response.data)
        ? response.data
        : response.data.items ?? []) as KGNode[];
      const matchedIds = new Set(matchedNodes.map((node) => node.id));
      const matchedEdges = fullGraph.edges.filter(
        (edge) => matchedIds.has(edge.source) && matchedIds.has(edge.target)
      );
      setVisibleGraph({ nodes: matchedNodes, edges: matchedEdges });
      setHasSearched(true);
    } catch (requestError) {
      setVisibleGraph({ nodes: [], edges: [] });
      setHasSearched(true);
      setError(getErrorMessage(requestError));
    } finally {
      setSearching(false);
    }
  };

  const categories = useMemo(
    () => Array.from(new Set(fullGraph.nodes.map((node) => node.category))),
    [fullGraph.nodes]
  );

  const relationCounts = useMemo(() => {
    const counts = new Map<string, number>();
    fullGraph.edges.forEach((edge: KGEdge) => {
      counts.set(edge.relation, (counts.get(edge.relation) || 0) + 1);
    });
    return Array.from(counts.entries())
      .sort((left, right) => right[1] - left[1])
      .slice(0, 4);
  }, [fullGraph.edges]);

  return (
    <div className="space-y-6 pb-20 md:pb-0">
      <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
        <div>
          <h1 className="text-2xl font-bold">知识图谱</h1>
          <p className="mt-1 text-sm text-sci-muted">
            展示科研概念、论文、技术、数据集与工具之间的结构化关系。
          </p>
        </div>
        <form onSubmit={handleSearch} className="flex w-full gap-2 lg:w-auto">
          <div className="relative flex-1 lg:w-72">
            <Search
              size={16}
              className="absolute left-3 top-1/2 -translate-y-1/2 text-sci-muted"
            />
            <input
              type="search"
              value={searchQuery}
              onChange={(event) => setSearchQuery(event.target.value)}
              placeholder="搜索概念或节点..."
              className="sci-input w-full pl-10"
            />
          </div>
          <button type="submit" className="sci-btn-primary" disabled={searching}>
            {searching ? <Loader2 size={16} className="animate-spin" /> : <Search size={16} />}
            搜索
          </button>
          <button
            type="button"
            onClick={() => {
              setSearchQuery('');
              setVisibleGraph(fullGraph);
              setHasSearched(false);
              setError('');
            }}
            className="sci-btn-secondary"
            title="清除搜索"
          >
            重置
          </button>
        </form>
      </div>

      {loading && (
        <div className="sci-card flex items-center gap-3 text-sm text-sci-muted">
          <Loader2 size={18} className="animate-spin text-sci-accent" />
          正在读取知识节点与关系...
        </div>
      )}

      {error && (
        <div className="rounded-xl border border-amber-500/30 bg-amber-500/10 p-5">
          <div className="flex items-start gap-3">
            <AlertCircle size={20} className="mt-0.5 flex-shrink-0 text-sci-warning" />
            <div className="flex-1">
              <h2 className="font-semibold text-sci-warning">知识图谱暂不可用</h2>
              <p className="mt-1 text-sm text-sci-muted">{error}</p>
              <p className="mt-2 text-xs text-sci-muted">
                若数据库尚未初始化，请依次执行 006_workspace_data_layer.sql 和
                007_seed_public_research_catalog.sql。
              </p>
              <button type="button" onClick={() => void loadGraph()} className="sci-btn-secondary mt-4">
                <RefreshCw size={15} />
                重新加载
              </button>
            </div>
          </div>
        </div>
      )}

      {!loading && !error && (
        <>
          <div className="flex flex-wrap items-center gap-4">
            {categories.map((category) => (
              <div key={category} className="flex items-center gap-2">
                <div
                  className="h-3 w-3 rounded-full"
                  style={{ backgroundColor: categoryColors[category] || '#38bdf8' }}
                />
                <span className="text-sm text-sci-muted">
                  {categoryLabels[category] || category}
                </span>
              </div>
            ))}
            <span className="ml-auto text-xs text-sci-muted">
              {hasSearched ? `搜索命中 ${visibleGraph.nodes.length} 个节点` : ''}
            </span>
          </div>

          <KnowledgeGraphCanvas graph={visibleGraph} />

          <div className="grid gap-4 md:grid-cols-3">
            <div className="sci-card">
              <div className="mb-3 flex items-center gap-2">
                <Share2 size={16} className="text-sci-accent" />
                <h3 className="font-semibold">关系类型</h3>
              </div>
              <div className="space-y-2 text-sm text-sci-muted">
                {relationCounts.map(([relation, count]) => (
                  <div key={relation} className="flex items-center gap-2">
                    <div className="h-px w-8 bg-sci-border" />
                    <span className="min-w-0 flex-1 truncate">{relation}</span>
                    <span>{count}</span>
                  </div>
                ))}
                {relationCounts.length === 0 && <p>暂无关系数据</p>}
              </div>
            </div>

            <div className="sci-card">
              <div className="mb-3 flex items-center gap-2">
                <Info size={16} className="text-sci-accent" />
                <h3 className="font-semibold">使用说明</h3>
              </div>
              <ul className="space-y-1 text-sm text-sci-muted">
                <li>拖拽节点可调整位置</li>
                <li>滚轮缩放画布</li>
                <li>悬停查看节点详情</li>
                <li>拖拽空白处平移画布</li>
              </ul>
            </div>

            <div className="sci-card">
              <div className="mb-3 flex items-center gap-2">
                <Search size={16} className="text-sci-accent" />
                <h3 className="font-semibold">图谱状态</h3>
              </div>
              <div className="space-y-2 text-sm text-sci-muted">
                <div className="flex justify-between">
                  <span>节点</span>
                  <strong className="text-sci-ink">{fullGraph.nodes.length}</strong>
                </div>
                <div className="flex justify-between">
                  <span>关系</span>
                  <strong className="text-sci-ink">{fullGraph.edges.length}</strong>
                </div>
                <div className="flex justify-between">
                  <span>类别</span>
                  <strong className="text-sci-ink">{categories.length}</strong>
                </div>
              </div>
            </div>
          </div>
        </>
      )}
    </div>
  );
}

export default KnowledgeGraph;
