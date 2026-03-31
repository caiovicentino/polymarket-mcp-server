# Contributing to Polymarket MCP Server

Thank you for your interest in contributing to the Polymarket MCP Server! 🎉

We welcome contributions from the community and are grateful for any help you can provide.

---

## 🌟 How to Contribute

There are many ways you can contribute to this project:

- 🐛 **Report Bugs** - Found a bug? Let us know!
- ✨ **Suggest Features** - Have an idea? We'd love to hear it!
- 📖 **Improve Documentation** - Help make our docs better
- 💻 **Submit Code** - Fix bugs or add features
- 🧪 **Add Tests** - Improve test coverage
- 💬 **Help Others** - Answer questions in Discussions
- 🌍 **Translations** - Help translate documentation

---

## 🚀 Getting Started

### Development Setup

1. **Fork the repository**
   ```bash
   # Click "Fork" button on GitHub
   ```

2. **Clone your fork**
   ```bash
   git clone https://github.com/YOUR_USERNAME/polymarket-mcp-server.git
   cd polymarket-mcp-server
   ```

3. **Create virtual environment**
   ```bash
   python -m venv venv
   source venv/bin/activate  # Windows: venv\Scripts\activate
   ```

4. **Install with dev dependencies**
   ```bash
   pip install -e ".[dev]"
   ```

5. **Create a branch**
   ```bash
   git checkout -b feature/your-feature-name
   # or
   git checkout -b fix/your-bug-fix
   ```

---

## 📝 Code Standards

### Python Code Style

We follow PEP 8 with some modifications:

- **Line length**: 100 characters (not 79)
- **Imports**: Group by standard library, third-party, local
- **Type hints**: Use type hints for all function signatures
- **Docstrings**: Google-style docstrings for all public functions

```python
def example_function(param1: str, param2: int) -> dict:
    """
    Brief description of what the function does.

    Args:
        param1: Description of param1
        param2: Description of param2

    Returns:
        Description of return value

    Raises:
        ValueError: When something goes wrong
    """
    pass
```

### Code Quality Tools

Before submitting, run:

```bash
# Format code
black src/

# Lint
ruff check src/

# Type checking (optional but recommended)
mypy src/
```

### Commit Messages

