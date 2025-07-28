from setuptools import setup, find_packages

setup(
    name="monitor-assistant",
    version="1.0.0",
    description="Monitor: Modular LLM Command-line Assistant",
    author="Your Name",
    author_email="support@monitorcli.com",
    packages=find_packages(include=['lib*', 'core*']),
    install_requires=[
        "pyyaml==6.0.2",
        "dotenv==0.9.9",
        "colored==2.3.0",
        "litellm==1.49.3",
        "prompt_toolkit==3.0.51",
        "pygments==2.19.1",
        "mcp==1.9.0",
        "tavily-python==0.7.2",
        "pandas==2.2.3",
        "scikit-learn==1.6.1",
        "redis==6.1.0",
        "openai-whisper-20240930",
        "pyaudio==0.2.14",
        "graphviz==0.20.3",
        "ollama==0.4.8",
        "duckdb==1.2.2",
        "GitPython==3.1.44",
        "tiktoken==0.9.0",
        "anthropic==0.54.0"
    ],
    entry_points={
        'console_scripts': [
            'monitor=app:main'
        ]
    },
    include_package_data=True,
    python_requires='>=3.9',
)
