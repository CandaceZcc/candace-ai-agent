"""Probe configured agent-provider capabilities without executing returned actions."""

import argparse
import json
import sys

from apps.qq_ai_bridge.config.settings import AGENT_PROVIDER
from shared.ai.capability_probe import ProbeName, run_probe


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--provider",
        choices=("openai", "responses_proxy", "chat_compatible"),
        default=AGENT_PROVIDER,
    )
    probe_group = parser.add_mutually_exclusive_group(required=True)
    probe_group.add_argument("--text", action="store_true", help="Probe minimal Responses text")
    probe_group.add_argument(
        "--web-search",
        action="store_true",
        help="Probe hosted web search; may incur provider charges",
    )
    probe_group.add_argument(
        "--computer",
        action="store_true",
        help="Probe hosted computer call shape without executing actions",
    )
    parser.add_argument(
        "--accept-billable-probe",
        action="store_true",
        help="Required for hosted-tool probes that may bill the configured provider",
    )
    args = parser.parse_args(argv)

    probe: ProbeName = "text"
    if args.web_search:
        probe = "web_search"
    elif args.computer:
        probe = "computer"

    result = run_probe(
        provider=args.provider,
        probe=probe,
        accept_billable_probe=args.accept_billable_probe,
    )
    print(
        json.dumps(
            {
                "provider": result.provider,
                "probe": result.probe,
                "supported": result.supported,
                "exit_code": result.exit_code,
                "message": result.message,
                "capabilities": result.capabilities.__dict__,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return result.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
