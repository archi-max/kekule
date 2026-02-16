import type { AgentStatus, SwarmMessage } from '../lib/api';
import StatusBadge from './StatusBadge';

export function AgentCard({ agent }: { agent: AgentStatus }) {
  return (
    <div className="border border-border rounded-lg p-3 bg-bg-card">
      <div className="flex items-center justify-between">
        <div>
          <span className="text-sm font-medium text-cyan">agent-{agent.agent_num}</span>
          <span className="text-xs text-text-muted ml-2">({agent.role})</span>
        </div>
        <StatusBadge status={agent.status} />
      </div>
      {agent.current_file && (
        <p className="text-xs font-mono text-text-muted mt-1.5 truncate">
          {agent.current_file}
        </p>
      )}
    </div>
  );
}

export function MessageFeed({ messages }: { messages: SwarmMessage[] }) {
  if (messages.length === 0) {
    return <p className="text-sm text-text-muted">No messages yet.</p>;
  }

  return (
    <div className="space-y-1.5 max-h-96 overflow-y-auto">
      {messages.map((msg) => (
        <div key={msg.seq} className="text-xs font-mono py-1 border-b border-border/50">
          <span className="text-cyan-dim">agent-{msg.agent_num}</span>
          <span className="text-text-muted mx-1">({msg.role})</span>
          <span className={`${msg.category === 'finding' ? 'text-amber' : 'text-text-muted'}`}>
            [{msg.category}]
          </span>
          <span className="text-text ml-1">{msg.content}</span>
        </div>
      ))}
    </div>
  );
}
