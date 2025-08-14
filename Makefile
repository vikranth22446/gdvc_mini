.PHONY: clean build test-upload upload install dev-install help

help:
	@echo "Available targets:"
	@echo "  clean        - Remove build artifacts"
	@echo "  build        - Build distribution packages"
	@echo "  test-upload  - Upload to TestPyPI"
	@echo "  upload       - Upload to PyPI"
	@echo "  install      - Install package locally"
	@echo "  dev-install  - Install package in development mode"
	@echo "  help         - Show this help message"

clean:
	rm -rf build/
	rm -rf dist/
	rm -rf *.egg-info/
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete

build: clean
	python setup.py sdist bdist_wheel

test-upload: build
	python -m twine upload --repository testpypi dist/*

upload: build
	python -m twine upload dist/*

install:
	pip install .

dev-install:
	pip install -e .

# Convenience target to check if twine is installed
check-twine:
	@python -c "import twine" 2>/dev/null || (echo "twine not installed. Run: pip install twine" && exit 1)