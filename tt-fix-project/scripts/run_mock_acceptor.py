"""
Run the mock TT FIX acceptor standalone. No credentials, no external
services required - this is the whole point (see PROJECT.md section 9,
replicability).

Usage:
    python scripts/run_mock_acceptor.py
"""
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import quickfix as fix

from mock_acceptor import MockAcceptorApplication


def main() -> None:
    config_path = os.path.join(os.path.dirname(__file__), "..", "src", "mock_acceptor.cfg")
    settings = fix.SessionSettings(config_path)
    application = MockAcceptorApplication()
    store_factory = fix.FileStoreFactory(settings)
    log_factory = fix.FileLogFactory(settings)
    acceptor = fix.SocketAcceptor(application, store_factory, settings, log_factory)

    acceptor.start()
    print("[mock] acceptor running - Ctrl+C to stop")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        acceptor.stop()


if __name__ == "__main__":
    main()
