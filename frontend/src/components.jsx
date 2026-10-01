import React, {useEffect, useRef, useState} from 'react';
import {Activity, Bell, Bot, CircleAlert, Clock3, LayoutDashboard, UserRound, X, ArrowUp, ArrowUpRight, Check, FileSearch, LoaderCircle, Plus, RefreshCw, Undo2} from 'lucide-react';
import {MessageContent, RawDetails, isCloudLink, isNotification} from './message-content.js';
import {actionBusy, incidentState, watchActive} from './incident-state.js';

export const time = value => value ? new Date(value).toLocaleTimeString([], {hour: '2-digit', minute: '2-digit'}) : '';
const date = value => value ? new Date(value).toLocaleDateString([], {month: 'short', day: 'numeric'}) : '';

export function Button({children, icon: Icon, tone = 'secondary', className = '', ...props}) {
  return <button type="button" className={`button button-${tone} ${className}`} {...props}>
    {Icon && <Icon size={15} aria-hidden="true"/>}{children}
  </button>;
}

export function Notice({children, tone = 'warning', onRetry}) {
  const Icon = tone === 'success' ? Check : CircleAlert;
  return <div className={`notice notice-${tone}`} role={tone === 'error' ? 'alert' : 'status'}>
    <Icon className="notice-icon" size={16} aria-hidden="true"/>
    <div className="notice-body">{children}</div>
    {onRetry && <Button icon={RefreshCw} tone="quiet" onClick={onRetry}>Retry</Button>}
  </div>;
}

export function StatusBadge({incident, configured}) {
  if (!incident) return null;
  const verified = incident.status === 'resolved' && incident.action?.status === 'succeeded';
  const closed = incident.status === 'resolved';
  return <span className={`status-tag ${verified ? 'resolved' : closed ? 'closed' : ''}`}>
    {closed ? <Check size={13} aria-hidden="true"/> : <span className="incident-dot" aria-hidden="true"/>}{incidentState(incident, configured)}
  </span>;
}

function IncidentItem({item, selected, configured, disabled, onSelect}) {
  const current = selected === item.id;
  return <button className={`incident-button ${current ? 'selected' : ''}`} aria-current={current ? 'page' : undefined} onClick={() => onSelect(item.id)} disabled={disabled}>
    <span className={`incident-dot ${item.status === 'resolved' ? 'closed' : ''}`} aria-hidden="true"/>
    <span className="incident-copy"><strong>{item.title || 'Production investigation'}</strong>
      <small>{item.status === 'resolved' ? date(item.updated_at) : incidentState(item, configured)}</small>
    </span>
  </button>;
}

export function Sidebar({incidents, selected, status, connectionError, loaded, disabled, onSelect, onNew, onHome, home}) {
  const active = incidents.filter(item => item.status !== 'resolved');
  const closed = incidents.filter(item => item.status === 'resolved');
  const list = items => items.map(item => <IncidentItem key={item.id} item={item} selected={selected} configured={status?.configured} disabled={disabled} onSelect={onSelect}/>);
  return <aside className="sidebar">
    <button className="brand" onClick={onHome} aria-label="On-call console home"><Activity size={20} aria-hidden="true"/>on-call</button>
    <button className={`overview-link ${home ? 'selected' : ''}`} onClick={onHome} disabled={disabled} aria-current={home ? 'page' : undefined}><LayoutDashboard size={16} aria-hidden="true"/>Overview</button>
    <Button className="new-button" icon={Plus} onClick={onNew} disabled={disabled}>New investigation</Button>
    <nav className="incident-list" aria-label="Incidents">
      <div className="section-label">Active incidents<span className="count">{status?.incidents?.active ?? '…'}</span></div>
      {list(active)}
      {loaded && !active.length && <p className="sidebar-empty">No active incidents.</p>}
      {closed.length > 0 && <section className="closed-history"><div className="section-label">Resolved history<span className="count">{closed.length}</span></div>{list(closed)}</section>}
    </nav>
    <div className="sidebar-bottom"><span className={`connection-dot ${status && !connectionError ? 'online' : ''}`} aria-hidden="true"/>
      <span>{connectionError ? 'Connection lost' : status ? status.subscriber_enabled ? 'Listening for alerts' : 'Manual investigations' : 'Connecting…'}</span>
    </div>
  </aside>;
}

export function ConsoleHeader({home}) {
  return <header className="topbar">
    <span className="header-location"><LayoutDashboard size={15} aria-hidden="true"/>Operations<span className="header-slash" aria-hidden="true">/</span><strong>{home ? 'Overview' : 'Investigation'}</strong></span>
    <span className="header-caption"><Bot size={15} aria-hidden="true"/>On-call agent</span>
  </header>;
}

