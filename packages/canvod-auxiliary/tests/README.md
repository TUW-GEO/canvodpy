# Tests for canvod-auxiliary

Comprehensive test suite for auxiliary data augmentation functionality.

## Test Structure

```
tests/
├── conftest.py              # Pytest configuration and fixtures
├── test_preprocessing.py    # Preprocessing (sv→sid) tests
├── test_position.py         # Coordinate transformation tests
├── test_products.py         # Product registry tests
├── test_interpolation.py    # Interpolation strategy tests
└── README.md               # This file
```

## Running Tests

### Run all tests
```bash
just test
# or
uv run pytest
```

### Run specific test file
```bash
uv run pytest tests/test_preprocessing.py
```

### Run specific test class
```bash
uv run pytest tests/test_preprocessing.py::TestMapAuxSvToSid
```

### Run specific test
```bash
uv run pytest tests/test_preprocessing.py::TestMapAuxSvToSid::test_dimension_expansion
```

### Run with verbose output
```bash
uv run pytest -v
```

### Run with coverage
```bash
uv run pytest --cov=canvod.auxiliary --cov-report=html
```

### Exclude slow tests
```bash
uv run pytest -m "not slow"
```

### Exclude network tests
```bash
uv run pytest -m "not network"
```

## Test Categories

### Unit Tests

**test_preprocessing.py** - 45+ tests
- `TestCreateSvToSidMapping` (7 tests) - Signal ID generation
- `TestMapAuxSvToSid` (6 tests) - sv→sid conversion
- `TestPadToGlobalSid` (4 tests) - Global sid padding
- `TestNormalizeSidDtype` (3 tests) - Dtype normalization
- `TestStripFillvalue` (3 tests) - Attribute cleaning
- `TestAddFutureDatavars` (2 tests) - Variable addition
- `TestPrepAuxDs` (2 tests) - Complete pipeline
- `TestPreprocessAuxForInterpolation` (3 tests) - Interpolation prep
- `TestPreprocessingIntegration` (4 tests) - Integration tests

**test_position.py** - 30+ tests
- `TestECEFPosition` (6 tests) - ECEF coordinates
- `TestGeodeticPosition` (5 tests) - Geodetic coordinates
- `TestComputeSphericalCoordinates` (9 tests) - Spherical coords
- `TestAddSphericalCoordsToDataset` (4 tests) - Dataset augmentation
- `TestCoordinateTransformationIntegration` (3 tests) - Integration

**test_products.py** - 25+ tests
- `TestProductSpec` (2 tests) - Product model
- `TestGetProductSpec` (5 tests) - Product retrieval
- `TestListAvailableProducts` (4 tests) - Product listing
- `TestListAgencies` (3 tests) - Agency listing
- `TestProductRegistry` (6 tests) - Registry integration
- `TestProductSpecConfiguration` (2 tests) - Configuration details

**test_interpolation.py** - 20+ tests
- `TestSp3Config` (3 tests) - SP3 configuration
- `TestClockConfig` (2 tests) - Clock configuration
- `TestSp3InterpolationStrategy` (6 tests) - SP3 interpolation
- `TestClockInterpolationStrategy` (4 tests) - Clock interpolation
- `TestInterpolationIntegration` (3 tests) - Integration
- `TestInterpolationEdgeCases` (3 tests) - Edge cases

### Integration Tests

Tests marked with `@pytest.mark.integration`:
- Complete preprocessing workflows
- Multi-step coordinate transformations
- Combined SP3 + CLK interpolation

### Network Tests

Tests marked with `@pytest.mark.network`:
- File downloading
- FTP connection tests
- Product URL validation

*Note: Network tests are skipped by default*

## Fixtures

### Data Fixtures (conftest.py)

**sample_sp3_data**
- Simulates raw SP3 dataset
- Dimensions: `(epoch: 96, sv: 4)`
- Contains: X, Y, Z positions + velocities

**sample_clk_data**
- Simulates raw CLK dataset
- Dimensions: `(epoch: 288, sv: 4)`
- Contains: clock_bias

**sample_rinex_data**
- Simulates RINEX dataset
- Dimensions: `(epoch: 2880, sid: 48)`
- Contains: SNR observations

**sample_preprocessed_sp3**
- Preprocessed SP3 with sid dimension
- Dimensions: `(epoch: 96, sid: 48)`
- Ready for interpolation

**ecef_position**
- ECEFPosition instance
- The made-up site (Bloemfontein) from `canvod.utils.testing`

**geodetic_position**
- GeodeticPosition instance
- The made-up site (Bloemfontein) from `canvod.utils.testing`

## Coverage Goals

Target coverage: **>85%**

Current coverage by module:
- `preprocessing.py`: ~95%
- `position.py`: ~90%
- `products.py`: ~85%
- `interpolation.py`: ~80%

Run coverage report:
```bash
uv run pytest --cov=canvod.auxiliary --cov-report=term-missing
```

## Test Conventions

### Naming
- Test files: `test_<module>.py`
- Test classes: `Test<ClassName>`
- Test methods: `test_<description>`

### Structure
```python
class TestFeature:
    """Test feature description."""

    def test_expected_behavior(self, fixture):
        """Test description in imperative mood."""
        # Arrange
        input_data = prepare_input()

        # Act
        result = function_under_test(input_data)

        # Assert
        assert result == expected
```

### Assertions
- Use `assert` statements
- Use `np.testing.assert_almost_equal()` for floats
- Use `pytest.raises()` for exceptions

## Adding New Tests

1. Create test file in `tests/` directory
2. Import necessary fixtures from `conftest.py`
3. Organize tests into classes by feature
4. Use descriptive test names
5. Add docstrings
6. Run tests to verify

Example:
```python
"""Tests for new feature."""

import pytest
from canvod.auxiliary import new_feature


class TestNewFeature:
    """Test new_feature function."""

    def test_basic_functionality(self):
        """Test basic usage works."""
        result = new_feature(input_data)
        assert result is not None

    def test_edge_case(self):
        """Test edge case is handled."""
        result = new_feature(edge_case_input)
        assert result == expected
```

## Continuous Integration

Tests run automatically on:
- Pull requests
- Pushes to main branch
- Nightly builds

CI configuration: `.github/workflows/test.yml`

## Troubleshooting

### Import Errors
```bash
# Install the workspace packages (editable) from the repository root
uv sync
```

### Missing Dependencies
```bash
# Sync all dependencies
just sync
```

### Test Discovery Issues
```bash
# Verify pytest can find tests
uv run pytest --collect-only
```

### Fixture Not Found
Check that fixture is defined in `conftest.py` or imported correctly.

## Contributing

When adding features:
1. Write tests first (TDD)
2. Aim for >80% coverage
3. Test edge cases
4. Add integration tests for workflows
5. Update this README if adding new test categories
