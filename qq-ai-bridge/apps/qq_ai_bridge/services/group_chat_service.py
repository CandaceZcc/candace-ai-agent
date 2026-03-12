"""Group chat orchestration helpers."""

from apps.qq_ai_bridge.config.settings import GROUP_CONFIG_PATH
from storage_utils import load_group_config as load_group_config_from_file


def load_group_config(group_id) -> dict:
    """Load merged group config for a specific QQ group."""
    return load_group_config_from_file(GROUP_CONFIG_PATH, group_id)


def should_log_group(group_id) -> bool:
    """Return whether logs should be printed for a group."""
    cfg = load_group_config(group_id)
    return not cfg.get("ignore", False) and not cfg.get("mute_log", False)
