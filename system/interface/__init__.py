"""
system/interface package — User interface layer

Per HAND_ARCHITECTURE_V2:
- Handles user-facing output
- Notifications (M10)
- Display formatting
- Control panels

Per AUTHORITY_MODEL:
- Output only — no control authority
- Advisory only — no decision influence
"""

from system.interface.notification_manager import (
    notify,
    queue_notification,
    get_notifications,
    clear_notifications,
    set_filter_level,
    NotificationManager
)

__all__ = [
    "notify",
    "queue_notification",
    "get_notifications",
    "clear_notifications",
    "set_filter_level",
    "NotificationManager"
]
