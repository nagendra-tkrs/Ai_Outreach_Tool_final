import os
import pytest

# ---------------------------------------------------------------------------
# Priority 2 — live-database isolation for the whole test suite.
#
# app.config.database reads the module-level DB_NAME at call time inside
# connect_db()/get_db(), so patching it here — conftest.py is imported by
# pytest before any test module — routes EVERY service-level database access
# made by tests in this process (including connect_db() calls from test
# fixtures) to a dedicated, disposable test database. The production
# `ai_client_outreach` database is therefore never opened for writes by the
# test suite. This is a test-process-only patch: the running backend and all
# live data are unaffected.
#
# Tests that already bind their own isolated databases (test_quarantine_guard,
# test_scheduling_policy, test_primary_email_and_sync) swap the binding
# themselves and continue to work unchanged.
# ---------------------------------------------------------------------------
import app.config.database as _db_module

TEST_SUITE_DB_NAME = "ai_client_outreach_test_suite"
_db_module.DB_NAME = TEST_SUITE_DB_NAME


def _drop_test_suite_db():
    """Drop the test-only database (start of session and end of session) so
    fixture residue can never accumulate or leak between runs."""
    try:
        import pymongo
        cli = pymongo.MongoClient(
            "mongodb://127.0.0.1:27017", serverSelectionTimeoutMS=5000
        )
        cli.drop_database(TEST_SUITE_DB_NAME)
        cli.close()
    except Exception:
        pass  # If Mongo is unreachable, individual tests will surface it.


_drop_test_suite_db()  # clean slate before the first test of every session


@pytest.fixture(scope="session", autouse=True)
def _cleanup_test_suite_db():
    yield
    _drop_test_suite_db()  # leave no test artifacts behind


@pytest.fixture(scope="session", autouse=True)
def setup_test_environment():
    # Explicitly enable development/test sandbox flag for test runs
    os.environ["ALLOW_ETHEREAL_TEST"] = "true"
    # E9: bump send limits + open the sending window so the automated test
    # suite can never be mistaken for production delivery or trip the
    # daily/per-domain caps. Production defaults (50/day, 5/domain) are NOT
    # changed — only the test environment overrides them.
    os.environ.setdefault("DAILY_SEND_LIMIT", "100000")
    os.environ.setdefault("PER_DOMAIN_DAILY_LIMIT", "100000")
    os.environ.setdefault("SEND_WINDOW_START", "00:00")
    os.environ.setdefault("SEND_WINDOW_END", "23:59")
    os.environ.setdefault("APP_TZ_OFFSET_MINUTES", "0")
    # E8: do not enable strict recipient-domain matching during tests (default)
    os.environ.setdefault("ENFORCE_RECIPIENT_DOMAIN_MATCH", "false")