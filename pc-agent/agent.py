"""Compatibility entrypoint for pc-agent."""

import os

from apps.pc_agent.app import app
from apps.pc_agent.config.settings import PC_AGENT_PORT


if __name__ == "__main__":
    port = int(os.environ.get("PC_AGENT_PORT", PC_AGENT_PORT))
    app.run(host="0.0.0.0", port=port)
