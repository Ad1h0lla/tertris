/**
 * Connectors.jsx — M3.5-A
 *
 * Per-platform structured credential forms for:
 *   Reddit, X/Twitter, LinkedIn, SendGrid, SMTP
 *
 * States per connector:
 *   NOT_CONNECTED  → [Connect] button
 *   CONNECTING     → structured form fields  [Connect] / [Cancel]
 *   CONNECTED      → [Test Connection] [Disconnect]
 *   TESTING        → spinner
 *   VERIFIED       → green verified badge
 *   FAILED         → red error + [Retry] / [Disconnect]
 *
 * Security: secret fields use type="password". Values are never logged or
 * displayed after submission.
 */

import React, { useEffect, useState, useCallback } from 'react';
import { useProjectStore } from '../store/projectStore';
import { api, ApiError } from '../api/client';
import {
  Link2, Check, ExternalLink, AlertCircle, Wifi, WifiOff,
  RefreshCw, Trash2, ChevronDown, ChevronUp, Loader
} from 'lucide-react';

// ─── Platform schemas ────────────────────────────────────────────────────────
// Mirrors CONNECTOR_FIELD_SCHEMAS in routes/credentials.py

const PLATFORMS = [
  {
    id: 'reddit',
    label: 'Reddit',
    description: 'Post to subreddits and build community presence',
    color: '#FF4500',
    fields: [
      { key: 'client_id',     label: 'Client ID',      secret: false, required: true,  placeholder: 'From reddit.com/prefs/apps' },
      { key: 'client_secret', label: 'Client Secret',  secret: true,  required: true,  placeholder: '••••••••••••••••' },
      { key: 'username',      label: 'Reddit Username', secret: false, required: true,  placeholder: 'your_reddit_username' },
      { key: 'password',      label: 'Reddit Password', secret: true,  required: true,  placeholder: '••••••••••••••••' },
      { key: 'user_agent',    label: 'User Agent',      secret: false, required: false, placeholder: 'TetrisBot/1.0 (by /u/yourname)' },
    ],
  },
  {
    id: 'twitter',
    label: 'X / Twitter',
    description: 'Publish posts and distribute content on X',
    color: '#1DA1F2',
    fields: [
      { key: 'api_key',             label: 'API Key',             secret: false, required: true,  placeholder: 'From developer.twitter.com' },
      { key: 'api_secret',          label: 'API Secret',          secret: true,  required: true,  placeholder: '••••••••••••••••' },
      { key: 'access_token',        label: 'Access Token',        secret: false, required: true,  placeholder: 'Your access token' },
      { key: 'access_token_secret', label: 'Access Token Secret', secret: true,  required: true,  placeholder: '••••••••••••••••' },
      { key: 'bearer_token',        label: 'Bearer Token',        secret: true,  required: false, placeholder: 'Optional — for read-only calls' },
    ],
  },
  {
    id: 'linkedin',
    label: 'LinkedIn',
    description: 'Publish professional content on LinkedIn',
    color: '#0A66C2',
    fields: [
      { key: 'access_token', label: 'Access Token', secret: true,  required: true, placeholder: 'Your LinkedIn OAuth access token' },
      { key: 'person_id',    label: 'Person ID',    secret: false, required: true, placeholder: 'urn:li:person:XXXXXXXX  or  XXXXXXXX' },
    ],
  },
  {
    id: 'sendgrid',
    label: 'SendGrid',
    description: 'Send outreach emails via SendGrid',
    color: '#1A82E2',
    fields: [
      { key: 'api_key',    label: 'SendGrid API Key', secret: true,  required: true,  placeholder: 'SG.xxxxxxxxxxxx' },
      { key: 'from_email', label: 'From Email',       secret: false, required: false, placeholder: 'noreply@yourdomain.com' },
      { key: 'from_name',  label: 'From Name',        secret: false, required: false, placeholder: 'Your Name or Company' },
    ],
  },
  {
    id: 'smtp',
    label: 'SMTP',
    description: 'Send outreach emails via your own SMTP server',
    color: '#6B7280',
    fields: [
      { key: 'host',       label: 'SMTP Host',     secret: false, required: true,  placeholder: 'smtp.gmail.com' },
      { key: 'port',       label: 'Port',          secret: false, required: false, placeholder: '587' },
      { key: 'username',   label: 'Username',      secret: false, required: true,  placeholder: 'you@example.com' },
      { key: 'password',   label: 'Password',      secret: true,  required: true,  placeholder: '••••••••••••••••' },
      { key: 'from_email', label: 'From Email',    secret: false, required: false, placeholder: 'you@example.com' },
      { key: 'from_name',  label: 'From Name',     secret: false, required: false, placeholder: 'Your Name' },
      { key: 'use_tls',    label: 'Use TLS',       secret: false, required: false, placeholder: 'true' },
    ],
  },
];

