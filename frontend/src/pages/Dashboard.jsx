import React, { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useProjectStore } from '../store/projectStore';
import { api } from '../api/client';
import {
  Plus,
  Globe,
  ExternalLink,
  Rocket,
  CheckCircle,
  AlertCircle,
  Clock,
  Loader,
  ChevronRight,
  Layers3,
  Activity,
  Zap,
} from 'lucide-react';

const PHASE_LABELS = {
  1: 'Build',
  2: 'Validate',
  3: 'Market',
  4: 'Launch',
};

const STATUS_CONFIG = {
  completed:  { color: 'var(--green)',  label: 'Completed',  icon: CheckCircle },
  APPROVED:   { color: 'var(--green)',  label: 'Approved',   icon: CheckCircle },
  running:    { color: 'var(--blue)',   label: 'Running',    icon: Loader },
  waiting_for_approval: { color: '#f59e0b', label: 'Awaiting Approval', icon: Clock },
  WAITING_FOR_APPROVAL: { color: '#f59e0b', label: 'Awaiting Approval', icon: Clock },
  FAILED:     { color: 'var(--red)',    label: 'Failed',     icon: AlertCircle },
  READY:      { color: 'var(--text-3)', label: 'Ready',      icon: Zap },
  LOCKED:     { color: 'var(--text-4)', label: 'Locked',     icon: null },
};

function StatusBadge({ status }) {
  const config = STATUS_CONFIG[status] || { color: 'var(--text-4)', label: status || 'Unknown', icon: null };
  const Icon = config.icon;
  return (
    <span style={{
      display: 'inline-flex',
      alignItems: 'center',
      gap: '5px',
      padding: '3px 10px',
      borderRadius: '99px',
      fontSize: '11px',
      fontFamily: 'var(--mono)',
      fontWeight: '600',
      color: config.color,
      background: `color-mix(in srgb, ${config.color} 12%, transparent)`,
      border: `1px solid color-mix(in srgb, ${config.color} 25%, transparent)`,
    }}>
      {Icon && <Icon size={12} />}
      {config.label}
    </span>
  );
}

function PhaseProgressBar({ phaseStatuses }) {
  if (!phaseStatuses) return null;
  const phases = [1, 2, 3, 4];
  return (
    <div style={{ display: 'flex', gap: '4px', marginTop: '10px' }}>
      {phases.map((ph) => {
        const st = phaseStatuses[String(ph)] || 'LOCKED';
        const color = st === 'APPROVED' ? 'var(--green)'
          : st === 'RUNNING' ? 'var(--blue)'
          : st === 'WAITING_FOR_APPROVAL' ? '#f59e0b'
          : st === 'READY' ? 'var(--text-3)'
          : 'var(--border)';
        return (
          <div key={ph} style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: '3px' }}>
            <div style={{
              height: '4px',
              borderRadius: '2px',
              background: color,
              transition: 'background 0.3s ease',
            }} />
            <span style={{
              fontSize: '9px',
              fontFamily: 'var(--mono)',
              color: st === 'LOCKED' ? 'var(--text-4)' : 'var(--text-3)',
              textAlign: 'center',
            }}>
              {PHASE_LABELS[ph]}
            </span>
          </div>
        );
      })}
    </div>
  );
}