function Message({message}) {
  const author = isNotification(message) ? 'Monitoring' : message.role === 'user' ? 'You' : message.role === 'assistant' ? 'On-call agent' : 'System';
  const AuthorIcon = isNotification(message) ? Bell : message.role === 'user' ? UserRound : Bot;
  return <article className={`message ${message.role === 'user' ? 'user-message' : 'agent-message'}`}>
    <div className="message-meta"><span className="author-icon"><AuthorIcon size={15} aria-hidden="true"/></span><span className="author">{author}</span><time dateTime={message.created_at}>{time(message.created_at)}</time></div>
    <MessageContent message={message}/>
  </article>;
}

export function Conversation({selected, detail, running, onPrompt}) {
  const messages = detail?.messages || [];
  const scroll = useRef(null);
  const follow = useRef(true);
  useEffect(() => {follow.current = true;}, [selected]);
  useEffect(() => {
    if (follow.current && scroll.current) scroll.current.scrollTop = scroll.current.scrollHeight;
  }, [selected, messages.length]);
  return <div className="messages" ref={scroll} onScroll={e => {
    const el = e.currentTarget; follow.current = el.scrollHeight - el.scrollTop - el.clientHeight < 100;
  }} aria-live="polite" aria-relevant="additions text">
    {!selected && <div className="welcome"><h2>What needs a closer look?</h2><p>New alerts arrive here automatically. You can also ask the agent to investigate.</p>
      <div className="starter-list">{['How is production doing?', 'Watch the next deployment for five minutes.'].map(prompt => <button type="button" key={prompt} onClick={() => onPrompt(prompt)}>{prompt}<ArrowUpRight size={15} aria-hidden="true"/></button>)}</div>
    </div>}
    {selected && !detail && <p className="empty-detail"><LoaderCircle className="spin" size={16} aria-hidden="true"/>Loading investigation…</p>}
    {messages.map(message => <Message key={message.id} message={message}/>)}
    {running && <div className="run-state" role="status"><LoaderCircle size={16} className="spin" aria-hidden="true"/>
      {actionBusy(detail?.incident) ? 'Applying the approved action and checking checkout…' : 'Reading logs, metrics and recent changes…'}
    </div>}
    {detail?.incident?.run_status === 'failed' && <Notice tone="error">Investigation stopped. Check activity, then send a follow-up to retry.</Notice>}
  </div>;
}

function ActionCard({icon: Icon, title, label, tone = 'neutral', children}) {
  return <section className={`action-card action-card-${tone}`} aria-label={label}>
    <div className="action-title"><span className="action-icon"><Icon size={16} aria-hidden="true"/></span><h3>{title}</h3></div>
    <div className="action-body">{children}</div>
  </section>;
}

function ActionDecisions({children, note}) {
  return <div className="action-decisions">{children}<span className="action-note">{note}</span></div>;
}

export function DeploymentWatchCard({incident, disabled, onStop}) {
  const watch = incident?.watch;
  if (!watch) return null;
  const active = watchActive(incident);
  const labels = {waiting: 'Waiting for deployment', watching: 'Monitoring deployment', passed: 'Deployment checks passed', failed: 'Deployment checks failed', inconclusive: 'Deployment checks inconclusive', cancelled: 'Deployment watch stopped'};
  const last = watch.observations?.at(-1);
  return <ActionCard icon={Clock3} title={labels[watch.status] || 'Deployment watch'} label="Deployment watch">
    <p>{watch.status === 'waiting' ? `Waiting for a serving revision change until ${time(watch.deadline)}.` : active ? `Checking checkout for ${watch.duration_minutes} ${watch.duration_minutes === 1 ? 'minute' : 'minutes'}, until ${time(watch.deadline)}.` : watch.result}</p>
    {watch.gap && <p>{watch.gap}</p>}
    {watch.revision && <p><code>{watch.revision}</code></p>}
    {last && <p className="watch-check">Last check {time(last.at)} · {last.unavailable ? 'Unavailable' : !last.verified ? 'Revision unverified' : `HTTP ${last.status} · ${last.latency_ms} ms`}</p>}
    {active && <ActionDecisions note="Runs in the background. Recovery requires approval."><Button icon={X} disabled={disabled} onClick={onStop}>Stop watching</Button></ActionDecisions>}
  </ActionCard>;
}

