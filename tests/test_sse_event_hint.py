"""
ISSUE-074A — Backend SSE Event-Hint Endpoint Tests

Per ISSUE-074A scope:
- Backend SSE endpoint behavior only.
- Direct async generator testing (no TestClient streaming hang).
- Validates: endpoint response, hint-only payload, disconnect cleanup,
  Last-Event-ID reconnect, existing endpoint preservation.

Per ISSUE-074A non-goals:
- No WebSocket tests.
- No projection delivery tests.
- No polling removal tests.
"""

import json
import uuid
import pytest
from fastapi.testclient import TestClient
from fastapi.responses import StreamingResponse

# Resolve project root for imports
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from ai_lab_gui.backend.api import app, get_events_sse
from system.interface.event_bus import (
    get_event_bus,
    publish_event,
    get_events,
    get_latest_sequence,
    clear_workflow,
)


# =============================================================================
# Helpers
# =============================================================================


def _make_workflow_id() -> str:
    """Generate a unique test workflow ID."""
    return f"test-sse-{uuid.uuid4().hex[:12]}"


def _parse_sse_chunk(text: str) -> dict:
    """Parse a single SSE chunk string into {id, event, data}."""
    result = {"id": None, "event": None, "data": None}
    for line in text.strip().split("\n"):
        if line.startswith("id: "):
            result["id"] = line[4:]
        elif line.startswith("event: "):
            result["event"] = line[7:]
        elif line.startswith("data: "):
            result["data"] = json.loads(line[6:])
    return result


class MockRequest:
    """
    Minimal mocked FastAPI Request for direct async generator testing.
    Per ISSUE-074A: avoid TestClient streaming hang on infinite SSE loop.
    """

    def __init__(self, disconnected: bool = False, headers: dict = None):
        self._disconnected = disconnected
        self.headers = headers or {}

    async def is_disconnected(self) -> bool:
        return self._disconnected


# =============================================================================
# Test Class: SSE Endpoint Foundation (Direct Generator Testing)
# =============================================================================


