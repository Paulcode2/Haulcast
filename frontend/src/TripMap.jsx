import React, { useEffect, useRef, useState } from 'react';
import * as maplibregl from 'maplibre-gl';
import 'maplibre-gl/dist/maplibre-gl.css';
import { checkpointText, riskColors } from './planner';

const colors = ['#2468c7', '#8752bd', '#d3651c'];
export default function TripMap({ routes, selectedId, onSelect, inspected, onInspect }) {
  const container = useRef(null), mapRef = useRef(null), latest = useRef({ onSelect });
  latest.current = { onSelect };
  const [ready, setReady] = useState(false), [mapError, setMapError] = useState('');
  useEffect(() => {
    let map;
    try {
      map = new maplibregl.Map({ container: container.current, center: [9.1, 50.7], zoom: 6,
        style: { version: 8, sources: { streets: { type: 'raster', tiles: ['https://tile.openstreetmap.org/{z}/{x}/{y}.png'], tileSize: 256, attribution: '© <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noreferrer">OpenStreetMap contributors</a>' } }, layers: [{ id: 'background', type: 'background', paint: { 'background-color': '#e7edf1' } }, { id: 'streets', type: 'raster', source: 'streets' }] } });
      mapRef.current = map;
      map.addControl(new maplibregl.NavigationControl({ showCompass: false }), 'top-right');
      map.on('error', () => setMapError('Some map tiles could not load. Route cards and checkpoint details remain available.'));
      map.on('load', () => {
        map.addSource('routes', { type: 'geojson', data: { type: 'FeatureCollection', features: [] } });
        map.addLayer({ id: 'route-lines', type: 'line', source: 'routes', paint: { 'line-color': ['get', 'color'], 'line-width': 5, 'line-opacity': 0.65 } });
        map.addLayer({ id: 'selected-route', type: 'line', source: 'routes', filter: ['==', ['get', 'id'], ''], paint: { 'line-color': ['get', 'color'], 'line-width': 8 } });
        map.on('click', 'route-lines', e => latest.current.onSelect(e.features[0].properties.id));
        map.on('mouseenter', 'route-lines', () => { map.getCanvas().style.cursor = 'pointer'; });
        map.on('mouseleave', 'route-lines', () => { map.getCanvas().style.cursor = ''; });
        setReady(true);
      });
      const observer = new ResizeObserver(() => map.resize()); observer.observe(container.current);
      return () => { observer.disconnect(); map.remove(); mapRef.current = null; };
    } catch { setMapError('Map unavailable: this browser needs WebGL. Use the route cards and checkpoint list below.'); map?.remove(); }
  }, []);
  useEffect(() => {
    if (!ready) return;
    const map = mapRef.current;
    map.getSource('routes').setData({ type: 'FeatureCollection', features: routes.map((route, index) => ({ type: 'Feature', geometry: route.geometry, properties: { id: route.id, color: colors[index % colors.length] } })) });
    const coordinates = routes.flatMap(route => route.geometry.coordinates);
    if (coordinates.length) map.fitBounds(coordinates.reduce((b, point) => b.extend(point), new maplibregl.LngLatBounds(coordinates[0], coordinates[0])), { padding: 55, maxZoom: 12, duration: 0 });
    const markers = routes.map((route, index) => {
      const button = document.createElement('button'); button.className = 'route-marker'; button.textContent = `R${index + 1}`; button.style.backgroundColor = colors[index % colors.length];
      button.setAttribute('aria-label', `Select route ${index + 1} on map`); button.addEventListener('click', event => { event.stopPropagation(); latest.current.onSelect(route.id); });
      return new maplibregl.Marker({ element: button, offset: [index * 8, -20 - index * 8] }).setLngLat(route.geometry.coordinates[Math.floor(route.geometry.coordinates.length / 2)]).addTo(map);
    });
    return () => markers.forEach(marker => marker.remove());
  }, [routes, ready]);
  useEffect(() => {
    if (!ready) return;
    const map = mapRef.current; map.setFilter('selected-route', ['==', ['get', 'id'], selectedId || '']);
    const markers = (routes.find(route => route.id === selectedId)?.checkpoints || []).map(point => {
      const button = document.createElement('button'), risk = point.risk?.level || 'Unknown', incomplete = point.weather?.coverage?.status !== 'complete';
      button.className = `checkpoint-marker${incomplete ? ' incomplete' : ''}`; button.textContent = String(point.index + 1); button.style.backgroundColor = riskColors[risk] || riskColors.Unknown;
      button.setAttribute('aria-label', `Inspect checkpoint ${point.index + 1}: ${risk}${incomplete ? ', incomplete coverage' : ''}`); button.title = button.getAttribute('aria-label');
      button.addEventListener('click', event => { event.stopPropagation(); onInspect(point.index); });
      return new maplibregl.Marker({ element: button }).setLngLat([point.longitude, point.latitude]).addTo(map);
    });
    return () => markers.forEach(marker => marker.remove());
  }, [routes, selectedId, ready, onInspect]);
  useEffect(() => {
    if (!ready || inspected == null) return;
    const point = routes.find(route => route.id === selectedId)?.checkpoints.find(p => p.index === inspected); if (!point) return;
    const content = document.createElement('div'); content.setAttribute('role', 'dialog'); content.setAttribute('aria-label', `Checkpoint ${point.index + 1} details`);
    checkpointText(point).forEach((text, index) => { const line = document.createElement(index === 0 ? 'h3' : 'p'); line.textContent = text; content.appendChild(line); });
    mapRef.current.panTo([point.longitude, point.latitude], { offset: [0, 110], duration: 0 });
    const popup = new maplibregl.Popup({ anchor: 'bottom', maxWidth: '280px', closeOnClick: false }).setLngLat([point.longitude, point.latitude]).setDOMContent(content).addTo(mapRef.current);
    const close = () => onInspect(null);
    popup.on('close', close);
    return () => { popup.off('close', close); popup.remove(); };
  }, [routes, selectedId, inspected, ready, onInspect]);
  function fitTrip() {
    const coordinates = routes.flatMap(route => route.geometry.coordinates);
    if (ready && coordinates.length) mapRef.current.fitBounds(coordinates.reduce((b, point) => b.extend(point), new maplibregl.LngLatBounds(coordinates[0], coordinates[0])), { padding: 55, maxZoom: 12, duration: 0 });
    onInspect(null);
  }
  return <section className="map-section" aria-label="Trip map"><div ref={container} className="map" data-testid="trip-map" data-ready={ready} data-selected-route={selectedId || ''}/>{!!routes.length && ready && <button className="fit-trip" onClick={fitTrip}>Fit trip</button>}{mapError && <p className="map-warning">{mapError}</p>}{!routes.length && <p className="map-hint">Your routes will appear here after analysis.</p>}
    <div className="map-key"><strong>Checkpoint risk</strong>{Object.entries(riskColors).map(([name, color]) => <span key={name}><i style={{ backgroundColor: color }}/>{name}</span>)}<span>Dashed outline: incomplete coverage</span></div></section>;
}
