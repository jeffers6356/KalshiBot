from fastapi import Request
from fastapi.responses import Response
from workers import WorkerEntrypoint, asgi

from app.main import app


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
        status=response.status,
        headers=dict(response.headers),
    )


class Default(WorkerEntrypoint):

    async def fetch(self, request):
        return await asgi.fetch(
            app,
            request,
            self.env,
        )

    async def scheduled(self, controller, env, ctx):
        if controller.cron != "*/5 * * * *":
            return

       from workers import fetch

        response = await fetch(
            "https://kalshibot.jeffers6356.workers.dev/api/collect",
            method="POST",
        )

        print(
            "KalshiBot Cron collection:",
            response.status,
        )
