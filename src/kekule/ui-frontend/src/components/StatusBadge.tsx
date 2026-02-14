const statusColors: Record<string, string> = {
  // Rule statuses
  draft: 'bg-amber/15 text-amber border-amber/30',
  confirmed: 'bg-cyan/15 text-cyan border-cyan/30',
  verified: 'bg-green/15 text-green border-green/30',
  // Waypoint statuses
  pending: 'bg-text-muted/15 text-text-muted border-text-muted/30',
  active: 'bg-cyan/15 text-cyan border-cyan/30',
  passed: 'bg-green/15 text-green border-green/30',
  failed: 'bg-red/15 text-red border-red/30',
  // Project statuses
  setup: 'bg-amber/15 text-amber border-amber/30',
  completed: 'bg-green/15 text-green border-green/30',
  archived: 'bg-text-muted/15 text-text-muted border-text-muted/30',
  // Agent statuses
  exploring: 'bg-cyan/15 text-cyan border-cyan/30',
  fixing: 'bg-amber/15 text-amber border-amber/30',
  verifying: 'bg-cyan-dim/15 text-cyan-dim border-cyan-dim/30',
  done: 'bg-green/15 text-green border-green/30',
  unknown: 'bg-text-muted/15 text-text-muted border-text-muted/30',
};

export default function StatusBadge({ status }: { status: string }) {
  const colors = statusColors[status] || statusColors.unknown;
  return (
    <span className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-medium border ${colors}`}>
      {status}
    </span>
  );
}
