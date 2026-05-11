"""Session package — Sprint 1 binding/lease/identity layer.

Verb contract: verb functions accept a ``session: Session`` argument; the
pipeline ``main()`` resolves the current session via
:func:`astrid.core.session.binding.resolve_current_session` and passes it in.
Tests use the ``attached_session`` fixture (see ``tests/conftest.py``).
"""
