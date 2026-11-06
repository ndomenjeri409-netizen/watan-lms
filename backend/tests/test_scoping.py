from types import SimpleNamespace
from unittest import TestCase

from common.scoping import ScopedViewSetMixin


class Queryset:
    def for_user(self, user):
        return ("scoped", user)


class BaseView:
    def get_queryset(self):
        return Queryset()


class ScopedViewSetTests(TestCase):
    def test_mixin_scopes_queryset_to_request_user(self):
        user = object()
        view = type("View", (ScopedViewSetMixin, BaseView), {})()
        view.request = SimpleNamespace(user=user, query_params={})
        self.assertEqual(view.get_queryset(), ("scoped", user))
