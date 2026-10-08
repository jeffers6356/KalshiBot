from fastapi import Request
from fastapi.responses import Response
from workers import asgi

from app.main import app


# Remove the local filesystem-based "/" route.
# Cloudflare Workers Static Assets will serve the dashboard instead.
app.router.routes = [
    route
    for route in app.router.routes
    if getattr(route, "path", None) != "/"
]


@app.get("/{path:path}")
async def frontend(path: str, request: Request):
    env = request.scope["env"]

    asset_url = f"https://assets.local/{path}"

    response = await env.ASSETS.fetch(asset_url)

    body = await response.bytes()

    return Response(
        content=body,
        status_code=response.status,
        headers=dict(response.headers),
    )


Default = asgi.entrypoint(app)
