import React, { useEffect, useState, useMemo } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { useProjectStore } from '../store/projectStore';
import { api, ApiError } from '../api/client';
import {
  Play, CheckCircle, AlertCircle, RefreshCw, Code, CheckSquare,
  Terminal, FileText, ArrowRight, CornerDownRight, ExternalLink,
  Globe, Copy, Server, Shield, DollarSign, Target, Users,
  Megaphone, Mail, Rocket, ChevronRight, Package, Zap, Key, Clock,
} from 'lucide-react';

// ─── Rich Deliverable Visualizers ────────────────────────────────────────────

function Phase2CompetitorIntel({ data }) {
  if (!data) return null;
  let parsed = data;
  if (typeof data === 'string') {
    try { parsed = JSON.parse(data); } catch { return null; }
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
      {/* Market Gap Alert */}
      {parsed.market_gap && (
        <div style={{
          padding: '14px 16px',
          background: 'linear-gradient(135deg, rgba(56, 189, 248, 0.08), rgba(168, 85, 247, 0.08))',
          border: '1px solid rgba(56, 189, 248, 0.2)',
          borderRadius: 'var(--radius)',
        }}>
          <div style={{ fontFamily: 'var(--mono)', fontSize: '10px', color: '#38bdf8', marginBottom: '6px', fontWeight: '700', letterSpacing: '0.5px' }}>
            🎯 MARKET GAP IDENTIFIED
          </div>
          <div style={{ fontSize: '12px', color: 'var(--text-2, var(--text))', lineHeight: '1.6' }}>
            {parsed.market_gap}
          </div>
        </div>
      )}

      {/* Competitor Breakdown Cards */}
      {parsed.competitors?.map((comp, idx) => (
        <div key={idx} style={{
          padding: '14px 16px',
          background: 'var(--surface)',
          border: '1px solid var(--border)',
          borderRadius: 'var(--radius)',
        }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '8px' }}>
            <span style={{ fontWeight: '600', fontSize: '13px', color: 'var(--text)' }}>
              {comp.name}
            </span>
            <span style={{
              padding: '2px 8px',
              borderRadius: '99px',
              fontSize: '10px',
              fontFamily: 'var(--mono)',
              color: '#f59e0b',
              background: 'rgba(245, 158, 11, 0.12)',
              border: '1px solid rgba(245, 158, 11, 0.25)',
            }}>
              <DollarSign size={10} style={{ display: 'inline', verticalAlign: 'middle' }} /> {comp.pricing}
            </span>
          </div>
          <div style={{ fontSize: '11px', color: 'var(--text-3)', marginBottom: '4px' }}>
            <Users size={11} style={{ display: 'inline', marginRight: '4px', verticalAlign: 'middle' }} />
            {comp.target_customer}
          </div>
          <div style={{ fontSize: '11px', color: 'var(--red)', fontFamily: 'var(--mono)' }}>
            ⚠ {comp.weakness}
          </div>
        </div>
      ))}

      {/* Pricing Strategy Matrix */}
      {(parsed.recommended_price_range || parsed.pricing_strategy) && (
        <div style={{
          padding: '14px 16px',
          background: 'var(--surface)',
          border: '1px solid var(--border)',
          borderRadius: 'var(--radius)',
        }}>
          <div style={{ fontFamily: 'var(--mono)', fontSize: '10px', color: 'var(--text-4)', marginBottom: '8px', fontWeight: '700' }}>
            💰 PRICING STRATEGY
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '8px' }}>
            <div>
              <div style={{ fontSize: '10px', color: 'var(--text-4)', fontFamily: 'var(--mono)' }}>PRICE RANGE</div>
              <div style={{ fontSize: '14px', fontWeight: '600', color: 'var(--green)' }}>{parsed.recommended_price_range}</div>
            </div>
            <div>
              <div style={{ fontSize: '10px', color: 'var(--text-4)', fontFamily: 'var(--mono)' }}>STRATEGY</div>
              <div style={{ fontSize: '12px', color: 'var(--text)' }}>{parsed.pricing_strategy}</div>
            </div>
          </div>
        </div>
      )}

      {/* Key Differentiators */}
      {parsed.key_differentiators?.length > 0 && (
        <div style={{
          padding: '14px 16px',
          background: 'var(--surface)',
          border: '1px solid var(--border)',
          borderRadius: 'var(--radius)',
        }}>
          <div style={{ fontFamily: 'var(--mono)', fontSize: '10px', color: 'var(--text-4)', marginBottom: '8px', fontWeight: '700' }}>
            ✦ KEY DIFFERENTIATORS
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
            {parsed.key_differentiators.map((d, i) => (
              <div key={i} style={{ fontSize: '12px', color: 'var(--text)', display: 'flex', alignItems: 'flex-start', gap: '6px' }}>
                <Shield size={12} color="var(--green)" style={{ flexShrink: 0, marginTop: '2px' }} />
                {d}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function Phase3MarketingCampaign({ data }) {
  if (!data) return null;
  let parsed = data;
  if (typeof data === 'string') {
    try { parsed = JSON.parse(data); } catch { return null; }
  }
  const [copiedIdx, setCopiedIdx] = useState(null);

  const handleCopy = (text, idx) => {
    navigator.clipboard.writeText(text).then(() => {
      setCopiedIdx(idx);
      setTimeout(() => setCopiedIdx(null), 1500);
    });
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
      {/* Target Audience & Positioning */}
      {parsed.target_audience && (
        <div style={{
          padding: '14px 16px',
          background: 'linear-gradient(135deg, rgba(168, 85, 247, 0.08), rgba(236, 72, 153, 0.08))',
          border: '1px solid rgba(168, 85, 247, 0.2)',
          borderRadius: 'var(--radius)',
        }}>
          <div style={{ fontFamily: 'var(--mono)', fontSize: '10px', color: 'var(--accent)', marginBottom: '6px', fontWeight: '700' }}>
            🎯 TARGET AUDIENCE
          </div>
          <div style={{ fontSize: '12px', color: 'var(--text)', lineHeight: '1.6' }}>
            {parsed.target_audience}
          </div>
          {parsed.positioning_statement && (
            <div style={{ marginTop: '10px', fontSize: '12px', color: 'var(--text-3)', fontStyle: 'italic', lineHeight: '1.5' }}>
              "{parsed.positioning_statement}"
            </div>
          )}
        </div>
      )}

      {/* Acquisition Channel Badges */}
      {parsed.key_channels?.length > 0 && (
        <div style={{
          padding: '14px 16px',
          background: 'var(--surface)',
          border: '1px solid var(--border)',
          borderRadius: 'var(--radius)',
        }}>
          <div style={{ fontFamily: 'var(--mono)', fontSize: '10px', color: 'var(--text-4)', marginBottom: '8px', fontWeight: '700' }}>
            📡 ACQUISITION CHANNELS
          </div>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px' }}>
            {parsed.key_channels.map((ch, i) => (
              <span key={i} style={{
                padding: '4px 10px',
                borderRadius: '99px',
                fontSize: '11px',
                fontFamily: 'var(--mono)',
                color: '#38bdf8',
                background: 'rgba(56, 189, 248, 0.1)',
                border: '1px solid rgba(56, 189, 248, 0.2)',
              }}>
                <Megaphone size={10} style={{ display: 'inline', marginRight: '4px', verticalAlign: 'middle' }} />
                {ch}
              </span>
            ))}
          </div>
        </div>
      )}

      {/* Campaign Angle */}
      {parsed.campaign_angle && (
        <div style={{
          padding: '12px 16px',
          background: 'var(--surface)',
          border: '1px solid var(--border)',
          borderRadius: 'var(--radius)',
          textAlign: 'center',
        }}>
          <div style={{ fontFamily: 'var(--mono)', fontSize: '10px', color: 'var(--text-4)', marginBottom: '4px' }}>CAMPAIGN ANGLE</div>
          <div style={{ fontSize: '16px', fontWeight: '700', color: 'var(--accent)' }}>
            {parsed.campaign_angle}
          </div>
        </div>
      )}

      {/* Ad Copy Blocks */}
      {parsed.ad_copy?.map((ad, idx) => (
        <div key={idx} style={{
          padding: '14px 16px',
          background: 'var(--surface)',
          border: '1px solid var(--border)',
          borderRadius: 'var(--radius)',
          position: 'relative',
        }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '6px' }}>
            <div style={{ fontWeight: '600', fontSize: '13px', color: 'var(--text)' }}>
              {ad.headline}
            </div>
            <button
              onClick={() => handleCopy(`${ad.headline}\n${ad.body}\n${ad.cta}`, idx)}
              style={{
                background: 'none',
                border: '1px solid var(--border)',
                borderRadius: '4px',
                padding: '3px 6px',
                cursor: 'pointer',
                color: copiedIdx === idx ? 'var(--green)' : 'var(--text-4)',
                fontSize: '10px',
                fontFamily: 'var(--mono)',
                display: 'flex',
                alignItems: 'center',
                gap: '3px',
              }}
            >
              <Copy size={10} /> {copiedIdx === idx ? 'Copied!' : 'Copy'}
            </button>
          </div>
          <div style={{ fontSize: '12px', color: 'var(--text-3)', lineHeight: '1.5', marginBottom: '8px' }}>
            {ad.body}
          </div>
          <span style={{
            padding: '3px 10px',
            borderRadius: '4px',
            fontSize: '11px',
            fontFamily: 'var(--mono)',
            fontWeight: '600',
            color: 'var(--green)',
            background: 'rgba(34, 197, 94, 0.1)',
            border: '1px solid rgba(34, 197, 94, 0.25)',
          }}>
            CTA: {ad.cta}
          </span>
        </div>
      ))}

      {/* Email Sequence Preview */}
      {parsed.email_sequence?.length > 0 && (
        <div style={{
          padding: '14px 16px',
          background: 'var(--surface)',
          border: '1px solid var(--border)',
          borderRadius: 'var(--radius)',
        }}>
          <div style={{ fontFamily: 'var(--mono)', fontSize: '10px', color: 'var(--text-4)', marginBottom: '10px', fontWeight: '700' }}>
            ✉️ EMAIL SEQUENCE ({parsed.email_sequence.length} emails)
          </div>
          {parsed.email_sequence.map((email, idx) => (
            <div key={idx} style={{
              padding: '10px 12px',
              background: 'var(--bg)',
              border: '1px solid var(--border)',
              borderRadius: 'var(--radius)',
              marginBottom: idx < parsed.email_sequence.length - 1 ? '8px' : 0,
            }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '6px', marginBottom: '4px' }}>
                <Mail size={12} color="var(--accent)" />
                <span style={{ fontWeight: '600', fontSize: '12px', color: 'var(--text)' }}>
                  {email.subject}
                </span>
              </div>
              <div style={{ fontSize: '11px', color: 'var(--text-4)', fontFamily: 'var(--mono)' }}>
                Preview: {email.preview}
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Launch Offer */}
      {parsed.launch_offer && (
        <div style={{
          padding: '12px 16px',
          background: 'linear-gradient(135deg, rgba(34, 197, 94, 0.08), rgba(56, 189, 248, 0.08))',
          border: '1px solid rgba(34, 197, 94, 0.2)',
          borderRadius: 'var(--radius)',
        }}>
          <div style={{ fontFamily: 'var(--mono)', fontSize: '10px', color: 'var(--green)', marginBottom: '4px', fontWeight: '700' }}>
            🚀 LAUNCH OFFER
          </div>
          <div style={{ fontSize: '12px', color: 'var(--text)', lineHeight: '1.5' }}>
            {parsed.launch_offer}
          </div>
        </div>
      )}
    </div>
  );
}

function Phase4DeploymentPrep({ data }) {
  if (!data) return null;
  let parsed = data;
  if (typeof data === 'string') {
    try { parsed = JSON.parse(data); } catch { return null; }
  }

  const [checklist, setChecklist] = useState(() =>
    (parsed.deploy_steps || []).map(() => false)
  );

  const toggleStep = (idx) => {
    setChecklist(prev => {
      const next = [...prev];
      next[idx] = !next[idx];
      return next;
    });
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
      {/* Platform & Framework Badges */}
      <div style={{
        padding: '14px 16px',
        background: 'var(--surface)',
        border: '1px solid var(--border)',
        borderRadius: 'var(--radius)',
        display: 'flex',
        gap: '8px',
        flexWrap: 'wrap',
      }}>
        {parsed.framework && (
          <span style={{
            padding: '4px 12px',
            borderRadius: '99px',
            fontSize: '11px',
            fontFamily: 'var(--mono)',
            fontWeight: '600',
            color: '#38bdf8',
            background: 'rgba(56, 189, 248, 0.1)',
            border: '1px solid rgba(56, 189, 248, 0.25)',
          }}>
            <Package size={10} style={{ display: 'inline', marginRight: '4px', verticalAlign: 'middle' }} />
            {parsed.framework}
          </span>
        )}
        {parsed.recommended_platform && (
          <span style={{
            padding: '4px 12px',
            borderRadius: '99px',
            fontSize: '11px',
            fontFamily: 'var(--mono)',
            fontWeight: '600',
            color: 'var(--accent)',
            background: 'rgba(168, 85, 247, 0.1)',
            border: '1px solid rgba(168, 85, 247, 0.25)',
          }}>
            <Rocket size={10} style={{ display: 'inline', marginRight: '4px', verticalAlign: 'middle' }} />
            {parsed.recommended_platform}
          </span>
        )}
        {parsed.monthly_cost && (
          <span style={{
            padding: '4px 12px',
            borderRadius: '99px',
            fontSize: '11px',
            fontFamily: 'var(--mono)',
            fontWeight: '600',
            color: 'var(--green)',
            background: 'rgba(34, 197, 94, 0.1)',
            border: '1px solid rgba(34, 197, 94, 0.25)',
          }}>
            <DollarSign size={10} style={{ display: 'inline', marginRight: '4px', verticalAlign: 'middle' }} />
            {parsed.monthly_cost}
          </span>
        )}
        {parsed.estimated_time && (
          <span style={{
            padding: '4px 12px',
            borderRadius: '99px',
            fontSize: '11px',
            fontFamily: 'var(--mono)',
            fontWeight: '600',
            color: '#f59e0b',
            background: 'rgba(245, 158, 11, 0.1)',
            border: '1px solid rgba(245, 158, 11, 0.25)',
          }}>
            <Clock size={10} style={{ display: 'inline', marginRight: '4px', verticalAlign: 'middle' }} />
            {parsed.estimated_time}
          </span>
        )}
      </div>

      {/* Build & Start Commands */}
      <div style={{
        padding: '14px 16px',
        background: 'var(--surface)',
        border: '1px solid var(--border)',
        borderRadius: 'var(--radius)',
      }}>
        <div style={{ fontFamily: 'var(--mono)', fontSize: '10px', color: 'var(--text-4)', marginBottom: '10px', fontWeight: '700' }}>
          ⚡ COMMANDS
        </div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
          {parsed.install_command && (
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
              <span style={{ fontSize: '10px', color: 'var(--text-4)', fontFamily: 'var(--mono)', width: '50px' }}>INSTALL</span>
              <code style={{ flex: 1, padding: '6px 10px', background: '#000', borderRadius: '4px', fontSize: '12px', fontFamily: 'var(--mono)', color: '#38bdf8' }}>
                {parsed.install_command}
              </code>
            </div>
          )}
          {parsed.build_command && (
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
              <span style={{ fontSize: '10px', color: 'var(--text-4)', fontFamily: 'var(--mono)', width: '50px' }}>BUILD</span>
              <code style={{ flex: 1, padding: '6px 10px', background: '#000', borderRadius: '4px', fontSize: '12px', fontFamily: 'var(--mono)', color: '#38bdf8' }}>
                {parsed.build_command}
              </code>
            </div>
          )}
          {parsed.start_command && (
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
              <span style={{ fontSize: '10px', color: 'var(--text-4)', fontFamily: 'var(--mono)', width: '50px' }}>START</span>
              <code style={{ flex: 1, padding: '6px 10px', background: '#000', borderRadius: '4px', fontSize: '12px', fontFamily: 'var(--mono)', color: 'var(--green)' }}>
                {parsed.start_command}
              </code>
            </div>
          )}
        </div>
      </div>

      {/* Environment Variables Table */}
      {parsed.environment_variables_needed?.length > 0 && (
        <div style={{
          padding: '14px 16px',
          background: 'var(--surface)',
          border: '1px solid var(--border)',
          borderRadius: 'var(--radius)',
        }}>
          <div style={{ fontFamily: 'var(--mono)', fontSize: '10px', color: 'var(--text-4)', marginBottom: '10px', fontWeight: '700' }}>
            🔑 ENVIRONMENT VARIABLES
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
            {parsed.environment_variables_needed.map((envVar, idx) => {
              const parts = envVar.split(' - ');
              const varName = parts[0]?.trim();
              const desc = parts.slice(1).join(' - ').trim();
              return (
                <div key={idx} style={{
                  display: 'flex',
                  alignItems: 'flex-start',
                  gap: '8px',
                  padding: '6px 8px',
                  background: idx % 2 === 0 ? 'var(--bg)' : 'transparent',
                  borderRadius: '4px',
                }}>
                  <Key size={11} color="#f59e0b" style={{ flexShrink: 0, marginTop: '2px' }} />
                  <code style={{ fontSize: '11px', fontFamily: 'var(--mono)', color: '#f59e0b', flexShrink: 0 }}>{varName}</code>
                  {desc && <span style={{ fontSize: '11px', color: 'var(--text-3)' }}>{desc}</span>}
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* Interactive Launch Checklist */}
      {parsed.deploy_steps?.length > 0 && (
        <div style={{
          padding: '14px 16px',
          background: 'var(--surface)',
          border: '1px solid var(--border)',
          borderRadius: 'var(--radius)',
        }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '10px' }}>
            <div style={{ fontFamily: 'var(--mono)', fontSize: '10px', color: 'var(--text-4)', fontWeight: '700' }}>
              🚀 LAUNCH CHECKLIST ({checklist.filter(Boolean).length}/{parsed.deploy_steps.length})
            </div>
            <div style={{
              height: '4px',
              width: '80px',
              background: 'var(--border)',
              borderRadius: '2px',
              overflow: 'hidden',
            }}>
              <div style={{
                height: '100%',
                width: `${(checklist.filter(Boolean).length / parsed.deploy_steps.length) * 100}%`,
                background: 'var(--green)',
                transition: 'width 0.3s ease',
                borderRadius: '2px',
              }} />
            </div>
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
            {parsed.deploy_steps.map((step, idx) => (
              <div
                key={idx}
                onClick={() => toggleStep(idx)}
                style={{
                  display: 'flex',
                  alignItems: 'flex-start',
                  gap: '8px',
                  padding: '8px 10px',
                  background: checklist[idx] ? 'rgba(34, 197, 94, 0.05)' : 'var(--bg)',
                  border: `1px solid ${checklist[idx] ? 'rgba(34, 197, 94, 0.2)' : 'transparent'}`,
                  borderRadius: '4px',
                  cursor: 'pointer',
                  transition: 'all 0.15s ease',
                }}
              >
                <div style={{
                  width: '16px',
                  height: '16px',
                  borderRadius: '3px',
                  border: `2px solid ${checklist[idx] ? 'var(--green)' : 'var(--text-4)'}`,
                  background: checklist[idx] ? 'var(--green)' : 'transparent',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  flexShrink: 0,
                  marginTop: '1px',
                  transition: 'all 0.15s ease',
                }}>
                  {checklist[idx] && <CheckCircle size={10} color="#fff" />}
                </div>
                <span style={{
                  fontSize: '12px',
                  color: checklist[idx] ? 'var(--text-3)' : 'var(--text)',
                  textDecoration: checklist[idx] ? 'line-through' : 'none',
                  lineHeight: '1.4',
                }}>
                  {step}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Deploy Button */}
      {parsed.deploy_button_url && parsed.one_click_ready && (
        <a
          href={parsed.deploy_button_url}
          target="_blank"
          rel="noreferrer"
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            gap: '8px',
            padding: '12px',
            borderRadius: 'var(--radius)',
            background: 'linear-gradient(135deg, var(--accent), #ec4899)',
            color: '#fff',
            fontSize: '13px',
            fontFamily: 'var(--mono)',
            fontWeight: '700',
            textDecoration: 'none',
            cursor: 'pointer',
            transition: 'opacity 0.15s ease',
          }}
        >
          <Rocket size={16} /> DEPLOY NOW — {parsed.recommended_platform}
        </a>
      )}
    </div>
  );
}

// ─── Phase Label Map ─────────────────────────────────────────────────────────
const PHASE_TITLES = {
  1: 'Build',
  2: 'Competitor Intel & Validation',
  3: 'Marketing Campaign',
  4: 'Deployment Operations',
};

// ─── Main Component ──────────────────────────────────────────────────────────
export default function PhaseCockpit() {
  const { id, phaseId } = useParams();
  const navigate = useNavigate();
  const {
    project,
    understanding,
    workflow,
    phases,
    agents,
    updatePhase,
    updateAgent,
    addAgentLog,
    setWorkflow,
    syncExecutionState,
    setCurrentPhaseId,
  } = useProjectStore();

  const [isRunning, setIsRunning]             = useState(false);
  const [selectedAgent, setSelectedAgent]     = useState(null);
  const [showRevisionModal, setShowRevisionModal] = useState(false);
  const [showPreviewModal, setShowPreviewModal]   = useState(false);
  const [revisionFeedback, setRevisionFeedback] = useState('');
  const [errorMessage, setErrorMessage]       = useState(null);

  const phaseNum = parseInt(phaseId) || 1;
  // URL route parameter takes precedence over potentially stale store state
  const realExecutionId = id || project?.id;
  const phaseData = phases[phaseNum] || { status: 'READY', outputs: {} };

  const workflowPhase = (workflow || []).find((p) => p.id === phaseNum);
  const assignedAgent = workflowPhase?.agent || { type: 'code', name: 'Code Builder & Executor' };

  const currentAgents = [
    { id: `agent_ph${phaseNum}`, type: assignedAgent.type, name: assignedAgent.name }
  ];

  useEffect(() => {
    if (phaseNum) {
      setCurrentPhaseId(phaseNum);
    }
  }, [phaseNum, setCurrentPhaseId]);

  useEffect(() => {
    if (realExecutionId) {
      api.getExecutionStatus(realExecutionId)
        .then((res) => {
          if (res && res.workflow) {
            syncExecutionState(res);
          }
        })
        .catch(() => {});
    }
  }, [realExecutionId, phaseNum]);

  useEffect(() => {
    if (!selectedAgent && currentAgents.length > 0) {
      setSelectedAgent(currentAgents[0].id);
    }
  }, [phaseNum, assignedAgent.type]);

  // ── Parse deliverable data for rich visualizers ────────────────────────────
  const deliverableData = useMemo(() => {
    // Look in workflow output data first (backend-provided)
    const wfPhase = (workflow || []).find(p => p.id === phaseNum);
    const wfOutput = wfPhase?.output;
    if (wfOutput?.outcome) {
      try { return JSON.parse(wfOutput.outcome); } catch { /* not JSON */ }
    }
    // Fallback to local phase state
    const outcome = phaseData.outcome;
    if (outcome) {
      try { return JSON.parse(outcome); } catch { /* not JSON */ }
    }
    return null;
  }, [workflow, phaseNum, phaseData.outcome]);

  // ── Execute Phase Specialist Agent ──────────────────────────────────────────
  const handleExecute = async (feedbackText = null) => {
    if (isRunning) return;
    setIsRunning(true);
    setErrorMessage(null);
    setShowRevisionModal(false);

    updatePhase(phaseNum, { status: 'RUNNING' });

    const agent = currentAgents[0];
    updateAgent(agent.id, {
      status: 'running',
      logs: [
        feedbackText ? `Initializing Revision with Feedback: "${feedbackText}"` : `Initializing Specialist Agent: ${agent.name}...`,
      ],
    });

    const previousOutput = Object.keys(phases)
      .filter((p) => parseInt(p) < phaseNum)
      .map((p) => phases[p]?.outcome || '')
      .join('\n\n');

    try {
      addAgentLog(agent.id, `Executing ${agent.name} (${agent.type})...`);
      const res = await api.executeAgent(
        understanding || {},
        phaseNum,
        agent.type,
        previousOutput,
        realExecutionId,
        feedbackText
      );

      const filesWritten = res.files_written || [];
      const runnerRes    = res.runner_result || {};
      const validation   = res.validation || {};

      if (filesWritten.length > 0) {
        addAgentLog(agent.id, `Workspace path: ${res.workspace_path}`);
        addAgentLog(agent.id, `Generated files: ${filesWritten.join(', ')}`);
      }
      addAgentLog(agent.id, `Controlled Runner: ${runnerRes.passed ? 'PASSED (0)' : 'FAILED (' + runnerRes.exit_code + ')'}`);
      addAgentLog(agent.id, `Reviewer Score: ${Math.round((validation.score || 0) * 100)}% (${validation.passed ? 'PASSED' : 'FAILED'})`);

      const outputMarkdown = res.outcome || '# Execution Completed';

      updateAgent(agent.id, {
        status: validation.passed ? 'completed' : 'failed',
        output: outputMarkdown,
        manifest: res.manifest,
        runner_result: runnerRes,
        validation: validation,
        files_written: filesWritten,
      });

      updatePhase(phaseNum, {
        status: res.status || (validation.passed ? 'WAITING_FOR_APPROVAL' : 'FAILED'),
        outcome: outputMarkdown,
        manifest: res.manifest,
        runner_result: runnerRes,
        validation: validation,
        files_written: filesWritten,
      });
    } catch (err) {
      const errorText = err instanceof ApiError
        ? `HTTP ${err.status} on ${err.endpoint} — ${err.detail}`
        : `Execution error: ${err.message || String(err)}`;

      setErrorMessage(errorText);
      updateAgent(agent.id, { status: 'failed', output: errorText });
      addAgentLog(agent.id, errorText);
      updatePhase(phaseNum, { status: 'FAILED' });
    } finally {
      setIsRunning(false);
    }
  };

  // ── Approve Phase ────────────────────────────────────────────────────────────
  const handleApprove = async () => {
    try {
      const res = await api.approve(realExecutionId, true, '', phaseNum);
      updatePhase(phaseNum, { status: 'APPROVED' });

      // Fetch authoritative status from backend
      const statusRes = await api.getExecutionStatus(realExecutionId);
      if (statusRes && statusRes.workflow) {
        syncExecutionState(statusRes);
      }

      // Navigate to next phase if available
      const nextPhaseExists = (statusRes?.workflow || workflow).some((p) => p.id === phaseNum + 1 && p.status !== 'LOCKED');
      if (nextPhaseExists) {
        navigate(`/project/${realExecutionId}/phase/${phaseNum + 1}`);
      } else {
        navigate(`/project/${realExecutionId}/workflow`);
      }
    } catch (err) {
      setErrorMessage(`Approval failed: ${err.message}`);
    }
  };

  // ── Submit Revision ──────────────────────────────────────────────────────────
  const handleSubmitRevision = async () => {
    if (!revisionFeedback.trim()) return;
    try {
      await api.approve(realExecutionId, false, revisionFeedback.trim(), phaseNum);
      updatePhase(phaseNum, { status: 'REVISION_REQUIRED' });
      await handleExecute(revisionFeedback.trim());
    } catch (err) {
      setErrorMessage(`Revision submission failed: ${err.message}`);
    }
  };

  const agentState = agents[selectedAgent] || {};
  const currentManifest = phaseData.manifest || agentState.manifest || {};
  const currentRunner   = phaseData.runner_result || agentState.runner_result || {};
  const currentVal      = phaseData.validation || agentState.validation || {};
  const currentFiles    = phaseData.files_written || agentState.files_written || [];

  // Check for web portal via workflow data
  const wfPhaseData = (workflow || []).find(p => p.id === phaseNum);
  const hasWebPortal = currentFiles.includes('index.html') || wfPhaseData?.has_web_portal;
  const webPortalUrl = wfPhaseData?.web_portal_url || `http://localhost:8000/projects/${realExecutionId}/phase_${phaseNum}/index.html`;

  return (
    <div style={{ display: 'flex', height: '100%', background: 'var(--bg)' }}>
      {/* Left Panel: Phase & Agent Controller */}
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', borderRight: '1px solid var(--border)' }}>
        <div style={{ padding: '20px', borderBottom: '1px solid var(--border)', background: 'var(--surface)' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <div>
              <div style={{ fontFamily: 'var(--mono)', fontSize: '11px', color: 'var(--text-4)' }}>PHASE 0{phaseNum}</div>
              <h2 style={{ fontSize: '20px', fontWeight: '600', color: 'var(--text)' }}>
                {PHASE_TITLES[phaseNum] || `Phase ${phaseNum}`} Cockpit
              </h2>
            </div>
            {/* Prominent Open Web Portal button in header */}
            {hasWebPortal && (
              <a
                href={webPortalUrl}
                target="_blank"
                rel="noreferrer"
                style={{
                  display: 'inline-flex',
                  alignItems: 'center',
                  gap: '6px',
                  padding: '8px 16px',
                  borderRadius: '8px',
                  fontSize: '12px',
                  fontFamily: 'var(--mono)',
                  fontWeight: '700',
                  color: '#fff',
                  background: 'linear-gradient(135deg, #0ea5e9, #38bdf8)',
                  textDecoration: 'none',
                  cursor: 'pointer',
                  boxShadow: '0 2px 8px rgba(56, 189, 248, 0.3)',
                  transition: 'all 0.15s ease',
                }}
              >
                <Globe size={14} /> Open Web Portal <ExternalLink size={12} />
              </a>
            )}
          </div>
        </div>

        {/* Error Banner */}
        {errorMessage && (
          <div style={{ padding: '12px 20px', background: 'var(--bg)', borderBottom: '1px solid var(--red-br)', color: 'var(--red)', fontFamily: 'var(--mono)', fontSize: '12px' }}>
            <AlertCircle size={14} style={{ display: 'inline', marginRight: '6px' }} />
            {errorMessage}
          </div>
        )}

        <div style={{ flex: 1, padding: '20px', display: 'flex', flexDirection: 'column', gap: '16px', overflowY: 'auto' }}>
          {/* Agent Card */}
          {currentAgents.map((agent) => {
            const aState = agents[agent.id] || {};
            const isSelected = selectedAgent === agent.id;
            return (
              <div
                key={agent.id}
                onClick={() => setSelectedAgent(agent.id)}
                style={{
                  padding: '16px',
                  background: isSelected ? 'var(--elevated)' : 'var(--surface)',
                  border: `1px solid ${isSelected ? 'var(--accent)' : 'var(--border)'}`,
                  borderRadius: 'var(--radius)',
                  cursor: 'pointer',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'space-between',
                  boxShadow: isSelected ? '0 0 0 1px var(--accent)' : 'none',
                }}
              >
                <div>
                  <div style={{ fontFamily: 'var(--mono)', fontSize: '13px', fontWeight: 'bold', color: 'var(--text)' }}>
                    🤖 {agent.name}
                  </div>
                  <div style={{ fontSize: '11px', color: 'var(--text-3)', marginTop: '2px' }}>
                    STATUS: {aState.status?.toUpperCase() || 'READY'}
                  </div>
                </div>
                {aState.status === 'completed' && <CheckCircle size={20} color="var(--green)" />}
                {aState.status === 'failed' && <AlertCircle size={20} color="var(--red)" />}
                {aState.status === 'running' && <RefreshCw size={20} color="var(--blue)" className="cursor" />}
              </div>
            );
          })}

          {/* Generated Artifacts List */}
          {currentFiles.length > 0 && (
            <div style={{
              padding: '16px',
              background: 'var(--surface)',
              border: '1px solid var(--border)',
              borderRadius: 'var(--radius)',
            }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '8px' }}>
                <div style={{ fontFamily: 'var(--mono)', fontSize: '11px', color: 'var(--text-4)' }}>
                  📂 GENERATED WORKSPACE FILES ({currentFiles.length})
                </div>
                {hasWebPortal && (
                  <button
                    onClick={() => setShowPreviewModal(true)}
                    style={{
                      background: 'rgba(56, 189, 248, 0.12)',
                      border: '1px solid #38bdf8',
                      color: '#38bdf8',
                      borderRadius: '4px',
                      padding: '4px 10px',
                      fontSize: '11px',
                      fontFamily: 'var(--mono)',
                      cursor: 'pointer',
                      display: 'flex',
                      alignItems: 'center',
                      gap: '5px',
                    }}
                  >
                    <Globe size={12} /> OPEN WEB DESIGN PREVIEW
                  </button>
                )}
              </div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
                {currentFiles.map((fn, idx) => (
                  <div key={idx} style={{ fontFamily: 'var(--mono)', fontSize: '12px', color: 'var(--green)', display: 'flex', alignItems: 'center', gap: '6px' }}>
                    <Code size={12} /> {fn}
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Rich Deliverable Visualizers */}
          {phaseNum === 2 && deliverableData && (
            <div>
              <div style={{ fontFamily: 'var(--mono)', fontSize: '11px', color: 'var(--text-4)', marginBottom: '8px', fontWeight: '700' }}>
                📊 COMPETITOR INTEL DASHBOARD
              </div>
              <Phase2CompetitorIntel data={deliverableData} />
            </div>
          )}
          {phaseNum === 3 && deliverableData && (
            <div>
              <div style={{ fontFamily: 'var(--mono)', fontSize: '11px', color: 'var(--text-4)', marginBottom: '8px', fontWeight: '700' }}>
                📣 MARKETING CAMPAIGN DASHBOARD
              </div>
              <Phase3MarketingCampaign data={deliverableData} />
            </div>
          )}
          {phaseNum === 4 && deliverableData && (
            <div>
              <div style={{ fontFamily: 'var(--mono)', fontSize: '11px', color: 'var(--text-4)', marginBottom: '8px', fontWeight: '700' }}>
                🚀 DEPLOYMENT OPERATIONS DASHBOARD
              </div>
              <Phase4DeploymentPrep data={deliverableData} />
            </div>
          )}

          {/* Verification Runner Summary */}
          {currentRunner.command && (
            <div style={{
              padding: '16px',
              background: 'var(--surface)',
              border: '1px solid var(--border)',
              borderRadius: 'var(--radius)',
            }}>
              <div style={{ fontFamily: 'var(--mono)', fontSize: '11px', color: 'var(--text-4)', marginBottom: '8px' }}>
                ⚡ CONTROLLED VERIFICATION RUNNER
              </div>
              <div style={{ fontFamily: 'var(--mono)', fontSize: '12px', color: currentRunner.passed ? 'var(--green)' : 'var(--red)' }}>
                Result: {currentRunner.passed ? 'PASSED (0)' : `FAILED (${currentRunner.exit_code})`}
              </div>
              <div style={{ fontFamily: 'var(--mono)', fontSize: '11px', color: 'var(--text-3)', marginTop: '4px' }}>
                Command: `{currentRunner.command}`
              </div>
            </div>
          )}
        </div>

        {/* Action Toolbar */}
        <div style={{ padding: '20px', background: 'var(--surface)', borderTop: '1px solid var(--border)' }}>
          {(phaseData.status === 'READY' || phaseData.status === 'FAILED') ? (
            <button
              className="new-project-btn"
              onClick={() => handleExecute(null)}
              disabled={isRunning}
              style={{ width: '100%', justifyContent: 'center' }}
            >
              <Play size={16} style={{ marginRight: '8px' }} />
              {isRunning ? 'EXECUTING AGENT...' : 'START PHASE EXECUTION'}
            </button>
          ) : phaseData.status === 'WAITING_FOR_APPROVAL' ? (
            <div style={{ display: 'flex', gap: '12px' }}>
              <button
                className="new-project-btn"
                onClick={handleApprove}
                style={{ flex: 1, justifyContent: 'center' }}
              >
                APPROVE & CONTINUE <ArrowRight size={14} />
              </button>
              <button
                className="retro-btn"
                onClick={() => setShowRevisionModal(true)}
                style={{ flex: 1 }}
              >
                REQUEST REVISION
              </button>
            </div>
          ) : phaseData.status === 'APPROVED' || phaseData.status === 'COMPLETED' ? (
            <div style={{ textAlign: 'center', color: 'var(--green)', fontFamily: 'var(--mono)', fontSize: '14px', fontWeight: 'bold' }}>
              ✓ PHASE APPROVED & FINALIZED IN DATABASE
            </div>
          ) : (
            <button className="retro-btn" disabled style={{ width: '100%' }}>
              EXECUTING...
            </button>
          )}
        </div>
      </div>

      {/* Right Panel: Output & Logs Inspector */}
      <div style={{ width: '460px', display: 'flex', flexDirection: 'column', background: 'var(--surface)' }}>
        <div style={{ padding: '20px', borderBottom: '1px solid var(--border)' }}>
          <h3 style={{ fontSize: '16px', fontFamily: 'var(--mono)', color: 'var(--accent)' }}>
            Inspection & Review
          </h3>
        </div>

        <div style={{ flex: 1, padding: '20px', overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: '16px' }}>
          {/* Criteria Evaluation */}
          {currentVal.criteria_evaluation && (
            <div>
              <div style={{ fontFamily: 'var(--mono)', fontSize: '11px', color: 'var(--text-4)', marginBottom: '8px' }}>
                REVIEWER CRITERIA EVALUATION (Score: {Math.round((currentVal.score || 0) * 100)}%)
              </div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
                {currentVal.criteria_evaluation.map((item, idx) => (
                  <div
                    key={idx}
                    style={{
                      padding: '8px 12px',
                      background: 'var(--bg)',
                      border: '1px solid var(--border)',
                      borderRadius: 'var(--radius)',
                      fontSize: '12px',
                    }}
                  >
                    <div style={{ display: 'flex', alignItems: 'center', gap: '6px', fontWeight: '500' }}>
                      {item.passed ? <CheckCircle size={14} color="var(--green)" /> : <AlertCircle size={14} color="var(--red)" />}
                      <span style={{ color: item.passed ? 'var(--green)' : 'var(--red)' }}>{item.criterion}</span>
                    </div>
                    {item.reason && (
                      <div style={{ fontSize: '11px', color: 'var(--text-3)', marginTop: '2px', fontFamily: 'var(--mono)' }}>
                        {item.reason}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Console / Terminal Stdout */}
          {currentRunner.stdout && (
            <div>
              <div style={{ fontFamily: 'var(--mono)', fontSize: '11px', color: 'var(--text-4)', marginBottom: '4px' }}>
                RUNNER STDOUT
              </div>
              <pre style={{
                background: '#000',
                padding: '10px',
                borderRadius: 'var(--radius)',
                color: '#38bdf8',
                fontSize: '11px',
                fontFamily: 'var(--mono)',
                whiteSpace: 'pre-wrap',
                maxHeight: '120px',
                overflowY: 'auto',
              }}>
                {currentRunner.stdout}
              </pre>
            </div>
          )}

          {/* Execution Logs */}
          <div>
            <div style={{ fontFamily: 'var(--mono)', fontSize: '11px', color: 'var(--text-4)', marginBottom: '4px' }}>
              AGENT EXECUTION LOGS
            </div>
            <div style={{
              background: '#000',
              padding: '10px',
              borderRadius: 'var(--radius)',
              color: 'var(--text-3)',
              fontSize: '11px',
              fontFamily: 'var(--mono)',
              maxHeight: '140px',
              overflowY: 'auto',
            }}>
              {(agentState.logs || ['Waiting to start...']).map((l, i) => (
                <div key={i}>&gt; {l}</div>
              ))}
            </div>
          </div>
        </div>
      </div>

      {/* Revision Modal */}
      {showRevisionModal && (
        <div style={{
          position: 'fixed',
          inset: 0,
          background: 'rgba(0,0,0,0.75)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          zIndex: 9999,
        }}>
          <div style={{
            background: 'var(--surface)',
            border: '1px solid var(--border)',
            padding: '24px',
            borderRadius: 'var(--radius)',
            width: '460px',
            display: 'flex',
            flexDirection: 'column',
            gap: '16px',
          }}>
            <h3 style={{ fontSize: '18px', fontWeight: '600', color: 'var(--text)' }}>Request Phase Revision</h3>
            <p style={{ fontSize: '13px', color: 'var(--text-3)' }}>
              Specify changes or fixes needed. Code Agent will reuse the existing workspace and apply your feedback.
            </p>
            <textarea
              className="term-input"
              rows={4}
              value={revisionFeedback}
              onChange={(e) => setRevisionFeedback(e.target.value)}
              placeholder="e.g. Add a task counter badge and make sure completed tasks have strike-through styling..."
              style={{ width: '100%', fontSize: '13px' }}
            />
            <div style={{ display: 'flex', gap: '12px', justifyContent: 'flex-end' }}>
              <button className="retro-btn" onClick={() => setShowRevisionModal(false)}>Cancel</button>
              <button className="new-project-btn" onClick={handleSubmitRevision} disabled={!revisionFeedback.trim()}>
                Submit & Re-Run Revision
              </button>
            </div>
          </div>
        </div>
      )}
      {/* Live Web Design Preview Modal */}
      {showPreviewModal && (
        <div style={{
          position: 'fixed',
          inset: 0,
          background: 'rgba(0,0,0,0.85)',
          display: 'flex',
          flexDirection: 'column',
          zIndex: 10000,
          padding: '24px',
        }}>
          <div style={{
            background: 'var(--surface)',
            border: '1px solid var(--border)',
            borderRadius: 'var(--radius)',
            flex: 1,
            display: 'flex',
            flexDirection: 'column',
            overflow: 'hidden',
          }}>
            <div style={{
              padding: '12px 20px',
              background: 'var(--elevated)',
              borderBottom: '1px solid var(--border)',
              display: 'flex',
              justifyContent: 'space-between',
              alignItems: 'center',
            }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                <Globe size={18} color="#38bdf8" />
                <span style={{ fontFamily: 'var(--mono)', fontSize: '13px', fontWeight: 'bold', color: 'var(--text)' }}>
                  LIVE WEB DESIGN PREVIEW — Phase {phaseNum} Generated Application
                </span>
              </div>
              <div style={{ display: 'flex', gap: '10px', alignItems: 'center' }}>
                <a
                  href={webPortalUrl}
                  target="_blank"
                  rel="noreferrer"
                  style={{
                    color: 'var(--accent)',
                    textDecoration: 'none',
                    fontSize: '12px',
                    fontFamily: 'var(--mono)',
                    display: 'flex',
                    alignItems: 'center',
                    gap: '4px',
                  }}
                >
                  <ExternalLink size={13} /> Open in New Tab
                </a>
                <button
                  className="retro-btn"
                  onClick={() => setShowPreviewModal(false)}
                  style={{ padding: '4px 12px', fontSize: '12px' }}
                >
                  Close
                </button>
              </div>
            </div>
            <iframe
              title="Phase Web Preview"
              src={webPortalUrl}
              style={{
                flex: 1,
                width: '100%',
                border: 'none',
                background: '#fff',
              }}
            />
          </div>
        </div>
      )}
    </div>
  );
}
