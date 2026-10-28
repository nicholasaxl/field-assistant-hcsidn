import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import { useCallback, useEffect, useState } from "react";
import { clearAllData, getInsights, getScorecard, loadSampleData, removeSampleData } from "./api";
import { Close } from "./Icons";
import type { InsightsData, Outcome, Reason, Scorecard } from "./types";
import { deviceLabel, percent, prettyDoc } from "./utils";

const EASE = [0.22, 1, 0.36, 1] as const;

const REASON_TEXT: Record<Reason, string> = {
  step_failed: "A step didn't work",
  different_problem: "Different problem",
  doc_wrong: "Document wrong or outdated",
  need_person: "Needed a person",
};
const OUTCOME_TEXT: Record<Outcome, string> = { fixed: "Fixed", not_fixed: "Not fixed", escalated: "Escalated" };

function Volume({ data }: { data: InsightsData["volume"] }) {
  const reduce = useReducedMotion();
  const max = Math.max(1, ...data.map((d) => d.count));
  const total = data.reduce((sum, d) => sum + d.count, 0);
  const width = 600;
  const height = 120;
  const slot = width / data.length;
  return (
    <figure className="volume">
      <svg viewBox={`0 0 ${width} ${height + 18}`} role="img" aria-label={`${total} questions over the last ${data.length} days`}>
        <line x1="0" x2={width} y1={height} y2={height} className="volume-axis" />
        {data.map((d, i) => {
          const h = Math.max(d.count ? 4 : 1.5, (d.count / max) * (height - 8));
          return (
            <motion.rect
              key={d.date}
              x={i * slot + slot * 0.18}
              width={slot * 0.64}
              y={height - h}
              height={h}
              rx={Math.min(3, slot * 0.2)}
              className={d.count ? "volume-bar" : "volume-bar volume-bar-empty"}
              style={{ transformOrigin: `0px ${height}px`, transformBox: "fill-box" }}
              initial={reduce ? false : { scaleY: 0 }}
              animate={{ scaleY: 1 }}
              transition={{ duration: 0.5, delay: i * 0.012, ease: EASE }}
            >
              <title>{`${d.date}: ${d.count}`}</title>
            </motion.rect>
          );
        })}
        <text x="0" y={height + 14} className="volume-label">
          {data[0]?.date}
        </text>
        <text x={width} y={height + 14} textAnchor="end" className="volume-label">
          {data[data.length - 1]?.date}
        </text>
      </svg>
    </figure>
  );
}

function Bars({ rows }: { rows: { label: string; value: number; note?: string }[] }) {
  const reduce = useReducedMotion();
  const max = Math.max(1, ...rows.map((r) => r.value));
  return (
    <ul className="bars-list">
      {rows.map((r, i) => (
        <li key={r.label}>
          <div className="bars-row">
            <span className="bars-label" title={r.label}>
              {r.label}
            </span>
            <span className="bars-value">{r.note ?? r.value}</span>
          </div>
          <span className="bars-track">
            <motion.span
              className="bars-fill"
              initial={reduce ? false : { scaleX: 0 }}
              animate={{ scaleX: r.value / max }}
              transition={{ duration: 0.6, delay: 0.05 * i, ease: EASE }}
            />
          </span>
        </li>
      ))}
    </ul>
  );
}

type Props = { open: boolean; onClose: () => void; onOpenLibrary: () => void };

