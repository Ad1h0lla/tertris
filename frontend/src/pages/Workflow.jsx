import React, { useEffect } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { useProjectStore } from '../store/projectStore';
import { api } from '../api/client';
import { Play, GripVertical, Server, ArrowLeft, CheckCircle2, Lock } from 'lucide-react';

export default function Workflow() {
  const { id } = useParams();
  const navigate = useNavigate();
  const { workflow, project, understanding, setCurrentPhaseId, syncExecutionState } = useProjectStore();

  const realExecutionId = project?.id || id;

  useEffect(() => {
    if (realExecutionId) {
      api.getExecutionStatus(realExecutionId)
        .then((res) => {
          if (res && res.workflow) {
            syncExecutionState(res);
          }
        })
        .catch((err) => {
          console.warn("Execution status sync warning:", err);
        });
    }
  }, [realExecutionId]);

  if (!workflow || workflow.length === 0) {
    return (
      <div style={{ padding: '24px' }}>
        <p style={{ color: 'var(--text-3)' }}>No workflow generated yet for this project.</p>
        <button
          className="retro-btn"
          style={{ marginTop: '12px' }}
          onClick={() => navigate(`/project/${realExecutionId}/understanding`)}
        >
          <ArrowLeft size={14} style={{ marginRight: '6px' }} /> Go to Understanding
        </button>
      </div>
    );
  }

  const handleStartPhase = (phaseId) => {
    setCurrentPhaseId(phaseId);
    navigate(`/project/${realExecutionId}/phase/${phaseId}`);
  };

  return (
    <div style={{ padding: '24px', display: 'flex', flexDirection: 'column', gap: '24px', height: '100%' }}>
      {/* Header */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
        <div>
          <h1 style={{ fontSize: '24px', fontWeight: '600', color: 'var(--text)' }}>
            Execution Workflow ({workflow.length} Phases)
          </h1>
          <p style={{ color: 'var(--text-3)', marginTop: '4px' }}>
            Authoritative execution map generated from backend specifications.
          </p>
        </div>

        {/* Execution Metadata Pill */}
        <div style={{
          fontFamily: 'var(--mono)',
          fontSize: '11px',
          padding: '6px 12px',
          background: 'var(--surface)',
          border: '1px solid var(--border)',
          borderRadius: 'var(--radius)',
          color: 'var(--accent)',
        }}>
          EXECUTION_ID: {realExecutionId}
        </div>
      </div>

      {/* Goal Summary Header */}
      {understanding?.understood_goal && (
        <div style={{
          padding: '16px 20px',
          background: 'var(--surface)',
          border: '1px solid var(--border)',
          borderRadius: 'var(--radius)',
        }}>
          <div style={{ fontFamily: 'var(--mono)', fontSize: '11px', color: 'var(--text-4)', marginBottom: '4px' }}>
            CONFIRMED GOAL
          </div>
          <div style={{ fontSize: '14px', color: 'var(--text)', fontWeight: '500' }}>
            {understanding.understood_goal}
          </div>
        </div>
      )}

      {/* Dynamic N-Phase List */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
        {workflow.map((phase, index) => {
          const isReady     = phase.status === 'READY' || phase.status === 'RUNNING';
          const isApproved  = phase.status === 'APPROVED' || phase.status === 'COMPLETED';
          const isWaiting   = phase.status === 'WAITING_FOR_APPROVAL';
          const isLocked    = phase.status === 'LOCKED';

          return (
            <div
              key={phase.id}
              style={{
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                background: 'var(--surface)',
                border: `1px solid ${isReady || isWaiting ? 'var(--accent)' : 'var(--border)'}`,
                padding: '16px 20px',
                borderRadius: 'var(--radius)',
                boxShadow: isReady || isWaiting ? '0 0 0 1px var(--accent)' : 'none',
              }}
            >
              <div style={{ display: 'flex', alignItems: 'center', gap: '16px' }}>
                <GripVertical size={16} color="var(--text-4)" style={{ cursor: 'grab' }} />
                <div>
                  <div style={{ fontFamily: 'var(--mono)', fontSize: '11px', color: 'var(--text-4)' }}>
                    PHASE 0{index + 1}
                  </div>
                  <div style={{ fontSize: '15px', fontWeight: '500', color: 'var(--text)' }}>
                    {phase.name}
                  </div>
                  {phase.agent && (
                    <div style={{ fontFamily: 'var(--mono)', fontSize: '11px', color: 'var(--text-3)', marginTop: '2px' }}>
                      🤖 Agent: {phase.agent.name}
                    </div>
                  )}
                </div>
              </div>

              <div style={{ display: 'flex', alignItems: 'center', gap: '16px' }}>
                <span className={`status-badge ${isApproved ? 'status-run' : isReady || isWaiting ? 'status-build' : ''}`}>
                  {phase.status}
                </span>

                <button
                  className={isReady || isWaiting ? 'new-project-btn' : 'retro-btn'}
                  style={{ display: 'flex', alignItems: 'center', gap: '6px' }}
                  onClick={() => handleStartPhase(phase.id)}
                  disabled={isLocked}
                >
                  {isApproved ? (
                    <>View Outcome <CheckCircle2 size={14} /></>
                  ) : isWaiting ? (
                    <>Review & Approve <CheckCircle2 size={14} /></>
                  ) : isReady ? (
                    <>Execute Phase <Play size={14} /></>
                  ) : (
                    <>Locked <Lock size={14} /></>
                  )}
                </button>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
