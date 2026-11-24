import React, { useCallback, useEffect, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import TripMap from './TripMap';
import { API_BASE, checkpointText, departureValue, duration, miles, utcTime, validate } from './planner';
import './style.css';

const tomorrow = new Date(Date.now() + 86400000).toISOString().slice(0, 10);
const initial = { origin: '', destination: '', departure_time: `${tomorrow}T09:00`, offset: '+00:00', load_weight_lbs: '', checkpoint_interval_miles: '25' };
const offsets = Array.from({ length: 105 }, (_, index) => { const minutes = -720 + index * 15; return `${minutes < 0 ? '-' : '+'}${String(Math.floor(Math.abs(minutes) / 60)).padStart(2, '0')}:${String(Math.abs(minutes) % 60).padStart(2, '0')}`; });
const noRoutes = [];
function App() {
const [form, setForm] = useState(initial), [fields, setFields] = useState({}), [error, setError] = useState('');
const [pending, setPending] = useState(false), [result, setResult] = useState(null), [submitted, setSubmitted] = useState(null);
const [selectedId, setSelectedId] = useState(null), [inspected, setInspected] = useState(null), [health, setHealth] = useState('Checking backend…');
const [forecastHour, setForecastHour] = useState(0);
const inFlight = useRef(false), controller = useRef(null), routes = result?.routes || noRoutes;
const corridor = result?.corridor_forecast || null;
const selected = routes.find(route => route.id === selectedId);
const selectRoute = useCallback(id => { setSelectedId(id); setInspected(null); }, []), inspect = useCallback(index => setInspected(index), []);
async function checkHealth() {
try { const response = await fetch(`${API_BASE}/api/health/`, { signal: AbortSignal.timeout(5000) }); const data = await response.json(); setHealth(response.ok && data.status === 'ok' ? 'Backend connected' : 'Backend unavailable'); } catch { setHealth('Backend unavailable'); }
}
useEffect(() => { checkHealth(); return () => controller.current?.abort(); }, []);
function change(event) { const { name, value } = event.target; setForm(old => ({ ...old, [name]: value })); setFields(old => ({ ...old, [name]: undefined })); }
async function submit(event) {
event.preventDefault(); if (inFlight.current) return;
const invalid = validate(form); setFields(invalid); setError('');
if (Object.keys(invalid).length) { document.getElementById(Object.keys(invalid)[0])?.focus(); return; }
inFlight.current = true; setPending(true); setResult(null); setSelectedId(null); setInspected(null); setForecastHour(0); controller.current = new AbortController();
const timer = setTimeout(() => controller.current?.abort(), 120000);
const payload = { origin: form.origin.trim(), destination: form.destination.trim(), departure_time: departureValue(form), load_weight_lbs: Number(form.load_weight_lbs), checkpoint_interval_miles: Number(form.checkpoint_interval_miles) };
try {
const response = await fetch(`${API_BASE}/api/trips/analyze`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload), signal: controller.current.signal }); const data = await response.json();
if (!response.ok) { if (data.error?.fields) setFields(Object.fromEntries(Object.entries(data.error.fields).map(([key, messages]) => [key, Array.isArray(messages) ? messages.join(' ') : String(messages)]))); throw new Error(data.error?.message || `Analysis failed (HTTP ${response.status}). Please retry.`); }
if (!Array.isArray(data.routes)) throw new Error('The server returned an unexpected response. Please retry.');
setResult(data); setSubmitted(payload); setForecastHour(0); setSelectedId(data.routes.find(r => r.id === data.recommended_route_id)?.id || data.routes[0]?.id || null);
} catch (err) { setError(err.name === 'AbortError' ? 'Analysis timed out. Please retry.' : err instanceof TypeError ? 'Cannot reach the backend. Check the server and local CORS settings.' : err.message); }
finally { clearTimeout(timer); inFlight.current = false; setPending(false); }
}
function input(name, label, type = 'text', extra = {}) { return <div className="form-field"><label htmlFor={name}>{label}<input id={name} name={name} type={type} value={form[name]} onChange={change} aria-invalid={Boolean(fields[name])} aria-describedby={fields[name] ? `${name}-error` : undefined} {...extra}/></label>{fields[name] && <small className="field-error" id={`${name}-error`}>{fields[name]}</small>}</div>; }
return <main><header><div><p className="eyebrow">DISPATCH / TRIP PLANNER</p><h1>Plan the road ahead.</h1><p className="intro">Compare truck routes with weather at the time you’ll reach it.</p></div><div className="connection"><span role="status" data-testid="health-status">{health}</span><button className="text-button" onClick={checkHealth}>Check connection</button></div></header>
<div className="workspace"><aside className="planner-panel"><h2>Your trip</h2><form onSubmit={submit} noValidate aria-label="Trip planner"><fieldset disabled={pending}>
{input('origin', 'Origin', 'text', { placeholder: 'City or street address', maxLength: 500 })}{input('destination', 'Destination', 'text', { placeholder: 'Where are you headed?', maxLength: 500 })}{input('departure_time', 'Departure date and time', 'datetime-local')}
<label htmlFor="offset">Departure UTC offset<select id="offset" name="offset" value={form.offset} onChange={change}>{offsets.map(value => <option key={value} value={value}>UTC{value}</option>)}</select></label>
<p className="help">Fixed offset at the departure location and date. Choose the correct summer/winter offset; daylight saving is not applied automatically.</p><p className="departure-preview">Sending: <strong>{departureValue(form)}</strong></p>
{input('load_weight_lbs', 'Cargo load (lb)', 'number', { min: '0.01', step: 'any', placeholder: '12000', inputMode: 'decimal' })}
<label htmlFor="checkpoint_interval_miles">Checkpoint interval<select id="checkpoint_interval_miles" name="checkpoint_interval_miles" value={form.checkpoint_interval_miles} onChange={change}>{[10, 25, 50].map(n => <option key={n} value={n}>{n} miles</option>)}</select>{fields.checkpoint_interval_miles && <small className="field-error">{fields.checkpoint_interval_miles}</small>}</label>
<button className="primary" type="submit" disabled={pending}>{pending ? 'Analyzing trip…' : 'Analyze trip'}</button><button className="demo-button" type="button" onClick={() => { setForm({ ...initial, origin: 'Frankfurt am Main, Germany', destination: 'Kassel, Germany', load_weight_lbs: '12000' }); setFields({}); }}>Use demo trip</button>
</fieldset></form><p className="help">Cargo weight is separate from gross vehicle weight.</p></aside>
<div className="trip-content">{pending && <p className="notice" role="status">Finding truck routes and checking checkpoint forecasts. This can take a moment.</p>}{error && <p className="error-banner" role="alert">{error}</p>}{result && !routes.length && <p className="notice" role="status">No routes returned. Try more specific locations or a different departure.</p>}
{!!routes.length && <section className="result-heading"><h2>{routes.length} {routes.length === 1 ? 'route' : 'routes'} to compare</h2><p>{submitted.origin} to {submitted.destination}</p><p>Departure {submitted.departure_time} · All arrival and forecast times below are UTC.</p><div className={`recommendation ${result.recommended_route_id ? '' : 'caution'}`}><strong>{result.recommended_route_id ? `Recommended: Route ${routes.findIndex(r => r.id === result.recommended_route_id) + 1}` : 'No recommendation'}</strong><p>{result.recommendation?.explanation || 'Review route coverage and exclusions before choosing a route.'}</p></div></section>}
<TripMap routes={routes} selectedId={selectedId} onSelect={selectRoute} inspected={inspected} onInspect={inspect} corridor={corridor} forecastHour={forecastHour} onForecastHour={setForecastHour}/>
{!!routes.length && <><div className="route-cards" aria-label="Route summaries">{routes.map((route, index) => <article key={route.id} className={`route-card ${route.id === selectedId ? 'selected' : ''}`} data-testid={`route-card-${index + 1}`}><button className="route-select" aria-pressed={route.id === selectedId} onClick={() => selectRoute(route.id)}>Route {index + 1}{route.id === result.recommended_route_id ? ' · Recommended' : ''}</button><div className="route-metrics"><strong>{miles(route.distance_miles)}</strong><strong>{duration(route.duration_seconds)}</strong></div><p>Destination ETA<br/><strong>{utcTime(route.destination_eta)}</strong></p>
<dl className="risk-breakdown">{[['severe_miles', 'Severe'], ['high_miles', 'High'], ['no_travel_miles', 'No Travel'], ['unknown_coverage_miles', 'Unknown coverage']].map(([key, label]) => <React.Fragment key={key}><dt>{label}</dt><dd>{miles(route.summary?.[key])}</dd></React.Fragment>)}<dt>Average risk (0–4)</dt><dd>{route.summary?.average_risk == null ? 'Unknown' : route.summary.average_risk.toFixed(2)}</dd></dl>
{route.summary?.eligible ? <p className="eligible">Eligible · complete coverage</p> : <div className="excluded"><strong>Excluded from recommendation</strong>{(route.summary?.exclusion_reasons || []).map(reason => <p key={reason.code}>{reason.message}</p>)}</div>}</article>)}</div>
{selected && <section className="checkpoint-panel"><h2>Route {routes.indexOf(selected) + 1} checkpoints</h2><p>Select a numbered map marker or a checkpoint below to inspect its weather and triggering rule.</p><div className="checkpoint-list">{selected.checkpoints.map(point => <button key={point.index} aria-pressed={inspected === point.index} onClick={() => inspect(point.index)}>{point.index + 1} · {miles(point.distance_miles)} · {point.risk?.level || 'Unknown'}{point.weather?.coverage?.status !== 'complete' ? ' · Incomplete' : ''}</button>)}</div>{inspected != null && <div className="inspection" aria-label="Selected checkpoint details">{checkpointText(selected.checkpoints.find(p => p.index === inspected)).map((line, index) => <p key={index}>{line}</p>)}</div>}</section>}</>}
</div></div><footer>Weather is assessed at checkpoint ETAs. Unknown or incomplete coverage is never a complete Low-risk assessment.</footer></main>;
}
createRoot(document.getElementById('root')).render(<App/>);
