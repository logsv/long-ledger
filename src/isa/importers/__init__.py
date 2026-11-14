"""Importers: turn broker JSON, CSV exports and extracted facts into rows.

Everything imported is untrusted data. Importers validate shape and types and
never execute or interpret text inside the data.
"""
