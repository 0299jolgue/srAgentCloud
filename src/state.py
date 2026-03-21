import threading
import queue

# ─── SSE Broadcaster ─────────────────────────────────────────────────────────

class Broadcaster:
    def __init__(self):
        self.queues = []
        self.lock = threading.Lock()
        self.buffer = []

    def push(self, msg):
        with self.lock:
            self.buffer.append(msg)
            if len(self.buffer) > 20: self.buffer.pop(0)
            for q in self.queues:
                q.put(msg)

    def subscribe(self):
        q = queue.Queue()
        with self.lock:
            for msg in self.buffer:
                q.put(msg)
            self.queues.append(q)
        return q

    def unsubscribe(self, q):
        with self.lock:
            if q in self.queues:
                self.queues.remove(q)

    def clear_buffer(self):
        with self.lock:
            self.buffer = []

# ─── Per-thread runtime state ─────────────────────────────────────────────────

_thread_state: dict = {}
_state_lock = threading.Lock()

# ─── Global process tracking ──────────────────────────────────────────────────

_running_processes: dict[int, dict] = {}
_proc_lock = threading.Lock()

def get_state(thread_id: int) -> dict:
    with _state_lock:
        if thread_id not in _thread_state:
            _thread_state[thread_id] = {
                "broadcaster":  Broadcaster(),
                "tool_event":   threading.Event(),
                "tool_decision": None,
                "pending_tool": None,
                "stop_requested": False,
                "agent_running": False,
            }
        return _thread_state[thread_id]
