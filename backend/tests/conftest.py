import os
import pytest

@pytest.fixture(scope="session", autouse=True)
def setup_test_environment():
    # Explicitly enable development/test sandbox flag for test runs
    os.environ["ALLOW_ETHEREAL_TEST"] = "true"
