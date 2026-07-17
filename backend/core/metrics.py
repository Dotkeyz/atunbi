"""
Shared token tracking — module-level counters used by both memory_service and memory_repo.
Living here avoids circular imports between those two modules.
"""

# user_id → total tokens if we stuffed everything into context
token_naive_total: dict[int, int] = {}

# user_id → total tokens actually used by Atunbi (after retrieval + compression)
token_actual_total: dict[int, int] = {}
