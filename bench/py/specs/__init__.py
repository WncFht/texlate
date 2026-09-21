"""bench/py/specs — Spec v2 spec files (§4), the unit a `bench run` executes.

Each module defines a module-level ``spec`` object built from
kernel.spec's Spec/Stage/Param. ``bench spec list`` scans this directory;
``bench run NAME`` resolves ``specs/NAME[.py]`` when the argument is not a
literal file path.

- smoke.py     — the free-stage validation spec (no lake, no paid gate)
- paid_stub.py — the paid-path spec with an injectable gateway factory
"""
