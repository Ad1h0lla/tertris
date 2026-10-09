import React, { useEffect, useState } from 'react';
import { useParams } from 'react-router-dom';
import { useProjectStore } from '../store/projectStore';
import { api, ApiError } from '../api/client';
import {
  Activity,
  AlertTriangle,
  CheckCircle2,
  XCircle,
  Clock,
  RefreshCw,
  ExternalLink,
  ShieldCheck,
  ShieldAlert,
  HelpCircle,
  Zap,
  ArrowRight,
} from 'lucide-react';

export default function Health() {
  const { id } = useParams();
  const { project } = useProjectStore();
  const executionId = id || project?.id;

  const [healthData, setHealthData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [assessing, setAssessing] = useState(false);
  const [error, setError] = useState(null);
  const [targetUrlInput, setTargetUrlInput] = useState('');

  const loadHealthReport = async () => {
    if (!executionId) {
      setLoading(false);
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const res = await api.getWorkforceHealth(executionId);
      setHealthData(res);
      if (res?.assessed_url) {
        setTargetUrlInput(res.assessed_url);
      }
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : err.message);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadHealthReport();
  }, [executionId]);

  const handleRunAssessment = async () => {
    if (!executionId || assessing) return;
    setAssessing(true);
    setError(null);
    try {
      const res = await api.assessWorkforceHealth(
        executionId,
        targetUrlInput.trim() || null
      );
      setHealthData(res);
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : err.message);
    } finally {
      setAssessing(false);
    }
  };

  const status = healthData?.status || 'NOT_ASSESSED';
  const observations = healthData?.observations || [];
  const findings = healthData?.findings || [];
  const unavailableSignals = healthData?.unavailable_signals || [];
  const recommendations = healthData?.recommendations || [];
  const assessedUrl = healthData?.assessed_url || targetUrlInput;
  const assessedAt = healthData?.assessed_at;

  const getStatusBadge = () => {
    switch (status) {
      case 'HEALTHY':
        return {
          icon: <CheckCircle2 size={16} color="var(--green)" />,
          color: 'var(--green)',
          bg: 'rgba(34, 197, 94, 0.1)',
          border: '1px solid rgba(34, 197, 94, 0.3)',
          label: 'HEALTHY',
        };
      case 'DEGRADED':
        return {
          icon: <AlertTriangle size={16} color="#f59e0b" />,
          color: '#f59e0b',
          bg: 'rgba(245, 158, 11, 0.1)',
          border: '1px solid rgba(245, 158, 11, 0.3)',
          label: 'DEGRADED',
        };
      case 'UNHEALTHY':
        return {
          icon: <XCircle size={16} color="var(--red)" />,
          color: 'var(--red)',
          bg: 'rgba(239, 68, 68, 0.1)',
          border: '1px solid rgba(239, 68, 68, 0.3)',
          label: 'UNHEALTHY',
        };
      default:
        return {
          icon: <HelpCircle size={16} color="var(--text-3)" />,
          color: 'var(--text-3)',
          bg: 'rgba(156, 163, 175, 0.1)',
          border: '1px solid rgba(156, 163, 175, 0.2)',
          label: 'NOT ASSESSED',
        };
    }
  };

  const badge = getStatusBadge();

  return (
    <div style={{ padding: '24px', display: 'flex', flexDirection: 'column', gap: '24px', height: '100%', overflowY: 'auto' }}>
      {/* Header */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', flexWrap: 'wrap', gap: '16px' }}>
        <div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
            <h1 style={{ fontSize: '24px', fontWeight: '600', color: 'var(--text)' }}>Health & Operate Monitor</h1>
            <div style={{
              display: 'inline-flex',
              alignItems: 'center',
              gap: '6px',
              padding: '4px 12px',
              borderRadius: '99px',
              fontFamily: 'var(--mono)',
              fontSize: '11px',
              fontWeight: '700',
              color: badge.color,
              background: badge.bg,
              border: badge.border,
            }}>
              {badge.icon} {badge.label}
            </div>
          </div>
          <p style={{ color: 'var(--text-3)', marginTop: '4px', fontSize: '13px' }}>
            Authoritative Stage 6F evidence-backed health inspection for verified deployment targets.
          </p>
        </div>

        {/* Action Controls */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
          <button
            className="new-project-btn"
            onClick={handleRunAssessment}
            disabled={assessing}
            style={{ display: 'flex', alignItems: 'center', gap: '8px' }}
          >
            <RefreshCw size={14} className={assessing ? 'animate-spin' : ''} />
            {assessing ? 'EVALUATING DEPLOYMENT...' : 'RUN HEALTH ASSESSMENT'}
          </button>
        </div>
      </div>

      {/* Target URL Configuration Bar */}
      <div style={{
        padding: '16px',
        background: 'var(--surface)',
        border: '1px solid var(--border)',
        borderRadius: 'var(--radius)',
        display: 'flex',
        alignItems: 'center',
        gap: '12px',
      }}>
        <div style={{ fontFamily: 'var(--mono)', fontSize: '11px', color: 'var(--text-4)', whiteSpace: 'nowrap' }}>
          DEPLOYMENT URL:
        </div>
        <input
          type="text"
          value={targetUrlInput}
          onChange={(e) => setTargetUrlInput(e.target.value)}
          placeholder="https://your-deployed-app.vercel.app (auto-detected from verified artifacts)"
          style={{
            flex: 1,
            background: 'var(--bg)',
            border: '1px solid var(--border)',
            borderRadius: '4px',
            padding: '8px 12px',
            color: 'var(--text)',
            fontSize: '13px',
            fontFamily: 'var(--mono)',
          }}
        />
        {assessedUrl && (
          <a
            href={assessedUrl}
            target="_blank"
            rel="noreferrer"
            style={{
              color: 'var(--accent)',
              display: 'flex',
              alignItems: 'center',
              gap: '4px',
              fontSize: '12px',
              textDecoration: 'none',
              fontFamily: 'var(--mono)',
            }}
          >
            Open <ExternalLink size={12} />
          </a>
        )}
      </div>

      {/* Error Banner */}
      {error && (
        <div style={{
          padding: '14px 16px',
          background: 'rgba(239, 68, 68, 0.08)',
          border: '1px solid var(--red-br)',
          borderRadius: 'var(--radius)',
          color: 'var(--red)',
          fontFamily: 'var(--mono)',
          fontSize: '12px',
          display: 'flex',
          alignItems: 'center',
          gap: '8px',
        }}>
          <AlertTriangle size={16} />
          <span>{error}</span>
        </div>
      )}

      {/* Loading state */}
      {loading && (
        <div style={{ padding: '40px', textAlign: 'center', color: 'var(--text-3)', fontFamily: 'var(--mono)' }}>
          <RefreshCw size={24} className="animate-spin" style={{ margin: '0 auto 12px' }} />
          Loading persisted health telemetry...
        </div>
      )}

      {/* Not Assessed Empty State */}
      {!loading && status === 'NOT_ASSESSED' && (
        <div style={{
          padding: '48px 24px',
          background: 'var(--surface)',
          border: '1px dashed var(--border)',
          borderRadius: 'var(--radius)',
          textAlign: 'center',
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          gap: '12px',
        }}>
          <ShieldAlert size={36} color="var(--text-4)" />
          <div style={{ fontSize: '16px', fontWeight: '600', color: 'var(--text)' }}>
            No Health Assessment Conducted Yet
          </div>
          <p style={{ fontSize: '13px', color: 'var(--text-3)', maxWidth: '460px', lineHeight: '1.5' }}>
            This project has not undergone an evidence-backed health inspection. Run an assessment to collect honest HTTP telemetry, response latency, and operational findings.
          </p>
          <button
            className="new-project-btn"
            onClick={handleRunAssessment}
            disabled={assessing}
            style={{ marginTop: '8px' }}
          >
            <Zap size={14} /> Assess Health Now
          </button>
        </div>
      )}

      {/* Assessed Telemetry View */}
      {!loading && status !== 'NOT_ASSESSED' && (
        <>
          {/* Key Metrics Cards */}
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: '16px' }}>
            <div style={{
              background: 'var(--surface)',
              border: '1px solid var(--border)',
              borderRadius: 'var(--radius)',
              padding: '18px',
            }}>
              <div style={{ fontSize: '11px', color: 'var(--text-4)', textTransform: 'uppercase', fontFamily: 'var(--mono)', marginBottom: '6px' }}>
                OVERALL HEALTH STATUS
              </div>
              <div style={{ fontSize: '24px', fontWeight: '700', color: badge.color, display: 'flex', alignItems: 'center', gap: '8px' }}>
                {badge.icon} {status}
              </div>
              <div style={{ fontSize: '11px', color: 'var(--text-3)', marginTop: '6px', fontFamily: 'var(--mono)' }}>
                {assessedAt ? `Evaluated: ${new Date(assessedAt).toLocaleString()}` : 'Recently evaluated'}
              </div>
            </div>

            <div style={{
              background: 'var(--surface)',
              border: '1px solid var(--border)',
              borderRadius: 'var(--radius)',
              padding: '18px',
            }}>
              <div style={{ fontSize: '11px', color: 'var(--text-4)', textTransform: 'uppercase', fontFamily: 'var(--mono)', marginBottom: '6px' }}>
                OBSERVATIONS COLLECTED
              </div>
              <div style={{ fontSize: '24px', fontWeight: '700', color: 'var(--text)' }}>
                {observations.length}
              </div>
              <div style={{ fontSize: '11px', color: 'var(--text-3)', marginTop: '6px' }}>
                Evidence signals verified
              </div>
            </div>

            <div style={{
              background: 'var(--surface)',
              border: `1px solid ${findings.length > 0 ? 'var(--red-br)' : 'var(--border)'}`,
              borderRadius: 'var(--radius)',
              padding: '18px',
            }}>
              <div style={{ fontSize: '11px', color: 'var(--text-4)', textTransform: 'uppercase', fontFamily: 'var(--mono)', marginBottom: '6px' }}>
                DIAGNOSTIC FINDINGS
              </div>
              <div style={{ fontSize: '24px', fontWeight: '700', color: findings.length > 0 ? 'var(--red)' : 'var(--green)' }}>
                {findings.length}
              </div>
              <div style={{ fontSize: '11px', color: 'var(--text-3)', marginTop: '6px' }}>
                {findings.length === 0 ? 'Zero active faults detected' : 'Issues requiring attention'}
              </div>
            </div>

            <div style={{
              background: 'var(--surface)',
              border: '1px solid var(--border)',
              borderRadius: 'var(--radius)',
              padding: '18px',
            }}>
              <div style={{ fontSize: '11px', color: 'var(--text-4)', textTransform: 'uppercase', fontFamily: 'var(--mono)', marginBottom: '6px' }}>
                UNAVAILABLE SIGNALS
              </div>
              <div style={{ fontSize: '24px', fontWeight: '700', color: 'var(--text-3)' }}>
                {unavailableSignals.length}
              </div>
              <div style={{ fontSize: '11px', color: 'var(--text-3)', marginTop: '6px' }}>
                Unobservable metrics flagged
              </div>
            </div>
          </div>

          {/* Observations & Findings Section */}
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '20px' }}>
            {/* Structured Observations */}
            <div style={{
              background: 'var(--surface)',
              border: '1px solid var(--border)',
              borderRadius: 'var(--radius)',
              padding: '20px',
              display: 'flex',
              flexDirection: 'column',
              gap: '14px',
            }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px', color: 'var(--text)' }}>
                <Activity size={16} color="var(--accent)" />
                <h3 style={{ fontSize: '14px', fontFamily: 'var(--mono)', fontWeight: '700' }}>
                  EVIDENCE OBSERVATIONS ({observations.length})
                </h3>
              </div>

              <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                {observations.map((obs, idx) => (
                  <div
                    key={idx}
                    style={{
                      padding: '10px 12px',
                      background: 'var(--bg)',
                      border: '1px solid var(--border)',
                      borderRadius: '4px',
                      display: 'flex',
                      justifyContent: 'space-between',
                      alignItems: 'center',
                    }}
                  >
                    <div>
                      <div style={{ fontFamily: 'var(--mono)', fontSize: '12px', color: 'var(--text)', fontWeight: '600' }}>
                        {obs.category || obs.name || `Signal ${idx + 1}`}
                      </div>
                      <div style={{ fontSize: '11px', color: 'var(--text-3)', marginTop: '2px' }}>
                        {typeof obs.value === 'object' ? JSON.stringify(obs.value) : String(obs.value ?? '')}
                      </div>
                    </div>
                    <span style={{
                      fontFamily: 'var(--mono)',
                      fontSize: '10px',
                      padding: '2px 8px',
                      borderRadius: '99px',
                      color: obs.status === 'OK' || obs.status === 'HEALTHY' ? 'var(--green)' : 'var(--red)',
                      background: obs.status === 'OK' || obs.status === 'HEALTHY' ? 'rgba(34, 197, 94, 0.1)' : 'rgba(239, 68, 68, 0.1)',
                    }}>
                      {obs.status || 'COLLECTED'}
                    </span>
                  </div>
                ))}
              </div>
            </div>

            {/* Diagnostic Findings */}
            <div style={{
              background: 'var(--surface)',
              border: '1px solid var(--border)',
              borderRadius: 'var(--radius)',
              padding: '20px',
              display: 'flex',
              flexDirection: 'column',
              gap: '14px',
            }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px', color: 'var(--text)' }}>
                <AlertTriangle size={16} color={findings.length > 0 ? 'var(--red)' : 'var(--green)'} />
                <h3 style={{ fontSize: '14px', fontFamily: 'var(--mono)', fontWeight: '700' }}>
                  DIAGNOSTIC FINDINGS ({findings.length})
                </h3>
              </div>

              {findings.length === 0 ? (
                <div style={{ padding: '24px', textAlign: 'center', color: 'var(--green)', fontFamily: 'var(--mono)', fontSize: '12px' }}>
                  ✓ All collected signals satisfy operational thresholds.
                </div>
              ) : (
                <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                  {findings.map((finding, idx) => (
                    <div
                      key={idx}
                      style={{
                        padding: '12px',
                        background: 'rgba(239, 68, 68, 0.05)',
                        borderLeft: '3px solid var(--red)',
                        borderRadius: '0 4px 4px 0',
                      }}
                    >
                      <div style={{ fontSize: '13px', color: 'var(--text)', fontWeight: '600' }}>
                        {finding.title || finding.category || 'Diagnostic Issue'}
                      </div>
                      <div style={{ fontSize: '12px', color: 'var(--text-2, var(--text))', marginTop: '4px', lineHeight: '1.4' }}>
                        {finding.description || finding.message || JSON.stringify(finding)}
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>

          {/* Recommendations & Unavailable Signals */}
          {recommendations.length > 0 && (
            <div style={{
              background: 'var(--surface)',
              border: '1px solid var(--border)',
              borderRadius: 'var(--radius)',
              padding: '20px',
            }}>
              <div style={{ fontFamily: 'var(--mono)', fontSize: '11px', color: 'var(--text-4)', marginBottom: '12px', fontWeight: '700' }}>
                💡 OPERATIONAL RECOMMENDATIONS ({recommendations.length})
              </div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                {recommendations.map((rec, idx) => (
                  <div key={idx} style={{ display: 'flex', alignItems: 'flex-start', gap: '8px', fontSize: '13px', color: 'var(--text)' }}>
                    <ArrowRight size={14} style={{ marginTop: '2px', color: 'var(--accent)', flexShrink: 0 }} />
                    <div>
                      {typeof rec === 'string' ? rec : rec.action || rec.recommendation || JSON.stringify(rec)}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
}
