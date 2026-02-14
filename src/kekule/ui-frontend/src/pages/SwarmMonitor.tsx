import { useEffect, useState } from 'react';
import {
  getSwarmStatus,
  getSwarmMessages,
  getSwarmConnected,
  type AgentStatus,
  type SwarmMessage,
} from '../lib/api';
import { AgentCard, MessageFeed } from '../components/AgentMonitor';

export default function SwarmMonitor() {
  const [agents, setAgents] = useState<AgentStatus[]>([]);
  const [messages, setMessages] = useState<SwarmMessage[]>([]);
  const [connected, setConnected] = useState({ bus_connected: false, tracker_connected: false });
  const [polling, setPolling] = useState(false);

  const load = () => {
    getSwarmConnected().then(setConnected).catch(console.error);
    getSwarmStatus().then(setAgents).catch(console.error);
    getSwarmMessages(0, 200).then(setMessages).catch(console.error);
  };

  useEffect(load, []);

  useEffect(() => {
    if (!polling) return;
    const interval = setInterval(load, 2000);
    return () => clearInterval(interval);
  }, [polling]);

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <h2 className="text-xl font-semibold text-cyan">Swarm Monitor</h2>
        <div className="flex items-center gap-3">
          <button
            onClick={() => setPolling(!polling)}
            className={`px-3 py-1.5 text-xs rounded-md border transition-colors ${
              polling
                ? 'bg-green/15 text-green border-green/30'
                : 'bg-bg-card text-text-muted border-border hover:text-text'
            }`}
          >
            {polling ? 'Live' : 'Paused'}
          </button>
          <button
            onClick={load}
            className="px-3 py-1.5 text-xs rounded-md bg-bg-card text-text-muted border border-border hover:text-text transition-colors"
          >
            Refresh
          </button>
        </div>
      </div>

      {/* Connection status */}
      <div className="flex items-center gap-4 mb-6 text-xs">
        <span className="flex items-center gap-1.5">
          <span className={`w-2 h-2 rounded-full ${connected.bus_connected ? 'bg-green' : 'bg-red'}`} />
          SwarmBus {connected.bus_connected ? 'connected' : 'disconnected'}
        </span>
        <span className="flex items-center gap-1.5">
          <span className={`w-2 h-2 rounded-full ${connected.tracker_connected ? 'bg-green' : 'bg-red'}`} />
          BeadsTracker {connected.tracker_connected ? 'connected' : 'disconnected'}
        </span>
      </div>

      {!connected.bus_connected ? (
        <div className="text-center py-16 border border-border/50 rounded-lg border-dashed">
          <p className="text-text-muted mb-2">No swarm running</p>
          <p className="text-xs text-text-muted">
            Start a swarm experiment to see live agent status and messages.
          </p>
        </div>
      ) : (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          {/* Agents */}
          <div>
            <h3 className="text-sm font-medium text-text-muted mb-3">
              Agents ({agents.length})
            </h3>
            <div className="space-y-2">
              {agents.map((a) => (
                <AgentCard key={a.agent_num} agent={a} />
              ))}
            </div>
          </div>

          {/* Messages */}
          <div>
            <h3 className="text-sm font-medium text-text-muted mb-3">
              Messages ({messages.length})
            </h3>
            <div className="border border-border rounded-lg p-3 bg-bg-card">
              <MessageFeed messages={messages} />
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
