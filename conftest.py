def pytest_configure(config):
    """Register the short feature showcase separately from regression checks."""
    config.addinivalue_line("markers", "demo: concise automated feature showcase")
