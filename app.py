"""Cloud hosting entrypoint alias for Render / Railway / Heroku."""
import asyncio
import sys
from main import main

if __name__ == "__main__":
    try:
        exit_code = asyncio.run(main())
        sys.exit(exit_code or 0)
    except (KeyboardInterrupt, SystemExit):
        sys.exit(0)
