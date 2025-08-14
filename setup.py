#!/usr/bin/env python3

from setuptools import find_packages, setup

with open("README.md", "r", encoding="utf-8") as fh:
    long_description = fh.read()

try:
    with open("requirements.txt", "r", encoding="utf-8") as fh:
        requirements = [
            line.strip() for line in fh if line.strip() and not line.startswith("#")
        ]
except FileNotFoundError:
    requirements = [
        "google-api-python-client>=2.0.0",
        "google-auth>=2.0.0", 
        "gdown>=4.0.0"
    ]

setup(
    name="gdvc",
    version="0.0.1",
    author="Vikranth Srivatsa",
    description="Lightweight Google Drive file upload and version control CLI tool",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/vikranth22446/gdvc_mini",
    py_modules=["gdvc_mini"],
    classifiers=[
        "Development Status :: 4 - Beta",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.7",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
    ],
    python_requires=">=3.7",
    install_requires=requirements,
    entry_points={
        "console_scripts": [
            "gdvc=gdvc_mini:main",
        ],
    },
)