class TestSSEEventHintEndpointDirect:
    """
    Per ISSUE-074A: Validate backend SSE endpoint logic via direct generator
    iteration. No TestClient streaming to avoid while-True hang.
    """

    # -------------------------------------------------------------------------
    # 1. Endpoint Response
    # -------------------------------------------------------------------------

    @pytest.mark.anyio
    async def test_sse_returns_streaming_response(self):
        """
        Validation 1: get_events_sse returns a StreamingResponse with
        text/event-stream media_type.
        """
        workflow_id = _make_workflow_id()
        clear_workflow(workflow_id)

        mock_request = MockRequest(disconnected=True)
        response = await get_events_sse(workflow_id, mock_request)

        assert isinstance(response, StreamingResponse)
        assert response.media_type == "text/event-stream"

    # -------------------------------------------------------------------------
    # 2. Event-Hint-Only Payload
    # -------------------------------------------------------------------------

    @pytest.mark.anyio
    async def test_sse_emits_event_hint(self):
        """
        Validation 2: body_iterator emits SSE-formatted event when an
        EventBus event is published.

        Per ISSUE-074A:
        - Payload contains event_type, bus_sequence_id, timestamp, workflow_id.
        - Payload does NOT contain projection snapshots or execution_result.
        """
        workflow_id = _make_workflow_id()
        clear_workflow(workflow_id)

        mock_request = MockRequest(disconnected=False)
        response = await get_events_sse(workflow_id, mock_request)

        # Publish after subscription is established
        publish_event(
            workflow_id,
            "step_started",
            {"step_id": "s1", "status": "running"},
        )

        chunk = await response.body_iterator.__anext__()
        await response.body_iterator.aclose()

        event = _parse_sse_chunk(chunk)
        assert event["event"] == "workflow_event"

        data = event["data"]
        assert data is not None
        assert data["event_type"] == "step_started"
        assert isinstance(data["bus_sequence_id"], int)
        assert isinstance(data["timestamp"], str)
        assert data["workflow_id"] == workflow_id
        assert event["id"] == str(data["bus_sequence_id"])

        # Projection / execution data MUST NOT be present
        assert "data" not in data
        assert "projection" not in data
        assert "execution_result" not in data
        assert "tool_call" not in data

    @pytest.mark.anyio
    async def test_sse_payload_excludes_execution_result(self):
        """
        Validation 2b: Raw event data containing execution_result must NOT
        leak into the SSE hint payload.
        """
        workflow_id = _make_workflow_id()
        clear_workflow(workflow_id)

        mock_request = MockRequest(disconnected=False)
        response = await get_events_sse(workflow_id, mock_request)

        publish_event(
            workflow_id,
            "step_completed",
            {
                "step_id": "s1",
                "execution_result": {"status": "success", "output": "secret"},
            },
        )

        chunk = await response.body_iterator.__anext__()
        await response.body_iterator.aclose()

        data = _parse_sse_chunk(chunk)["data"]
        assert data is not None
        assert "execution_result" not in data
        assert "output" not in data

    # -------------------------------------------------------------------------
    # 3. Disconnect Cleanup
    # -------------------------------------------------------------------------

    @pytest.mark.anyio
    async def test_sse_disconnect_removes_subscriber(self):
        """
        Validation 4: Disconnect causes generator exit and removes subscriber.
        Per ISSUE-074A: subscriber lifecycle leak is the highest risk.
        """
        workflow_id = _make_workflow_id()
        bus = get_event_bus()
        clear_workflow(workflow_id)

        before = len(bus._subscribers.get(workflow_id, []))

        mock_request = MockRequest(disconnected=True)
        response = await get_events_sse(workflow_id, mock_request)

        # Iterate — generator exits immediately due to disconnect, cleanup runs
        chunks = []
        async for chunk in response.body_iterator:
            chunks.append(chunk)

        after = len(bus._subscribers.get(workflow_id, []))
        assert after == before, (
            f"Subscriber leak: before={before}, after={after}"
        )

    # -------------------------------------------------------------------------
    # 4. Last-Event-ID / since_sequence Reconnect
    # -------------------------------------------------------------------------

    @pytest.mark.anyio
    async def test_sse_last_event_id_replay(self):
        """
        Validation 8: Last-Event-ID header causes missed events to be replayed.
        """
        workflow_id = _make_workflow_id()
        clear_workflow(workflow_id)

        publish_event(workflow_id, "event_one", {"n": 1})
        publish_event(workflow_id, "event_two", {"n": 2})

        headers = {"last-event-id": "1"}  # bus_sequence_id of first event
        mock_request = MockRequest(disconnected=False, headers=headers)
        response = await get_events_sse(workflow_id, mock_request)

        chunk = await response.body_iterator.__anext__()
        await response.body_iterator.aclose()

        event = _parse_sse_chunk(chunk)
        assert event["data"]["event_type"] == "event_two"

    @pytest.mark.anyio
    async def test_sse_last_event_id_no_missed_events(self):
        """
        Validation 8b: Last-Event-ID = latest sequence means no replay.
        """
        workflow_id = _make_workflow_id()
        clear_workflow(workflow_id)

        publish_event(workflow_id, "only_event", {"n": 1})
        latest_seq = get_latest_sequence(workflow_id)

        headers = {"last-event-id": str(latest_seq)}
        mock_request = MockRequest(disconnected=True, headers=headers)
        response = await get_events_sse(workflow_id, mock_request)

        # No missed events → generator exits immediately via disconnect
        chunks = []
        async for chunk in response.body_iterator:
            chunks.append(chunk)

        assert len(chunks) == 0

    @pytest.mark.anyio
    async def test_sse_last_event_id_invalid_ignored(self):
        """
        Validation 8c: Invalid Last-Event-ID is ignored without crash.
        """
        workflow_id = _make_workflow_id()
        clear_workflow(workflow_id)

        headers = {"last-event-id": "not-a-number"}
        mock_request = MockRequest(disconnected=True, headers=headers)
        response = await get_events_sse(workflow_id, mock_request)

        chunks = []
        async for chunk in response.body_iterator:
            chunks.append(chunk)

        assert len(chunks) == 0

    # -------------------------------------------------------------------------
    # 5. Existing Endpoint Preservation
    # -------------------------------------------------------------------------

    def test_existing_events_endpoint_unchanged(self):
        """
        Validation 5: Existing /events/{workflow_id} polling endpoint still works.
        """
        client = TestClient(app)
        workflow_id = _make_workflow_id()
        clear_workflow(workflow_id)

        publish_event(workflow_id, "step_started", {"step_id": "s1"})

        response = client.get(f"/events/{workflow_id}?since=-1&limit=100")
        assert response.status_code == 200

        data = response.json()
        assert data["workflow_id"] == workflow_id
        assert len(data["events"]) == 1
        assert data["events"][0]["event_type"] == "step_started"
        assert "latest_bus_sequence_id" in data

    def test_existing_projection_endpoint_unchanged(self):
        """
        Validation 6: Existing /projection/{workflow_id} still works.
        """
        client = TestClient(app)
        workflow_id = _make_workflow_id()

        response = client.get(f"/projection/{workflow_id}")
        assert response.status_code in (200, 404)

    # -------------------------------------------------------------------------
    # 6. Workflow Isolation
    # -------------------------------------------------------------------------

    @pytest.mark.anyio
    async def test_sse_workflow_isolation(self):
        """
        Validation: Events for workflow A do not leak to workflow B SSE.
        """
        wf_a = _make_workflow_id()
        wf_b = _make_workflow_id()
        clear_workflow(wf_a)
        clear_workflow(wf_b)

        mock_request_b = MockRequest(disconnected=False)
        response_b = await get_events_sse(wf_b, mock_request_b)

        publish_event(wf_a, "step_started", {"step_id": "s1"})
        publish_event(wf_b, "step_completed", {"step_id": "s2"})

        chunk = await response_b.body_iterator.__anext__()
        await response_b.body_iterator.aclose()

        event = _parse_sse_chunk(chunk)
        assert event["data"]["event_type"] == "step_completed"
        assert event["data"]["workflow_id"] == wf_b