function ProjectCard({ project, onOpenCockpit }) {
  return (
    <div style={{
      background: 'var(--surface)',
      border: '1px solid var(--border)',
      borderRadius: 'var(--radius)',
      padding: '20px',
      display: 'flex',
      flexDirection: 'column',
      gap: '12px',
      transition: 'border-color 0.2s ease, box-shadow 0.2s ease',
      cursor: 'pointer',
    }}
    onMouseEnter={(e) => {
      e.currentTarget.style.borderColor = 'var(--accent)';
      e.currentTarget.style.boxShadow = '0 0 0 1px var(--accent), 0 4px 20px rgba(0,0,0,0.2)';
    }}
    onMouseLeave={(e) => {
      e.currentTarget.style.borderColor = 'var(--border)';
      e.currentTarget.style.boxShadow = 'none';
    }}
    onClick={() => onOpenCockpit(project)}
    >
      {/* Header row */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{
            fontSize: '14px',
            fontWeight: '600',
            color: 'var(--text)',
            lineHeight: '1.4',
            overflow: 'hidden',
            textOverflow: 'ellipsis',
            display: '-webkit-box',
            WebkitLineClamp: 2,
            WebkitBoxOrient: 'vertical',
          }}>
            {project.title}
          </div>
          <div style={{
            fontSize: '11px',
            fontFamily: 'var(--mono)',
            color: 'var(--text-4)',
            marginTop: '4px',
          }}>
            {project.id.substring(0, 8)}...
            {project.created_at && (
              <> · {new Date(project.created_at).toLocaleDateString()}</>
            )}
          </div>
        </div>
        <StatusBadge status={project.status} />
      </div>

      {/* Phase Progress */}
      <PhaseProgressBar phaseStatuses={project.phase_statuses} />

      {/* Action Buttons */}
      <div style={{ display: 'flex', gap: '8px', marginTop: '4px' }}>
        {project.has_web_portal && (
          <a
            href={project.web_portal_url}
            target="_blank"
            rel="noreferrer"
            onClick={(e) => e.stopPropagation()}
            style={{
              display: 'inline-flex',
              alignItems: 'center',
              gap: '5px',
              padding: '6px 12px',
              borderRadius: '6px',
              fontSize: '11px',
              fontFamily: 'var(--mono)',
              fontWeight: '600',
              color: '#38bdf8',
              background: 'rgba(56, 189, 248, 0.1)',
              border: '1px solid rgba(56, 189, 248, 0.25)',
              textDecoration: 'none',
              cursor: 'pointer',
              transition: 'all 0.15s ease',
            }}
            onMouseEnter={(e) => {
              e.currentTarget.style.background = 'rgba(56, 189, 248, 0.2)';
              e.currentTarget.style.borderColor = 'rgba(56, 189, 248, 0.5)';
            }}
            onMouseLeave={(e) => {
              e.currentTarget.style.background = 'rgba(56, 189, 248, 0.1)';
              e.currentTarget.style.borderColor = 'rgba(56, 189, 248, 0.25)';
            }}
          >
            <Globe size={12} /> Open Web Portal <ExternalLink size={10} />
          </a>
        )}
        <button
          onClick={(e) => { e.stopPropagation(); onOpenCockpit(project); }}
          style={{
            display: 'inline-flex',
            alignItems: 'center',
            gap: '5px',
            padding: '6px 12px',
            borderRadius: '6px',
            fontSize: '11px',
            fontFamily: 'var(--mono)',
            fontWeight: '600',
            color: 'var(--accent)',
            background: 'rgba(var(--accent-rgb, 168, 85, 247), 0.1)',
            border: '1px solid var(--accent)',
            cursor: 'pointer',
            transition: 'all 0.15s ease',
          }}
          onMouseEnter={(e) => {
            e.currentTarget.style.background = 'rgba(var(--accent-rgb, 168, 85, 247), 0.2)';
          }}
          onMouseLeave={(e) => {
            e.currentTarget.style.background = 'rgba(var(--accent-rgb, 168, 85, 247), 0.1)';
          }}
        >
          <Rocket size={12} /> Open Cockpit <ChevronRight size={10} />
        </button>
      </div>
    </div>
  );
}

