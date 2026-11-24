export function tripFixture(count = 3, excluded = false) {
  const paths = [ [[8.68,50.11],[8.7,50.6],[9.51,51.32]], [[8.68,50.11],[9.5,50.55],[9.51,51.32]], [[8.68,50.11],[8.25,50.7],[9.51,51.32]] ];
  const routes = paths.slice(0, count).map((coordinates, i) => ({
    id: `route-${i + 1}`, distance_miles: 111 + i * 5, duration_seconds: 9000 + i * 600, destination_eta: '2026-11-25T10:30:00Z', geometry: { type: 'LineString', coordinates },
    summary: { severe_miles: 0, high_miles: i * 5, no_travel_miles: excluded && i === 0 ? 50 : 0, unknown_coverage_miles: excluded ? 25 : 0, average_risk: excluded ? null : i * .3, eligible: !excluded,
      exclusion_reasons: excluded ? [{ code: 'incomplete_forecast_coverage', message: 'Route has incomplete forecast coverage.' }, ...(i === 0 ? [{ code: 'no_travel_segments', message: 'Route contains confirmed No Travel segments.' }] : [])] : [] },
    checkpoints: coordinates.map(([longitude, latitude], index) => {
      const unknown = excluded && index === 1;
      const level = unknown ? 'Unknown' : excluded && i === 0 ? 'No Travel' : index === 1 ? 'High' : 'Low';
      return { index, longitude, latitude, distance_miles: index * 50, eta: `2026-11-25T${String(8 + index).padStart(2, '0')}:00:00Z`,
        risk: { level, assessment_status: unknown ? 'incomplete' : 'confirmed', reasons: [unknown ? 'No usable weather data for this ETA.' : level === 'High' ? 'Wind 35 mph: High.' : `Wind: ${level}.`] },
        weather: { coverage: { status: unknown ? 'unavailable' : 'complete' }, values: { wind_mph: unknown ? null : 35, rain_in_per_hour: unknown ? null : .02, snow_in_per_hour: unknown ? null : 0 }, field_timestamps: { wind_mph: '2026-11-25T09:00:00Z', rain_in_per_hour: '2026-11-25T09:00:00Z', snow_in_per_hour: '2026-11-25T09:00:00Z' } } };
    })
  }));
  return { routes, route_count: routes.length, recommended_route_id: excluded || !count ? null : 'route-1', recommendation: { explanation: excluded ? 'No route has both complete forecast coverage and no No Travel segments.' : 'Fewest High miles decides the comparison.' } };
}
export async function mockBase(page) {
  await page.route('**/api/health/', route => route.fulfill({ json: { status: 'ok' } }));
  // Deterministic blank tiles; real MapLibre rendering/GeoJSON/markers still run.
  await page.route('https://tile.openstreetmap.org/**', route => route.fulfill({ contentType: 'image/png', body: Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aS1sAAAAASUVORK5CYII=', 'base64') }));
}
