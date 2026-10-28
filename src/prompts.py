"""Prompt templates. Kept short and strict because the default model is small."""

GRADE = """You are checking search results for a field-service assistant.

Question: {question}

Passages:
{passages}

List the passages that are related to the question: same device, component, symptom, or procedure. Be lenient: include a passage if it is even partly useful.
The question may not name a device; that is fine. Only exclude passages that are about something completely different.
Reply with only the passage numbers separated by commas (for example: 1,3)."""

REWRITE = """Rewrite this support question as a short keyword search query for a technical manual.
Keep device names and error codes. Reply with only the query.

Question: {question}"""

ANSWER = """You are a support assistant for field engineers servicing POS terminals, ATMs and kiosks.
Answer the question using ONLY the numbered context below. Be concise and give steps as a numbered list.
Stay close to the wording of the context. Do not add citation numbers; they are added automatically.
If the context does not contain the answer, say you could not find it in the documents.

Context:
{context}

Question: {question}

Answer:"""

FALLBACK = (
    "I couldn't find this in the indexed documents. Try rephrasing with the device model or error code, "
    "check that the relevant manual has been uploaded, or escalate to level 2 support."
)
