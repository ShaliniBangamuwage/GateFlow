import { useMutation, useQuery } from '@tanstack/react-query'
import { Activity, Bot, Gauge, Network, Radar, ShieldAlert, Sparkles } from 'lucide-react'
import { useMemo, useState } from 'react'

import { api } from '../../api'

export default function AIInsights() {
  const overview = useQuery({ queryKey: ['ai-overview'], queryFn: api.aiOverview, refetchInterval: 30000 })
  const anomalies = useQuery({ queryKey: ['ai-anomalies'], queryFn: () => api.aiRecentAnomalies(5), refetchInterval: 30000 })
  const forecast = useQuery({ queryKey: ['ai-forecast'], queryFn: api.aiForecast, refetchInterval: 30000 })
  const incident = useQuery({ queryKey: ['ai-incident'], queryFn: api.aiIncidentAnalysis, refetchInterval: 30000 })
  const [question, setQuestion] = useState('Summarize observed traffic.')
  const [answer, setAnswer] = useState('')
  const [sources, setSources] = useState<string[]>([])
  const [interpretation, setInterpretation] = useState<string[]>([])
  const [route, setRoute] = useState('')

  const assistant = useMutation({
    mutationFn: (value: string) => api.aiAssistant(value),
    onSuccess: result => {
      setAnswer(result.answer)
      setSources(result.sources)
      setInterpretation(result.interpretation)
      setRoute(result.route)
    },
  })

  const sourceList = useMemo(() => {
    const values = [...sources, ...(incident.data?.evidence_sources ?? [])]
    return Array.from(new Set(values.filter(Boolean)))
  }, [incident.data?.evidence_sources, sources])

  if (overview.isLoading) return <div className="state">Loading tenant-scoped AI telemetry...</div>
  if (overview.error || !overview.data) return <div className="state">Unable to load tenant traffic telemetry. Check the Go gateway, AI service, and database connection.</div>

  const anomalyCount = anomalies.data?.status === 'UNAVAILABLE' ? 'unavailable' : anomalies.data?.count ?? '—'
  const forecastStatus = forecast.data?.status ?? (forecast.error ? 'unavailable' : 'loading')

  return (
    <div className="page-stack">
      <div className="page-heading"><div><p className="eyebrow">AI SERVICE</p><h2>AI insights</h2></div></div>
      <section className="metric-grid">
        <Metric label="Observed traffic" value={overview.data.summary} icon={<Sparkles />} />
        <Metric label="ML anomalies" value={anomalyCount} icon={<ShieldAlert />} accent="red" />
        <Metric label="Blocked requests" value={overview.data.blocked_requests} icon={<Gauge />} accent="yellow" />
        <Metric label="Live forecast" value={forecastStatus} icon={<Radar />} />
        <Metric label="Most-used route" value={overview.data.most_used_route || 'n/a'} icon={<Network />} />
        <Metric label="Anomaly model" value={overview.data.model_status} icon={<Bot />} />
      </section>

      <div className="chart-grid">
        <section className="panel">
          <div className="panel-heading"><h3>Recent anomalies</h3><span className="count-pill">MODEL SCORED</span></div>
          {anomalies.isLoading ? <p className="muted">Loading anomaly results...</p>
            : anomalies.error ? <p className="muted">Anomaly results are unavailable. No detection result is being inferred.</p>
              : anomalies.data?.status === 'UNAVAILABLE' ? <p className="muted">{anomalies.data.detail}</p>
                : anomalies.data?.anomalies.length ? <ul className="stack-list">{anomalies.data.anomalies.map((item, index) => <li key={`${item.window_start ?? item.route_id ?? index}`}><span className="tag active">ML DETECTION</span> <strong>{item.route_id ?? 'unknown route'}</strong><small>{item.window_start ?? 'time unavailable'} • {item.client_id ?? 'client unavailable'} • score {typeof item.score === 'number' ? item.score.toFixed(3) : 'n/a'} ({item.model_version ?? 'model version unavailable'})</small></li>)}</ul>
                  : <p className="muted">No model-scored anomalies were observed in the selected window.</p>}
        </section>

        <section className="panel">
          <div className="panel-heading"><h3>Traffic forecast</h3><span className="count-pill">{forecastStatus}</span></div>
          {forecast.isLoading ? <p className="muted">Loading forecast status...</p>
            : forecast.error ? <p className="muted">Forecast status is unavailable.</p>
              : forecast.data?.forecast.length ? <ul className="stack-list">{forecast.data.forecast.map(item => <li key={item.timestamp}><strong>{new Date(item.timestamp).toLocaleString()}</strong><small>{item.predicted_requests} predicted requests</small><span className="tag active">{item.label ?? 'FORECAST'}</span></li>)}</ul>
                : <p className="muted">{forecast.data?.evaluation.note ?? 'No live forecast is available.'}</p>}
          {forecast.data?.evaluation.status && <p className="muted">Evaluation: {forecast.data.evaluation.status}</p>}
        </section>

        <section className="panel">
          <div className="panel-heading"><h3>Incident analysis</h3><span className="count-pill">OBSERVED + INTERPRETATION</span></div>
          {incident.isLoading ? <p className="muted">Loading tenant request-log analysis...</p>
            : incident.error || !incident.data ? <p className="muted">Incident analysis is unavailable; no findings are being inferred.</p>
              : <><p>{incident.data.summary}</p><div className="evidence-block"><strong>Observed</strong>{incident.data.observed.map(item => <small key={item}>{item}</small>)}</div><div className="evidence-block"><strong>Interpretation</strong>{incident.data.interpretations.map(item => <small key={item}>{item}</small>)}</div><div className="evidence-block"><strong>Suggested checks</strong>{incident.data.recommended_actions.map(item => <small key={item}>{item}</small>)}</div></>}
        </section>

        <section className="panel assistant-panel">
          <div className="panel-heading"><h3><Bot size={18} /> AI assistant</h3><span className="count-pill">RULE-BASED</span></div>
          <form onSubmit={event => { event.preventDefault(); if (question.trim()) assistant.mutate(question.trim()) }}>
            <label className="sr-only" htmlFor="ai-question">Ask about tenant traffic</label>
            <input id="ai-question" value={question} onChange={event => setQuestion(event.target.value)} placeholder="Ask about observed traffic" maxLength={1000} />
            <button type="submit" disabled={assistant.isPending || !question.trim()}><Activity size={16} /> {assistant.isPending ? 'Checking...' : 'Ask'}</button>
          </form>
          {assistant.error && <p className="muted">Assistant request failed. No answer was generated.</p>}
          {answer && <div className="assistant-answer"><span className="tag active">{route}</span><p>{answer}</p>{interpretation.map(item => <small key={item}>{item}</small>)}</div>}
          {sourceList.length > 0 && <div className="evidence-block"><strong>Sources</strong>{sourceList.map(source => <small key={source}>{source}</small>)}</div>}
        </section>

        <section className="panel">
          <div className="panel-heading"><h3>Evidence and service status</h3><span className="count-pill">TENANT SCOPED</span></div>
          <p>{overview.data.summary}</p>
          <div className="evidence-block"><strong>Observation window</strong><small>{new Date(overview.data.window.start_time).toLocaleString()} – {new Date(overview.data.window.end_time).toLocaleString()}</small><small>Top client: {overview.data.top_client}</small><small>Model status: {overview.data.model_status}</small></div>
        </section>
      </div>
    </div>
  )
}

function Metric({ label, value, icon, accent = '' }: { label: string; value: React.ReactNode; icon: React.ReactNode; accent?: string }) {
  return <article className={`metric-card ${accent}`}><div className="metric-icon">{icon}</div><span>{label}</span><strong>{String(value)}</strong></article>
}
