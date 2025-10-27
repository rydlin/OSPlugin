# Tests for Favorite.py

This directory contains unit tests for the `Favorite.py` action class.

## Running Tests

### Option 1: Using the test runner script
```bash
cd tests
python run_tests.py
```

### Option 2: Using Python's unittest module directly
```bash
python -m unittest discover tests/
```

### Option 3: Running specific test file
```bash
python -m unittest tests.test_favorite
```

## Test Structure

- `stubs.py`: Mock implementations of dependencies to isolate the code under test
- `test_favorite.py`: Unit tests for the Favorite class
- `run_tests.py`: Test runner script
- `requirements.txt`: Test dependencies (minimal, just unittest)

## Test Coverage

The tests cover:
- Successful and error cases for `get_favorites()`
- Event callback with valid/invalid favorites
- App launching success/failure
- Desktop file finding and parsing
- Configuration setup
- Error handling and logging

## Dependencies

The tests use only standard library modules (unittest, unittest.mock) plus the stubs for mocking external dependencies.