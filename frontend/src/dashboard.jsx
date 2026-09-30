import React from 'react';
import {Activity, ArrowUpRight, Check} from 'lucide-react';
import {Button, StatusBadge} from './components.jsx';

export function Dashboard({status, incidents, loaded, stale, onSelect, onNew}) {
  const counts = status?.incidents;
  const known = loaded && counts && !stale;
  const active = incidents.filter(item => item.status !== 'resolved');
  const recent = incidents.filter(item => item.status === 'resolved').slice(0, 5);
  const healthy = known && counts.active === 0;
  const rows = active.length ? active : recent;
  return <section className="dashboard" aria-label="Operations overview">
    <div className="dashboard-heading"><div><p className="eyebrow">Overview</p><h1>Production, at a glance.</h1></div><Button onClick={onNew}>Ask the agent<ArrowUpRight size={15}/></Button></div>
    <div className={`health-summary ${healthy ? 'clear' : ''}`}>
      <span className="health-icon">{healthy ? <Check size={22}/> : <Activity size={22}/>}</span>
      <div><h2>{!known ? 'Waiting for current status' : healthy ? 'No active incidents' : `${counts.active} active ${counts.active === 1 ? 'incident' : 'incidents'}`}</h2>
      <p>{!known ? 'The overview updates when the connection is available.' : healthy ? 'New alerts will appear here for investigation.' : counts.attention ? `${counts.attention} ${counts.attention === 1 ? 'investigation needs' : 'investigations need'} your attention.` : 'The agent is working on the latest alerts.'}</p></div>
    </div>
    <div className="dashboard-metrics">{[['Active incidents', counts?.active], ['Need attention', counts?.attention], ['Investigating', counts?.investigating]].map(([label, value]) => <div key={label}><span>{label}</span><strong>{known ? value : '—'}</strong></div>)}</div>
    <section className="dashboard-history"><div className="history-heading"><h2>{active.length ? 'Active incidents' : 'Recent history'}</h2><span>Latest recorded investigations</span></div>
      {rows.length ? rows.map(item => <button className="history-row" key={item.id} onClick={() => onSelect(item.id)}><div><strong>{item.title || 'Production investigation'}</strong><span>{new Date(item.created_at).toLocaleString([], {month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit'})}</span></div><StatusBadge incident={item} configured={status?.configured}/><ArrowUpRight size={16}/></button>) : <div className="history-empty"><Activity size={22}/><p>{known ? 'No investigations recorded yet.' : 'Incident history is loading.'}</p></div>}
    </section>
    <p className="dashboard-note">Incident status reflects recorded investigations. It is not an uptime measurement.</p>
  </section>;
}
