from setuptools import setup, find_packages

setup(
    name="monitor",
    version="0.1.0",
    package_dir={"": "src"},
    packages=find_packages(where="src"),
    entry_points={
        "console_scripts": [
            "monitor = monitor.__main__:main"
        ]
    },
    description="A hello world CLI project",
    author="Your Name",
    python_requires='>=3.6',
    install_requires=[
        "appdirs>=1.4.0",
    ],
    package_data={"monitor": ["example.cfg"]},
)
