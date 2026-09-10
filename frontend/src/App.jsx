import React, { useState, useEffect } from 'react';
import { BrowserRouter, Routes, Route, Navigate, Link, useLocation } from 'react-router-dom';
import { Layers3, MessageSquare, Sliders, Activity, Server, Cpu } from 'lucide-react';
import { useProjectStore } from './store/projectStore';
import { api } from './api/client';

// Pages (to be implemented)
import Dashboard from './pages/Dashboard';
import JamSession from './pages/JamSession';
import Understanding from './pages/Understanding';
import Workflow from './pages/Workflow';
import PhaseCockpit from './pages/PhaseCockpit';

import Connectors from './pages/Connectors';
import Health from './pages/Health';

const Sidebar = () => {
  const location = useLocation();
  const { project, understanding, currentPhaseId } = useProjectStore();

  // Extract project ID from URL path: /project/:id/...
  const urlMatch = location.pathname.match(/^\/project\/([^/]+)/);
  const projectId = urlMatch ? urlMatch[1] : project?.id || 'current';
  const hasProject = !!(urlMatch || project || understanding);
  
  const navItems = [
    { name: 'Dashboard', path: '/dashboard', icon: <Layers3 size={16} /> },
  ];

  if (hasProject) {
    navItems.push(
      { name: 'Jam Session', path: `/project/${projectId}/jam`, icon: <MessageSquare size={16} /> },
      { name: 'Understanding', path: `/project/${projectId}/understanding`, icon: <Cpu size={16} /> },
      { name: 'Workflow', path: `/project/${projectId}/workflow`, icon: <Sliders size={16} /> },
      { name: 'Phase Execution', path: `/project/${projectId}/phase/${currentPhaseId || 1}`, icon: <Server size={16} /> },
      { name: 'Connectors', path: `/project/${projectId}/connectors`, icon: <Server size={16} /> },
      { name: 'Health & Impact', path: `/project/${projectId}/health`, icon: <Activity size={16} /> }
    );
  }

  return (
    <div className="sidebar">
      <div className="sidebar-header">
        <div className="sidebar-title">TETRIS.OS</div>
        <div className="sidebar-subtitle">Idea Execution Engine</div>
      </div>
      <div className="sidebar-nav">
        <div className="sidebar-section-title">COMMAND CENTER</div>
        {navItems.map((item) => (
          <Link
            key={item.path}
            to={item.path}
            style={{ textDecoration: 'none' }}
          >
            <div className={`sidebar-item ${location.pathname.startsWith(item.path) ? 'active' : ''}`}>
              {item.icon} {item.name}
            </div>
          </Link>
        ))}
      </div>
      <div className="sidebar-footer">
        v1.0.0-release<br />
        System Online
      </div>
    </div>
  );
};

const Topbar = () => {
  const [health, setHealth] = useState({ ok: null, label: 'Checking...' });

  useEffect(() => {
    let cancelled = false;

    const check = async () => {
      const result = await api.checkHealth();
      if (cancelled) return;
      if (result.ok) {
        setHealth({ ok: true, label: 'Backend Connected' });
      } else {
        // Show the actual error — not a static string
        const errMsg = result.error || 'Unreachable';
        setHealth({ ok: false, label: `Backend Offline — ${errMsg}` });
      }
    };

    check();
    const interval = setInterval(check, 30_000);
    return () => { cancelled = true; clearInterval(interval); };
  }, []);

  const dotStyle = {
    width: '8px',
    height: '8px',
    borderRadius: '50%',
    background: health.ok === true ? 'var(--green)' : health.ok === false ? 'var(--red)' : 'var(--text-4)',
    flexShrink: 0,
  };

  return (
    <div className="topbar">
      <div className="topbar-left">
        <div style={dotStyle}></div>
        <div className="status-text" style={{ color: health.ok === false ? 'var(--red)' : undefined }}>
          {health.label}
        </div>
      </div>
      <div className="topbar-right">
        {health.ok === true ? 'Execution Ready' : 'Not Ready'}
      </div>
    </div>
  );
};

const Layout = ({ children }) => {
  return (
    <div className="app-container">
      <Sidebar />
      <div className="main-area">
        <Topbar />
        <div className="content-body" style={{ flex: 1, overflow: 'auto', display: 'flex', flexDirection: 'column' }}>
          {children}
        </div>
      </div>
    </div>
  );
};

export default function App() {
  return (
    <BrowserRouter>
      <Layout>
        <Routes>
          <Route path="/" element={<Navigate to="/dashboard" replace />} />
          <Route path="/dashboard" element={<Dashboard />} />
          <Route path="/project/:id/jam" element={<JamSession />} />
          <Route path="/project/:id/understanding" element={<Understanding />} />
          <Route path="/project/:id/workflow" element={<Workflow />} />
          <Route path="/project/:id/phase/:phaseId" element={<PhaseCockpit />} />
          <Route path="/project/:id/connectors" element={<Connectors />} />
          <Route path="/project/:id/health" element={<Health />} />
        </Routes>
      </Layout>
    </BrowserRouter>
  );
}
