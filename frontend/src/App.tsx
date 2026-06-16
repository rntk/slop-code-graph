import { useCallback, useEffect, useState } from 'react';
import { fetchGraph, fetchHealth } from './api';
import { FileBrowser } from './components/FileBrowser';
import { FlowExplorer } from './components/FlowExplorer';
import type { GraphResponse } from './types';

export default function App() {
  const [selectedFile, setSelectedFile] = useState<string | null>(null);
  const [graph, setGraph] = useState<GraphResponse | null>(null);
  const [loadingGraph, setLoadingGraph] = useState(false);
  const [graphError, setGraphError] = useState<string | null>(null);
  const [healthInfo, setHealthInfo] = useState<string | null>(null);

  useEffect(() => {
    fetchHealth()
      .then((h) => {
        if (h.ok) {
          setHealthInfo(`${h.project_root} · ${h.llm}`);
        }
      })
      .catch(() => {
        setHealthInfo(null);
      });
  }, []);

  const handleFileSelect = useCallback(async (path: string) => {
    setSelectedFile(path);
    setGraph(null);
    setGraphError(null);
    setLoadingGraph(true);

    try {
      const data = await fetchGraph(path);
      setGraph(data);
    } catch (err) {
      setGraphError(err instanceof Error ? err.message : 'Failed to build graph');
    } finally {
      setLoadingGraph(false);
    }
  }, []);

  return (
    <div className="app">
      <header className="app-header">
        <div className="app-header__brand">
          <h1>Traverse</h1>
          <p className="app-header__tagline">Explore code flows with context</p>
        </div>
        {healthInfo && <p className="app-header__health">{healthInfo}</p>}
      </header>

      <main className="app-layout">
        <FileBrowser onFileSelect={handleFileSelect} selectedFile={selectedFile} />
        <FlowExplorer
          graph={graph}
          loadingGraph={loadingGraph}
          graphError={graphError}
        />
      </main>
    </div>
  );
}