export default function Dashboard() {
  const navigate = useNavigate();
  const { setProject, reset } = useProjectStore();
  const [projects, setProjects] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    let cancelled = false;
    const fetchProjects = async () => {
      try {
        const res = await api.getProjects();
        if (!cancelled) {
          setProjects(res.projects || []);
          setLoading(false);
        }
      } catch (err) {
        if (!cancelled) {
          setError(err.message || 'Failed to load projects');
          setLoading(false);
        }
      }
    };
    fetchProjects();
    // Refresh every 30s
    const interval = setInterval(fetchProjects, 30000);
    return () => { cancelled = true; clearInterval(interval); };
  }, []);

  const handleNewProject = () => {
    reset();
    const newProjectId = `PRJ-${Math.floor(Math.random() * 10000)}`;
    setProject({ id: newProjectId, name: 'Untitled Project', createdAt: Date.now() });
    navigate(`/project/${newProjectId}/jam`);
  };

  const handleOpenCockpit = (project) => {
    const phase = project.current_phase || 1;
    navigate(`/project/${project.id}/phase/${phase}`);
  };

  // Compute real metrics
  const activeProjects = projects.filter(p => p.status === 'running' || p.status === 'waiting_for_approval').length;
  const completedPhases = projects.reduce((acc, p) => {
    if (!p.phase_statuses) return acc;
    return acc + Object.values(p.phase_statuses).filter(s => s === 'APPROVED').length;
  }, 0);
  const completedProjects = projects.filter(p => p.status === 'completed').length;
  const portalCount = projects.filter(p => p.has_web_portal).length;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '24px', height: '100%', padding: '24px' }}>
      {/* Header */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <div>
          <h1 style={{ fontSize: '24px', fontWeight: '600', color: 'var(--text)' }}>Command Center</h1>
          <p style={{ color: 'var(--text-3)', marginTop: '4px' }}>
            Overview of all execution outcomes.
            {projects.length > 0 && <span style={{ fontFamily: 'var(--mono)', color: 'var(--text-4)', marginLeft: '8px' }}>({projects.length} total)</span>}
          </p>
        </div>
        <button className="new-project-btn" onClick={handleNewProject}>
          <Plus size={14} /> New Project
        </button>
      </div>

      {/* Metrics Grid */}
      <div className="metrics-grid" style={{ background: 'var(--surface)', borderRadius: 'var(--radius)', border: '1px solid var(--border)' }}>
        <div className="metric-card">
          <div className="metric-label">Active Projects</div>
          <div className="metric-value">{activeProjects}</div>
          <div className="metric-subtitle">Currently in execution</div>
        </div>
        <div className="metric-card">
          <div className="metric-label">Phases Completed</div>
          <div className="metric-value">{completedPhases}</div>
          <div className="metric-subtitle">Across all projects</div>
        </div>
        <div className="metric-card">
          <div className="metric-label">Completed Projects</div>
          <div className="metric-value" style={{ color: completedProjects > 0 ? 'var(--green)' : undefined }}>{completedProjects}</div>
          <div className="metric-subtitle">All phases approved</div>
        </div>
        <div className="metric-card">
          <div className="metric-label">Web Portals</div>
          <div className="metric-value" style={{ color: portalCount > 0 ? '#38bdf8' : undefined }}>
            <Globe size={16} style={{ display: 'inline', marginRight: '4px', verticalAlign: 'middle' }} />{portalCount}
          </div>
          <div className="metric-subtitle">Live preview available</div>
        </div>
      </div>

      {/* Project List */}
      <div style={{ flex: 1, overflowY: 'auto' }}>
        {loading ? (
          <div style={{
            flex: 1,
            border: '1px solid var(--border)',
            borderRadius: 'var(--radius)',
            background: 'var(--surface)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            padding: '60px',
          }}>
            <Loader size={20} color="var(--accent)" style={{ animation: 'spin 1s linear infinite' }} />
            <span style={{ color: 'var(--text-3)', marginLeft: '10px', fontFamily: 'var(--mono)', fontSize: '13px' }}>Loading projects...</span>
          </div>
        ) : error ? (
          <div style={{
            flex: 1,
            border: '1px solid var(--red-br, var(--red))',
            borderRadius: 'var(--radius)',
            background: 'var(--surface)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            padding: '40px',
            color: 'var(--red)',
            fontFamily: 'var(--mono)',
            fontSize: '13px',
            gap: '8px',
          }}>
            <AlertCircle size={16} /> {error}
          </div>
        ) : projects.length === 0 ? (
          <div style={{
            flex: 1,
            border: '1px solid var(--border)',
            borderRadius: 'var(--radius)',
            background: 'var(--surface)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            padding: '60px',
          }}>
            <p style={{ color: 'var(--text-4)' }}>No recent projects. Start a new project to begin execution.</p>
          </div>
        ) : (
          <div style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fill, minmax(360px, 1fr))',
            gap: '16px',
          }}>
            {projects.map((proj) => (
              <ProjectCard
                key={proj.id}
                project={proj}
                onOpenCockpit={handleOpenCockpit}
              />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
