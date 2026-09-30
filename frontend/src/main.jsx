import React, {useEffect, useRef, useState} from 'react';
import {createRoot} from 'react-dom/client';
import {Sidebar, ConsoleHeader, StatusBadge, Notice, Conversation, RollbackCard, Composer, ContextPanel} from './components.jsx';
import {Dashboard} from './dashboard.jsx';
import {actionBusy} from './incident-state.js';
import './style.css';

const busy = run => ['queued', 'running'].includes(run);

function App() {
  const [status, setStatus] = useState(null);
  const [incidents, setIncidents] = useState([]);
  const [selected, setSelected] = useState(null);
  const [detail, setDetail] = useState(null);
  const [draft, setDraft] = useState('');
  const [error, setError] = useState('');
  const [sending, setSending] = useState(false);
  const [connectionError, setConnectionError] = useState('');
  const [detailError, setDetailError] = useState('');
  const [loaded, setLoaded] = useState(false);
  const [refresh, setRefresh] = useState(0);
  const [home, setHome] = useState(true);
  const composer = useRef(null), selectedRef = useRef(null), requestRef = useRef(null);
  selectedRef.current = selected;

  async function api(path, body) {
    const response = await fetch(path, body === undefined ? {} : {
      method: 'POST', headers: {'Content-Type': 'application/json', 'X-CSRF-Token': status?.csrf_token || ''}, body: JSON.stringify(body),
    });
    if (!response.ok) {
      let message = `Request failed (${response.status}).`;
      try {const result = await response.json(); if (typeof result.detail === 'string') message = result.detail;} catch {}
      throw new Error(message);
    }
    return response.json();
  }

  useEffect(() => {
    let active = true;
    const poll = async () => {
      try {
        const [s, list] = await Promise.all([api('/api/status'), api('/api/incidents')]);
        if (!active) return;
        setStatus(s); setIncidents(list); setLoaded(true); setConnectionError('');

      } catch (e) {
        if (active) {setConnectionError(`${e.message} Displayed data may be stale.`); setLoaded(true);}
      }
    };
    poll(); const timer = setInterval(poll, 4000);
    return () => {active = false; clearInterval(timer);};
  }, [refresh]);

  useEffect(() => {
    setDetail(null); setDetailError('');
    if (!selected) return;
    let active = true;
    const poll = async () => {
      try {
        const result = await api(`/api/incidents/${selected}`);
        if (active) {setDetail(result); setDetailError('');}
      } catch (e) {if (active) setDetailError(e.message);}
    };
    poll(); const timer = setInterval(poll, 2000);
    return () => {active = false; clearInterval(timer);};
  }, [selected, refresh]);

  function choose(id) {
    setHome(false); setSelected(id); setDraft(''); setError(''); requestRef.current = null;
  }
  function retry() {setError(''); setRefresh(n => n + 1);}
  function prompt(content) {setDraft(content); composer.current?.focus();}

  const incident = detail?.incident;
  const running = busy(incident?.run_status) || actionBusy(incident);
  const unavailable = !status || Boolean(connectionError || detailError) || Boolean(selected && !detail);
  const disabled = sending || unavailable || status?.configured === false || running || incident?.status === 'resolved';

  async function send(event) {
    event?.preventDefault();
    const content = draft.trim();
    if (!content || disabled) return;
    const selection = selected;
    setSending(true); setError('');
    try {
      if (selection) {
        if (requestRef.current?.content !== content || requestRef.current?.id !== selection) requestRef.current = {content, id: selection, key: crypto.randomUUID()};
        await api(`/api/incidents/${selection}/messages`, {content, request_id: requestRef.current.key});
      } else {
        const result = await api('/api/incidents', {question: content}); setSelected(result.id);
      }
      if (selectedRef.current === selection) setDraft('');
      requestRef.current = null; setRefresh(n => n + 1);
    } catch (e) {setError(e.message);} finally {setSending(false);}
  }

  async function decideRollback(decision) {
    if (disabled) return;
    setSending(true); setError('');
    try {await api(`/api/incidents/${selected}/actions/${incident.action.id}/${decision}`, {}); setRefresh(n => n + 1);}
    catch (e) {setError(e.message);} finally {setSending(false);}
  }

  async function close(notes) {
    setSending(true); setError('');
    try {await api(`/api/incidents/${selected}/close`, {notes}); setRefresh(n => n + 1); return true;}
    catch (e) {setError(e.message); return false;} finally {setSending(false);}
  }

  return <div className="app-shell">
    <Sidebar incidents={incidents} selected={selected} status={status} connectionError={connectionError} loaded={loaded} disabled={sending} onSelect={choose} onHome={() => {choose(null); setHome(true);}} onNew={() => {choose(null); composer.current?.focus();}}/>
    <main>
      <ConsoleHeader status={status} stale={Boolean(connectionError)}/>
      {(error || connectionError || detailError) && <Notice tone="error" onRetry={retry}>{error || connectionError || detailError}</Notice>}
      {status?.configured === false && <Notice>Agent model is not configured. Configure the backend model to start investigations.</Notice>}
      {status?.worker_error && <Notice>{status.worker_error}</Notice>}
      {status?.subscriber_error && <Notice>{status.subscriber_error}</Notice>}
      {home ? <Dashboard status={status} incidents={incidents} loaded={loaded} stale={Boolean(connectionError)} onSelect={choose} onNew={() => choose(null)}/> : <>
      <div className="page-heading"><h1>{selected ? incident?.title || 'Loading investigation…' : 'Investigate production'}</h1><StatusBadge incident={incident} configured={status?.configured}/></div>
      <div className={`workspace ${!selected ? 'workspace-empty' : ''}`}>
        <section className="conversation" aria-label="Agent conversation">
          <Conversation selected={selected} detail={detail} running={running} onPrompt={prompt}/>
          <RollbackCard incident={incident} service={status?.service} disabled={disabled} onDecision={decideRollback}/>
          <Composer inputRef={composer} draft={draft} onChange={setDraft} onSend={send} disabled={disabled} sending={sending} running={running} closed={incident?.status === 'resolved'}/>
        </section>
        {selected && <ContextPanel detail={detail} disabled={sending || running || unavailable} onClose={close}/>}
      </div>
      </>}
    </main>
  </div>;
}

createRoot(document.getElementById('root')).render(<App/>);
