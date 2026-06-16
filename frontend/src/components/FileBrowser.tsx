import { useCallback, useEffect, useState } from 'react';
import { fetchFiles } from '../api';
import type { FileEntry } from '../types';
import { LoadingSpinner } from './LoadingSpinner';

interface FileBrowserProps {
  onFileSelect: (path: string) => void;
  selectedFile: string | null;
}

function splitPath(dir: string): string[] {
  if (!dir || dir === '.' || dir === '') return [];
  return dir.split('/').filter(Boolean);
}

export function FileBrowser({ onFileSelect, selectedFile }: FileBrowserProps) {
  const [currentDir, setCurrentDir] = useState('');
  const [entries, setEntries] = useState<FileEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const loadDir = useCallback(async (dir: string) => {
    setLoading(true);
    setError(null);
    try {
      const data = await fetchFiles(dir);
      setCurrentDir(dir);
      setEntries(
        [...data.entries].sort((a, b) => {
          if (a.type !== b.type) return a.type === 'dir' ? -1 : 1;
          return a.path.localeCompare(b.path);
        }),
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load directory');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadDir('');
  }, [loadDir]);

  const crumbs = splitPath(currentDir);

  const navigateTo = (index: number) => {
    if (index < 0) {
      void loadDir('');
      return;
    }
    const parts = crumbs.slice(0, index + 1);
    void loadDir(parts.join('/'));
  };

  const handleEntryClick = (entry: FileEntry) => {
    if (entry.type === 'dir') {
      void loadDir(entry.path);
    } else {
      onFileSelect(entry.path);
    }
  };

  return (
    <section className="file-browser panel">
      <header className="panel__header">
        <h2>Files</h2>
      </header>

      <nav className="breadcrumb" aria-label="Directory path">
        <button type="button" className="breadcrumb__item" onClick={() => navigateTo(-1)}>
          root
        </button>
        {crumbs.map((part, index) => (
          <span key={`${part}-${index}`} className="breadcrumb__segment">
            <span className="breadcrumb__sep">/</span>
            <button
              type="button"
              className="breadcrumb__item"
              onClick={() => navigateTo(index)}
            >
              {part}
            </button>
          </span>
        ))}
      </nav>

      <div className="file-browser__body">
        {loading && <LoadingSpinner label="Loading directory…" size="sm" />}
        {error && <p className="error-text">{error}</p>}
        {!loading && !error && (
          <ul className="file-list">
            {entries.length === 0 && (
              <li className="file-list__empty">No supported files in this directory</li>
            )}
            {entries.map((entry) => {
              const isSelected = selectedFile === entry.path;
              return (
                <li key={entry.path}>
                  <button
                    type="button"
                    className={`file-list__item ${entry.type === 'dir' ? 'file-list__item--dir' : 'file-list__item--file'}${isSelected ? ' file-list__item--selected' : ''}`}
                    onClick={() => handleEntryClick(entry)}
                  >
                    <span className="file-list__icon" aria-hidden="true">
                      {entry.type === 'dir' ? '📁' : '📄'}
                    </span>
                    <span className="file-list__name">
                      {entry.path.split('/').pop() ?? entry.path}
                    </span>
                    {entry.ext && (
                      <span className="file-list__ext">{entry.ext}</span>
                    )}
                  </button>
                </li>
              );
            })}
          </ul>
        )}
      </div>
    </section>
  );
}