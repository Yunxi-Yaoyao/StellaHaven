"""Renewals carry only a capability and epoch, never arbitrary project data."""
from fastapi import HTTPException
from app.routers.web_project_limits import ProjectStateRoute

RENEW_WIRE_BYTES = 1024


class ProjectRuntimeRoute(ProjectStateRoute):
    def get_route_handler(self):
        handler = super().get_route_handler()
        if 'POST' not in self.methods or not self.path.endswith('/{root_id}/renew'):
            return handler

        async def bounded(request):
            chunks = bytearray()
            async for chunk in request.stream():
                if len(chunks) + len(chunk) > RENEW_WIRE_BYTES:
                    raise HTTPException(413, '网页续期请求过大')
                chunks.extend(chunk)
            request._body = bytes(chunks)
            return await handler(request)

        return bounded
