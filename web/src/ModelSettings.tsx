import { AnimatePresence, motion } from "motion/react";
import { useEffect, useState } from "react";
import { listAvailableModels, removeApiKey, saveApiKey, selectModel, testModel } from "./api";
import { Check, Close } from "./Icons";
import type { ActiveModel, ModelProvider, ModelsInfo, ModelTest, OnlineProviderId, ProviderId } from "./types";

type Props = { open: boolean; onClose: () => void; models: ModelsInfo | null; onChanged: () => Promise<void> | void };
type Note = { tone: "ok" | "error"; text: string } | null;

const EASE = [0.22, 1, 0.36, 1] as const;

function hostOf(url: string) {
  try {
    return new URL(url).hostname;
  } catch {
    return "";
  }
}

function TestLine({ result }: { result?: ModelTest | "running" }) {
  if (!result) return null;
  if (result === "running") return <p className="test-line">Testing…</p>;
  return result.ok ? (
    <p className="test-line" data-tone="ok">
      <Check /> Works. It answered in {result.ms} ms.
    </p>
  ) : (
    <p className="test-line" data-tone="error" role="alert">
      {result.message}
    </p>
  );
}

type CardProps = {
  provider: ModelProvider;
  active: ActiveModel | undefined;
  busy: boolean;
  run: (action: () => Promise<void>) => Promise<void>;
  say: (note: Note) => void;
};

