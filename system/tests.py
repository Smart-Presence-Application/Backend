from unittest import mock

import requests
from django.core.cache import cache
from django.test import TestCase
from rest_framework.test import APIClient

from . import services

SERVICES = "/api/system/services/"


class ServicesStatusTests(TestCase):
    def setUp(self):
        cache.clear()
        self.client = APIClient()

    def tearDown(self):
        cache.clear()

    def fetch(self):
        response = self.client.get(SERVICES)
        self.assertEqual(response.status_code, 200)
        return response.json()["data"]

    def ai_health(self, body):
        response = mock.Mock(status_code=200)
        response.json.return_value = body
        response.raise_for_status.return_value = None
        return mock.patch("system.views.requests.get", return_value=response)

    def test_all_services_up(self):
        with self.ai_health({"status": "running", "model_loaded": True, "database": "ok"}):
            data = self.fetch()

        checks = data["services"]
        self.assertTrue(all(checks[name]["ok"] for name in ("backend", "postgres", "ai_service", "mongodb")))
        self.assertTrue(checks["ai_service"]["model_loaded"])
        self.assertEqual(data["maintenance"], {"enabled": False, "message": "", "updated_at": None})

    def test_mongodb_down_is_reported_by_the_ai_service(self):
        with self.ai_health({"status": "running", "model_loaded": True, "database": "down"}):
            checks = self.fetch()["services"]

        self.assertTrue(checks["ai_service"]["ok"])
        self.assertFalse(checks["mongodb"]["ok"])

    def test_ai_service_unreachable_leaves_mongodb_unknown(self):
        with mock.patch("system.views.requests.get", side_effect=requests.ConnectionError):
            checks = self.fetch()["services"]

        self.assertFalse(checks["ai_service"]["ok"])
        self.assertIsNone(checks["mongodb"]["ok"])

    def test_maintenance_details_shown_and_cache_cleared_on_switch(self):
        with self.ai_health({"database": "ok"}):
            self.assertFalse(self.fetch()["maintenance"]["enabled"])
            services.set_maintenance(actor=None, is_enabled=True, message="Upgrading the database.")
            maintenance = self.fetch()["maintenance"]

        self.assertTrue(maintenance["enabled"])
        self.assertEqual(maintenance["message"], "Upgrading the database.")
        self.assertIsNotNone(maintenance["updated_at"])

    def test_reachable_during_maintenance(self):
        services.set_maintenance(actor=None, is_enabled=True)

        with self.ai_health({"database": "ok"}):
            self.assertEqual(self.client.get(SERVICES).status_code, 200)
