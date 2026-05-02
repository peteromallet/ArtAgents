#!/usr/bin/env python3
import sys


REMOVED_PUBLIC_COMMANDS = {"conductors", "performers", "instruments", "primitives"}


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] in REMOVED_PUBLIC_COMMANDS:
        print(f"unknown ArtAgents command: {sys.argv[1]}", file=sys.stderr)
        print("public commands: orchestrators, executors, elements, doctor, setup", file=sys.stderr)
        raise SystemExit(2)
    if len(sys.argv) > 1 and sys.argv[1] == "reigh-data":
        from artagents.executors.reigh_data.run import main

        raise SystemExit(main(sys.argv[2:]))
    if len(sys.argv) > 1 and sys.argv[1] == "executors":
        from artagents.executors.cli import main

        raise SystemExit(main(sys.argv[2:]))
    if len(sys.argv) > 1 and sys.argv[1] == "orchestrators":
        from artagents.orchestrators.cli import main

        raise SystemExit(main(sys.argv[2:]))
    if len(sys.argv) > 1 and sys.argv[1] == "elements":
        from artagents.elements.cli import main

        raise SystemExit(main(sys.argv[2:]))
    if len(sys.argv) > 1 and sys.argv[1] == "doctor":
        from artagents.doctor import main

        raise SystemExit(main(sys.argv[2:]))
    if len(sys.argv) > 1 and sys.argv[1] == "setup":
        from artagents.setup_cli import main

        raise SystemExit(main(sys.argv[2:]))

    from artagents.pipeline import main

    raise SystemExit(main())
