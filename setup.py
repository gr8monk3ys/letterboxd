from setuptools import setup, find_packages

setup(
    name="letterboxd-automation",
    version="0.1.0",
    packages=find_packages(),
    install_requires=[
        "playwright>=1.32.1",
        "openai>=1.3.0",
        "python-dotenv>=1.0.0",
        "tqdm>=4.66.1",
        "agentql>=0.1.0",
        "letterboxd",
        "pandas>=1.5.3"
    ],
    author="Lorenzo Scaturchio",
    author_email="lorenzosca7@gmail.com",
    description="A toolkit for automating Letterboxd interactions",
    long_description=open("README.md").read(),
    long_description_content_type="text/markdown",
    python_requires=">=3.8",
)
