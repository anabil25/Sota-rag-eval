from __future__ import annotations

import asyncio
import logging
import os

import requests
from azure.identity import DefaultAzureCredential
from fastapi import FastAPI, HTTPException, Request, Response

from retrieve.backoff import BackoffPolicy, async_call_with_backoff, is_retryable_http_response

app = FastAPI(title="Retrieve Azure OpenAI Managed Identity Proxy", version="0.1.0")
logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"))
log = logging.getLogger("retrieve.azure_openai_proxy")
logging.getLogger("azure.core.pipeline.policies.http_logging_policy").setLevel(logging.WARNING)

_credential = DefaultAzureCredential(exclude_interactive_browser_credential=True)
_TOKEN_SCOPE = os.environ.get(
    "AZURE_OPENAI_TOKEN_SCOPE",
    "https://cognitiveservices.azure.com/.default",
)
_HOP_BY_HOP_HEADERS = {
    "connection",
    "content-encoding",
    "content-length",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailer",
    "transfer-encoding",
    "upgrade",
}
_BACKOFF_POLICY = BackoffPolicy.from_env(
    "PROXY_BACKOFF",
    max_attempts=6,
    base_delay_seconds=10.0,
    max_delay_seconds=45.0,
)


def _target_endpoint() -> str:
    endpoint = (
        os.environ.get("AI_SERVICES_ENDPOINT")
        or os.environ.get("AZURE_OPENAI_TARGET_ENDPOINT")
        or ""
    ).strip()
    if not endpoint:
        raise HTTPException(status_code=500, detail="AI_SERVICES_ENDPOINT is not configured")
    return endpoint.rstrip("/")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.api_route(
    "/{path:path}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"],
)
async def proxy(path: str, request: Request) -> Response:
    target_url = f"{_target_endpoint()}/{path}"
    if request.url.query:
        target_url = f"{target_url}?{request.url.query}"

    body = await request.body()
    token = _credential.get_token(_TOKEN_SCOPE).token
    headers = {
        key: value
        for key, value in request.headers.items()
        if key.lower() not in _HOP_BY_HOP_HEADERS
        and key.lower() not in {"host", "authorization", "api-key"}
    }
    headers["Authorization"] = f"Bearer {token}"

    try:
        upstream = await async_call_with_backoff(
            lambda: asyncio.to_thread(
                requests.request,
                request.method,
                target_url,
                headers=headers,
                data=body,
                timeout=(10, int(os.environ.get("PROXY_TIMEOUT_SECONDS", "600"))),
            ),
            policy=_BACKOFF_POLICY,
            operation=f"Azure OpenAI proxy {path}",
            logger=log,
            retry_exceptions=(requests.RequestException,),
            should_retry_result=is_retryable_http_response,
        )
    except requests.RequestException as exc:
        log.warning("Azure OpenAI proxy request failed for %s: %s", path, exc)
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    response_headers = {
        key: value
        for key, value in upstream.headers.items()
        if key.lower() not in _HOP_BY_HOP_HEADERS
    }
    return Response(
        content=upstream.content,
        status_code=upstream.status_code,
        headers=response_headers,
        media_type=upstream.headers.get("content-type"),
    )