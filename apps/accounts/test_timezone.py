from django.http import HttpResponse
from django.test import RequestFactory, SimpleTestCase
from django.utils import timezone

from .timezone import ClientTimezoneMiddleware, TIMEZONE_COOKIE


class ClientTimezoneMiddlewareTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()

    def test_browser_timezone_is_active_inside_request(self):
        request = self.factory.get("/")
        request.COOKIES[TIMEZONE_COOKIE] = "Europe/Vilnius"
        middleware = ClientTimezoneMiddleware(
            lambda _request: HttpResponse(timezone.get_current_timezone_name())
        )

        response = middleware(request)

        self.assertEqual(response.content.decode("utf-8"), "Europe/Vilnius")
        self.assertEqual(timezone.get_current_timezone_name(), "UTC")

    def test_invalid_timezone_falls_back_to_project_default(self):
        request = self.factory.get("/")
        request.COOKIES[TIMEZONE_COOKIE] = "Definitely/Not-A-Timezone"
        middleware = ClientTimezoneMiddleware(
            lambda _request: HttpResponse(timezone.get_current_timezone_name())
        )

        response = middleware(request)

        self.assertEqual(response.content.decode("utf-8"), "UTC")
