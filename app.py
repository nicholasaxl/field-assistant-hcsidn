"""Streamlit UI: troubleshooting chat with citations, plus document upload and management."""
import streamlit as st

import config
from src.error_lookup import ErrorCodeDB
from src.graph import ask, build_default_app
from src.ingest import delete_document, get_store, ingest_file, list_documents
from src.loader import SUPPORTED_EXTENSIONS, InvalidUpload, validate_upload

st.set_page_config(page_title="Field Support Assistant", page_icon=None, layout="wide")

OLLAMA_HINT = (
    "Could not reach the local model. Make sure Ollama is running and the models are pulled: "
    f"`ollama pull {config.CHAT_MODEL}` and `ollama pull {config.EMBED_MODEL}`."
)


@st.cache_resource
def get_resources():
    store = get_store()
    code_db = ErrorCodeDB()
    return store, code_db, build_default_app(store, code_db)


store, code_db, app = get_resources()
config.MANUALS_DIR.mkdir(parents=True, exist_ok=True)

try:
    indexed = list_documents(store)
except Exception as exc:
    indexed = []
    st.sidebar.warning(f"Could not read the document index: {exc}")

known_models = sorted((set(code_db.devices()) | {d["device_model"] for d in indexed}) - {config.ALL_DEVICES})

with st.sidebar:
    st.header("Device")
    device = st.selectbox("Device model", [config.ALL_DEVICES] + known_models)

    st.header("Documents")
    tag = st.selectbox("Tag uploads as", [config.ALL_DEVICES] + known_models)
    new_tag = st.text_input("...or a new device model")
    uploads = st.file_uploader(
        f"Upload manuals (max {config.MAX_UPLOAD_MB} MB each)",
        type=[ext.lstrip(".") for ext in SUPPORTED_EXTENSIONS],
        accept_multiple_files=True,
    )
    if st.button("Index uploaded files", disabled=not uploads):
        upload_tag = new_tag.strip() or tag
        for upload in uploads:
            try:
                safe_name = validate_upload(upload.name, upload.size)
                target = config.MANUALS_DIR / safe_name
                target.write_bytes(upload.getbuffer())
                with st.spinner(f"Indexing {safe_name}..."):
                    result = ingest_file(target, store, upload_tag)
                st.success(f"{result.source}: {result.status} ({result.chunks} chunks)")
            except InvalidUpload as exc:
                st.error(str(exc))
            except Exception as exc:
                st.error(f"{upload.name}: {exc}")
                if "connect" in str(exc).lower():
                    st.info(OLLAMA_HINT)

    st.subheader("Indexed documents")
    if indexed:
        st.dataframe(indexed, hide_index=True, use_container_width=True)
        to_delete = st.selectbox("Remove a document", [""] + [d["source"] for d in indexed])
        if st.button("Remove", disabled=not to_delete):
            removed = delete_document(to_delete, store)
            (config.MANUALS_DIR / to_delete).unlink(missing_ok=True)
            st.success(f"Removed {to_delete} ({removed} chunks). Refresh to update the table.")
    else:
        st.caption("No documents indexed yet. Upload files above or run `python -m src.ingest`.")

st.title("Field Support Assistant")
st.caption("Answers come only from the indexed manuals, runbooks and error-code table. Everything runs locally.")

if "history" not in st.session_state:
    st.session_state.history = []


def render(entry: dict) -> None:
    st.markdown(entry["answer"])
    if entry.get("elapsed") is not None:
        st.caption(f"{entry['elapsed']:.1f}s - {entry.get('intent', '')}")
    if entry.get("sources"):
        with st.expander("Retrieved context"):
            for i, source in enumerate(entry["sources"], start=1):
                st.markdown(f"**[{i}] {source['label']}**")
                st.text(source["text"][:800])
    if entry.get("trace"):
        with st.expander("Agent steps"):
            st.write(entry["trace"])


for turn in st.session_state.history:
    with st.chat_message("user"):
        st.markdown(turn["question"])
    with st.chat_message("assistant"):
        render(turn)

question = st.chat_input("Describe the problem or enter an error code (e.g. P-1002)")
if question:
    with st.chat_message("user"):
        st.markdown(question)
    with st.chat_message("assistant"):
        with st.spinner("Searching the documents..."):
            try:
                state = ask(app, question, device)
                entry = {
                    "question": question,
                    "answer": state["answer"],
                    "sources": state.get("sources", []),
                    "trace": state.get("trace", []),
                    "intent": state.get("intent", ""),
                    "elapsed": state["elapsed"],
                }
            except Exception as exc:
                entry = {"question": question, "answer": f"Something went wrong: {exc}\n\n{OLLAMA_HINT}"}
        render(entry)
    st.session_state.history.append(entry)
