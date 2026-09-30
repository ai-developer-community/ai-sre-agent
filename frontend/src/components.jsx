import React, {useEffect, useRef, useState} from 'react';
import {Activity, Bell, Bot, Clock3, LayoutDashboard, UserRound, X, ArrowUp, ArrowUpRight, Check, ChevronRight, FileSearch, LoaderCircle, Plus, RefreshCw, Undo2} from 'lucide-react';
import {MessageContent, RawDetails, isCloudLink, isNotification} from './message-content.js';
import {actionBusy, incidentState} from './incident-state.js';

export const time = value => value ? new Date(value).toLocaleTimeString([], {hour: '2-digit', minute: '2-digit'}) : '';
const date = value => value ? new Date(value).toLocaleDateString([], {month: 'short', day: 'numeric'}) : '';

export function Button({children, icon: Icon, tone = 'secondary', className = '', ...props}) {
  return <button type="button" className={`button button-${tone} ${className}`} {...props}>
    {Icon && <Icon size={15} aria-hidden="true"/>}{children}
  </button>;
}

export function Notice({children, tone = 'warning', onRetry}) {
  return <div className={`notice notice-${tone}`} role={tone === 'error' ? 'alert' : 'status'}>
    <div>{children}</div>{onRetry && <Button icon={RefreshCw} tone="quiet" onClick={onRetry}>Retry</Button>}
  </div>;
}

export function StatusBadge({incident, configured}) {
  if (!incident) return null;
  const verified = incident.status === 'resolved' && incident.action?.status === 'succeeded';
  const closed = incident.status === 'resolved';
  return <span className={`status-tag ${verified ? 'resolved' : closed ? 'closed' : ''}`}>
    {closed ? <Check size={13}/> : <span className="incident-dot"/>}{incidentState(incident, configured)}
  </span>;
}

function IncidentItem({item, selected, configured, disabled, onSelect}) {
  return <button className={`incident-button ${selected === item.id ? 'selected' : ''}`} onClick={() => onSelect(item.id)} disabled={disabled}>
    <span className={`incident-dot ${item.status === 'resolved' ? 'closed' : ''}`}/>
    <span className="incident-copy"><strong>{item.title || 'Production investigation'}</strong>
      <small>{item.status === 'resolved' ? date(item.updated_at) : incidentState(item, configured)}</small>
    </span>{selected === item.id && <ChevronRight size={15}/>}
  </button>;
}

export function Sidebar({incidents, selected, status, connectionError, loaded, disabled, onSelect, onNew, onHome, home}) {
  const active = incidents.filter(item => item.status !== 'resolved');
  const closed = incidents.filter(item => item.status === 'resolved');
  const list = items => items.map(item => <IncidentItem key={item.id} item={item} selected={selected} configured={status?.configured} disabled={disabled} onSelect={onSelect}/>);
  return <aside className="sidebar">
    <button className="brand" onClick={onHome} aria-label="On-call console home"><Activity size={23}/>on-call</button>
    <button className={`overview-link ${home ? 'selected' : ''}`} onClick={onHome} disabled={disabled} aria-current={home ? 'page' : undefined}><LayoutDashboard size={17} aria-hidden="true"/>Overview</button>
    <Button className="new-button" icon={Plus} onClick={onNew} disabled={disabled}>New investigation</Button>
    <nav className="incident-list" aria-label="Incidents">
      <div className="section-label">Active incidents<span>{status?.incidents?.active ?? '…'}</span></div>
      {list(active)}
      {loaded && !active.length && <p className="sidebar-empty">No active incidents.</p>}
      {closed.length > 0 && <section className="closed-history"><div className="section-label">Closed history <span>{closed.length}</span></div>{list(closed)}</section>}
    </nav>
    <div className="sidebar-bottom"><span className={`connection-dot ${status && !connectionError ? 'online' : ''}`}/>
      <span>{connectionError ? 'Connection lost' : status ? status.subscriber_enabled ? 'Listening for alerts' : 'Manual investigations' : 'Connecting…'}</span>
    </div>
  </aside>;
}

