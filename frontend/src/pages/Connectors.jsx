import React, { useEffect, useState } from 'react';
import { useParams } from 'react-router-dom';
import { useProjectStore } from '../store/projectStore';
import { api, ApiError } from '../api/client';
import { Link2, Check, ExternalLink, AlertCircle } from 'lucide-react';

export default function Connectors() {
  const { id } = useParams();
  const { connectors, setConnectors } = useProjectStore();
  const [loading, setLoading]     = useState(true);
  const [fetchError, setFetchError] = useState(null);
  // Per-connector: which one is showing the credential input form
  const [connectingId, setConnectingId] = useState(null);
  // Per-connector: the credential value being typed
  const [credInput, setCredInput]   = useState('');
  const [connectError, setConnectError] = useState(null);
  const [connectBusy, setConnectBusy]   = useState(false);

  const availableConnectors = [
    { id: 'github', name: 'GitHub', type: 'code',      placeholder: 'GitHub Personal Access Token' },
    { id: 'vercel', name: 'Vercel', type: 'deploy',    placeholder: 'Vercel API Token' },
    { id: 'discord', name: 'Discord', type: 'community', placeholder: 'Discord Bot Token' },
    { id: 'reddit', name: 'Reddit', type: 'marketing', placeholder: 'Reddit API Key' },
  ];

  useEffect(() => {
    const fetchCreds = async () => {
      try {
        const res = await api.getConnectors();
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
    };
    fetchCreds();
  }, [setConnectors]);

  const handleBeginConnect = (appId) => {
    setConnectingId(appId);
    setCredInput('');
    setConnectError(null);
  };

  const handleSubmitCredential = async (appName) => {
    const trimmed = credInput.trim();
    if (!trimmed) {
      setConnectError('Please enter a credential value.');
      return;
    }
    setConnectBusy(true);
    setConnectError(null);
    try {
      await api.connectApp(appName, trimmed);
      const res = await api.getConnectors();
      setConnectors(res.connected_apps || res.credentials || []);
      setConnectingId(null);
      setCredInput('');
    } catch (err) {
      const msg = err instanceof ApiError
        ? `HTTP ${err.status} on ${err.endpoint} — ${err.detail}`
        : err.message;
      setConnectError(msg);
    } finally {
      setConnectBusy(false);
    }
  };

  return (
    <div style={{ padding: '24px', display: 'flex', flexDirection: 'column', gap: '24px', height: '100%' }}>
      <div>
        <h1 style={{ fontSize: '24px', fontWeight: '600', color: 'var(--text)' }}>Connectors</h1>
        <p style={{ color: 'var(--text-3)', marginTop: '4px' }}>Global and phase-specific external integrations.</p>
      </div>

      {fetchError && (
        <div style={{ padding: '12px', background: 'var(--bg)', border: '1px solid var(--red-br)', borderRadius: 'var(--radius)', color: 'var(--red)', fontFamily: 'var(--mono)', fontSize: '12px' }}>
          <AlertCircle size={14} style={{ display: 'inline', marginRight: '6px' }} />
          Failed to load connectors: {fetchError}
        </div>
      )}

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))', gap: '16px' }}>
        {availableConnectors.map(conn => {
          const isConnected  = connectors.some(c => c.app_name === conn.id || c.name === conn.id);
          const isExpanded   = connectingId === conn.id;
          return (
            <div key={conn.id} style={{
              background: 'var(--surface)',
              border: '1px solid var(--border)',
              borderRadius: 'var(--radius)',
              padding: '20px',
              display: 'flex',
              flexDirection: 'column',
              gap: '12px'
            }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <div style={{ fontWeight: '600', fontSize: '16px' }}>{conn.name}</div>
                {isConnected ? <Check size={16} color="var(--green)" /> : <Link2 size={16} color="var(--text-4)" />}
              </div>
              <div style={{ fontFamily: 'var(--mono)', fontSize: '11px', color: 'var(--text-4)' }}>
                TYPE: {conn.type.toUpperCase()}
              </div>

              {isConnected ? (
                <div style={{ color: 'var(--green)', fontSize: '13px', display: 'flex', alignItems: 'center', gap: '4px' }}>
                  Connected <ExternalLink size={12} />
                </div>
              ) : isExpanded ? (
                <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                  <input
                    type="password"
                    className="term-input"
                    style={{ padding: '6px 10px', fontSize: '12px', width: '100%' }}
                    placeholder={conn.placeholder}
                    value={credInput}
                    onChange={e => setCredInput(e.target.value)}
                    onKeyDown={e => e.key === 'Enter' && handleSubmitCredential(conn.id)}
                    autoFocus
                  />
                  {connectError && (
                    <div style={{ color: 'var(--red)', fontSize: '11px', fontFamily: 'var(--mono)', whiteSpace: 'pre-wrap' }}>
                      {connectError}
                    </div>
                  )}
                  <div style={{ display: 'flex', gap: '8px' }}>
                    <button className="new-project-btn"
                      style={{ flex: 1, justifyContent: 'center', fontSize: '12px' }}
                      onClick={() => handleSubmitCredential(conn.id)}
                      disabled={connectBusy}>
                      {connectBusy ? 'Connecting...' : 'Connect'}
                    </button>
                    <button className="retro-btn"
                      style={{ fontSize: '12px' }}
                      onClick={() => { setConnectingId(null); setConnectError(null); }}
                      disabled={connectBusy}>
                      Cancel
                    </button>
                  </div>
                </div>
              ) : (
                <button className="retro-btn"
                  onClick={() => handleBeginConnect(conn.id)}
                  disabled={loading}>
                  {loading ? 'Loading...' : 'Connect'}
                </button>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
