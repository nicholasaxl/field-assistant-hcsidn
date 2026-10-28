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
from src.error_lookup import ErrorCodeDB
from src.policy import evaluate as evaluate_policy


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
    retries: int
    trace: list


def _text(response: Any) -> str:
    return response if isinstance(response, str) else str(getattr(response, "content", response))


def _doc_label(doc) -> str:
    meta = doc.metadata
    where = f"p.{meta['page']}" if "page" in meta else meta.get("section", "")
    return f"{meta.get('source', 'unknown')}" + (f", {where}" if where else "")


def build_graph(
    llm,
    retrieve_fn: Callable[[str, str | None], list],
    code_db: ErrorCodeDB,
    max_retries: int = config.MAX_RETRIES,
    policy_fn: Callable[[str, list, str], list] = evaluate_policy,
):
    """Compile the agent. `llm` needs .invoke(str); `retrieve_fn(query, device_model)` returns Documents."""

    def classify(state: AgentState) -> dict:
        question = state["question"].strip()
        if not question:
            return {"intent": "out_of_scope", "trace": ["classify: empty question"]}
        records = code_db.find(question, state.get("device_model"))
        intent = "error_code" if records else "troubleshooting"
        return {
            "intent": intent,
            "code_records": records,
            "query": question,
            "retries": 0,
            "trace": [f"classify: {intent}" + (f" ({len(records)} record(s))" if records else "")],
        }

    def lookup_code(state: AgentState) -> dict:
        extra = " ".join(r["meaning"] for r in state["code_records"])
        return {"query": f"{state['question']} {extra}", "trace": state["trace"] + ["lookup_code: exact match"]}

    def retrieve(state: AgentState) -> dict:
        docs = retrieve_fn(state["query"], state.get("device_model"))
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
        if distances and min(distances) > config.RELEVANCE_MAX_DISTANCE:
            # Scope is decided by retrieval distance: a small model said NONE even when the best
            # chunk was exactly right (e.g. a question that doesn't name the device).
            note = f"grade: best distance {min(distances):.2f} > {config.RELEVANCE_MAX_DISTANCE}, out of scope"
            return {"docs": [], "trace": state["trace"] + [note]}
        passages = "\n\n".join(f"[{i}] {d.page_content[:600]}" for i, d in enumerate(docs, start=1))
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
        return "rewrite" if state["retries"] < max_retries else "fallback"

    def rewrite(state: AgentState) -> dict:
        new_query = _text(llm.invoke(prompts.REWRITE.format(question=state["question"]))).strip()
        retries = state["retries"] + 1
        return {
            "query": new_query or state["query"],
            "retries": retries,
            "trace": state["trace"] + [f"rewrite #{retries}: {new_query[:80]}"],
        }

    def generate(state: AgentState) -> dict:
        sources = [
            {
                "label": f"Error code {r['code']} ({r['device_model']})",
                "text": f"{r['meaning']} Fix: {r['fix']} Severity: {r['severity']}",
                "kind": "error_code",
                "distance": None,
                "device": r["device_model"],
            }
            for r in state["code_records"]
        ] + [
            {
                "label": _doc_label(d),
                "text": d.page_content,
                "kind": "document",
                "distance": d.metadata.get("distance"),
                "device": d.metadata.get("device_model"),
            }
            for d in state["docs"]
        ]
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
            "answer": prompts.FALLBACK,
            "sources": [],
            "trace": state.get("trace", []) + ["fallback"],
        }

    graph = StateGraph(AgentState)
    for name, fn in [
        ("classify", classify),
        ("lookup_code", lookup_code),
        ("retrieve", retrieve),
        ("grade", grade),
        ("rewrite", rewrite),
        ("generate", generate),
        ("format_citations", format_citations),
        ("apply_policy", apply_policy),
        ("fallback", fallback),
    ]:
        graph.add_node(name, fn)

    graph.add_edge(START, "classify")
    graph.add_conditional_edges(
        "classify",
        lambda s: {"error_code": "lookup_code", "troubleshooting": "retrieve"}.get(s["intent"], "fallback"),
        {"lookup_code": "lookup_code", "retrieve": "retrieve", "fallback": "fallback"},
    )
    graph.add_edge("lookup_code", "retrieve")
    graph.add_edge("retrieve", "grade")
    graph.add_conditional_edges(
        "grade", route_after_grade, {"generate": "generate", "rewrite": "rewrite", "fallback": "fallback"}
    )
    graph.add_edge("rewrite", "retrieve")
    graph.add_edge("generate", "format_citations")
    graph.add_edge("format_citations", "apply_policy")
    graph.add_edge("fallback", "apply_policy")
    graph.add_edge("apply_policy", END)
    return graph.compile()


def make_llm():
    from langchain_ollama import ChatOllama

    return ChatOllama(
        model=config.CHAT_MODEL,
        base_url=config.OLLAMA_BASE_URL,
        temperature=0,
        num_ctx=config.NUM_CTX,
        keep_alive=config.KEEP_ALIVE,
    )


def build_default_app(store=None, code_db: ErrorCodeDB | None = None):
    from src.ingest import get_store
    from src.retriever import retrieve

    store = store or get_store()
    return build_graph(
        make_llm(),
        lambda query, device: retrieve(query, store, device),
        code_db or ErrorCodeDB(),
    )


def ask(app, question: str, device_model: str | None = None) -> dict:
    started = time.perf_counter()
    state = app.invoke({"question": question, "device_model": device_model or config.ALL_DEVICES})
    state["elapsed"] = time.perf_counter() - started
    return state
