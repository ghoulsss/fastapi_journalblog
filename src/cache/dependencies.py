from fastapi import Request, Response

from src.cache.service import ResponseCache


def get_response_cache(request: Request) -> ResponseCache:
    return request.app.state.cache


def cache_headers(response: Response, status: str) -> None:
    response.headers["X-Cache"] = status
    # Redis invalidation cannot invalidate an intermediary/browser's copy.
    response.headers["Cache-Control"] = "no-store"
