#!/usr/bin/env python3
"""
Quick test script for the Web Dashboard.

Tests:
- FastAPI app can be imported
- Templates directory exists
- Static files exist
- API endpoints are registered
"""
import sys
from pathlib import Path


def test_imports():
    """Test that all modules can be imported"""
    print("Testing imports...")
    try:
        from polymarket_mcp.web.app import app
        print("✅ FastAPI app imported successfully")
        return True
    except ImportError as e:
        print(f"❌ Import failed: {e}")
        return False

def test_directory_structure():
    """Test that directory structure is correct"""
    print("\nTesting directory structure...")

    base_dir = Path(__file__).parent / "src" / "polymarket_mcp" / "web"

    checks = [
        (base_dir / "templates", "Templates directory"),
        (base_dir / "static" / "css", "CSS directory"),
        (base_dir / "static" / "js", "JavaScript directory"),
        (base_dir / "templates" / "index.html", "Index template"),
        (base_dir / "templates" / "config.html", "Config template"),
        (base_dir / "templates" / "markets.html", "Markets template"),
        (base_dir / "templates" / "monitoring.html", "Monitoring template"),
        (base_dir / "static" / "css" / "style.css", "Stylesheet"),
        (base_dir / "static" / "js" / "app.js", "JavaScript file"),
    ]

    all_passed = True
    for path, name in checks:
        if path.exists():
            print(f"✅ {name}: {path}")
        else:
            print(f"❌ {name}: NOT FOUND at {path}")
            all_passed = False

    return all_passed

def test_routes():
    """Test that routes are registered"""
    print("\nTesting routes...")
    try:
        from polymarket_mcp.web.app import app

        routes = [route.path for route in app.routes]

        expected_routes = [
            "/",
            "/config",
            "/markets",
            "/monitoring",
            "/api/status",
            "/api/test-connection",
            "/api/markets/trending",
            "/api/markets/search",
            "/ws",
        ]

        all_passed = True
        for route in expected_routes:
            if route in routes:
                print(f"✅ Route registered: {route}")
            else:
                print(f"❌ Route missing: {route}")
                all_passed = False

        return all_passed
    except Exception as e:
        print(f"❌ Route check failed: {e}")
        return False

def test_dependencies():
    """Test that required dependencies are installed"""
    print("\nTesting dependencies...")

    dependencies = [
        ("fastapi", "FastAPI"),
        ("uvicorn", "Uvicorn"),
        ("jinja2", "Jinja2"),
    ]

    all_passed = True
    for module, name in dependencies:
        try:
            __import__(module)
            print(f"✅ {name} installed")
        except ImportError:
            print(f"❌ {name} NOT installed - run: pip install {module}")
            all_passed = False

    return all_passed

def main():
    """Run all tests"""
    print("=" * 60)
    print("Polymarket MCP Web Dashboard - Test Suite")
    print("=" * 60)

    tests = [
        ("Dependencies", test_dependencies),
        ("Imports", test_imports),
        ("Directory Structure", test_directory_structure),
        ("Routes", test_routes),
    ]

    results = {}
    for name, test_func in tests:
        results[name] = test_func()

    print("\n" + "=" * 60)
    print("Test Results")
    print("=" * 60)

    for name, passed in results.items():
        status = "✅ PASSED" if passed else "❌ FAILED"
        print(f"{name}: {status}")

    print("=" * 60)

    if all(results.values()):
        print("\n✅ All tests passed! Web dashboard is ready to use.")
        print("\nTo start the dashboard, run:")
        print("  polymarket-web")
        print("  or")
        print("  ./start_web_dashboard.sh")
        print("\nThen open: http://localhost:8080")
        return 0
    else:
        print("\n❌ Some tests failed. Please check the errors above.")
        return 1

if __name__ == "__main__":
    sys.exit(main())