export function RollbackCard({incident, service, disabled, onDecision}) {
  const action = incident?.action;
  if (!action) return null;
  if (action.status === 'pending' && incident.status !== 'resolved') {
    const expired = new Date(action.expires_at) <= new Date();
    return <ActionCard icon={Undo2} title="Rollback" label="Rollback approval" tone="approval">
      <p>Return all traffic on {service} to its verified healthy revision. Do you approve?</p>
      <dl className="revision-details"><dt>From</dt><dd>{action.plan.revision}</dd><dt>To</dt><dd>{action.plan.target}</dd><dt>Expires</dt><dd>{time(action.expires_at)}</dd></dl>
      {expired && <p className="action-warning">Request a new rollback proposal to continue.</p>}
      <ActionDecisions note="Checkout checks run after approval."><Button icon={Check} tone="primary" disabled={disabled || expired} onClick={() => onDecision('approve')}>Approve</Button><Button icon={X} disabled={disabled} onClick={() => onDecision('deny')}>Deny</Button></ActionDecisions>
    </ActionCard>;
  }
  if (action.status === 'succeeded') return <Notice tone="success"><strong>Recovery verified</strong><p>5 checkout checks passed at {time(action.result.verified_at)}. Monitoring may take longer to clear.</p><p><code>{action.result.revision}</code></p></Notice>;
  if (action.status === 'failed') return <Notice tone="error">{action.result?.error}</Notice>;
  return null;
}

export function Composer({inputRef, draft, onChange, onSend, disabled, sending, running, closed}) {
  return <form className="composer" onSubmit={onSend}>
    <label htmlFor="question" className="sr-only">Message the on-call agent</label>
    <textarea id="question" ref={inputRef} value={draft} onChange={e => onChange(e.target.value)} placeholder={closed ? 'Incident resolved. Start a new investigation.' : 'Ask a question, watch a deployment or request a rollback…'} rows={2} disabled={disabled} onKeyDown={e => {if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {e.preventDefault(); onSend(e);}}}/>
    <div className="composer-footer"><span>{running ? 'Waiting for the current task' : 'Enter to send'}</span><button type="submit" className="send-button" disabled={disabled || !draft.trim()} aria-label="Send message">{sending ? <LoaderCircle size={17} className="spin" aria-hidden="true"/> : <ArrowUp size={17} aria-hidden="true"/>}</button></div>
  </form>;
}

function EvidenceItem({item}) {
  return <li className="evidence-item"><FileSearch size={15} aria-hidden="true"/><div>
    {isCloudLink(item.url) ? <a href={item.url} target="_blank" rel="noopener noreferrer">{item.title || 'View evidence'}<ArrowUpRight size={13} aria-hidden="true"/></a> : <span className="evidence-title">{item.title || 'Evidence'}</span>}
    <time dateTime={item.observed_at}>{time(item.observed_at)}</time>
    {item.data && <RawDetails content={JSON.stringify(item.data, null, 2)}/>}
  </div></li>;
}

export function ResolveIncident({disabled, onClose}) {
  const [open, setOpen] = useState(false);
  const [notes, setNotes] = useState('');
  async function submit(event) {event.preventDefault(); if (await onClose(notes.trim())) {setOpen(false); setNotes('');}}
  if (!open) return <Button icon={Check} disabled={disabled} onClick={() => setOpen(true)}>Resolve incident</Button>;
  return <form className="close-form" onSubmit={submit}><label htmlFor="resolution">Resolution notes</label><p className="resolution-help" id="resolution-help">Record why you are resolving this incident. This does not verify production health.</p><textarea autoFocus aria-describedby="resolution-help" id="resolution" value={notes} onChange={e => setNotes(e.target.value)} required rows={3} placeholder="What fixed it, and how did you check?"/>
    <div className="close-actions"><Button onClick={() => setOpen(false)}>Cancel</Button><Button type="submit" tone="primary" disabled={disabled || !notes.trim()}>Resolve incident</Button></div>
  </form>;
}

export function ContextPanel({detail}) {
  const [panel, setPanel] = useState('evidence');
  const evidence = detail?.evidence || [], events = detail?.events || [];
  return <aside className="context-panel" aria-label="Investigation context">
    <div className="context-tabs" role="group" aria-label="Context view">{['evidence', 'activity'].map(name => <button type="button" key={name} aria-pressed={panel === name} onClick={() => setPanel(name)}>{name === 'evidence' ? <FileSearch size={14} aria-hidden="true"/> : <Clock3 size={14} aria-hidden="true"/>}{name === 'evidence' ? 'Evidence' : 'Activity'}</button>)}</div>
    <div className="context-content">{panel === 'evidence' ? <section className="context-section">
      {evidence.length ? <ul className="evidence-list">{evidence.map(item => <EvidenceItem key={item.id} item={item}/>)}</ul> : <p className="context-empty">Evidence appears as the agent investigates.</p>}
    </section> : <section className="context-section">
      {events.length ? <ol className="event-list">{events.map(item => <li key={item.id}><div className="event-head"><strong>{item.tool_name || (item.kind || 'Event').replaceAll('_', ' ')}</strong><time dateTime={item.created_at}>{time(item.created_at)}</time></div><p>{item.content}</p>{item.data && Object.keys(item.data).length > 0 && <RawDetails content={JSON.stringify(item.data, null, 2)}/>}</li>)}</ol> : <p className="context-empty">No activity yet.</p>}
    </section>}</div>
  </aside>;
}
