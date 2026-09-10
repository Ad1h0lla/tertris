import React, { useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { useProjectStore } from '../store/projectStore';
import { api, ApiError } from '../api/client';
import { ArrowRight, CheckCircle2, Cpu, HelpCircle, Layers, Users, AlertCircle, RefreshCw } from 'lucide-react';

export default function Understanding() {
  const { id } = useParams();
  const navigate = useNavigate();

  const {
    understanding,
    setProject,
    setWorkflow,
    setUnderstanding,
  } = useProjectStore();

  const [isExecuting, setIsExecuting] = useState(false);
  const [errorMsg, setErrorMsg]       = useState(null);

  if (!understanding) {
    return (
      <div style={{ padding: '24px' }}>
        <p style={{ color: 'var(--text-3)' }}>No understanding state found. Please complete the Jam Session first.</p>
        <button
          className="retro-btn"
          style={{ marginTop: '12px' }}
          onClick={() => navigate(`/project/${id}/jam`)}
        >
          Go to Jam Session
        </button>
      </div>
    );
  }

  // Extract real fields from backend understanding output
  const goalText             = understanding.understood_goal || 'No goal specified';
  const ideaType             = understanding.idea_type || 'saas';
  const intentClass          = understanding.intent_classification || 'full_product';
  const confidence           = understanding.confidence ?? 0.7;
  const recommendedPhases    = understanding.recommended_phases || [1, 2, 3, 4];
  const phaseNames           = understanding.phase_names || [];
  const recommendedAgents    = understanding.recommended_agents || [];
  const suggestedApps        = understanding.suggested_apps || [];
  const assumptions          = understanding.assumptions || [];
  const acceptanceCriteria   = understanding.acceptance_criteria || [];
  const visualSummary        = understanding.visual_summary || null;

  // Handle workflow generation & backend execution registration
  const handleGenerateWorkflow = async () => {
    if (isExecuting) return;
    setIsExecuting(true);
    setErrorMsg(null);

    try {
      // Call real backend execution endpoint
      const res = await api.execute(understanding, 1, 'auto');

      const realExecutionId = res.execution_id || id;
      const realWorkflow    = res.workflow || recommendedPhases.map((phId, idx) => ({
        id: phId,
        name: phaseNames[idx] || `Phase ${phId}`,
        status: idx === 0 ? 'READY' : 'LOCKED',
      }));

      // Update store state with backend execution results
      setProject({
        id: realExecutionId,
        name: goalText.length > 40 ? `${goalText.slice(0, 40)}...` : goalText,
        createdAt: Date.now(),
      });

      setWorkflow(realWorkflow);

      if (res.goal) {
        setUnderstanding(res.goal);
      }

      // Navigate to workflow page with real backend execution_id
      navigate(`/project/${realExecutionId}/workflow`);
    } catch (err) {
      if (err instanceof ApiError) {
        setErrorMsg(`❌ Backend Error (${err.endpoint}): HTTP ${err.status} — ${err.detail}`);
      } else {
        setErrorMsg(`❌ Execution initiation failed: ${err.message || String(err)}`);
      }
    } finally {
      setIsExecuting(false);
    }
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '24px', height: '100%', padding: '24px' }}>
      {/* Header */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <div>
          <h1 style={{ fontSize: '24px', fontWeight: '600', color: 'var(--text)' }}>Understanding</h1>
          <p style={{ color: 'var(--text-3)', marginTop: '4px' }}>Structured understanding produced by the Jam Session Brain.</p>
        </div>
        <button
          className="new-project-btn"
          onClick={handleGenerateWorkflow}
          disabled={isExecuting}
        >
          {isExecuting ? (
            <>
              <RefreshCw size={14} className="cursor" style={{ marginRight: '6px' }} />
              Creating Execution...
            </>
          ) : (
            <>
              Generate Workflow <ArrowRight size={14} />
            </>
          )}
        </button>
      </div>

      {/* Error banner if backend execution creation fails */}
      {errorMsg && (
        <div style={{
          padding: '12px 16px',
          background: 'var(--bg)',
          border: '1px solid var(--red-br)',
          borderRadius: 'var(--radius)',
          color: 'var(--red)',
          fontFamily: 'var(--mono)',
          fontSize: '12px',
          whiteSpace: 'pre-wrap',
        }}>
          <AlertCircle size={14} style={{ display: 'inline', marginRight: '6px' }} />
          {errorMsg}
        </div>
      )}

      {/* Content Body */}
      <div className="understood-card" style={{ margin: 0, flex: 1, overflowY: 'auto' }}>
        {/* Project Summary */}
        <div className="understood-title">UNDERSTOOD GOAL</div>
        <div className="understood-goal">{goalText}</div>

        {/* System Metadata Tags */}
        <div className="understood-title" style={{ marginTop: '24px' }}>CLASSIFICATION & TYPE</div>
        <div className="phase-tags">
          <span className="phase-tag">Idea: {ideaType.toUpperCase()}</span>
          <span className="phase-tag">Intent: {intentClass.toUpperCase()}</span>
          <span className="phase-tag" style={{ color: 'var(--accent)' }}>
            Confidence: {Math.round(confidence * 100)}%
          </span>
        </div>

        {/* Dynamic Recommended Phases (N Phases) */}
        <div className="understood-title" style={{ marginTop: '24px' }}>
          RECOMMENDED EXECUTION PHASES ({recommendedPhases.length} PHASES)
        </div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: '8px', marginTop: '8px' }}>
          {recommendedPhases.map((phId, idx) => {
            const name = phaseNames[idx] || `Phase ${phId}`;
            return (
              <div
                key={phId}
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: '12px',
                  padding: '10px 14px',
                  background: 'var(--surface)',
                  border: '1px solid var(--border)',
                  borderRadius: 'var(--radius)',
                }}
              >
                <span style={{ fontFamily: 'var(--mono)', fontSize: '11px', color: 'var(--text-4)' }}>
                  PHASE 0{idx + 1}
                </span>
                <span style={{ fontSize: '14px', fontWeight: '500', color: 'var(--text)' }}>
                  {name}
                </span>
              </div>
            );
          })}
        </div>

        {/* Recommended Agents */}
        {recommendedAgents.length > 0 && (
          <>
            <div className="understood-title" style={{ marginTop: '24px' }}>RECOMMENDED AGENTS</div>
            <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap', marginTop: '8px' }}>
              {recommendedAgents.map((agent, i) => (
                <span
                  key={i}
                  style={{
                    fontFamily: 'var(--mono)',
                    fontSize: '12px',
                    padding: '4px 10px',
                    background: 'var(--elevated)',
                    border: '1px solid var(--border)',
                    borderRadius: '4px',
                    color: 'var(--text-2)',
                  }}
                >
                  🤖 {agent}
                </span>
              ))}
            </div>
          </>
        )}

        {/* Acceptance Criteria */}
        <div className="understood-title" style={{ marginTop: '24px' }}>ACCEPTANCE CRITERIA</div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: '8px', marginTop: '8px' }}>
          {acceptanceCriteria.length > 0 ? (
            acceptanceCriteria.map((c, i) => (
              <div key={i} className="criteria-item">
                <CheckCircle2 size={14} color="var(--green)" style={{ marginRight: '6px', flexShrink: 0 }} />
                {c}
              </div>
            ))
          ) : (
            <div style={{ color: 'var(--text-4)', fontSize: '13px', fontStyle: 'italic' }}>
              No specific acceptance criteria provided. Standard working outcome expected.
            </div>
          )}
        </div>

        {/* Assumptions (if present) */}
        {assumptions.length > 0 && (
          <>
            <div className="understood-title" style={{ marginTop: '24px' }}>ASSUMPTIONS</div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '6px', marginTop: '8px' }}>
              {assumptions.map((asm, i) => (
                <div key={i} style={{ fontSize: '13px', color: 'var(--text-3)', fontFamily: 'var(--mono)' }}>
                  • {asm}
                </div>
              ))}
            </div>
          </>
        )}

        {/* Visual Summary Flowchart (if present) */}
        {visualSummary && (
          <>
            <div className="understood-title" style={{ marginTop: '24px' }}>VISUAL FLOWCHART</div>
            <div style={{
              padding: '14px',
              background: 'var(--bg)',
              border: '1px solid var(--border)',
              borderRadius: 'var(--radius)',
              fontFamily: 'var(--mono)',
              fontSize: '12px',
              color: 'var(--text-2)',
            }}>
              <div style={{ fontWeight: 'bold', color: 'var(--accent)', marginBottom: '8px' }}>
                📊 {visualSummary.title || 'System Diagram'}
              </div>
              <div>{visualSummary.description || ''}</div>
              {visualSummary.nodes && visualSummary.nodes.length > 0 && (
                <div style={{ display: 'flex', gap: '8px', marginTop: '10px', flexWrap: 'wrap' }}>
                  {visualSummary.nodes.map((node) => (
                    <div key={node.id} style={{
                      padding: '4px 8px',
                      background: 'var(--surface)',
                      border: '1px solid var(--border)',
                      borderRadius: '4px',
                    }}>
                      [{node.label}]
                    </div>
                  ))}
                </div>
              )}
            </div>
          </>
        )}
      </div>
    </div>
  );
}
