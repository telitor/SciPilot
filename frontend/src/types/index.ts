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
  project_id?: string | null;
  title: string;
  authors: string[];
  abstract: string;
  url?: string;
  arxiv_id?: string;
  uploaded_at: string;
  status: 'uploading' | 'processing' | 'completed' | 'error';
  knowledge_sync?: PaperKnowledgeSync;
}

export type PaperKnowledgeSyncStatus =
  | 'not_configured'
  | 'unavailable'
  | 'not_started'
  | 'pending'
  | 'uploaded'
  | 'processing'
  | 'vectored'
  | 'failed';

export interface PaperKnowledgeSync {
  provider: 'xunfei-chatdoc' | string;
  status: PaperKnowledgeSyncStatus;
  error_message?: string | null;
  attempt_count: number;
  last_attempt_at?: string | null;
  vectored_at?: string | null;
  updated_at?: string | null;
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

export type ResearchJobStatus =
  | 'pending'
  | 'running'
  | 'succeeded'
  | 'failed'
  | 'cancelled';

export interface ResearchJob {
  id: string;
  project_id?: string | null;
  paper_id?: string | null;
  job_type: string;
  status: ResearchJobStatus;
  progress: number;
  result?: Record<string, unknown>;
  error_message?: string | null;
  error_code?: string | null;
  attempts: number;
  max_attempts: number;
  created_at: string;
  updated_at: string;
  started_at?: string | null;
  completed_at?: string | null;
}

export interface PaperUploadJob {
  job_id: string;
  paper_id: string;
  status: ResearchJobStatus;
  progress: number;
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
  project_id?: string | null;
  title: string;
  module: string;
  agent_id?: string;
  status?: 'active' | 'archived';
  context?: Record<string, unknown>;
  messages: Message[];
  created_at: string;
  updated_at: string;
}

// ==================== Research Types ====================
export type ArtifactReviewStatus = 'draft' | 'confirmed' | 'deprecated';

export interface ArtifactVersionMetadata {
  id?: string;
  project_id?: string | null;
  review_status?: ArtifactReviewStatus;
  version_group_id?: string;
  version?: number;
  parent_version_id?: string | null;
  confirmed_at?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
}

export interface ArtifactDetail<TContent extends Record<string, unknown> = Record<string, unknown>>
  extends ArtifactVersionMetadata {
  id: string;
  artifact_type: string;
  title: string;
  content: TContent;
  review_status: ArtifactReviewStatus;
  version_group_id: string;
  version: number;
}

export interface ArtifactVersionSummary {
  id: string;
  title: string;
  review_status: ArtifactReviewStatus;
  version: number;
  parent_version_id?: string | null;
  confirmed_at?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
}

export interface ArtifactVersionList {
  version_group_id: string;
  latest_version: number;
  items: ArtifactVersionSummary[];
}

export interface ResearchNode {
  id: string;
  question: string;
  feasibility: 'high' | 'medium' | 'low';
  datasets: string[];
  papers: string[];
  children?: ResearchNode[];
}

export interface ResearchTree extends ArtifactVersionMetadata {
  core_question: string;
  sub_questions: ResearchNode[];
  generation_mode?: string;
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

export interface ExperimentRoadmap extends ArtifactVersionMetadata {
  objective: string;
  steps: ExperimentStep[];
  baselines: Baseline[];
  datasets: Dataset[];
  tools?: string[];
  generation_mode?: string;
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

export interface CodeReproduction extends ArtifactVersionMetadata {
  repo_name: string;
  repo_url: string;
  language: string;
  stars: number;
  description: string;
  file_tree: RepoFile[];
  dependencies: Dependency[];
  steps: ReproductionStep[];
  generation_mode?: string;
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
  count?: number;
  p_value?: number;
}

export interface ResultAnalysis extends ArtifactVersionMetadata {
  charts: ChartData[];
  stats: StatsSummary[];
  interpretation: string;
  suggestions: string[];
  row_count?: number;
  generation_mode?: string;
}

// ==================== Research Project Types ====================
export type ResearchProjectStatus = 'draft' | 'active' | 'completed' | 'archived';
export type ResearchProjectStage =
  | 'discovery'
  | 'literature'
  | 'question'
  | 'experiment'
  | 'reproduction'
  | 'analysis'
  | 'completed';

export interface ResearchProject {
  id: string;
  user_id: string;
  name: string;
  objective?: string | null;
  status: ResearchProjectStatus;
  current_stage: ResearchProjectStage;
  metadata?: Record<string, unknown>;
  archived_at?: string | null;
  created_at: string;
  updated_at: string;
}

export interface ProjectAsset {
  id: string;
  title: string;
  status: string;
  project_id?: string | null;
  module?: string;
  artifact_type?: string;
  uploaded_at?: string;
  created_at?: string;
  updated_at?: string;
}

export interface ResearchProjectDetail extends ResearchProject {
  assets: {
    papers: ProjectAsset[];
    conversations: ProjectAsset[];
    artifacts: ProjectAsset[];
  };
  counts: {
    papers: number;
    conversations: number;
    artifacts: number;
  };
  recent_activities: Array<{
    id: string;
    module: string;
    action: string;
    target: string;
    created_at: string;
  }>;
}

export interface UnassignedProjectAssets {
  papers: ProjectAsset[];
  conversations: ProjectAsset[];
  artifacts: ProjectAsset[];
  counts: {
    papers: number;
    conversations: number;
    artifacts: number;
  };
}

export type ProjectMemoryType =
  | 'fact'
  | 'decision'
  | 'constraint'
  | 'preference'
  | 'lesson'
  | 'artifact-summary';

export type ProjectMemoryStatus = 'active' | 'archived';

export interface ProjectMemory {
  id: string;
  project_id: string;
  memory_type: ProjectMemoryType;
  title: string;
  content: string;
  source_type: 'manual' | 'artifact';
  source_id?: string | null;
  source_version?: number | null;
  status: ProjectMemoryStatus;
  created_at?: string;
  updated_at?: string;
}

export interface ProjectMemoryList {
  items: ProjectMemory[];
  total: number;
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
  rerank_score?: number;
  matched_queries?: string[];
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
  retrieval_queries?: string[];
  candidate_count?: number;
  rerank_mode?: string;
  retrieval_degraded?: boolean;
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
  conversation_id?: string | null;
  persistence_unavailable?: boolean;
}

// ==================== UI Types ====================
export interface Notification {
  id: string;
  type: 'success' | 'error' | 'warning' | 'info';
  message: string;
  duration?: number;
}

export type Theme = 'dark' | 'light' | 'system';
