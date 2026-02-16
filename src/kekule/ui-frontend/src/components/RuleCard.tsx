import type { Rule } from '../lib/api';
import StatusBadge from './StatusBadge';

export default function RuleCard({ rule }: { rule: Rule }) {
  return (
    <div className="border border-border rounded-lg p-4 bg-bg-card hover:bg-bg-hover transition-colors">
      <div className="flex items-start justify-between gap-3">
        <div className="flex-1 min-w-0">
          <p className="text-sm text-text leading-relaxed">{rule.description}</p>
          <div className="flex items-center gap-3 mt-2">
            <span className="text-xs font-mono text-cyan-dim">{rule.oracle_type}</span>
            {rule.uncertainty > 0 && (
              <span className="text-xs text-text-muted">
                uncertainty: {rule.uncertainty.toFixed(1)}
              </span>
            )}
            <span className="text-xs text-text-muted font-mono">{rule.id}</span>
          </div>
        </div>
        <StatusBadge status={rule.status} />
      </div>
    </div>
  );
}
