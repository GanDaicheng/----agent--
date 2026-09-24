"""Print the installed Deep Agents API surface used by this project."""

import inspect

import deepagents


def main() -> None:
    version = getattr(deepagents, "__version__", "unknown")
    print(f"deepagents={version}")
    print(f"create_deep_agent={inspect.signature(deepagents.create_deep_agent)}")


if __name__ == "__main__":
    main()
