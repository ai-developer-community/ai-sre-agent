import React from 'react';
import {Activity, ArrowUpRight, Check, CircleAlert, Clock3, Inbox, MessageSquare, Search} from 'lucide-react';
import {Button, StatusBadge} from './components.jsx';

export function Dashboard({status, incidents, loaded, stale, onSelect, onNew}) {
  const counts = status?.incidents;
  const known = loaded && counts && !stale;
  const active = incidents.filter(item => item.status !== 'resolved');
  const recent = incidents.filter(item => item.status === 'resolved').slice(0, 5);
  const healthy = known && counts.active === 0;
  const rows = active.length ? active : recent;
  return <section className="dashboard" aria-label="Operations overview">
    <div className="dashboard-heading"><div><h1>Production overview</h1><p className="dashboard-description">Your incidents, investigations and recovery actions.</p></div><Button icon={MessageSquare} onClick={onNew}>Ask the agent</Button></div>
    <div className={`health-summary ${!known ? 'unknown' : healthy ? 'clear' : ''}`}>
      <span className="health-icon">{!known ? <Activity size={22} aria-hidden="true"/> : healthy ? <Check size={22} aria-hidden="true"/> : <CircleAlert size={22} aria-hidden="true"/>}</span>
      <div><h2>{!known ? 'Waiting for current status' : healthy ? 'No active incidents' : `${counts.active} active ${counts.active === 1 ? 'incident' : 'incidents'}`}</h2>
      <p>{!known ? 'The overview updates when the connection is available.' : healthy ? 'New alerts will appear here for investigation.' : counts.attention ? `${counts.attention} ${counts.attention === 1 ? 'investigation needs' : 'investigations need'} your attention.` : counts.watching ? 'A deployment watch is running in the background.' : 'The agent is working on the latest alerts.'}</p></div>
    </div>
    <div className="dashboard-metrics">{[[CircleAlert, 'Need attention', counts?.attention], [Search, 'Investigating', counts?.investigating], ...(counts?.watching ? [[Clock3, 'Watching deployments', counts.watching]] : [])].map(([Icon, label, value]) => <div key={label}><Icon size={15} aria-hidden="true"/><span>{label}</span><strong>{known ? value : '…'}</strong></div>)}</div>
    <section className="dashboard-history"><div className="history-heading"><h2>{active.length ? 'Active incidents' : 'Recent history'}</h2><span><Clock3 size={13} aria-hidden="true"/>Latest activity</span></div>
      {rows.length ? rows.map(item => <button className="history-row" key={item.id} onClick={() => onSelect(item.id)}><span className={`history-icon ${item.status === 'resolved' ? 'closed' : ''}`}>{item.status === 'resolved' ? <Check size={17} aria-hidden="true"/> : <CircleAlert size={17} aria-hidden="true"/>}</span><div><strong>{item.title || 'Production investigation'}</strong><time dateTime={item.created_at}>{new Date(item.created_at).toLocaleString([], {month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit'})}</time></div><StatusBadge incident={item} configured={status?.configured}/><ArrowUpRight className="history-arrow" size={16} aria-hidden="true"/></button>) : <div className="history-empty"><Inbox size={24} aria-hidden="true"/><p>{known ? 'No investigations recorded yet.' : 'Incident history is loading.'}</p></div>}
    </section>
    <p className="dashboard-note">Incident status reflects recorded investigations. It is not an uptime measurement.</p>
  </section>;
}
