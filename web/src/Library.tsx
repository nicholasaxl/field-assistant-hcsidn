import { AnimatePresence, motion } from "motion/react";
import { useEffect, useId, useRef, useState } from "react";
import type { DragEvent } from "react";
import { deleteDocument, uploadDocuments } from "./api";
import { Arcs } from "./Arcs";
import { Close, Trash } from "./Icons";
import type { DocInfo, UploadResult } from "./types";
import { deviceLabel, fileKind, formatSize } from "./utils";

type Props = {
  open: boolean;
  onClose: () => void;
  docs: DocInfo[];
  devices: string[];
  extensions: string[];
  maxMb: number;
  onChanged: () => Promise<void> | void;
};

const STATUS_TEXT: Record<UploadResult["status"], (r: UploadResult) => string> = {
  added: (r) => `Added, ${r.chunks} passages`,
  updated: (r) => `Updated, ${r.chunks} passages`,
  skipped: () => "Already up to date",
  error: (r) => r.message ?? "Couldn't add this file",
};

export function Library({ open, onClose, docs, devices, extensions, maxMb, onChanged }: Props) {
  const [staged, setStaged] = useState<File[]>([]);
  const [tag, setTag] = useState("");
  const [busy, setBusy] = useState(false);
  const [results, setResults] = useState<UploadResult[]>([]);
  const [over, setOver] = useState(false);
  const [confirming, setConfirming] = useState<string | null>(null);
  const [removeError, setRemoveError] = useState<string | null>(null);
  const picker = useRef<HTMLInputElement>(null);
  const listId = useId();

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  function stage(list: FileList | File[]) {
    const incoming = Array.from(list);
    setResults([]);
    setStaged((current) => [...current, ...incoming.filter((f) => !current.some((c) => c.name === f.name))]);
  }

  function onDrop(e: DragEvent) {
    e.preventDefault();
    setOver(false);
    if (e.dataTransfer.files.length) stage(e.dataTransfer.files);
  }

  async function submit() {
    setBusy(true);
    try {
      const { results } = await uploadDocuments(staged, tag.trim() || "all");
      setResults(results);
      setStaged([]);
      await onChanged();
    } catch (err) {
      setResults([{ name: "Upload", status: "error", message: err instanceof Error ? err.message : "Upload failed" }]);
    } finally {
      setBusy(false);
    }
  }

  async function remove(source: string) {
    if (confirming !== source) {
      setConfirming(source);
      return;
    }
    setConfirming(null);
    setRemoveError(null);
    try {
      await deleteDocument(source);
      await onChanged();
    } catch (err) {
      setRemoveError(err instanceof Error ? err.message : "Couldn't remove the document");
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
            data-side="left"
            role="dialog"
            aria-label="Library"
            initial={{ x: "-100%" }}
            animate={{ x: 0 }}
            exit={{ x: "-100%" }}
            transition={{ duration: 0.38, ease: [0.22, 1, 0.36, 1] }}
          >
            <div className="panel-head">
              <h2 className="panel-title">Library</h2>
              <button className="icon-btn" onClick={onClose} aria-label="Close library">
                <Close />
              </button>
            </div>

            <div className="sheet-body">
              <div
                className="dropzone"
                data-over={over}
                onDragOver={(e) => {
                  e.preventDefault();
                  setOver(true);
                }}
                onDragLeave={() => setOver(false)}
                onDrop={onDrop}
              >
                <Arcs className="dropzone-arcs" size={40} count={3} strokeWidth={8} active={over} />
                <p className="dropzone-title">Drop manuals here</p>
                <p className="dropzone-sub">
                  or{" "}
                  <button className="link-btn" onClick={() => picker.current?.click()}>
                    browse files
                  </button>
                  . {extensions.map((e) => e.slice(1).toUpperCase()).join(", ")} up to {maxMb} MB each.
                </p>
                <input
                  ref={picker}
                  type="file"
                  multiple
                  hidden
                  accept={extensions.join(",")}
                  onChange={(e) => {
                    if (e.target.files) stage(e.target.files);
                    e.target.value = "";
                  }}
                />
              </div>

              <div className="field">
                <label htmlFor="device-tag">Applies to</label>
                <input
                  id="device-tag"
                  list={listId}
                  value={tag}
                  placeholder="All devices"
                  onChange={(e) => setTag(e.target.value)}
                />
                <datalist id={listId}>
                  {devices.map((d) => (
                    <option key={d} value={d} />
                  ))}
                </datalist>
                <small>
                  Leave empty for every device, or enter a model such as HX-ATM-500. Markdown files can set their own
                  device in front matter.
                </small>
              </div>

              <AnimatePresence initial={false}>
                {(staged.length > 0 || results.length > 0) && (
                  <motion.ul
                    className="file-list"
                    initial={{ opacity: 0, height: 0 }}
                    animate={{ opacity: 1, height: "auto" }}
                    exit={{ opacity: 0, height: 0 }}
                    style={{ overflow: "hidden" }}
                  >
                    {staged.map((f) => (
                      <li className="file-row" key={f.name}>
                        <span className="file-type">{fileKind(f.name)}</span>
                        <span className="row-main">
                          <p className="row-name">{f.name}</p>
                          <p className="row-sub">{formatSize(f.size)}, ready to add</p>
                        </span>
                        <button
                          className="icon-btn"
                          aria-label={`Remove ${f.name} from this batch`}
                          onClick={() => setStaged((s) => s.filter((x) => x !== f))}
                        >
                          <Close />
                        </button>
                      </li>
                    ))}
                    {results.map((r) => (
                      <li className="file-row" key={r.name}>
                        <span className="file-type">{fileKind(r.name)}</span>
                        <span className="row-main">
                          <p className="row-name">{r.name}</p>
                          <p className="row-sub" data-tone={r.status === "error" ? "error" : "ok"}>
                            {STATUS_TEXT[r.status](r)}
                          </p>
                        </span>
                        <span />
                      </li>
                    ))}
                  </motion.ul>
                )}
              </AnimatePresence>

              {staged.length > 0 && (
                <button className="primary-btn" disabled={busy} onClick={submit}>
                  {busy ? "Adding..." : `Add ${staged.length} document${staged.length === 1 ? "" : "s"}`}
                </button>
              )}

              <div>
                <h3 className="section-title">
                  Indexed documents <span className="count">{docs.length}</span>
                </h3>
                {removeError && (
                  <p className="row-sub" data-tone="error" role="alert" style={{ marginTop: 8 }}>
                    {removeError}
                  </p>
                )}
                {docs.length === 0 ? (
                  <p className="empty" style={{ marginTop: 10 }}>
                    No documents yet. Drop a manual above to start.
                  </p>
                ) : (
                  <ul className="doc-list" style={{ marginTop: 10 }}>
                    <AnimatePresence initial={false}>
                      {docs.map((d) => (
                        <motion.li
                          key={d.source}
                          className="doc-row"
                          layout
                          initial={{ opacity: 0, y: 6 }}
                          animate={{ opacity: 1, y: 0 }}
                          exit={{ opacity: 0, x: -24 }}
                          transition={{ duration: 0.28 }}
                        >
                          <span className="file-type">{fileKind(d.source)}</span>
                          <span className="row-main">
                            <p className="row-name" title={d.source}>
                              {d.source}
                            </p>
                            <p className="row-sub">
                              {deviceLabel(d.device_model)}, {d.chunks} passages
                            </p>
                          </span>
                          {confirming === d.source ? (
                            <button
                              className="confirm-btn"
                              onClick={() => remove(d.source)}
                              onBlur={() => setConfirming(null)}
                              autoFocus
                            >
                              Remove
                            </button>
                          ) : (
                            <button className="icon-btn" aria-label={`Remove ${d.source}`} onClick={() => remove(d.source)}>
                              <Trash />
                            </button>
                          )}
                        </motion.li>
                      ))}
                    </AnimatePresence>
                  </ul>
                )}
              </div>
            </div>
          </motion.aside>
        </>
      )}
    </AnimatePresence>
  );
}
