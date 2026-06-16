import type {
  FilesResponse,
  FlowSummaryRequest,
  FlowSummaryResponse,
  GraphResponse,
  HealthResponse,
} from './types';

const API_BASE = import.meta.env.VITE_API_BASE ?? '';

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    headers: {
      'Content-Type': 'application/json',
      ...init?.headers,
    },
    ...init,
  });

  if (!response.ok) {
    let message = `Request failed (${response.status})`;
    try {
      const body = (await response.json()) as { error?: string };
      if (body.error) message = body.error;
    } catch {
      // ignore parse errors
    }
    throw new Error(message);
  }

  return response.json() as Promise<T>;
}

export function fetchFiles(dir = ''): Promise<FilesResponse> {
  const params = new URLSearchParams();
  if (dir) params.set('dir', dir);
  const query = params.toString();
  return request<FilesResponse>(`/api/files${query ? `?${query}` : ''}`);
}

export function fetchGraph(file: string): Promise<GraphResponse> {
  return request<GraphResponse>('/api/graph', {
    method: 'POST',
    body: JSON.stringify({ file }),
  });
}

export function fetchFlowSummary(
  payload: FlowSummaryRequest,
): Promise<FlowSummaryResponse> {
  return request<FlowSummaryResponse>('/api/flow/summary', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export function fetchHealth(): Promise<HealthResponse> {
  return request<HealthResponse>('/api/health');
}