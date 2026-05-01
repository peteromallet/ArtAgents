#!/usr/bin/env python3
import sys


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "reigh-data":
        from artagents.reigh_data import main

        raise SystemExit(main(sys.argv[2:]))

    from artagents.pipeline import main

    raise SystemExit(main())
