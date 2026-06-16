export interface FileEntry {
  path: string;
  type: 'dir' | 'file';
  ext?: string;
}

export interface FilesResponse {
  root: string;
  entries: FileEntry[];
}

export interface GraphNode {
  id: string;
  name: string;
  qualified_name: string;
  file: string;
  relative_file: string;
  class_name: string | null;
  start_line: number;
  end_line: number;
  language: string;
  stable_key: string;
  is_entrypoint: boolean;
  depth: number;
  source_code: string;
  summary: string;
  description: string;
}

export interface GraphEdge {
  id: string;
  source: string;
  target: string;
  confidence: 'definite' | 'possible';
  semantic_label: string;
}

export interface GraphStats {
  nodes: number;
  edges: number;
}

export interface GraphResponse {
  scope_file: string;
  collection_root: string;
  nodes: GraphNode[];
  edges: GraphEdge[];
  entrypoints: string[];
  stats: GraphStats;
}

export interface FlowSummaryRequest {
  scope_file: string;
  start_node_id: string;
  context_path?: string[];
  regenerate?: boolean;
}

export interface FlowSummaryResponse {
  start_node_id: string;
  summary: string;
  edge_labels: Record<string, string>;
  nodes_in_view: string[];
  truncated: boolean;
}

export interface HealthResponse {
  ok: boolean;
  project_root: string;
  llm: string;
}

export interface ApiError {
  error: string;
}