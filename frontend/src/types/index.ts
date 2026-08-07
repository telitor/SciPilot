// ==================== User Types ====================
export interface User {
  id: string;
  email: string;
  username: string;
  avatar_url?: string;
  role: 'user' | 'admin';
  created_at: string;
}

export interface AuthState {
  user: User | null;
  token: string | null;
  isAuthenticated: boolean;
  isLoading: boolean;
}

// ==================== Paper Types ====================
export interface Paper {
  id: string;
  title: string;
  authors: string[];
  abstract: string;
  url?: string;
  arxiv_id?: string;
  uploaded_at: string;
  status: 'uploading' | 'processing' | 'completed' | 'error';
}

export interface Citation {
  source: string;
  text: string;
  page?: number;
}

export interface ReportSection {
  heading: string;
  content: string;
  citations: Citation[];
}

export interface DeepReadReport {
  paper_id: string;
  sections: ReportSection[];
}

// ==================== Chat Types ====================
export interface Message {
  id: string;
  role: 'user' | 'assistant' | 'system';
  content: string;
  citations?: Citation[];
  created_at: string;
  isStreaming?: boolean;
}

export interface Conversation {
  id: string;
  title: string;
  module: string;
  agent_id?: string;
  messages: Message[];
  created_at: string;
  updated_at: string;
}

// ==================== Research Types ====================
export interface ResearchNode {
  id: string;
  question: string;
  feasibility: 'high' | 'medium' | 'low';
  datasets: string[];
  papers: string[];
  children?: ResearchNode[];
}

export interface ResearchTree {
  core_question: string;
  sub_questions: ResearchNode[];
}

// ==================== Experiment Types ====================
export interface ExperimentStep {
  step: number;
  task: string;
  details: string;
  estimated_days: number;
  status?: 'pending' | 'in_progress' | 'completed';
}

export interface Baseline {
  name: string;
  paper_id: string;
  github_url: string;
  stars?: number;
  description?: string;
}

export interface Dataset {
  name: string;
  size: string;
  language: string;
  url: string;
  description?: string;
}

export interface ExperimentRoadmap {
  objective: string;
  steps: ExperimentStep[];
  baselines: Baseline[];
  datasets: Dataset[];
  tools?: string[];
}

// ==================== Code Reproduction Types ====================
export interface RepoFile {
  name: string;
  path: string;
  type: 'file' | 'directory';
  children?: RepoFile[];
  size?: number;
}

export interface Dependency {
  name: string;
  version: string;
  purpose: string;
}

export interface ReproductionStep {
  step: number;
  instruction: string;
  command?: string;
  checked: boolean;
}

export interface CodeReproduction {
  repo_name: string;
  repo_url: string;
  language: string;
  stars: number;
  description: string;
  file_tree: RepoFile[];
  dependencies: Dependency[];
  steps: ReproductionStep[];
}

// ==================== Result Analysis Types ====================
export interface ChartData {
  type: 'bar' | 'line' | 'boxplot' | 'radar' | 'heatmap';
  title: string;
  data: unknown;
  options?: Record<string, unknown>;
}

export interface StatsSummary {
  metric: string;
  mean: number;
  std: number;
  min: number;
  max: number;
  ci95: [number, number];
  p_value?: number;
}

export interface ResultAnalysis {
  charts: ChartData[];
  stats: StatsSummary[];
  interpretation: string;
  suggestions: string[];
}

// ==================== Knowledge Graph Types ====================
export interface KGNode {
  id: string;
  label: string;
  category: string;
  description?: string;
  x?: number;
  y?: number;
}

export interface KGEdge {
  source: string;
  target: string;
  relation: string;
  strength?: number;
}

export interface KnowledgeGraph {
  nodes: KGNode[];
  edges: KGEdge[];
}

// ==================== External Spark Knowledge Base Types ====================
export interface KnowledgeCitation {
  index: number;
  document_id: string;
  chunk_id?: string | null;
  title: string;
  chunk_index?: number;
  file_name?: string | null;
  score?: number;
  excerpt: string;
}

export interface XunfeiKnowledgeFile {
  file_id: string;
  file_name: string;
  status: string;
  extension?: string | null;
  created_at?: string | null;
}

export interface KnowledgeBaseStatus {
  provider: 'xunfei-chatdoc' | string;
  configured: boolean;
  ready: boolean;
  repository_name?: string | null;
  document_count: number;
  vectored_count: number;
  files: XunfeiKnowledgeFile[];
  reason?: string | null;
}

export interface KnowledgeSearchResponse {
  query: string;
  citations: KnowledgeCitation[];
  total: number;
  provider: 'xunfei-chatdoc' | string;
}

export interface KnowledgeAnswerResponse extends KnowledgeSearchResponse {
  answer: string;
  model?: string | null;
}

// ==================== Knowledge-enabled Agent Types ====================
export type AgentCategory =
  | 'paper-reading'
  | 'problem-decomposition'
  | 'project-planning'
  | 'code-reproduction'
  | 'result-interpretation';

export interface PublicAgent {
  id: string;
  name: string;
  description?: string | null;
  category: AgentCategory | string;
  is_public: boolean;
  created_at?: string;
}

export interface AgentKnowledgeAskRequest {
  message: string;
  top_k?: number;
}

export interface AgentKnowledgeCitation {
  index?: number;
  document_id?: string;
  chunk_id?: string;
  title: string;
  excerpt?: string;
  content?: string;
  source_url?: string | null;
  file_name?: string | null;
  score?: number;
}

export interface AgentKnowledgeAnswerResponse {
  reply: string;
  citations: AgentKnowledgeCitation[];
  knowledge_used: boolean;
  agent: PublicAgent;
}

// ==================== Dashboard Model Chat ====================
export interface ModelChatMessage {
  role: 'user' | 'assistant';
  content: string;
}

export interface DashboardChatStatus {
  available: boolean;
  fine_tuned: boolean;
  model?: string | null;
  provider?: string;
  transport?: string;
  reason?: string | null;
  knowledge_available?: boolean;
}

export interface DashboardChatResponse {
  reply: string;
  citations: KnowledgeCitation[];
  model?: string | null;
  knowledge_used: boolean;
  knowledge_unavailable?: boolean;
}

// ==================== UI Types ====================
export interface Notification {
  id: string;
  type: 'success' | 'error' | 'warning' | 'info';
  message: string;
  duration?: number;
}

export type Theme = 'dark' | 'light' | 'system';
