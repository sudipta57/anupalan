"""Authentication — phone OTP and JWT issue/refresh.

Endpoints (docs/02-trd.md §5):

    POST /v1/auth/otp/request   {phone}              -> {request_id}
    POST /v1/auth/otp/verify    {request_id, code}   -> {access, refresh, user, org}

Implements **TRD SR-xx** (security requirements) and the auth half of
docs/01-architecture.md §10: phone OTP plus JWT access/refresh, org-scoped RBAC over the roles
``admin | inspector | analyst | viewer``, and per-org and per-IP rate limiting.

Not implemented yet — P2.2.
"""
