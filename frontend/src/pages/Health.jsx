import React from 'react';
import { useParams } from 'react-router-dom';
import { Activity, AlertTriangle, ArrowUpRight } from 'lucide-react';

export default function Health() {
  const { id } = useParams();

  // Mocked foundational data - this would come from the API in the future
  const healthMetrics = [
    { label: 'Uptime', value: '99.9%', status: 'healthy' },
    { label: 'API Errors', value: '12', status: 'warning' },
    { label: 'Bot Activity', value: '3 Active', status: 'healthy' },
    { label: 'User Conversion', value: '2.4%', status: 'healthy' },
  ];

  return (
    <div style={{ padding: '24px', display: 'flex', flexDirection: 'column', gap: '24px', height: '100%' }}>
      <div>
        <h1 style={{ fontSize: '24px', fontWeight: '600', color: 'var(--text)' }}>Health & Impact</h1>
        <p style={{ color: 'var(--text-3)', marginTop: '4px' }}>Post-launch continuous monitoring layer.</p>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: '16px' }}>
        {healthMetrics.map((metric, i) => (
          <div key={i} style={{
            background: 'var(--surface)',
            border: `1px solid ${metric.status === 'warning' ? 'var(--red-br)' : 'var(--border)'}`,
            borderRadius: 'var(--radius)',
            padding: '20px',
          }}>
            <div style={{ fontSize: '12px', color: 'var(--text-3)', textTransform: 'uppercase', fontFamily: 'var(--mono)', marginBottom: '8px' }}>
              {metric.label}
            </div>
            <div style={{ fontSize: '28px', fontWeight: '600', color: metric.status === 'warning' ? 'var(--red)' : 'var(--text)' }}>
              {metric.value}
            </div>
          </div>
        ))}
      </div>

      <div style={{
        background: 'var(--surface)',
        border: '1px solid var(--border)',
        borderRadius: 'var(--radius)',
        padding: '24px',
        flex: 1
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '16px', color: 'var(--accent)' }}>
          <Activity size={18} />
          <h2 style={{ fontSize: '16px', fontFamily: 'var(--mono)' }}>SYSTEM EVENTS</h2>
        </div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
          <div style={{ padding: '12px', background: 'var(--bg)', borderLeft: '3px solid var(--green)' }}>
            <div style={{ fontSize: '13px', color: 'var(--text)' }}>Reddit Marketing Bot successfully posted to r/entrepreneur</div>
            <div style={{ fontSize: '11px', color: 'var(--text-4)', marginTop: '4px', fontFamily: 'var(--mono)' }}>2 mins ago</div>
          </div>
          <div style={{ padding: '12px', background: 'var(--bg)', borderLeft: '3px solid var(--red)' }}>
            <div style={{ fontSize: '13px', color: 'var(--text)' }}>Stripe Webhook Failed: Connection Timeout</div>
            <div style={{ fontSize: '11px', color: 'var(--text-4)', marginTop: '4px', fontFamily: 'var(--mono)' }}>14 mins ago</div>
          </div>
          <div style={{ padding: '12px', background: 'var(--bg)', borderLeft: '3px solid var(--green)' }}>
            <div style={{ fontSize: '13px', color: 'var(--text)' }}>Deployment v1.0.4 Live on Vercel</div>
            <div style={{ fontSize: '11px', color: 'var(--text-4)', marginTop: '4px', fontFamily: 'var(--mono)' }}>1 hour ago</div>
          </div>
        </div>
      </div>
    </div>
  );
}
