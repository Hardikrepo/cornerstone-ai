"""Generates synthetic construction-industry sample PDFs for local testing.

Produces three documents in this directory: an invoice, a building permit,
and a change order — the document types the classify/summarize Lambdas are
prompted to recognize. Pure-Python dependency (reportlab has no compiled
extensions), so it installs cleanly everywhere including this machine's
locked-down pip environment.

Usage:
    pip install reportlab
    python generate_samples.py
"""
import os

from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

OUTPUT_DIR = os.path.dirname(os.path.abspath(__file__))


def _write_pdf(filename: str, lines: list[str]) -> None:
    path = os.path.join(OUTPUT_DIR, filename)
    c = canvas.Canvas(path, pagesize=letter)
    width, height = letter
    y = height - 72
    for line in lines:
        c.drawString(72, y, line)
        y -= 18
        if y < 72:
            c.showPage()
            y = height - 72
    c.save()
    print(f"wrote {path}")


INVOICE_LINES = [
    "GRANITE PEAK CONSTRUCTION SUPPLY",
    "1420 Quarry Road, Suite 200, Denver, CO 80202",
    "",
    "INVOICE",
    "Invoice #: INV-48213",
    "Date: 2026-06-14",
    "Due Date: 2026-07-14",
    "",
    "Bill To: Summit Ridge Builders LLC",
    "Project: Summit Ridge Apartments - Phase 2",
    "",
    "Description                    Qty     Unit Price     Total",
    "Ready-mix concrete, 4000 PSI    80 yd3    $145.00      $11,600.00",
    "Rebar, #4 grade 60             12,000 lb    $0.85       $10,200.00",
    "Delivery and pumping fee          1        $1,200.00    $1,200.00",
    "",
    "Subtotal:                                              $23,000.00",
    "Tax (7.5%):                                             $1,725.00",
    "TOTAL DUE:                                             $24,725.00",
    "",
    "Payment Terms: Net 30",
    "Remit to: Granite Peak Construction Supply, Acct #00293841",
]

PERMIT_LINES = [
    "CITY OF DENVER - DEPARTMENT OF BUILDING SAFETY",
    "BUILDING PERMIT",
    "",
    "Permit Number: BP-2026-119874",
    "Issue Date: 2026-05-02",
    "Expiration Date: 2027-05-02",
    "",
    "Project Address: 4410 Summit Ridge Way, Denver, CO 80238",
    "Project Name: Summit Ridge Apartments - Phase 2",
    "Owner: Summit Ridge Builders LLC",
    "Contractor: Apex Structural Contracting, License #CO-GC-88213",
    "",
    "Work Description: New construction - 3-story, 48-unit multifamily",
    "residential building, Type V-A construction, sprinklered.",
    "",
    "Permit Fee: $18,420.00",
    "Fee Status: PAID",
    "",
    "Inspections Required: Foundation, Framing, Electrical Rough-In,",
    "Plumbing Rough-In, Insulation, Final",
    "",
    "This permit is valid only in accordance with the approved plans on",
    "file with the Department of Building Safety.",
]

CHANGE_ORDER_LINES = [
    "CHANGE ORDER",
    "Summit Ridge Apartments - Phase 2",
    "",
    "Change Order #: CO-007",
    "Date: 2026-07-01",
    "Original Contract Sum: $8,240,000.00",
    "",
    "Contractor: Apex Structural Contracting",
    "Owner: Summit Ridge Builders LLC",
    "",
    "Description of Change:",
    "Substitute specified exterior cladding (fiber cement panel) with",
    "upgraded metal composite panel system per owner request, Buildings",
    "A and B only. Includes revised structural attachment detailing and",
    "updated fire rating documentation.",
    "",
    "Cost Impact: +$186,400.00",
    "Schedule Impact: +9 calendar days",
    "",
    "New Contract Sum: $8,426,400.00",
    "New Substantial Completion Date: 2027-03-22",
    "",
    "Approved by Owner: ______________________  Date: __________",
    "Approved by Contractor: __________________  Date: __________",
]


if __name__ == "__main__":
    _write_pdf("invoice_sample.pdf", INVOICE_LINES)
    _write_pdf("permit_sample.pdf", PERMIT_LINES)
    _write_pdf("change_order_sample.pdf", CHANGE_ORDER_LINES)
