import { Routes, Route } from 'react-router-dom'
import Sidebar from './components/Sidebar'
import ProjectList from './pages/ProjectList'
import ProjectDetail from './pages/ProjectDetail'
import SwarmMonitor from './pages/SwarmMonitor'

export default function App() {
  return (
    <div className="flex min-h-screen">
      <Sidebar />
      <main className="flex-1 px-8 py-6 max-w-5xl">
        <Routes>
          <Route path="/" element={<ProjectList />} />
          <Route path="/project/:projectId" element={<ProjectDetail />} />
          <Route path="/swarm" element={<SwarmMonitor />} />
        </Routes>
      </main>
    </div>
  )
}
