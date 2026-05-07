"""WebDAV-based cloud sync for cc-switch-tool.

Public API is exposed via :mod:`.manager`. CLI/TUI callers should use
:func:`cc_switch_tool.sync.manager.SyncManager` rather than reaching into
the lower-level ``webdav``/``crypto``/``config`` modules.
"""
