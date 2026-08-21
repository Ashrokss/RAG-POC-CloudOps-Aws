"""
The /health vectorstore handle is built lazily inside the request rather
than at import/startup time, so `uvicorn api.main:app` doesn't have to reach
Chroma (or the embedding function it needs, Bedrock in live mode) before the
process can bind a port - a health probe should be able to report the
server as up even on a request where that dependency call fails.
"""

from __future__ import annotations

from fastapi import FastAPI
from pydantic import BaseModel

from config.settings import get_settings
from rag.chain.rag_chain import answer_question
from rag.embeddings.factory import get_embeddings
from rag.models import RAGAnswer
from rag.vectorstore.chroma_store import get_collection_stats, get_vectorstore

app = FastAPI()


class QueryRequest(BaseModel):
    question: str
    strategy: str = "hybrid"
    k: int = 5


@app.get("/health")
def health() -> dict[str, object]:
    settings = get_settings()
    vectorstore = get_vectorstore(get_embeddings())
    stats = get_collection_stats(vectorstore)
    return {
        "status": "ok",
        "mode": "mock" if settings.mock_mode else "live",
        "collection_count": stats["count"],
    }


@app.post("/query", response_model=RAGAnswer)
def query(request: QueryRequest) -> RAGAnswer:
    return answer_question(request.question, strategy=request.strategy, k=request.k)