Follow the [Conventional Commits](https://www.conventionalcommits.org/) specification:

```
feat: add new market filtering tool
fix: resolve rate limiting issue in trading module
docs: update installation instructions
test: add tests for portfolio analysis
refactor: improve orderbook parsing logic
```

---

## 🧪 Testing

### Run Tests

```bash
# Run all tests
pytest

# Run specific test file
pytest tests/test_trading_tools.py -v

# Run with coverage
pytest --cov=polymarket_mcp --cov-report=html

# Run only fast tests (skip integration tests)
pytest -m "not slow"
```

### Writing Tests

- **All tests must use real Polymarket APIs** (NO MOCKS per project policy)
- Use `pytest` framework
- Place tests in `/tests/` directory
- Name test files `test_*.py`
- Each new feature should include corresponding tests

Example test structure:

```python
import pytest
from polymarket_mcp.tools import your_module

async def test_your_feature():
    """Test description"""
    result = await your_module.your_function()
    assert result is not None
    assert result['key'] == 'expected_value'
```

---

## 🔀 Pull Request Process

### Before Submitting

1. ✅ **Tests pass** - `pytest`
2. ✅ **Code is formatted** - `black src/`
3. ✅ **No linting errors** - `ruff check src/`
4. ✅ **Documentation updated** - If you changed functionality
5. ✅ **Commits are clean** - Squash if needed

### Submitting

1. **Push your branch**
   ```bash
   git push origin feature/your-feature-name
   ```

2. **Open Pull Request**
   - Go to GitHub repository
   - Click "New Pull Request"
   - Select your branch
   - Fill out the PR template

3. **Describe your changes**
   - What does this PR do?
   - Why is this change needed?
   - How was it tested?
   - Any breaking changes?

4. **Wait for review**
   - Maintainers will review your PR
   - Address any feedback
   - Once approved, it will be merged!

### PR Title Format

```
feat: add XYZ feature
fix: resolve ABC bug
docs: improve XYZ documentation
test: add tests for ABC
refactor: improve XYZ implementation
```

---

## 🐛 Reporting Bugs

### Before Reporting

1. **Check existing issues** - Maybe it's already reported
2. **Try latest version** - Bug might be fixed already
3. **Reproduce the bug** - Make sure it's consistent

### Bug Report Template

When creating a bug report, include:

- **Description**: Clear description of the bug
- **Steps to Reproduce**: Numbered steps to reproduce
- **Expected Behavior**: What should happen
- **Actual Behavior**: What actually happens
- **Environment**:
  - Python version
  - OS (macOS/Windows/Linux)
  - Claude Desktop version
  - MCP server version
- **Error Messages**: Full error messages or stack traces
- **Screenshots**: If applicable

---

## ✨ Suggesting Features

### Feature Request Template

When requesting a feature, include:

- **Problem**: What problem does this solve?
- **Proposed Solution**: How would you solve it?
- **Alternatives**: Other solutions you've considered
- **Use Cases**: How would you use this feature?
- **Priority**: How important is this to you?

---

## 📚 Documentation

### Improving Documentation

Documentation improvements are always welcome!

- Fix typos or grammar
- Add examples
- Clarify confusing sections
- Add missing information
- Translate to other languages

### Documentation Files

- `README.md` - Main project documentation
- `SETUP_GUIDE.md` - Installation and setup
- `TOOLS_REFERENCE.md` - API reference
- `TRADING_ARCHITECTURE.md` - System architecture
- Code docstrings - Inline documentation

---

## 🤝 Code of Conduct

### Our Pledge

We are committed to providing a welcoming and inspiring community for all.

### Expected Behavior

- ✅ Be respectful and inclusive
- ✅ Be collaborative
- ✅ Be constructive in criticism
- ✅ Focus on what is best for the community
- ✅ Show empathy towards others

### Unacceptable Behavior

- ❌ Harassment or discrimination
- ❌ Trolling or insulting comments
- ❌ Personal or political attacks
- ❌ Publishing private information
- ❌ Other unprofessional conduct

---

## 💬 Getting Help

Need help contributing?

- 💬 **[GitHub Discussions](https://github.com/joe67-67/polymarket-mcp-server/discussions)** - Ask questions
- 📱 **[Telegram Communities](#)** - Chat with community members
- 📧 **Email**: Contact project maintainers

---

## 🎯 Priority Areas

We're especially interested in contributions in these areas:

### High Priority
- 🐛 Bug fixes
- 🧪 Test coverage improvements
- 📖 Documentation improvements
- 🔒 Security enhancements

### Medium Priority
- ✨ New analysis tools
- 📊 Performance improvements
- 🎨 Code refactoring
- 🌍 Internationalization

### Nice to Have
- 🎥 Video tutorials
- 📱 Mobile support
- 🖼️ UI dashboard
- 🤖 Additional AI features

---

## 🏆 Recognition

Contributors will be:
- Listed in the project's contributors list
- Mentioned in release notes (for significant contributions)
- Credited in documentation they improve
- Recognized in our community channels

---

## 📜 License

By contributing, you agree that your contributions will be licensed under the MIT License.

---

## 🙏 Thank You!

Your contributions make this project better for everyone. We appreciate your time and effort!

**Special thanks to our community partners:**
- 🌾 Yield Hacker
- 💰 Renda Cripto
- 🏗️ Cultura Builder

Together, we're building the future of AI-powered prediction market trading! 🚀

---

## 📞 Contact

- **Project Maintainer**: [Caio Vicentino](https://github.com/caiovicentino)
- **Issues**: [GitHub Issues](https://github.com/joe67-67/polymarket-mcp-server/issues)
- **Discussions**: [GitHub Discussions](https://github.com/joe67-67/polymarket-mcp-server/discussions)

---

<div align="center">

**Happy Contributing! 🎉**

</div>