export function Insights({ open, onClose, onOpenLibrary }: Props) {
  const [data, setData] = useState<InsightsData | null>(null);
  const [score, setScore] = useState<Scorecard | null>(null);
  const [minutes, setMinutes] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [confirmClear, setConfirmClear] = useState(false);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      setData(await getInsights(30, minutes));
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Couldn't load insights");
    }
  }, [minutes]);

  useEffect(() => {
    if (!open) return;
    void load();
    getScorecard().then(setScore).catch(() => setScore(null));
  }, [open, load]);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  async function act(action: () => Promise<unknown>) {
    setBusy(true);
    try {
      await action();
      setConfirmClear(false);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "That didn't work");
    } finally {
      setBusy(false);
    }
  }

  const empty = data !== null && data.questions === 0;

  return (
    <AnimatePresence>
      {open && (
        <motion.section
          className="insights"
          role="dialog"
          aria-label="Insights"
          initial={{ opacity: 0, y: 28 }}
          animate={{ opacity: 1, y: 0 }}
          exit={{ opacity: 0, y: 28 }}
          transition={{ duration: 0.38, ease: EASE }}
        >
          <div className="insights-inner">
            <div className="insights-head">
              <div>
                <h2 className="insights-title">Insights</h2>
                <p className="insights-sub">Last 30 days, from this device's own records.</p>
              </div>
              <button className="icon-btn" onClick={onClose} aria-label="Close insights">
                <Close />
              </button>
            </div>

            {error && (
              <p className="insights-error" role="alert">
                {error}
              </p>
            )}

            {data?.sample && (
              <div className="sample-banner" role="status">
                <div>
                  <p className="sample-title">Sample data</p>
                  <p>
                    These numbers are invented for demonstration.
                    {data.has_real ? " Your real data is kept and returns when you remove the sample." : ""}
                  </p>
                </div>
                <button className="pill-btn" disabled={busy} onClick={() => act(removeSampleData)}>
                  Remove sample data
                </button>
              </div>
            )}

            {empty && !data.sample && (
              <div className="insights-empty">
                <p className="notice-title">No answers recorded yet</p>
                <p>Ask a question and mark whether it fixed the problem, or preview this page with sample data.</p>
                <button className="primary-btn" disabled={busy} onClick={() => act(loadSampleData)}>
                  Load sample data
                </button>
              </div>
            )}

            {data && !empty && (
              <>
                <div className="kpis">
                  <div className="kpi">
                    <p className="kpi-value">{data.questions}</p>
                    <p className="kpi-label">Questions asked</p>
                    <p className="kpi-note">
                      {data.answered} answered, {data.no_answer} not found
                    </p>
                  </div>
                  <div className="kpi">
                    <p className="kpi-value">{percent(data.fixed_rate)}</p>
                    <p className="kpi-label">Fixed on the first try</p>
                    <p className="kpi-note">
                      {data.feedback_count === 0
                        ? "No responses yet"
                        : `${data.fixed} of ${data.feedback_count} responses, given on ${percent(data.feedback_coverage)} of answers`}
                    </p>
                  </div>
                  <div className="kpi">
                    <p className="kpi-value">
                      {data.estimated_hours_saved} <span className="kpi-unit">h</span>
                    </p>
                    <p className="kpi-label">Time saved (estimate)</p>
                    <p className="kpi-note">
                      {data.fixed} fixed ×{" "}
                      <input
                        className="kpi-input"
                        type="number"
                        min={0}
                        max={600}
                        aria-label="Minutes of engineer time avoided per fixed question"
                        value={minutes ?? data.minutes_per_escalation}
                        onChange={(e) => setMinutes(Math.max(0, Math.min(600, Number(e.target.value) || 0)))}
                      />{" "}
                      min each
                    </p>
                  </div>
                  <div className="kpi">
                    <p className="kpi-value">
                      {data.median_seconds ?? "n/a"} <span className="kpi-unit">s</span>
                    </p>
                    <p className="kpi-label">Median answer time</p>
                    <p className="kpi-note">{percent(data.escalation_rate)} of responses escalated</p>
                  </div>
                </div>

                <div className="insights-grid">
                  <section>
                    <h3 className="section-title">Questions per day</h3>
                    <Volume data={data.volume} />
                  </section>

                  <section>
                    <h3 className="section-title">What people ask about</h3>
                    <Bars rows={data.topics.map((t) => ({ label: prettyDoc(t.topic), value: t.count }))} />
                  </section>

                  <section>
                    <div className="section-row">
                      <h3 className="section-title">Gaps in the library</h3>
                      <button className="link-btn" onClick={onOpenLibrary}>
                        Add a document
                      </button>
                    </div>
                    {data.gaps.length === 0 ? (
                      <p className="insights-note">No gaps found. Every question found an answer people accepted.</p>
                    ) : (
                      <ul className="plain-list">
                        {data.gaps.map((g, i) => (
                          <li key={i}>
                            <span>{g.question}</span>
                            <span className="plain-meta">
                              {deviceLabel(g.device)},{" "}
                              {g.kind === "no_answer" ? "no answer found" : REASON_TEXT[g.reason ?? "different_problem"].toLowerCase()}
                              {g.count > 1 ? `, asked ${g.count}×` : ""}
                            </span>
                          </li>
                        ))}
                      </ul>
                    )}
                  </section>

                  <section>
                    <h3 className="section-title">How each document performs</h3>
                    <Bars
                      rows={data.documents.map((d) => ({
                        label: prettyDoc(d.document),
                        value: d.answers,
                        note: `${d.answers} answers, ${d.fix_rate === null ? "no verdicts" : `${percent(d.fix_rate)} fixed`}`,
                      }))}
                    />
                  </section>

                  <section>
                    <h3 className="section-title">Steps that fail most</h3>
                    {data.failing_steps.length === 0 ? (
                      <p className="insights-note">No failed steps recorded yet.</p>
                    ) : (
                      <ul className="plain-list">
                        {data.failing_steps.map((s) => (
                          <li key={s.step}>
                            <span>{s.step}</span>
                            <span className="plain-meta">failed {s.count}×</span>
                          </li>
                        ))}
                      </ul>
                    )}
                  </section>

                  <section>
                    <h3 className="section-title">Accuracy check</h3>
                    {score && score.available ? (
                      <dl className="score">
                        <div>
                          <dt>Answers that pass</dt>
                          <dd>{percent(score.answer_pass_rate)}</dd>
                        </div>
                        <div>
                          <dt>Right document found</dt>
                          <dd>{percent(score.retrieval_hit_rate)}</dd>
                        </div>
                        <div>
                          <dt>Unrelated questions refused</dt>
                          <dd>{percent(score.refusal_rate)}</dd>
                        </div>
                        <div>
                          <dt>Steps traced to a source</dt>
                          <dd>{percent(score.traced_rate)}</dd>
                        </div>
                        <div>
                          <dt>Safety alerts raised</dt>
                          <dd>{percent(score.alert_rate)}</dd>
                        </div>
                        <p className="insights-note">
                          Run on {score.date}: {score.questions.in_scope + score.questions.out_of_scope + score.questions.critical}{" "}
                          test questions over {score.corpus.documents} documents, model {score.model}. This tests the sample
                          library, not live use.
                        </p>
                      </dl>
                    ) : (
                      <p className="insights-note">
                        No accuracy check yet. Run <code>python -m src.evaluate --answers</code> to measure it.
                      </p>
                    )}
                  </section>
                </div>

                <section>
                  <h3 className="section-title">Recent responses</h3>
                  {data.recent.length === 0 ? (
                    <p className="insights-note">No responses yet. They appear after someone taps Fixed it or Didn't fix it.</p>
                  ) : (
                    <ul className="recent-list">
                      {data.recent.map((r, i) => (
                        <li key={i}>
                          <span className="outcome" data-outcome={r.outcome}>
                            {OUTCOME_TEXT[r.outcome]}
                          </span>
                          <span className="recent-q">{r.question}</span>
                          <span className="plain-meta">
                            {deviceLabel(r.device)}
                            {r.reason ? `, ${REASON_TEXT[r.reason].toLowerCase()}` : ""}
                          </span>
                        </li>
                      ))}
                    </ul>
                  )}
                </section>

                <div className="insights-foot">
                  <a className="pill-btn" href="/api/insights/export.csv" download>
                    Export CSV
                  </a>
                  {!data.sample && (
                    <button className="pill-btn" disabled={busy} onClick={() => act(loadSampleData)}>
                      Preview with sample data
                    </button>
                  )}
                  {confirmClear ? (
                    <button
                      className="confirm-btn"
                      disabled={busy}
                      onClick={() => act(clearAllData)}
                      onBlur={() => setConfirmClear(false)}
                      autoFocus
                    >
                      Clear all recorded data
                    </button>
                  ) : (
                    <button className="pill-btn" onClick={() => setConfirmClear(true)}>
                      Clear data
                    </button>
                  )}
                  <span className="insights-note">Stored on this machine in data/feedback.db.</span>
                </div>
              </>
            )}
          </div>
        </motion.section>
      )}
    </AnimatePresence>
  );
}
