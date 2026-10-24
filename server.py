#!/usr/bin/env python3
"""Relay launcher. Backend composition and services live in the relay package."""
from pathlib import Path

from relay.application import Application

application = Application(Path(__file__).resolve().parent)


def main():
    application.main()


if __name__ == '__main__':
    main()
