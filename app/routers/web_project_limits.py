"""Bound the runtime state wire representation before FastAPI JSON decoding."""
from fastapi import HTTPException
from fastapi.routing import APIRoute

# A 1MiB JSON.stringify payload can be serialized with up to six bytes per
# ASCII character (\\uXXXX). Extra space is only for fixed grant/version fields.
STATE_WIRE_BYTES = 6 * 1024 * 1024 + 4096


class ProjectStateRoute(APIRoute):
    def get_route_handler(self):
        handler = super().get_route_handler()
        if 'PUT' not in self.methods or not self.path.endswith('/{root_id}/state'):
            return handler

        async def bounded(request):
            chunks = bytearray()
            async for chunk in request.stream():
                if len(chunks) + len(chunk) > STATE_WIRE_BYTES:
                    raise HTTPException(413, '网页状态请求过大')
                chunks.extend(chunk)
            # Starlette's normal body cache is consumed by FastAPI immediately;
            # no parsing has happened yet, including for missing/false lengths.
            request._body = bytes(chunks)
            return await handler(request)

        return bounded