/** One online provider: its key, its model, the confirmation, and the buttons. */
function OnlineCard({ provider, active, busy, run, say }: CardProps) {
  const id = provider.id as OnlineProviderId;
  const fixedModels = provider.models.length > 0;
  const keyState = provider.key;
  const isActive = Boolean(active && !active.local && active.provider === id);

  const [model, setModel] = useState(fixedModels ? provider.models[0].id : "");
  const [baseUrl, setBaseUrl] = useState(provider.base_url ?? "");
  const [keyInput, setKeyInput] = useState("");
  const [consent, setConsent] = useState(false);
  const [available, setAvailable] = useState<string[]>([]);
  const [test, setTest] = useState<ModelTest | "running">();
  const [expanded, setExpanded] = useState(isActive); // four open cards would make a very long panel

  // Start on what is in use, or on what was saved for the address last time.
  useEffect(() => {
    if (isActive && active) setModel(active.model);
  }, [isActive, active?.model]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (provider.needs_base_url && provider.base_url) setBaseUrl((current) => current || provider.base_url || "");
  }, [provider.base_url, provider.needs_base_url]);

  const sendsTo = provider.sends_to ?? (hostOf(baseUrl) || "the service at the address you entered");
  const modelInfo = provider.models.find((m) => m.id === model);
  const addressOk = !provider.needs_base_url || baseUrl.trim().length > 8;
  const inUse = isActive && active?.model === model;
  const address = provider.needs_base_url ? baseUrl.trim() : undefined;

  const save = () =>
    run(async () => {
      await saveApiKey(id, keyInput);
      setKeyInput(""); // the field never keeps the key once it has been sent
      say({ tone: "ok", text: "Key saved. It is stored in this computer's credential store, not in the app." });
    });

  const remove = () =>
    run(async () => {
      await removeApiKey(id);
      setConsent(false);
      setAvailable([]);
      say({ tone: "ok", text: "Key removed. If this provider was in use, answers are written on this computer again." });
    });

  const use = () =>
    run(async () => {
      await selectModel(id, model.trim(), consent, address);
      say({ tone: "ok", text: `Now using ${provider.label.replace(", online", "")}. Answers are written online.` });
    });

  async function check() {
    setTest("running");
    try {
      setTest(await testModel(id, model.trim(), address));
    } catch (err) {
      setTest({ ok: false, message: err instanceof Error ? err.message : "Test failed" });
    }
  }

  async function loadModels() {
    say(null);
    try {
      const result = await listAvailableModels(id, address);
      if (result.ok) {
        setAvailable(result.models);
        if (!model && result.models[0]) setModel(result.models[0]);
        if (result.models.length === 0) say({ tone: "error", text: "The service returned no models. Type the model name instead." });
      } else {
        say({ tone: "error", text: result.message });
      }
    } catch (err) {
      say({ tone: "error", text: err instanceof Error ? err.message : "Couldn't load the model list." });
    }
  }

  return (
    <section className="model-card" data-active={isActive} data-disabled={!provider.enabled}>
      <h3 className="model-card-title">
        <button
          className="model-card-toggle"
          aria-expanded={expanded}
          aria-controls={`${id}-body`}
          onClick={() => setExpanded((e) => !e)}
          disabled={!provider.enabled}
        >
          <span>{provider.label}</span>
          <span className="model-card-status">
            {!provider.enabled ? "Turned off" : isActive ? "In use" : keyState?.saved ? "Key saved" : "No key"}
          </span>
        </button>
      </h3>
      {(expanded || !provider.enabled) && (
        <p className="model-card-note" data-warn={provider.enabled} id={`${id}-body`}>
          {provider.note}
        </p>
      )}

      {expanded && provider.enabled && keyState && (
        <>
          {provider.needs_base_url && (
            <div className="field">
              <label htmlFor={`${id}-url`}>Service address</label>
              <input
                id={`${id}-url`}
                type="url"
                spellCheck={false}
                placeholder="https://api.example.com/v1"
                value={baseUrl}
                onChange={(e) => setBaseUrl(e.target.value)}
              />
              <small>Any service that speaks the OpenAI chat format. It must start with https://.</small>
            </div>
          )}

          <div className="field">
            <label htmlFor={`${id}-key`}>API key</label>
            {keyState.saved ? (
              <div className="key-saved">
                <span>
                  Saved ({keyState.hint}){" "}
                  {keyState.source === "env"
                    ? `from the ${keyState.env_var} environment variable`
                    : "in this computer's credential store"}
                </span>
                {keyState.source === "store" && (
                  <button className="link-btn" onClick={remove} disabled={busy}>
                    Remove key
                  </button>
                )}
              </div>
            ) : keyState.can_store ? (
              <div className="key-row">
                <input
                  id={`${id}-key`}
                  type="password"
                  autoComplete="off"
                  spellCheck={false}
                  placeholder={keyState.placeholder}
                  value={keyInput}
                  onChange={(e) => setKeyInput(e.target.value)}
                />
                <button className="pill-btn" onClick={save} disabled={busy || keyInput.trim().length < 20}>
                  Save key
                </button>
              </div>
            ) : (
              <small>
                This computer has no secure place to keep a key. Set the {keyState.env_var} environment variable and
                restart the app instead.
              </small>
            )}
            <small>
              The key is sent once and stays on this computer. The page only ever shows its last four characters.
            </small>
          </div>

          <div className="field">
            <label htmlFor={`${id}-model`}>Model</label>
            {fixedModels ? (
              <select id={`${id}-model`} className="select" value={model} onChange={(e) => setModel(e.target.value)}>
                {provider.models.map((m) => (
                  <option key={m.id} value={m.id}>
                    {m.label}
                  </option>
                ))}
              </select>
            ) : (
              <div className="key-row">
                <input
                  id={`${id}-model`}
                  list={`${id}-models`}
                  spellCheck={false}
                  autoComplete="off"
                  placeholder="Type a model name"
                  value={model}
                  onChange={(e) => setModel(e.target.value)}
                />
                <datalist id={`${id}-models`}>
                  {available.map((m) => (
                    <option key={m} value={m} />
                  ))}
                </datalist>
                <button
                  className="pill-btn"
                  onClick={loadModels}
                  disabled={busy || !keyState.saved || !addressOk}
                  title="Asks the provider which models this key can use"
                >
                  Load list
                </button>
              </div>
            )}
            {modelInfo && <small>{modelInfo.price}. List price; check the provider's pricing page.</small>}
            {!fixedModels && (
              <small>
                {available.length > 0
                  ? `${available.length} models available. Pick one or type a name.`
                  : "Type the exact model name, or load the list once the key is saved."}
              </small>
            )}
          </div>

          <label className="consent">
            <input type="checkbox" checked={consent} onChange={(e) => setConsent(e.target.checked)} />
            <span>
              I understand that questions and the document passages found for them are sent to {sendsTo} over the
              internet, and that this may be against company policy.
            </span>
          </label>

          <div className="model-actions">
            <button
              className="primary-btn"
              onClick={use}
              disabled={busy || !keyState.saved || !consent || !model.trim() || !addressOk || inUse}
            >
              {inUse ? "In use" : "Use this model"}
            </button>
            <button
              className="pill-btn"
              onClick={check}
              disabled={busy || !keyState.saved || !model.trim() || !addressOk}
              title="Sends one tiny request, which costs a fraction of a cent"
            >
              Test connection
            </button>
          </div>
          <TestLine result={test} />
        </>
      )}
    </section>
  );
}