export function ConsoleHeader({status, stale, home}) {
  const counts = status?.incidents;
  return <>
    <header className="topbar"><span className="header-location"><LayoutDashboard size={15} aria-hidden="true"/>Operations<span className="header-slash">/</span><strong>{home ? 'Overview' : 'Investigation'}</strong></span><span className="header-caption"><Bot size={15} aria-hidden="true"/>On-call agent</span></header>
    {!home && <div className="incident-summary" aria-label="Incident summary" aria-live="polite">
      <strong className={counts?.attention === 0 ? 'quiet' : ''}>{counts?.attention ?? '…'} {counts?.attention === 1 ? 'needs' : 'need'} attention</strong>
      <span>{counts?.active ?? '…'} active</span>
      {Boolean(counts?.investigating) && <span>{counts.investigating} investigating</span>}
      {stale && <span>Last known state</span>}
    </div>}
  </>;
}

function Message({message}) {
  const author = isNotification(message) ? 'Monitoring' : message.role === 'user' ? 'You' : message.role === 'assistant' ? 'On-call agent' : 'System';
  const AuthorIcon = isNotification(message) ? Bell : message.role === 'user' ? UserRound : Bot;
  return <article className={`message ${message.role === 'user' ? 'user-message' : 'agent-message'}`}>
    <div className="message-meta"><span className="author-icon"><AuthorIcon size={15} aria-hidden="true"/></span><span>{author}</span><time dateTime={message.created_at}>{time(message.created_at)}</time></div>
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
      <div className="starter-list">{['How is production doing?', 'What changed before the failures?'].map(prompt => <button key={prompt} onClick={() => onPrompt(prompt)}>{prompt}<ArrowUpRight size={15}/></button>)}</div>
    </div>}
    {selected && !detail && <p className="empty-detail"><LoaderCircle className="spin" size={16}/>Loading investigation…</p>}
    {messages.map(message => <Message key={message.id} message={message}/>)}
    {running && <div className="run-state" role="status"><LoaderCircle size={16} className="spin"/>
      {actionBusy(detail?.incident) ? 'Applying the approved action and checking checkout…' : 'Reading logs, metrics and recent changes…'}
    </div>}
    {detail?.incident?.run_status === 'failed' && <Notice tone="error">Investigation stopped. Check activity, then send a follow-up to retry.</Notice>}
  </div>;
}

export function RollbackCard({incident, service, disabled, onDecision}) {
  const action = incident?.action;
  if (!action) return null;
  if (action.status === 'pending' && incident.status !== 'resolved') {
    const expired = new Date(action.expires_at) <= new Date();
    return <section className="rollback-proposal" aria-label="Rollback approval">
      <div className="action-title"><Undo2 size={17}/><h3>Rollback</h3></div>
      <p>Return all traffic on {service} to its verified healthy revision. Do you approve?</p>
      <div className="revision-details">
        <dl><dt>From</dt><dd>{action.plan.revision}</dd><dt>To</dt><dd>{action.plan.target}</dd><dt>Expires</dt><dd>{time(action.expires_at)}</dd></dl>
      </div>
      {expired && <p>Request a new rollback proposal to continue.</p>}
      <div className="rollback-decisions"><Button icon={Check} tone="primary" disabled={disabled || expired} onClick={() => onDecision('approve')}>Approve</Button><Button icon={X} disabled={disabled} onClick={() => onDecision('deny')}>Deny</Button><span>Checkout checks run after approval.</span></div>
    </section>;
  }
  if (action.status === 'succeeded') return <Notice tone="success"><strong>Recovery verified</strong><p>5 checkout checks passed at {time(action.result.verified_at)}. Monitoring may take longer to clear.</p><p><code>{action.result.revision}</code></p></Notice>;
  if (action.status === 'failed') return <Notice tone="error">{action.result?.error}</Notice>;
  return null;
}