// ─── Connection state machine ─────────────────────────────────────────────────
const STATE = {
  IDLE:        'IDLE',
  CONNECTING:  'CONNECTING',
  SAVING:      'SAVING',
  CONNECTED:   'CONNECTED',
  TESTING:     'TESTING',
  VERIFIED:    'VERIFIED',
  FAILED:      'FAILED',
};

// ─── Status badge ─────────────────────────────────────────────────────────────
function StatusBadge({ state }) {
  const map = {
    [STATE.CONNECTED]: { label: 'Connected',    color: 'var(--green)',  icon: <Check  size={12} /> },
    [STATE.VERIFIED]:  { label: 'Verified',     color: '#22d3ee',       icon: <Wifi   size={12} /> },
    [STATE.FAILED]:    { label: 'Auth Failed',  color: 'var(--red)',    icon: <WifiOff size={12} /> },
    [STATE.TESTING]:   { label: 'Testing…',     color: 'var(--text-3)', icon: <Loader size={12} style={{ animation: 'spin 1s linear infinite' }} /> },
    [STATE.SAVING]:    { label: 'Saving…',      color: 'var(--text-3)', icon: <Loader size={12} style={{ animation: 'spin 1s linear infinite' }} /> },
  };
  const info = map[state];
  if (!info) return null;
  return (
    <span style={{
      display: 'inline-flex', alignItems: 'center', gap: '4px',
      fontSize: '11px', fontWeight: 600, color: info.color,
      fontFamily: 'var(--mono)', textTransform: 'uppercase', letterSpacing: '0.05em',
    }}>
      {info.icon} {info.label}
    </span>
  );
}

