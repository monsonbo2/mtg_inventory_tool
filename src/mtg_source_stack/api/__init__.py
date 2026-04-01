"""HTTP-facing package for the local-demo web backend.

The current API shell is intended for local/demo use and wraps the existing
synchronous inventory service layer. It provides a stable enough HTTP surface
for demo UI and contract work, but it is not yet the concurrency-hardened shape
for shared deployment.
"""
