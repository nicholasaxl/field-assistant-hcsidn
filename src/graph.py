"""LangGraph agent. Routing is plain Python; the LLM only grades, rewrites and writes the answer.

classify -> (error_code) lookup_code -> retrieve -> grade -> generate -> format_citations -> apply_policy
                                            ^          |                                       ^
                                            |       (weak, retries left)                       |
                                         rewrite <-----+      (still weak) -> fallback --------+
"""
from __future__ import annotations

import re
import time
from typing import Any, Callable, TypedDict

from langgraph.graph import END, START, StateGraph

import config
from src import prompts
from src.citations import analyze, answer_strength, attribute
from src.conversation import contextualize as contextualize_question
from src.conversation import is_vague, tied_devices
from src.devices import infer_device
from src.error_lookup import ErrorCodeDB
from src.fastpath import pick_fast_steps
from src.policy import evaluate as evaluate_policy
from src.textutil import body_text


class AgentState(TypedDict, total=False):
    question: str
    device_model: str
    intent: str  # error_code | troubleshooting | out_of_scope
    query: str
    docs: list
    code_records: list
    answer: str
    sources: list
    blocks: list  # structured answer for the UI: steps with their citations
    strength: dict  # coarse trust label for the UI
    alerts: list  # safety alerts decided by rules, not by the model
    fast: bool  # the steps are the manual's own wording, shown without a model call
    inferred_device: str | None  # device worked out from the question when none was chosen
    infer_device: bool  # False when the engineer asked to search every device
    history: list  # the last few turns, for follow-up questions
    followup: bool  # this question continues the previous one
    failure_followup: bool  # ...and says the previous procedure didn't work
    exclude: list  # passage labels already shown for a failed procedure
    clarify: dict  # a question back to the engineer instead of an answer
    best_distance: float  # closest passage when nothing was close enough
    retries: int
    trace: list


def _text(response: Any) -> str:
    return response if isinstance(response, str) else str(getattr(response, "content", response))


def _doc_label(doc) -> str:
    meta = doc.metadata
    where = f"p.{meta['page']}" if "page" in meta else meta.get("section", "")
    return f"{meta.get('source', 'unknown')}" + (f", {where}" if where else "")


def _build_sources(code_records: list, docs: list) -> list[dict]:
    """What the answer is written from: exact error-table entries first, then the retrieved passages."""
    return [
        {
            "label": f"Error code {r['code']} ({r['device_model']})",
            "text": f"{r['meaning']} Fix: {r['fix']} Severity: {r['severity']}",
            "kind": "error_code",
            "distance": None,
            "device": r["device_model"],
        }
        for r in code_records
    ] + [
        {
            "label": _doc_label(d),
            "text": body_text(d),
            "kind": "document",
            "distance": d.metadata.get("distance"),
            "device": d.metadata.get("device_model"),
            "file": d.metadata.get("source"),
            "page": d.metadata.get("page"),
        }
        for d in docs
    ]