export function ModelSettings({ open, onClose, models, onChanged }: Props) {
  const local = models?.providers.find((p) => p.id === "ollama");
  const onlineProviders = models?.providers.filter((p) => p.id !== "ollama") ?? [];
  const active = models?.active;

  const [localModel, setLocalModel] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<Note>(null);
  const [localTest, setLocalTest] = useState<ModelTest | "running">();

  // Start the picker on what is in use now.
  useEffect(() => {
    if (active?.local) setLocalModel(active.model);
  }, [active?.provider, active?.model]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  async function run(action: () => Promise<void>) {
    setBusy(true);
    setMessage(null);
    try {
      await action();
      await onChanged();
    } catch (err) {
      setMessage({ tone: "error", text: err instanceof Error ? err.message : "That didn't work." });
    } finally {
      setBusy(false);
    }
  }

  const useLocal = () =>
    run(async () => {
      await selectModel("ollama", localModel);
      setMessage({ tone: "ok", text: `Now using ${localModel} on this computer.` });
    });

  async function testLocal(provider: ProviderId, model: string) {
    setLocalTest("running");
    try {
      setLocalTest(await testModel(provider, model));
    } catch (err) {
      setLocalTest({ ok: false, message: err instanceof Error ? err.message : "Test failed" });
    }
  }

  return (
    <AnimatePresence>
      {open && (
        <>
          <motion.div
            key="scrim"
            className="scrim"
            onClick={onClose}
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
          />
          <motion.aside
            key="sheet"
            className="sheet"
            data-side="right"
            role="dialog"
            aria-label="Model settings"
            initial={{ x: "100%" }}
            animate={{ x: 0 }}
            exit={{ x: "100%" }}
            transition={{ duration: 0.38, ease: EASE }}
          >
            <div className="panel-head">
              <h2 className="panel-title">Model</h2>
              <button className="icon-btn" onClick={onClose} aria-label="Close model settings">
                <Close />
              </button>
            </div>

            <div className="sheet-body">
              {active && (
                <div className="model-now" data-local={active.local}>
                  <p className="model-now-label">{active.label}</p>
                  <p className="model-now-where">
                    {active.local ? "Runs on this computer" : `Runs online at ${active.where.replace(/ \(online\)$/, "")}`} · writes the answers
                  </p>
                  <p className="model-now-where">Search uses {models?.search.model} on this computer, in both cases.</p>
                  {active.note && <p className="model-now-note">Back on the local model: {active.note}</p>}
                </div>
              )}

              {/* ---- local ---- */}
              {local && (
                <section className="model-card" data-active={active?.local}>
                  <h3 className="model-card-title">{local.label}</h3>
                  <p className="model-card-note">{local.note}</p>
                  <div className="field">
                    <label htmlFor="local-model">Model</label>
                    <select id="local-model" className="select" value={localModel} onChange={(e) => setLocalModel(e.target.value)}>
                      {local.models.map((m) => (
                        <option key={m.id} value={m.id}>
                          {m.label}
                        </option>
                      ))}
                    </select>
                  </div>
                  <div className="model-actions">
                    <button
                      className="primary-btn"
                      onClick={useLocal}
                      disabled={busy || !localModel || (active?.local && active.model === localModel)}
                    >
                      {active?.local && active.model === localModel ? "In use" : "Use this model"}
                    </button>
                    <button className="pill-btn" onClick={() => testLocal("ollama", localModel)} disabled={busy || !localModel}>
                      Test
                    </button>
                  </div>
                  <TestLine result={localTest} />
                </section>
              )}

              {/* ---- online: one card per provider ---- */}
              {onlineProviders.map((provider) => (
                <OnlineCard key={provider.id} provider={provider} active={active} busy={busy} run={run} say={setMessage} />
              ))}

              {message && (
                <p className="model-message" data-tone={message.tone} role={message.tone === "error" ? "alert" : "status"}>
                  {message.text}
                </p>
              )}
            </div>
          </motion.aside>
        </>
      )}
    </AnimatePresence>
  );
}
