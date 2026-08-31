"""Upload validation — an uploaded file is untrusted input.

The parsers (PyMuPDF, python-docx) are the most exposed code in the ingestion path, so
what reaches them is constrained first. The extension is attacker-chosen and proves
nothing; these tests pin the content check that backs it up.
"""

import pytest

from backend.routers.documents import ALLOWED_UPLOAD_EXTENSIONS, _content_matches_extension

PDF_HEADER = b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n"
DOCX_HEADER = b"PK\x03\x04\x14\x00\x06\x00"


def test_a_real_pdf_is_accepted():
    assert _content_matches_extension(".pdf", PDF_HEADER) is True


def test_a_real_docx_is_accepted():
    assert _content_matches_extension(".docx", DOCX_HEADER) is True


@pytest.mark.parametrize(
    "payload",
    [
        b"<!DOCTYPE html><script>alert(1)</script>",
        b"#!/bin/sh\nrm -rf /",
        b"MZ\x90\x00",
        b"",
    ],
    ids=["html", "shell-script", "executable", "empty"],
)
def test_content_renamed_to_pdf_is_rejected(payload):
    """The whole point: a hostile file renamed to .pdf must not reach the parser."""
    assert _content_matches_extension(".pdf", payload) is False


def test_a_pdf_renamed_to_docx_is_rejected():
    """Cross-format mismatch counts too — the docx parser would choke on PDF bytes."""
    assert _content_matches_extension(".docx", PDF_HEADER) is False


def test_an_extension_outside_the_allowlist_is_rejected():
    """Fails closed: an unlisted extension has no signature and cannot be admitted."""
    assert _content_matches_extension(".exe", b"MZ\x90\x00") is False
    assert ".exe" not in ALLOWED_UPLOAD_EXTENSIONS
