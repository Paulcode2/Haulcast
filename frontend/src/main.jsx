import React, { useEffect, useState } from 'react';
import { createRoot } from 'react-dom/client';
import './style.css';

const baseUrl = (import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:8000').replace(/\/$/, '');
function App() {
  const [status, setStatus] = useState('Checking backend…');
  const [checking, setChecking] = useState(false);
  async function checkHealth() {
    setChecking(true);
    setStatus('Checking backend…');
    try {
      const response = await fetch(`${baseUrl}/api/health/`, { signal: AbortSignal.timeout(5000) });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const data = await response.json();
      if (data.status !== 'ok') throw new Error('Unexpected health response');
      setStatus('Backend connected');
    } catch {
      setStatus('Backend unavailable. Check the server, API URL, and local CORS settings.');
    } finally { setChecking(false); }
  }
  useEffect(() => { checkHealth(); }, []);
  return <main><p className="eyebrow">PHASE 1 · SETUP</p><h1>Weather-Aware<br/>Truck Routing</h1><p>Local app connectivity and provider verification.</p><section><h2>Backend health</h2><p role="status">{status}</p><code>{baseUrl}/api/health/</code><button disabled={checking} onClick={checkHealth}>Check connection</button></section><p className="note">Trip analysis is reserved for a later phase. Run the backend provider checker to verify geocoding, truck routes, and hourly weather.</p></main>;
}
createRoot(document.getElementById('root')).render(<App/>);
