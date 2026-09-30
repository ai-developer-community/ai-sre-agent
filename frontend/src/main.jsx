import React, {useEffect, useRef, useState} from 'react';
import {createRoot} from 'react-dom/client';
import {Activity, ArrowUp, ArrowUpRight, Check, ChevronRight, CircleHelp, Clock3, FileSearch, LoaderCircle, MessageSquare, Plus, Radio, RefreshCw, Search, Terminal} from 'lucide-react';
import './style.css';

const prompts = ['How is production doing?', 'What changed before the failures?', 'Has the service recovered?'];
const time = (value) => value ? new Date(value).toLocaleTimeString([], {hour: '2-digit', minute: '2-digit'}) : '';
const date = (value) => value ? new Date(value).toLocaleDateString([], {month: 'short', day: 'numeric'}) : '';
const busy = (run) => ['queued', 'running'].includes(run);
function EvidenceLink({item}) {
  let safe = false;
  try {const url = new URL(item.url); safe = url.protocol === 'https:' && ['console.cloud.google.com', 'cloud.google.com'].includes(url.hostname);} catch {}
  return <div className="evidence-item"><FileSearch size={16}/><div>{safe ? <a href={item.url} target="_blank" rel="noopener noreferrer">{item.title || 'View evidence'}<ArrowUpRight size={13}/></a> : <span>{item.title || 'Evidence'}</span>}<small>{item.kind || 'Observation'}{item.observed_at ? ` · ${time(item.observed_at)}` : ''}</small>{item.data && <details className="evidence-details"><summary>Inspect observation</summary><pre>{JSON.stringify(item.data, null, 2)}</pre></details>}</div></div>;
}
function App() {
  const [status, setStatus] = useState(null), [incidents, setIncidents] = useState([]), [selected, setSelected] = useState(null), [detail, setDetail] = useState(null);
  const [draft, setDraft] = useState(''), [error, setError] = useState(''), [sending, setSending] = useState(false), [closing, setClosing] = useState(false), [notes, setNotes] = useState('');
  const [connectionError, setConnectionError] = useState('');
  const [loaded, setLoaded] = useState(false), [refresh, setRefresh] = useState(0), [tab, setTab] = useState('evidence');
  const composer = useRef(null), selectedRef = useRef(null), requestRef = useRef(null);
  selectedRef.current = selected;
  async function api(path, body) {
    const response = await fetch(path, body === undefined ? {} : {method: 'POST', headers: {'Content-Type': 'application/json', 'X-CSRF-Token': status?.csrf_token || ''}, body: JSON.stringify(body)});
    if (!response.ok) {let message = `Request failed (${response.status}).`; try {const result = await response.json(); if (typeof result.detail === 'string') message = result.detail;} catch {} throw new Error(message);}
    return response.json();
  }
  useEffect(() => {
    let active = true;
    const poll = async () => {try {const [s, list] = await Promise.all([api('/api/status'), api('/api/incidents')]); if (!active) return; setStatus(s); setIncidents(list); setLoaded(true); setConnectionError('');} catch (e) {if (active) {setConnectionError(`${e.message} Check that the local backend is running, then retry.`); setLoaded(true);}}};
    poll(); const timer = setInterval(poll, 4000); return () => {active = false; clearInterval(timer);};
  }, [refresh]);
  useEffect(() => {
    setDetail(null); setClosing(false); setNotes('');
    if (!selected) return;
    let active = true;
    const poll = async () => {try {const result = await api(`/api/incidents/${selected}`); if (active) setDetail(result);} catch (e) {if (active) setError(e.message);}};
    poll(); const timer = setInterval(poll, 2000); return () => {active = false; clearInterval(timer);};
  }, [selected, refresh]);
  function choose(id) {setSelected(id); setDraft(''); requestRef.current = null;}
  async function send(event) {
    event?.preventDefault(); const content = draft.trim(); if (!content || sending || !status || busy(detail?.incident?.run_status)) return;
    const selection = selected; setSending(true); setError('');
    try {
      if (selection) {if (requestRef.current?.content !== content || requestRef.current?.id !== selection) requestRef.current = {content, id: selection, key: crypto.randomUUID()}; await api(`/api/incidents/${selection}/messages`, {content, request_id: requestRef.current.key});}
      else {const result = await api('/api/incidents', {question: content}); setSelected(result.id);}
      if (selectedRef.current === selection) setDraft(''); requestRef.current = null; setRefresh(n => n + 1);
    } catch (e) {setError(e.message);} finally {setSending(false);}
  }
  async function close(event) {event.preventDefault(); setSending(true); try {await api(`/api/incidents/${selected}/close`, {notes: notes.trim()}); setClosing(false); setRefresh(n => n + 1);} catch (e) {setError(e.message);} finally {setSending(false);}}
  const incident = detail?.incident, running = busy(incident?.run_status), messages = detail?.messages || [], events = detail?.events || [], evidence = detail?.evidence || [];
  const disabled = sending || !status || Boolean(connectionError) || status.configured === false || running || incident?.status === 'resolved';
  return <div className="app-shell">
    <aside className="sidebar"><a className="brand" href="/" aria-label="On-call console home"><span className="brand-mark"><Activity size={23}/></span>on-call<span className="version">v1</span></a>
      <button className="new-button" onClick={() => {choose(null); composer.current?.focus();}} disabled={sending}><Plus size={17}/>New investigation</button>
      <div className="section-label">Investigations<span>{incidents.length}</span></div>
      <nav className="incident-list" aria-label="Investigations">{incidents.map(item => <button className={`incident-button ${selected === item.id ? 'selected' : ''}`} key={item.id} onClick={() => choose(item.id)} disabled={sending}><span className={`incident-dot ${item.status === 'resolved' ? 'resolved' : ''}`}/><span className="incident-copy"><strong>{item.title || 'Production investigation'}</strong><small>{date(item.created_at)} · {busy(item.run_status) ? 'Investigating' : item.status === 'resolved' ? 'Resolved' : 'Open'}</small></span>{selected === item.id && <ChevronRight size={15}/>}</button>)}{loaded && !incidents.length && <p className="sidebar-empty">New alerts and manual investigations will appear here.</p>}</nav>
      <div className="sidebar-bottom"><span className={`connection-dot ${status && !connectionError ? 'online' : ''}`}/><div><span>{connectionError ? 'Backend disconnected' : status ? 'Local console connected' : 'Connecting to backend'}</span><small>{connectionError ? 'Displayed data may be stale' : status?.subscriber_error ? 'Pub/Sub listener needs attention' : status?.subscriber_enabled ? 'Pub/Sub listener enabled' : 'Pub/Sub listener disabled'}</small></div></div>
    </aside>
    <main>
      <header className="topbar"><span><span className="breadcrumb">Workspace</span><ChevronRight size={14}/><strong>Production</strong></span><span className="read-only"><Radio size={14}/>Investigation mode</span></header>
      {(error || connectionError) && <div className="error-banner" role="alert"><span>{error || connectionError}</span><button onClick={() => {setError(''); setRefresh(n => n + 1);}}><RefreshCw size={14}/>Retry</button></div>}
      {status?.configured === false && <div className="setup-banner" role="status"><strong>Agent model is not configured.</strong><span>Set CLAUDE_MODEL in the backend environment and restart it to begin investigating.</span></div>}
      {status?.worker_error && <div className="setup-banner warning" role="alert"><strong>Investigation worker needs attention.</strong><span>{status.worker_error}</span></div>}
      {status?.subscriber_error && <div className="setup-banner warning" role="alert"><strong>Alert listener needs attention.</strong><span>{status.subscriber_error}</span></div>}
      <div className="page-heading"><div><h1>{selected ? incident?.title || 'Loading investigation…' : 'Production, explained.'}</h1><p>{selected ? 'Follow the evidence. Ask the next question.' : 'An on-call partner for finding out what went wrong.'}</p></div>{incident && <span className={`status-tag ${incident.status === 'resolved' ? 'resolved' : ''}`}>{incident.status === 'resolved' ? <Check size={13}/> : <span className="incident-dot"/>}{incident.status === 'resolved' ? 'Resolved' : 'Open incident'}</span>}</div>
      <div className="environment"><div><span className="env-label">Service</span><strong>{status?.service || 'Not connected'}</strong></div><div><span className="env-label">Project</span><span>{status?.project || 'Unavailable'}</span></div><div><span className="env-label">Region</span><span>{status?.region || 'Unavailable'}</span></div><div className="health-note"><CircleHelp size={15}/><span>Health requires a fresh investigation</span></div></div>
      <div className="workspace">
        <section className="conversation" aria-label="Agent conversation"><div className="panel-heading"><h2><MessageSquare size={16}/>Investigation</h2><span>{running ? 'In progress' : incident?.status === 'resolved' ? 'Closed' : 'Ask your agent'}</span></div>
          <div className="messages" aria-live="polite" aria-relevant="additions text">{!selected && <div className="welcome"><div className="welcome-icon"><Search size={29}/></div><h2>Start with a question.</h2><p>The agent checks your service, inspects logs and deployment history, and brings back findings with evidence.</p><div className="starter-list">{prompts.map(prompt => <button key={prompt} onClick={() => {setDraft(prompt); composer.current?.focus();}}>{prompt}<ArrowUpRight size={15}/></button>)}</div><small>Automatic alerts also start an investigation when the Pub/Sub listener is enabled.</small></div>}
          {selected && !detail && <p className="empty-detail"><LoaderCircle className="spin" size={16}/>Loading investigation…</p>}
          {selected && detail && messages.length === 0 && <p className="empty-detail">No messages yet. The investigation record is ready.</p>}
          {messages.map(message => <article className={`message ${message.role === 'user' ? 'user-message' : 'agent-message'}`} key={message.id}><div className="message-meta"><span>{message.role === 'user' ? 'You' : message.role === 'assistant' ? 'On-call agent' : 'System'}</span><time dateTime={message.created_at}>{time(message.created_at)}</time></div><div className="message-content">{message.content}</div></article>)}
          {running && <div className="run-state" role="status"><LoaderCircle size={16} className="spin"/>{incident.run_status === 'queued' ? 'Investigation queued' : 'Agent is investigating'}<span>Tool activity appears alongside.</span></div>}
          {incident?.run_status === 'failed' && <p className="run-failed">The investigation stopped. Check the activity for details, then send a follow-up to try again.</p>}
          </div>
          <form className="composer" onSubmit={send}><label htmlFor="question" className="sr-only">Message the on-call agent</label><textarea id="question" ref={composer} value={draft} onChange={e => setDraft(e.target.value)} placeholder={incident?.status === 'resolved' ? 'This incident is closed. Start a new investigation.' : 'Ask about production…'} rows={3} disabled={disabled} onKeyDown={e => {if (e.key === 'Enter' && !e.shiftKey) {e.preventDefault(); send(e);}}}/><div className="composer-footer"><span>{running ? 'Waiting for this investigation to finish' : 'Enter to send · Shift + Enter for a new line'}</span><button type="submit" className="send-button" disabled={disabled || !draft.trim()} aria-label="Send message">{sending ? <LoaderCircle size={18} className="spin"/> : <ArrowUp size={19}/>}</button></div></form>
        </section>
        <aside className="context-panel" aria-label="Investigation context"><div className="context-tabs" role="tablist" aria-label="Investigation context"><button role="tab" aria-selected={tab === 'evidence'} aria-controls="context-content" onClick={() => setTab('evidence')}>Evidence <span>{evidence.length}</span></button><button role="tab" aria-selected={tab === 'activity'} aria-controls="context-content" onClick={() => setTab('activity')}>Activity <span>{events.length}</span></button></div><div id="context-content" className="context-content" role="tabpanel" aria-label={tab === 'evidence' ? 'Evidence' : 'Activity'}>{tab === 'evidence' ? evidence.length ? evidence.map(item => <EvidenceLink key={item.id} item={item}/>) : <div className="context-empty"><FileSearch size={24}/><h3>Evidence belongs here.</h3><p>Logs, deployment details and observations gathered during the investigation.</p><span>No observations collected yet</span></div> : events.length ? <ol className="event-list">{events.map(item => <li key={item.id}><div className="event-icon"><Terminal size={13}/></div><div><strong>{item.tool_name || (item.kind || 'Tool event').replaceAll('_', ' ')}</strong><time>{time(item.created_at)}</time><p>{item.content}</p>{item.data && Object.keys(item.data).length > 0 && <details><summary>View details</summary><pre>{JSON.stringify(item.data, null, 2)}</pre></details>}</div></li>)}</ol> : <div className="context-empty"><Clock3 size={24}/><h3>A clear record.</h3><p>The agent's tool calls and results will appear here as it works.</p></div>}</div>
        <div className="context-bottom"><h3>Human-led operations</h3><p>The agent investigates. You decide when the incident is resolved.</p>{incident && incident.status !== 'resolved' && <button className="close-button" disabled={running || sending} onClick={() => setClosing(!closing)}><Check size={14}/>Close incident</button>}{closing && <form className="close-form" onSubmit={close}><label htmlFor="resolution">Resolution notes</label><textarea autoFocus id="resolution" value={notes} onChange={e => setNotes(e.target.value)} required rows={3} placeholder="What fixed it, and how was recovery verified?"/><div><button type="button" onClick={() => setClosing(false)}>Cancel</button><button className="confirm-close" disabled={sending || !notes.trim()}>Save and close</button></div></form>}</div></aside>
      </div>
      <footer className="page-footer"><span>Real observations. Human judgment.</span><span>{status?.agent_provider || 'Agent'}{status?.model ? ` / ${status.model}` : ''}</span></footer>
    </main>
  </div>;
}

createRoot(document.getElementById('root')).render(<App/>);
