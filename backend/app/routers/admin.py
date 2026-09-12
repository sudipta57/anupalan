"""Admin — rule pack publication and org administration.

Endpoint (docs/02-trd.md §5):

    POST /v1/admin/rulepacks   {yaml}  -> {code, version, checksum}

Implements the API half of **TRD FR-26 Rule pack loading**: a pack uploaded here is validated
against a JSON schema, checksummed and stored, and findings record the version used.

Accept: an invalid rule pack is rejected with a **line-level error** and the **previous pack
stays active**. Also **TRD NFR-06**: a rule pack change requires no code deploy.

Changing anything in ``rulepacks/`` needs review — rule text has legal consequences
(CLAUDE.md §7).

Not implemented yet — P2.4.
"""