def build_graph(
    llm,
    retrieve_fn: Callable[[str, str | None], list],
    code_db: ErrorCodeDB,
    max_retries: int = config.MAX_RETRIES,
    policy_fn: Callable[[str, list, str], list] = evaluate_policy,
    known_devices_fn: Callable[[], list[str]] | None = None,
    fast_path: bool = config.FAST_PATH,
):
    """Compile the agent. `llm` needs .invoke(str); `retrieve_fn(query, device_model)` returns Documents."""

    def contextualize(state: AgentState) -> dict:
        """Turn a follow-up ("that didn't work") into a standalone question using the last few turns."""
        result = contextualize_question(state["question"], state.get("history") or [])
        if result is None:
            return {"followup": False, "failure_followup": False, "exclude": [], "trace": []}
        update = {
            "question": result["question"],
            "followup": True,
            "failure_followup": result["failure"],
            "exclude": result["exclude"],
            "trace": [f"contextualize: follow-up ({'that did not work' if result['failure'] else 'question'})"],
        }
        if (state.get("device_model") or config.ALL_DEVICES) == config.ALL_DEVICES and result["device"] not in (
            None,
            config.ALL_DEVICES,
        ):
            update["device_model"] = result["device"]
        return update

    def classify(state: AgentState) -> dict:
        question = state["question"].strip()
        if not question:
            return {"intent": "out_of_scope", "trace": state.get("trace", []) + ["classify: empty question"]}
        device = state.get("device_model") or config.ALL_DEVICES
        records = code_db.find(question, device)
        intent = "error_code" if records else "troubleshooting"
        inferred = None
        if device == config.ALL_DEVICES and known_devices_fn is not None and state.get("infer_device", True):
            inferred = infer_device(question, records, known_devices_fn())
        note = f"classify: {intent}" + (f" ({len(records)} record(s))" if records else "")
        return {
            "intent": intent,
            "code_records": records,
            "query": question,
            "retries": 0,
            "device_model": inferred or device,
            "inferred_device": inferred,
            "trace": state.get("trace", []) + [note + (f", device inferred: {inferred}" if inferred else "")],
        }

    def lookup_code(state: AgentState) -> dict:
        extra = " ".join(r["meaning"] for r in state["code_records"])
        return {"query": f"{state['question']} {extra}", "trace": state["trace"] + ["lookup_code: exact match"]}

    def retrieve(state: AgentState) -> dict:
        docs = retrieve_fn(state["query"], state.get("device_model"))
        shown = set(state.get("exclude") or [])
        if shown:  # a procedure that didn't work is not offered a second time
            docs = [d for d in docs if _doc_label(d) not in shown]
        return {"docs": docs, "trace": state["trace"] + [f"retrieve: {len(docs)} chunk(s)"]}

    def grade(state: AgentState) -> dict:
        docs = state["docs"]
        if state["code_records"]:
            # An exact error-code match is authoritative; keep the runbook chunks as extra
            # context instead of letting a small model discard them.
            return {"trace": state["trace"] + [f"grade: skipped (exact error-code match), kept {len(docs)}"]}
        if not docs:
            return {"trace": state["trace"] + ["grade: nothing retrieved"]}
        distances = [d.metadata["distance"] for d in docs if "distance" in d.metadata]
        gate = config.RELEVANCE_MAX_DISTANCE - (config.REWRITE_TIGHTEN if state.get("retries", 0) > 0 else 0.0)
        if distances and min(distances) > gate:
            # Scope is decided by retrieval distance: a small model said NONE even when the best
            # chunk was exactly right (e.g. a question that doesn't name the device). After a rewrite
            # the bar is higher, so an unrelated question can't be rewritten into a false match.
            note = f"grade: best distance {min(distances):.2f} > {gate:.2f}, out of scope"
            return {"docs": [], "best_distance": min(distances), "trace": state["trace"] + [note]}
        if distances and (len(docs) == 1 or min(distances) <= config.STRONG_DISTANCE):
            # A strong top match needs no model opinion: keep it and anything about as close, skip the call.
            best = min(distances)
            best_source = next(d.metadata.get("source") for d in docs if d.metadata.get("distance") == best)
            # Keep everything about as close, plus sibling sections of the same document: the answer to a
            # symptom is often in the "Fix" section next to it, which is a little further away.
            kept = [
                d
                for d in docs
                if d.metadata.get("distance", best) <= best + 0.15
                or (d.metadata.get("source") == best_source and d.metadata.get("distance", best) <= best + 0.30)
            ][:4]
            return {"docs": kept, "trace": state["trace"] + [f"grade: skipped (strong match), kept {len(kept)}/{len(docs)}"]}
        passages = "\n\n".join(f"[{i}] {body_text(d)[:600]}" for i, d in enumerate(docs, start=1))
        reply = _text(llm.invoke(prompts.GRADE.format(question=state["question"], passages=passages)))
        numbers = {int(n) for n in re.findall(r"\d+", reply)}
        if numbers:
            # The grader may only prune lower-ranked chunks; retrieval already ranks the best match first.
            numbers.add(1)
            kept = [d for i, d in enumerate(docs, start=1) if i in numbers]
        elif "none" in reply.lower():
            kept = docs[:1]  # distance already says something relevant exists, so keep the best chunk
        else:  # unparsable reply from a small model: keep everything, the answer prompt is still strict
            kept = docs
        return {"docs": kept, "trace": state["trace"] + [f"grade: kept {len(kept)}/{len(docs)}"]}

    def route_after_grade(state: AgentState) -> str:
        if state["docs"] or state["code_records"]:
            return "generate"
        if state["retries"] >= max_retries:
            return "fallback"
        if state.get("best_distance", 0.0) > config.RELEVANCE_MAX_DISTANCE + config.REWRITE_MAX_OVERSHOOT:
            return "fallback"  # nowhere near any document: rewording won't help
        return "rewrite"

    def rewrite(state: AgentState) -> dict:
        new_query = _text(llm.invoke(prompts.REWRITE.format(question=state["question"]))).strip()
        retries = state["retries"] + 1
        return {
            "query": new_query or state["query"],
            "retries": retries,
            "trace": state["trace"] + [f"rewrite #{retries}: {new_query[:80]}"],
        }

    def clarification(state: AgentState) -> dict | None:
        """Ask rather than guess: only for a vague question or a near-tie between devices, never on a follow-up."""
        if state.get("intent") != "troubleshooting" or state.get("followup") or not state.get("infer_device", True):
            return None
        if (state.get("device_model") or config.ALL_DEVICES) != config.ALL_DEVICES:
            return None
        if is_vague(state["question"]):
            options = known_devices_fn() if known_devices_fn else []
            return {
                "kind": "detail",
                "prompt": "Tell me a bit more: which device is it, and what does it show or do?",
                "options": options,
            }
        tied = tied_devices(state.get("docs", []))
        if tied:
            return {"kind": "device", "prompt": "Which device are you working on?", "options": tied}
        return None

    def clarify(state: AgentState) -> dict:
        return {
            "clarify": clarification(state),
            "answer": "",
            "sources": [],
            "blocks": [],
            "alerts": [],
            "trace": state["trace"] + ["clarify"],
        }

    def route_after_retrieve(state: AgentState) -> str:
        if clarification(state):
            return "clarify"
        if fast_path and state.get("intent") in ("error_code", "troubleshooting"):
            doc, _steps = pick_fast_steps(state["question"], state["docs"], state["code_records"], config.FAST_PATH_DISTANCE)
            if doc is not None:
                return "fast_answer"
        return "grade"

    def fast_answer(state: AgentState) -> dict:
        """Show the manual's own numbered steps; no model call, every step traceable."""
        doc, steps = pick_fast_steps(state["question"], state["docs"], state["code_records"], config.FAST_PATH_DISTANCE)
        sources = _build_sources(state["code_records"], [doc])
        answer = "\n".join(f"{i}. {step}" for i, step in enumerate(steps, start=1))
        return {
            "docs": [doc],
            "answer": answer,
            "sources": sources,
            "fast": True,
            "trace": state["trace"] + [f"fast_answer: {len(steps)} step(s) from {_doc_label(doc)}"],
        }

    def generate(state: AgentState) -> dict:
        sources = _build_sources(state["code_records"], state["docs"])
        context = "\n\n".join(f"[{i}] ({s['label']}) {s['text']}" for i, s in enumerate(sources, start=1))
        answer = _text(llm.invoke(prompts.ANSWER.format(context=context, question=state["question"]))).strip()
        return {"answer": answer, "sources": sources, "trace": state["trace"] + ["generate"]}

    def format_citations(state: AgentState) -> dict:
        sources = state["sources"]
        answer, matched, unmatched = attribute(state["answer"], [s["text"] for s in sources])
        lines = [f"- [{i}] {s['label']}" for i, s in enumerate(sources, start=1)]  # bullets render one per line
        note = (
            f"\n\n_{unmatched} step(s) could not be matched to a source. Verify before acting._"
            if unmatched
            else ""
        )
        return {
            "answer": f"{answer}{note}\n\n**Sources**\n" + "\n".join(lines),
            "blocks": analyze(state["answer"], [s["text"] for s in sources]),
            "strength": answer_strength(sources, matched, unmatched, bool(state["code_records"])),
            "trace": state["trace"] + [f"citations: {matched} step(s) matched, {unmatched} unmatched"],
        }

    def apply_policy(state: AgentState) -> dict:
        """Rule-based safety check. Runs on every path, including 'not found'."""
        blocks = state.get("blocks") or []
        text = " ".join(b["text"] for b in blocks) if blocks else state.get("answer", "")
        alerts = policy_fn(state["question"], state.get("code_records", []), text)
        return {"alerts": alerts, "trace": state.get("trace", []) + [f"policy: {len(alerts)} alert(s)"]}

    def fallback(state: AgentState) -> dict:
        return {
            "answer": prompts.EXHAUSTED if state.get("failure_followup") else prompts.FALLBACK,
            "sources": [],
            "trace": state.get("trace", []) + ["fallback"],
        }

    graph = StateGraph(AgentState)
    for name, fn in [
        ("contextualize", contextualize),
        ("clarify", clarify),
        ("classify", classify),
        ("lookup_code", lookup_code),
        ("retrieve", retrieve),
        ("grade", grade),
        ("rewrite", rewrite),
        ("fast_answer", fast_answer),
        ("generate", generate),
        ("format_citations", format_citations),
        ("apply_policy", apply_policy),
        ("fallback", fallback),
    ]:
        graph.add_node(name, fn)

    graph.add_edge(START, "contextualize")
    graph.add_edge("contextualize", "classify")
    graph.add_conditional_edges(
        "classify",
        lambda s: {"error_code": "lookup_code", "troubleshooting": "retrieve"}.get(s["intent"], "fallback"),
        {"lookup_code": "lookup_code", "retrieve": "retrieve", "fallback": "fallback"},
    )
    graph.add_edge("lookup_code", "retrieve")
    graph.add_conditional_edges(
        "retrieve", route_after_retrieve, {"fast_answer": "fast_answer", "grade": "grade", "clarify": "clarify"}
    )
    graph.add_edge("clarify", END)
    graph.add_edge("fast_answer", "format_citations")
    graph.add_conditional_edges(
        "grade", route_after_grade, {"generate": "generate", "rewrite": "rewrite", "fallback": "fallback"}
    )
    graph.add_edge("rewrite", "retrieve")
    graph.add_edge("generate", "format_citations")
    graph.add_edge("format_citations", "apply_policy")
    graph.add_edge("fallback", "apply_policy")
    graph.add_edge("apply_policy", END)
    return graph.compile()


def make_llm(model: str | None = None):
    from langchain_ollama import ChatOllama

    return ChatOllama(
        model=model or config.CHAT_MODEL,
        base_url=config.OLLAMA_BASE_URL,
        temperature=0,
        num_ctx=config.NUM_CTX,
        keep_alive=config.KEEP_ALIVE,
    )


def build_default_app(store=None, code_db: ErrorCodeDB | None = None, llm=None):
    from src.ingest import get_store
    from src.retriever import retrieve

    from src.ingest import list_documents

    store = store or get_store()
    code_db = code_db or ErrorCodeDB()

    def known_devices() -> list[str]:
        library = {d["device_model"] for d in list_documents(store)}
        return sorted((set(code_db.devices()) | library) - {config.ALL_DEVICES})

    return build_graph(
        llm or make_llm(),
        lambda query, device: retrieve(query, store, device),
        code_db,
        known_devices_fn=known_devices,
    )


def ask(app, question: str, device_model: str | None = None) -> dict:
    started = time.perf_counter()
    state = app.invoke({"question": question, "device_model": device_model or config.ALL_DEVICES})
    state["elapsed"] = time.perf_counter() - started
    return state
