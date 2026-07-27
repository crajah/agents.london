"""Redis Communication & Work Queue Bus for agent.london agents.

Provides inter-agent event channels, task queues, and session state pub/sub using Redis.
Includes clean fallback if Redis server is unavailable during testing.
"""
import json
import logging
import os
import time
from typing import Dict, Any, List, Optional

logger = logging.getLogger(__name__)

REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
REDIS_PASSWORD = os.getenv("REDIS_PASSWORD", None)

class RedisBus:
    def __init__(self):
        self.redis_client = None
        self._in_memory_queues: Dict[str, List[Dict[str, Any]]] = {}
        self._in_memory_events: Dict[str, List[Dict[str, Any]]] = {}
        self._init_redis()

    def _init_redis(self):
        import redis
        hosts_to_try = [
            REDIS_HOST,
            "redis-master",
            "redis-master.default.svc.cluster.local",
            "redis-service.default.svc.cluster.local",
            "redis-service",
            "localhost"
        ]
        
        # Deduplicate preserving order
        unique_hosts = []
        for h in hosts_to_try:
            if h and h not in unique_hosts:
                unique_hosts.append(h)

        for host in unique_hosts:
            # 1. Try with password if provided
            if REDIS_PASSWORD:
                try:
                    client = redis.Redis(host=host, port=REDIS_PORT, password=REDIS_PASSWORD, db=0, socket_timeout=2)
                    client.ping()
                    self.redis_client = client
                    logger.info(f"Connected to Redis at {host}:{REDIS_PORT} (Password Authenticated)")
                    return
                except Exception as e:
                    logger.debug(f"Authenticated connection to {host}:{REDIS_PORT} failed: {e}")

            # 2. Try unauthenticated connection (Local Redis dev instance)
            try:
                client = redis.Redis(host=host, port=REDIS_PORT, db=0, socket_timeout=2)
                client.ping()
                self.redis_client = client
                logger.info(f"Connected to Redis at {host}:{REDIS_PORT} (Local Unauthenticated)")
                return
            except Exception as e:
                logger.debug(f"Unauthenticated connection to {host}:{REDIS_PORT} failed: {e}")

        logger.warning(f"Redis unavailable across all host candidates ({unique_hosts}); utilizing in-memory fallback bus.")
        self.redis_client = None

    def publish_event(self, org_id: str, project_id: str, event_data: Dict[str, Any]):
        """Publish event to civilization stream."""
        event_payload = {
            **event_data,
            "timestamp": time.time(),
            "org_id": org_id,
            "project_id": project_id
        }
        channel = f"agent:events:{org_id}:{project_id}"
        
        if self.redis_client:
            try:
                self.redis_client.publish(channel, json.dumps(event_payload))
                self.redis_client.lpush(f"audit:{channel}", json.dumps(event_payload))
                self.redis_client.ltrim(f"audit:{channel}", 0, 100)
            except Exception as e:
                logger.error(f"Error publishing Redis event: {e}")
        
        if channel not in self._in_memory_events:
            self._in_memory_events[channel] = []
        self._in_memory_events[channel].append(event_payload)
        if len(self._in_memory_events[channel]) > 100:
            self._in_memory_events[channel].pop(0)

    def enqueue_task(self, agent_id: str, task_data: Dict[str, Any], project_id: Optional[str] = None) -> str:
        """Enqueue task into agent's dedicated Redis work queue scoped strictly to project_id."""
        proj = project_id or task_data.get("project_id", "proj_alpha_civilization")
        task_payload = {
            **task_data,
            "task_id": f"task-{int(time.time()*1000)}",
            "enqueued_at": time.time(),
            "project_id": proj,
            "status": "pending"
        }
        queue_key = f"agent:queue:{proj}:{agent_id}"

        if self.redis_client:
            try:
                self.redis_client.rpush(queue_key, json.dumps(task_payload))
            except Exception as e:
                logger.error(f"Error enqueueing task in Redis: {e}")

        if queue_key not in self._in_memory_queues:
            self._in_memory_queues[queue_key] = []
        self._in_memory_queues[queue_key].append(task_payload)
        return task_payload["task_id"]

    def dequeue_task(self, agent_id: str, project_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Dequeue next available task for an agent scoped strictly to project_id."""
        proj = project_id or "proj_alpha_civilization"
        queue_key = f"agent:queue:{proj}:{agent_id}"

        if self.redis_client:
            try:
                data = self.redis_client.lpop(queue_key)
                if data:
                    return json.loads(data)
            except Exception as e:
                logger.error(f"Error dequeueing task from Redis: {e}")

        if queue_key in self._in_memory_queues and self._in_memory_queues[queue_key]:
            return self._in_memory_queues[queue_key].pop(0)
        return None

    def get_recent_events(self, org_id: str, project_id: str, limit: int = 50) -> List[Dict[str, Any]]:
        channel = f"agent:events:{org_id}:{project_id}"

        if self.redis_client:
            try:
                raw_items = self.redis_client.lrange(f"audit:{channel}", 0, limit - 1)
                return [json.loads(item) for item in raw_items]
            except Exception:
                pass

        return self._in_memory_events.get(channel, [])[-limit:]

redis_bus = RedisBus()
