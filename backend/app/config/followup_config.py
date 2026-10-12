"""Follow-up default delays (centralized configuration)."""
import os

FOLLOW_UP_1_DELAY_DAYS = int(os.getenv("FOLLOW_UP_1_DELAY_DAYS", 3))
FOLLOW_UP_2_DELAY_DAYS = int(os.getenv("FOLLOW_UP_2_DELAY_DAYS", 7))

def get_follow_up_delays() -> tuple[int, int]:
    return FOLLOW_UP_1_DELAY_DAYS, FOLLOW_UP_2_DELAY_DAYS
