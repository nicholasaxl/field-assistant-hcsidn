import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { askStream, getDevices, getDocuments, getHealth } from "./api";
import { Composer } from "./Composer";
import { EvidenceDock } from "./Evidence";
import { Header } from "./Header";
import { Hero } from "./Hero";
import { Insights } from "./Insights";
import { Library } from "./Library";
import { TurnView } from "./TurnView";
import type { DocInfo, Health, StreamEvent, Turn } from "./types";
import { newId, useMedia, useTheme } from "./utils";

function applyEvent(turn: Turn, event: StreamEvent): Turn {
  switch (event.type) {
    case "stage": {
      const { type: _type, ...stage } = event;
      return { ...turn, stages: [...turn.stages, stage] };
    }
    case "answer": {
      const { type: _type, ...answer } = event;
      return { ...turn, status: "done", answer };
    }
    case "error":
      return { ...turn, status: "error", error: event.message };
  }
}

export default function App() {
  const [theme, toggleTheme] = useTheme();
  const narrow = useMedia("(max-width: 1040px)");

  const [turns, setTurns] = useState<Turn[]>([]);
  const [draft, setDraft] = useState("");
  const [device, setDevice] = useState("all");
  const [devices, setDevices] = useState<string[]>([]);
  const [docs, setDocs] = useState<DocInfo[]>([]);
  const [libraryReady, setLibraryReady] = useState(false);
  const [library, setLibrary] = useState({ extensions: [".pdf", ".md"] as string[], maxMb: 50 });
  const [health, setHealth] = useState<Health | null>(null);
  const [libraryOpen, setLibraryOpen] = useState(false);
  const [insightsOpen, setInsightsOpen] = useState(false);
  const [evidence, setEvidence] = useState<{ turnId: string; n: number | null; open: boolean } | null>(null);

  const abortRef = useRef<AbortController | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const running = turns.some((t) => t.status === "running");

  const refreshLibrary = useCallback(async () => {
    // The server may still be starting when the page first loads, so retry with a growing pause.
    for (let attempt = 0; attempt < 6; attempt++) {
      try {
        const [{ documents, extensions, max_mb }, deviceList] = await Promise.all([getDocuments(), getDevices()]);
        setDocs(documents);
        setDevices(deviceList);
        setLibrary({ extensions, maxMb: max_mb });
        setLibraryReady(true);
        // A device that disappeared from the library can't stay selected.
        setDevice((current) => (current === "all" || deviceList.includes(current) ? current : "all"));
        return;
      } catch {
        await new Promise((resolve) => setTimeout(resolve, 1500 * (attempt + 1)));
      }
    }
    /* still failing: the header health pill already tells the user the server is unreachable */
  }, []);

  useEffect(() => {
    void refreshLibrary();
    const poll = () => getHealth().then(setHealth).catch(() => setHealth({ ollama: false, ready: false, chat_model: "", embed_model: "" }));
    void poll();
    const timer = setInterval(poll, 15000);
    return () => clearInterval(timer);
  }, [refreshLibrary]);

  const ask = useCallback(
    async (question: string) => {
      const text = question.trim();
      if (!text || running) return;
      const id = newId();
      setTurns((t) => [...t, { id, question: text, device, status: "running", stages: [] }]);
      setDraft("");
      const controller = new AbortController();
      abortRef.current = controller;

      const update = (fn: (t: Turn) => Turn) => setTurns((ts) => ts.map((t) => (t.id === id ? fn(t) : t)));
      try {
        await askStream(text, device, (event) => update((t) => applyEvent(t, event)), controller.signal);
        update((t) =>
          t.status === "running" ? { ...t, status: "error", error: "The connection closed before an answer arrived." } : t,
        );
      } catch (err) {
        const stopped = err instanceof DOMException && err.name === "AbortError";
        update((t) => ({
          ...t,
          status: "error",
          error: stopped ? "Stopped. Ask again when you're ready." : err instanceof Error ? err.message : "Something went wrong.",
        }));
      } finally {
        abortRef.current = null;
      }
    },
    [device, running],
  );

  // Keep the newest activity in view.
  const last = turns[turns.length - 1];
  useEffect(() => {
    const el = scrollRef.current;
    if (!el || turns.length === 0) return;
    const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;
    el.scrollTo({ top: el.scrollHeight, behavior: reduce ? "auto" : "smooth" });
  }, [turns.length, last?.stages.length, last?.status]);

  const evidenceTurn = useMemo(() => turns.find((t) => t.id === evidence?.turnId), [turns, evidence]);
  const latestWithSources = useMemo(() => [...turns].reverse().find((t) => t.answer && t.answer.sources.length > 0), [turns]);

  const openSources = (turnId: string, n: number | null) => setEvidence({ turnId, n, open: true });
  const sourcesOpen = Boolean(evidence?.open && evidenceTurn?.answer);

  return (
    <div className="app">
      <Header
        theme={theme}
        onTheme={toggleTheme}
        health={health}
        docCount={libraryReady ? docs.length : null}
        libraryOpen={libraryOpen}
        onLibrary={() => setLibraryOpen((o) => !o)}
        insightsOpen={insightsOpen}
        onInsights={() => setInsightsOpen((o) => !o)}
        sourcesAvailable={Boolean(latestWithSources)}
        sourcesOpen={sourcesOpen}
        onSources={() =>
          sourcesOpen
            ? setEvidence((e) => (e ? { ...e, open: false } : e))
            : latestWithSources && openSources(evidenceTurn?.answer ? evidenceTurn.id : latestWithSources.id, null)
        }
      />

      <main className="workspace">
        <div className="stage">
          <div className="scroll" ref={scrollRef}>
            <div className="column">
              {turns.length === 0 ? (
                <Hero onPick={(q) => void ask(q)} />
              ) : (
                turns.map((turn) => (
                  <TurnView
                    key={turn.id}
                    turn={turn}
                    activeSource={evidence?.turnId === turn.id ? evidence.n : null}
                    onCite={(n) => openSources(turn.id, n)}
                    onOpenSources={() => openSources(turn.id, null)}
                    onOpenLibrary={() => setLibraryOpen(true)}
                  />
                ))
              )}
            </div>
          </div>

          <Composer
            value={draft}
            onChange={setDraft}
            onSubmit={() => void ask(draft)}
            onStop={() => abortRef.current?.abort()}
            running={running}
            devices={devices}
            device={device}
            onDevice={setDevice}
          />
        </div>

        <EvidenceDock
          open={sourcesOpen}
          overlay={narrow}
          sources={evidenceTurn?.answer?.sources ?? []}
          active={evidence?.n ?? null}
          onClose={() => setEvidence((e) => (e ? { ...e, open: false } : e))}
        />
      </main>

      <Insights
        open={insightsOpen}
        onClose={() => setInsightsOpen(false)}
        onOpenLibrary={() => {
          setInsightsOpen(false);
          setLibraryOpen(true);
        }}
      />

      <Library
        open={libraryOpen}
        onClose={() => setLibraryOpen(false)}
        docs={docs}
        devices={devices}
        extensions={library.extensions}
        maxMb={library.maxMb}
        onChanged={refreshLibrary}
      />
    </div>
  );
}
