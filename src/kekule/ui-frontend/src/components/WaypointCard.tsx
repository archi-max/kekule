import type { Waypoint } from '../lib/api';
import StatusBadge from './StatusBadge';

export default function WaypointCard({
  waypoint,
  onApprove,
  onReject,
}: {
  waypoint: Waypoint;
  onApprove?: () => void;
  onReject?: () => void;
}) {
  return (
    <div className="border border-border rounded-lg p-4 bg-bg-card hover:bg-bg-hover transition-colors">
      <div className="flex items-start justify-between gap-3">
        <div className="flex-1 min-w-0">
          <p className="text-sm font-medium text-text">{waypoint.description}</p>
          <div className="flex items-center gap-3 mt-2">
            <span className="text-xs text-text-muted">
              {waypoint.rule_ids.length} rule{waypoint.rule_ids.length !== 1 ? 's' : ''}
            </span>
            {waypoint.git_ref && (
              <span className="text-xs font-mono text-cyan-dim">{waypoint.git_ref.slice(0, 8)}</span>
            )}
            <span className="text-xs text-text-muted font-mono">{waypoint.id}</span>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <StatusBadge status={waypoint.status} />
          {waypoint.status === 'pending' && (
            <>
              {onApprove && (
                <button
                  onClick={onApprove}
                  className="px-2 py-1 text-xs rounded bg-green/15 text-green border border-green/30 hover:bg-green/25 transition-colors"
                >
                  Approve
                </button>
              )}
              {onReject && (
                <button
                  onClick={onReject}
                  className="px-2 py-1 text-xs rounded bg-red/15 text-red border border-red/30 hover:bg-red/25 transition-colors"
                >
                  Reject
                </button>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  );
}
