from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import (
    AccountViewSet,
    AdjustmentViewSet,
    CashAccountViewSet,
    FeeStructureViewSet,
    InvoiceViewSet,
    JournalEntryViewSet,
    PaymentViewSet,
    ReceiptPdfView,
    RefundViewSet,
    StudentStatementView,
)

router = DefaultRouter()
router.register("accounts", AccountViewSet, basename="finance-account")
router.register("cash-accounts", CashAccountViewSet, basename="cash-account")
router.register("fee-structures", FeeStructureViewSet, basename="fee-structure")
router.register("invoices", InvoiceViewSet, basename="invoice")
router.register("payments", PaymentViewSet, basename="payment")
router.register("adjustments", AdjustmentViewSet, basename="adjustment")
router.register("refunds", RefundViewSet, basename="refund")
router.register("journal-entries", JournalEntryViewSet, basename="journal-entry")

urlpatterns = [
    path("", include(router.urls)),
    path(
        "receipts/<uuid:receipt_id>/pdf/",
        ReceiptPdfView.as_view(),
        name="receipt-pdf",
    ),
    path(
        "students/<uuid:student_id>/statement/",
        StudentStatementView.as_view(),
        name="student-statement",
    ),
]