export function Composer({inputRef, draft, onChange, onSend, disabled, sending, running, closed}) {
  return <form className="composer" onSubmit={onSend}>
    <label htmlFor="question" className="sr-only">Message the on-call agent</label>
    <textarea id="question" ref={inputRef} value={draft} onChange={e => onChange(e.target.value)} placeholder={closed ? 'Incident closed. Start a new investigation.' : 'Ask a question or request a rollback…'} rows={2} disabled={disabled} onKeyDown={e => {if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {e.preventDefault(); onSend(e);}}}/>
    <div className="composer-footer"><span>{running ? 'Waiting for the current task' : 'Enter to send'}</span><button type="submit" className="send-button" disabled={disabled || !draft.trim()} aria-label="Send message">{sending ? <LoaderCircle size={18} className="spin"/> : <ArrowUp size={19}/>}</button></div>
  </form>;
}

function EvidenceItem({item}) {
  return <div className="evidence-item"><FileSearch size={16}/><div>
    {isCloudLink(item.url) ? <a href={item.url} target="_blank" rel="noopener noreferrer">{item.title || 'View evidence'}<ArrowUpRight size={13}/></a> : <span>{item.title || 'Evidence'}</span>}
    <small>{time(item.observed_at)}</small>
    {item.data && <RawDetails content={JSON.stringify(item.data, null, 2)}/>}
  </div></div>;
}

function CloseIncident({disabled, onClose}) {
  const [open, setOpen] = useState(false);
  const [notes, setNotes] = useState('');
  async function submit(event) {event.preventDefault(); if (await onClose(notes.trim())) {setOpen(false); setNotes('');}}
  if (!open) return <Button tone="quiet" disabled={disabled} onClick={() => setOpen(true)}>Close manually</Button>;
  return <form className="close-form" onSubmit={submit}><label htmlFor="resolution">Resolution notes</label><textarea autoFocus id="resolution" value={notes} onChange={e => setNotes(e.target.value)} required rows={3} placeholder="What fixed it, and how did you check?"/>
    <div><Button onClick={() => setOpen(false)}>Cancel</Button><Button type="submit" tone="primary" disabled={disabled || !notes.trim()}>Close incident</Button></div>
  </form>;
}

export function ContextPanel({detail, disabled, onClose}) {
  const [panel, setPanel] = useState('evidence');
  const evidence = detail?.evidence || [], events = detail?.events || [];
  return <aside className="context-panel" aria-label="Investigation context">
    <div className="context-tabs" aria-label="Context view">{['evidence', 'activity'].map(name => <button key={name} aria-pressed={panel === name} onClick={() => setPanel(name)}>{name === 'evidence' ? <FileSearch size={14} aria-hidden="true"/> : <Clock3 size={14} aria-hidden="true"/>}{name === 'evidence' ? 'Evidence' : 'Activity'}</button>)}</div>
    <div className="context-content">{panel === 'evidence' ? <section className="context-section">
      {evidence.length ? evidence.map(item => <EvidenceItem key={item.id} item={item}/>) : <p className="context-empty">Evidence appears as the agent investigates.</p>}
    </section> : <section className="context-section">
      {events.length ? <ol className="event-list">{events.map(item => <li key={item.id}><div><strong>{item.tool_name || (item.kind || 'Event').replaceAll('_', ' ')}</strong><time>{time(item.created_at)}</time><p>{item.content}</p>{item.data && Object.keys(item.data).length > 0 && <RawDetails content={JSON.stringify(item.data, null, 2)}/>}</div></li>)}</ol> : <p className="context-empty">No activity yet.</p>}
    </section>}</div>
    {detail?.incident?.status !== 'resolved' && <div className="context-bottom"><CloseIncident key={detail?.incident?.id} disabled={disabled || !detail} onClose={onClose}/></div>}
  </aside>;
}
