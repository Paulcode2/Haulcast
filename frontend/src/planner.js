export const API_BASE = (import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:8000').replace(/\/$/, '');
export const riskColors = { Low: '#168161', Moderate: '#b38308', High: '#d45c18', Severe: '#bb323c', 'No Travel': '#7e245e', Unknown: '#657489' };
export function departureValue(form) { return `${form.departure_time}:00${form.offset}`; }
export function validate(form) {
  const errors = {};
  for (const key of ['origin', 'destination']) {
    if (!form[key].trim()) errors[key] = 'Enter a location.';
    else if (form[key].trim().length > 500) errors[key] = 'Use 500 characters or fewer.';
  }
  if (!/^\d{4}-\d\d-\d\dT\d\d:\d\d$/.test(form.departure_time) || !Number.isFinite(Date.parse(departureValue(form)))) errors.departure_time = 'Choose a valid departure date and time.';
  if (!form.load_weight_lbs || !Number.isFinite(Number(form.load_weight_lbs)) || Number(form.load_weight_lbs) <= 0) errors.load_weight_lbs = 'Enter a finite cargo weight greater than zero.';
  if (![10, 25, 50].includes(Number(form.checkpoint_interval_miles))) errors.checkpoint_interval_miles = 'Choose 10, 25, or 50 miles.';
  return errors;
}
export const miles = value => Number.isFinite(value) ? `${value.toFixed(1)} mi` : 'Unavailable';
export const duration = seconds => `${Math.floor(seconds / 3600)}h ${Math.floor((seconds % 3600) / 60)}m`;
export const utcTime = value => value && Number.isFinite(Date.parse(value)) ? `${new Date(value).toISOString().replace('T', ' ').slice(0, 19)} UTC` : 'Unavailable';
export const weatherValue = (value, unit) => Number.isFinite(value) ? `${value.toFixed(2)} ${unit}` : 'Unavailable';
export function checkpointText(point) {
  const w = point.weather || {}, r = point.risk || {}, v = w.values || {};
  return [`Checkpoint ${point.index + 1} · ${miles(point.distance_miles)}`, `ETA: ${utcTime(point.eta)}`, `Risk: ${r.level || 'Unknown'}`,
    `Coverage: ${w.coverage?.status || 'unavailable'}${r.assessment_status === 'incomplete' ? ' — risk assessment incomplete' : ''}`,
    `Wind: ${weatherValue(v.wind_mph, 'mph')}`, `Rain: ${weatherValue(v.rain_in_per_hour, 'in/hr')}`, `Snow: ${weatherValue(v.snow_in_per_hour, 'in/hr')}`,
    `Wind forecast: ${utcTime(w.field_timestamps?.wind_mph)}`, `Rain forecast: ${utcTime(w.field_timestamps?.rain_in_per_hour)}`, `Snow forecast: ${utcTime(w.field_timestamps?.snow_in_per_hour)}`,
    `Triggering rule: ${(r.reasons || ['Weather is unknown.']).join(' ')}`];
}
