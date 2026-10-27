"""LangGraph agent. Routing is plain Python; the LLM only grades, rewrites and writes the answer.

classify -> (error_code) lookup_code -> retrieve -> grade -> generate -> format_citations
                                            ^          |
                                            |       (weak, retries left)
                                         rewrite <-----+      (still weak) -> fallback
"""
from __future__ import annotations

import re
import time
from typing import Any, Callable, TypedDict

from langgraph.graph import END, START, StateGraph

import config
from src import prompts
from src.citations import attribute
from src.error_lookup import ErrorCodeDB


class AgentState(TypedDict, total=False):
    question: str
    device_model: str
    intent: str  # error_code | troubleshooting | out_of_scope
    query: str
    docs: list
    code_records: list
    answer: str
    sources: list
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
        passages = "\n\n".join(f"[{i}] {d.page_content[:600]}" for i, d in enumerate(docs, start=1))
        reply = _text(llm.invoke(prompts.GRADE.format(question=state["question"], passages=passages)))
        numbers = {int(n) for n in re.findall(r"\d+", reply)}
        if numbers:
            # Retrieval already ranks the best match first and a small model often vetoes it wrongly,
            # so the grader may only prune lower-ranked chunks. Rejecting everything needs an explicit NONE.
            numbers.add(1)
            kept = [d for i, d in enumerate(docs, start=1) if i in numbers]
        elif "none" in reply.lower():
            kept = []
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
            }
            for r in state["code_records"]
        ] + [{"label": _doc_label(d), "text": d.page_content} for d in state["docs"]]
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
            "trace": state["trace"] + [f"citations: {matched} step(s) matched, {unmatched} unmatched"],
        }

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
    graph.add_edge("format_citations", END)
    graph.add_edge("fallback", END)
    return graph.compile()


def make_llm():
    from langchain_ollama import ChatOllama

    return ChatOllama(
        model=config.CHAT_MODEL,
        base_url=config.OLLAMA_BASE_URL,
        temperature=0,
        num_ctx=config.NUM_CTX,
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
