import { useEffect, useState } from 'react';
import { useParams, Link } from 'react-router-dom';
import {
  getProject,
  listRules,
  listWaypoints,
  createRule,
  createWaypoint,
  approveWaypoint,
  rejectWaypoint,
  type Project,
  type Rule,
  type Waypoint,
} from '../lib/api';
import StatusBadge from '../components/StatusBadge';
import RuleCard from '../components/RuleCard';
import WaypointCard from '../components/WaypointCard';

export default function ProjectDetail() {
  const { projectId } = useParams<{ projectId: string }>();
  const [project, setProject] = useState<Project | null>(null);
  const [rules, setRules] = useState<Rule[]>([]);
  const [waypoints, setWaypoints] = useState<Waypoint[]>([]);
  const [tab, setTab] = useState<'rules' | 'waypoints'>('rules');
  const [showAddRule, setShowAddRule] = useState(false);
  const [showAddWp, setShowAddWp] = useState(false);
  const [ruleDesc, setRuleDesc] = useState('');
  const [ruleType, setRuleType] = useState('pytest');
  const [wpDesc, setWpDesc] = useState('');

  const load = () => {
    if (!projectId) return;
    getProject(projectId).then(setProject).catch(console.error);
    listRules(projectId).then(setRules).catch(console.error);
    listWaypoints(projectId).then(setWaypoints).catch(console.error);
  };

  useEffect(load, [projectId]);

  const handleAddRule = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!ruleDesc.trim() || !projectId) return;
    await createRule({ project_id: projectId, description: ruleDesc.trim(), oracle_type: ruleType });
    setRuleDesc('');
    setShowAddRule(false);
    load();
  };

  const handleAddWaypoint = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!wpDesc.trim() || !projectId) return;
    await createWaypoint({ project_id: projectId, description: wpDesc.trim() });
    setWpDesc('');
    setShowAddWp(false);
    load();
  };

  const handleApprove = async (wpId: string) => {
    await approveWaypoint(wpId);
    load();
  };

  const handleReject = async (wpId: string) => {
    await rejectWaypoint(wpId);
    load();
  };

  if (!project) return <p className="text-sm text-text-muted">Loading...</p>;

  return (
    <div>
      <div className="mb-6">
        <Link to="/" className="text-xs text-text-muted hover:text-cyan transition-colors">
          &larr; Projects
        </Link>
        <div className="flex items-center gap-3 mt-2">
          <h2 className="text-xl font-semibold text-cyan">{project.name}</h2>
          <StatusBadge status={project.status} />
        </div>
        {project.description && (
          <p className="text-sm text-text-muted mt-1">{project.description}</p>
        )}
      </div>

      {/* Tabs */}
      <div className="flex items-center gap-1 mb-4 border-b border-border">
        {(['rules', 'waypoints'] as const).map((t) => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={`px-4 py-2 text-sm font-medium transition-colors border-b-2 -mb-px ${
              tab === t
                ? 'border-cyan text-cyan'
                : 'border-transparent text-text-muted hover:text-text'
            }`}
          >
            {t === 'rules' ? `Rules (${rules.length})` : `Waypoints (${waypoints.length})`}
          </button>
        ))}
      </div>

      {/* Rules tab */}
      {tab === 'rules' && (
        <div>
          <div className="flex justify-end mb-3">
            <button
              onClick={() => setShowAddRule(!showAddRule)}
              className="px-3 py-1 text-xs rounded bg-cyan/15 text-cyan border border-cyan/30 hover:bg-cyan/25 transition-colors"
            >
              {showAddRule ? 'Cancel' : '+ Add Rule'}
            </button>
          </div>
          {showAddRule && (
            <form onSubmit={handleAddRule} className="mb-4 border border-border rounded-lg p-4 bg-bg-card">
              <textarea
                value={ruleDesc}
                onChange={(e) => setRuleDesc(e.target.value)}
                placeholder="Describe the acceptance criteria..."
                rows={2}
                className="w-full bg-bg border border-border rounded px-3 py-2 text-sm text-text placeholder:text-text-muted focus:outline-none focus:border-cyan/50 mb-3 resize-none"
                autoFocus
              />
              <div className="flex items-center gap-3">
                <select
                  value={ruleType}
                  onChange={(e) => setRuleType(e.target.value)}
                  className="bg-bg border border-border rounded px-3 py-1.5 text-sm text-text focus:outline-none focus:border-cyan/50"
                >
                  <option value="pytest">pytest</option>
                  <option value="e2e">e2e</option>
                  <option value="type_check">type_check</option>
                  <option value="lint">lint</option>
                  <option value="security">security</option>
                </select>
                <button
                  type="submit"
                  className="px-4 py-1.5 text-sm rounded bg-cyan text-bg font-medium hover:bg-cyan-glow transition-colors"
                >
                  Add Rule
                </button>
              </div>
            </form>
          )}
          {rules.length === 0 ? (
            <p className="text-sm text-text-muted text-center py-8">
              No rules yet. Add acceptance criteria for this project.
            </p>
          ) : (
            <div className="space-y-2">
              {rules.map((r) => (
                <RuleCard key={r.id} rule={r} />
              ))}
            </div>
          )}
        </div>
      )}

      {/* Waypoints tab */}
      {tab === 'waypoints' && (
        <div>
          <div className="flex justify-end mb-3">
            <button
              onClick={() => setShowAddWp(!showAddWp)}
              className="px-3 py-1 text-xs rounded bg-cyan/15 text-cyan border border-cyan/30 hover:bg-cyan/25 transition-colors"
            >
              {showAddWp ? 'Cancel' : '+ Add Waypoint'}
            </button>
          </div>
          {showAddWp && (
            <form onSubmit={handleAddWaypoint} className="mb-4 border border-border rounded-lg p-4 bg-bg-card">
              <input
                type="text"
                value={wpDesc}
                onChange={(e) => setWpDesc(e.target.value)}
                placeholder="Waypoint description..."
                className="w-full bg-bg border border-border rounded px-3 py-2 text-sm text-text placeholder:text-text-muted focus:outline-none focus:border-cyan/50 mb-3"
                autoFocus
              />
              <button
                type="submit"
                className="px-4 py-1.5 text-sm rounded bg-cyan text-bg font-medium hover:bg-cyan-glow transition-colors"
              >
                Add Waypoint
              </button>
            </form>
          )}
          {waypoints.length === 0 ? (
            <p className="text-sm text-text-muted text-center py-8">
              No waypoints yet. Add checkpoints to track progress.
            </p>
          ) : (
            <div className="space-y-2">
              {waypoints.map((wp) => (
                <WaypointCard
                  key={wp.id}
                  waypoint={wp}
                  onApprove={() => handleApprove(wp.id)}
                  onReject={() => handleReject(wp.id)}
                />
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
