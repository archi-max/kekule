import { NavLink } from 'react-router-dom';

const navItems = [
  { to: '/', label: 'Projects', icon: '{}' },
  { to: '/swarm', label: 'Swarm Monitor', icon: '>_' },
];

export default function Sidebar() {
  return (
    <aside className="w-56 border-r border-border bg-bg-card flex flex-col min-h-screen">
      <div className="px-5 py-5 border-b border-border">
        <h1 className="text-lg font-bold text-cyan tracking-tight">
          Kekule
        </h1>
        <p className="text-xs text-text-muted mt-0.5">Oracle Dashboard</p>
      </div>
      <nav className="flex-1 px-3 py-4 space-y-1">
        {navItems.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            end={item.to === '/'}
            className={({ isActive }) =>
              `flex items-center gap-3 px-3 py-2 rounded-md text-sm transition-colors ${
                isActive
                  ? 'bg-bg-hover text-cyan'
                  : 'text-text-muted hover:text-text hover:bg-bg-hover'
              }`
            }
          >
            <span className="font-mono text-xs w-5 text-center opacity-60">{item.icon}</span>
            {item.label}
          </NavLink>
        ))}
      </nav>
      <div className="px-5 py-4 border-t border-border">
        <p className="text-xs text-text-muted">v0.1.0</p>
      </div>
    </aside>
  );
}
