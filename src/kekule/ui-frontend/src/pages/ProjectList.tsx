import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { listProjects, createProject, type Project } from '../lib/api';
import StatusBadge from '../components/StatusBadge';

export default function ProjectList() {
  const [projects, setProjects] = useState<Project[]>([]);
  const [loading, setLoading] = useState(true);
  const [showCreate, setShowCreate] = useState(false);
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');

  const load = () => {
    listProjects()
      .then(setProjects)
      .catch(console.error)
      .finally(() => setLoading(false));
  };

  useEffect(load, []);

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!name.trim()) return;
    await createProject({ name: name.trim(), description: description.trim() });
    setName('');
    setDescription('');
    setShowCreate(false);
    load();
  };

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <h2 className="text-xl font-semibold text-cyan">Projects</h2>
        <button
          onClick={() => setShowCreate(!showCreate)}
          className="px-3 py-1.5 text-sm rounded-md bg-cyan/15 text-cyan border border-cyan/30 hover:bg-cyan/25 transition-colors"
        >
          {showCreate ? 'Cancel' : '+ New Project'}
        </button>
      </div>

      {showCreate && (
        <form onSubmit={handleCreate} className="mb-6 border border-border rounded-lg p-4 bg-bg-card">
          <input
            type="text"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="Project name"
            className="w-full bg-bg border border-border rounded px-3 py-2 text-sm text-text placeholder:text-text-muted focus:outline-none focus:border-cyan/50 mb-3"
            autoFocus
          />
          <textarea
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            placeholder="Describe the project goal..."
            rows={2}
            className="w-full bg-bg border border-border rounded px-3 py-2 text-sm text-text placeholder:text-text-muted focus:outline-none focus:border-cyan/50 mb-3 resize-none"
          />
          <button
            type="submit"
            className="px-4 py-1.5 text-sm rounded-md bg-cyan text-bg font-medium hover:bg-cyan-glow transition-colors"
          >
            Create Project
          </button>
        </form>
      )}

      {loading ? (
        <p className="text-sm text-text-muted">Loading...</p>
      ) : projects.length === 0 ? (
        <div className="text-center py-16 border border-border/50 rounded-lg border-dashed">
          <p className="text-text-muted mb-2">No projects yet</p>
          <p className="text-xs text-text-muted">Create a project to start defining rules and waypoints.</p>
        </div>
      ) : (
        <div className="space-y-3">
          {projects.map((p) => (
            <Link
              key={p.id}
              to={`/project/${p.id}`}
              className="block border border-border rounded-lg p-4 bg-bg-card hover:bg-bg-hover transition-colors"
            >
              <div className="flex items-center justify-between">
                <div>
                  <h3 className="text-sm font-medium text-text">{p.name}</h3>
                  {p.description && (
                    <p className="text-xs text-text-muted mt-1">{p.description}</p>
                  )}
                </div>
                <StatusBadge status={p.status} />
              </div>
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}
