from backend.apps.orchestrator.core.orchestration_service import OrchestrationService
from backend.apps.orchestrator.core.session_store import SessionStore
from backend.apps.orchestrator.streaming.stream_manager import StreamManager

_sessions = SessionStore()
_streams = StreamManager()
_service = OrchestrationService(_sessions, _streams)


def get_orchestration_service() -> OrchestrationService:
    return _service
