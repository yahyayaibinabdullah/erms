"""Stable, language-independent catalogues from Disposition sections 4 and 17."""
from enum import IntEnum, StrEnum


class DispositionStatus(IntEnum):
    not_ready = 1
    eligible_destruction = 2
    eligible_permanent_transfer = 3
    eligible_selective_transfer = 4
    eligible_local_archives = 5
    pending_destruction = 6
    pending_permanent_transfer = 7
    pending_selective_transfer = 8
    pending_local_archives = 9
    destroyed = 10
    permanently_transferred = 11
    retained_local_archives = 12
    partially_disposed_action_required = 13


class JobType(StrEnum):
    destruction = 'destruction'
    permanent_transfer = 'permanent_transfer'
    selective_transfer = 'selective_transfer'
    local_archives = 'local_archives'


class LifecycleState(StrEnum):
    active = 'active'
    completed = 'completed'
    terminated = 'terminated'
