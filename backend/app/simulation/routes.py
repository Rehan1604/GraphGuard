import logging

from fastapi import APIRouter, HTTPException, Request, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field

from app.config import get_settings
from app.simulation.service import SimulationStateError

router = APIRouter()
log = logging.getLogger("graphguard.ws")


class StartRequest(BaseModel):
    events_per_second: float = Field(2.0, ge=0.1, le=20)
    seed: int = 42
    duplicate_rate: float = Field(0.05, ge=0, le=0.5)


def _sim(request: Request):
    return request.app.state.simulator


async def _run_control(action) -> None:
    try:
        await action
    except SimulationStateError as exc:
        raise HTTPException(409, str(exc))


@router.get("/api/simulation")
def simulation_state(request: Request) -> dict:
    return _sim(request).state()


@router.post("/api/simulation/start")
async def start(request: Request, body: StartRequest | None = None) -> dict:
    body = body or StartRequest()
    await _run_control(_sim(request).start(body.events_per_second, body.seed, body.duplicate_rate))
    return _sim(request).state()


@router.post("/api/simulation/pause")
async def pause(request: Request) -> dict:
    await _run_control(_sim(request).pause())
    return _sim(request).state()


@router.post("/api/simulation/resume")
async def resume(request: Request) -> dict:
    await _run_control(_sim(request).resume())
    return _sim(request).state()


@router.post("/api/simulation/reset")
async def reset(request: Request) -> dict:
    await _run_control(_sim(request).reset())
    return _sim(request).state()


@router.websocket("/ws/events")
async def events(ws: WebSocket, last_seq: int | None = None) -> None:
    # Browsers don't apply CORS to WebSockets, so we check the Origin ourselves.
    origin = ws.headers.get("origin")
    if origin is not None and origin not in get_settings().ws_allowed_origins:
        log.warning("websocket rejected: origin not allowed")
        await ws.close(code=1008)  # policy violation
        return
    hub = ws.app.state.hub
    await hub.connect(ws, last_seq)
    log.info("websocket connected")
    try:
        while True:
            await ws.receive_text()  # we ignore what clients say; this just notices disconnects
    except WebSocketDisconnect:
        pass
    finally:
        await hub.disconnect(ws)
        log.info("websocket disconnected")