// ─── Single connector card ────────────────────────────────────────────────────
function ConnectorCard({ platform, connectedApps, userId, onRefresh }) {
  const isConnectedInDB = connectedApps.some(
    c => c.app_name === platform.id || c.name === platform.id
  );

  const [state,      setState]      = useState(isConnectedInDB ? STATE.CONNECTED : STATE.IDLE);
  const [expanded,   setExpanded]   = useState(false);
  const [formValues, setFormValues] = useState({});
  const [error,      setError]      = useState(null);
  const [testInfo,   setTestInfo]   = useState(null); // display_name from test endpoint

  // Sync state if parent data changes (e.g. after a refresh)
  useEffect(() => {
    const nowConnected = connectedApps.some(
      c => c.app_name === platform.id || c.name === platform.id
    );
    if (!nowConnected && state === STATE.CONNECTED) setState(STATE.IDLE);
    if (nowConnected  && state === STATE.IDLE)      setState(STATE.CONNECTED);
  }, [connectedApps]); // eslint-disable-line

  const handleFieldChange = (key, value) => {
    setFormValues(prev => ({ ...prev, [key]: value }));
  };

  const validateRequired = () => {
    const missing = platform.fields
      .filter(f => f.required && !(formValues[f.key] || '').trim())
      .map(f => f.label);
    return missing;
  };

  const handleConnect = async () => {
    const missing = validateRequired();
    if (missing.length > 0) {
      setError(`Required: ${missing.join(', ')}`);
      return;
    }
    setError(null);
    setState(STATE.SAVING);

    // Strip empty optional fields so workers don't receive empty strings
    const cleaned = {};
    for (const [k, v] of Object.entries(formValues)) {
      if (v && v.trim()) cleaned[k] = v.trim();
    }

    try {
      await api.connectApp(platform.id, cleaned);
      setState(STATE.CONNECTED);
      setExpanded(false);
      setFormValues({});
      onRefresh();
    } catch (err) {
      const msg = err instanceof ApiError
        ? `HTTP ${err.status} — ${err.detail}`
        : err.message;
      setError(msg);
      setState(STATE.CONNECTING);
    }
  };

  const handleTest = async () => {
    setError(null);
    setTestInfo(null);
    setState(STATE.TESTING);
    try {
      const res = await api.testConnector(platform.id, userId);
      if (res.verified) {
        setState(STATE.VERIFIED);
        setTestInfo(res.display_name || null);
      } else {
        setState(STATE.FAILED);
        setError(res.error || 'Authentication failed');
      }
    } catch (err) {
      const msg = err instanceof ApiError
        ? `HTTP ${err.status} — ${err.detail}`
        : err.message;
      setState(STATE.FAILED);
      setError(msg);
    }
  };

  const handleDisconnect = async () => {
    setError(null);
    try {
      await api.disconnectApp(platform.id, userId);
      setState(STATE.IDLE);
      setTestInfo(null);
      onRefresh();
    } catch (err) {
      const msg = err instanceof ApiError
        ? `HTTP ${err.status} — ${err.detail}`
        : err.message;
      setError(msg);
    }
  };

  const isBusy   = [STATE.SAVING, STATE.TESTING].includes(state);
  const isConn   = [STATE.CONNECTED, STATE.VERIFIED, STATE.FAILED, STATE.TESTING].includes(state);

  return (
    <div style={{
      background: 'var(--surface)',
      border: `1px solid ${isConn ? (state === STATE.VERIFIED ? '#22d3ee44' : state === STATE.FAILED ? 'var(--red-br)' : 'var(--green-br, #22d97844)') : 'var(--border)'}`,
      borderRadius: 'var(--radius)',
      padding: '20px',
      display: 'flex',
      flexDirection: 'column',
      gap: '14px',
      transition: 'border-color 0.2s',
    }}>
      {/* Header */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
          <div style={{
            width: 10, height: 10, borderRadius: '50%',
            background: platform.color, flexShrink: 0,
          }} />
          <div>
            <div style={{ fontWeight: 600, fontSize: '15px', color: 'var(--text)' }}>
              {platform.label}
            </div>
            <div style={{ fontSize: '11px', color: 'var(--text-4)', marginTop: '2px' }}>
              {platform.description}
            </div>
          </div>
        </div>
        <StatusBadge state={isConn ? state : null} />
      </div>

      {/* Verified identity display */}
      {testInfo && state === STATE.VERIFIED && (
        <div style={{
          fontSize: '12px', color: '#22d3ee', fontFamily: 'var(--mono)',
          display: 'flex', alignItems: 'center', gap: '6px',
        }}>
          <Check size={12} /> {testInfo}
        </div>
      )}

      {/* Error banner */}
      {error && (
        <div style={{
          padding: '8px 10px',
          background: 'var(--bg)',
          border: '1px solid var(--red-br)',
          borderRadius: 'var(--radius)',
          color: 'var(--red)',
          fontSize: '11px',
          fontFamily: 'var(--mono)',
          whiteSpace: 'pre-wrap',
          wordBreak: 'break-word',
          display: 'flex',
          gap: '6px',
          alignItems: 'flex-start',
        }}>
          <AlertCircle size={12} style={{ flexShrink: 0, marginTop: 1 }} />
          {error}
        </div>
      )}

      {/* State: NOT connected — show credential form when expanded */}
      {!isConn && (
        <div>
          {!expanded ? (
            <button
              className="retro-btn"
              style={{ width: '100%', justifyContent: 'center' }}
              onClick={() => { setExpanded(true); setState(STATE.CONNECTING); setError(null); }}
            >
              <Link2 size={13} /> Connect
            </button>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
              {platform.fields.map(field => (
                <div key={field.key} style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
                  <label style={{
                    fontSize: '10px', fontWeight: 600, color: 'var(--text-3)',
                    fontFamily: 'var(--mono)', textTransform: 'uppercase',
                    letterSpacing: '0.06em',
                  }}>
                    {field.label}
                    {field.required && <span style={{ color: 'var(--red)', marginLeft: 3 }}>*</span>}
                  </label>
                  <input
                    type={field.secret ? 'password' : 'text'}
                    className="term-input"
                    style={{ padding: '7px 10px', fontSize: '12px', width: '100%', boxSizing: 'border-box' }}
                    placeholder={field.placeholder || ''}
                    value={formValues[field.key] || ''}
                    onChange={e => handleFieldChange(field.key, e.target.value)}
                    onKeyDown={e => {
                      if (e.key === 'Enter' && !isBusy) handleConnect();
                      if (e.key === 'Escape') { setExpanded(false); setState(STATE.IDLE); setError(null); }
                    }}
                    autoComplete={field.secret ? 'new-password' : 'off'}
                  />
                </div>
              ))}
              <div style={{ display: 'flex', gap: '8px', marginTop: '4px' }}>
                <button
                  className="new-project-btn"
                  style={{ flex: 1, justifyContent: 'center', fontSize: '12px' }}
                  onClick={handleConnect}
                  disabled={isBusy}
                >
                  {state === STATE.SAVING ? <><Loader size={12} /> Saving…</> : 'Connect'}
                </button>
                <button
                  className="retro-btn"
                  style={{ fontSize: '12px' }}
                  onClick={() => { setExpanded(false); setState(STATE.IDLE); setError(null); setFormValues({}); }}
                  disabled={isBusy}
                >
                  Cancel
                </button>
              </div>
            </div>
          )}
        </div>
      )}

      {/* State: CONNECTED / VERIFIED / FAILED / TESTING */}
      {isConn && (
        <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
          <button
            className="retro-btn"
            style={{ fontSize: '12px', flex: '1 1 auto', justifyContent: 'center' }}
            onClick={handleTest}
            disabled={isBusy}
          >
            {state === STATE.TESTING
              ? <><Loader size={12} style={{ animation: 'spin 1s linear infinite' }} /> Testing…</>
              : <><RefreshCw size={12} /> Test Connection</>
            }
          </button>
          <button
            className="retro-btn"
            style={{ fontSize: '12px', color: 'var(--text-4)', borderColor: 'var(--border)' }}
            onClick={handleDisconnect}
            disabled={isBusy}
            title="Disconnect"
          >
            <Trash2 size={12} />
          </button>
        </div>
      )}

      {/* Re-connect form for FAILED state */}
      {state === STATE.FAILED && (
        <button
          className="retro-btn"
          style={{ fontSize: '11px', color: 'var(--text-3)', justifyContent: 'center' }}
          onClick={() => { setState(STATE.CONNECTING); setExpanded(true); setError(null); }}
        >
          Update Credentials
        </button>
      )}
    </div>
  );
}

// ─── Main Connectors page ─────────────────────────────────────────────────────
export default function Connectors() {
  const { connectors, setConnectors } = useProjectStore();
  const [loading,    setLoading]    = useState(true);
  const [fetchError, setFetchError] = useState(null);
  const userId = 'user_001';

  const fetchCreds = useCallback(async () => {
    try {
      const res = await api.getConnectors(userId);
      setConnectors(res.connected_apps || res.credentials || []);
      setFetchError(null);
    } catch (err) {
      const msg = err instanceof ApiError
        ? `HTTP ${err.status} — ${err.detail}`
        : err.message;
      setFetchError(msg);
    } finally {
      setLoading(false);
    }
  }, [setConnectors, userId]);

  useEffect(() => { fetchCreds(); }, [fetchCreds]);

  return (
    <div style={{ padding: '24px', display: 'flex', flexDirection: 'column', gap: '24px', maxWidth: '900px' }}>
      <div>
        <h1 style={{ fontSize: '24px', fontWeight: '700', color: 'var(--text)', margin: 0 }}>
          Connectors
        </h1>
        <p style={{ color: 'var(--text-3)', marginTop: '6px', fontSize: '13px' }}>
          Connect distribution platforms so Tetris can execute campaigns on your behalf.
          Credentials are encrypted at rest and never returned by the API.
        </p>
      </div>

      {fetchError && (
        <div style={{
          padding: '12px',
          background: 'var(--bg)',
          border: '1px solid var(--red-br)',
          borderRadius: 'var(--radius)',
          color: 'var(--red)',
          fontFamily: 'var(--mono)',
          fontSize: '12px',
          display: 'flex',
          alignItems: 'center',
          gap: '8px',
        }}>
          <AlertCircle size={14} />
          Failed to load connectors: {fetchError}
        </div>
      )}

      {loading ? (
        <div style={{ color: 'var(--text-4)', fontSize: '13px', fontFamily: 'var(--mono)' }}>
          Loading…
        </div>
      ) : (
        <div style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fill, minmax(320px, 1fr))',
          gap: '16px',
        }}>
          {PLATFORMS.map(platform => (
            <ConnectorCard
              key={platform.id}
              platform={platform}
              connectedApps={connectors}
              userId={userId}
              onRefresh={fetchCreds}
            />
          ))}
        </div>
      )}

      <style>{`
        @keyframes spin { to { transform: rotate(360deg); } }
      `}</style>
    </div>
  );
}
