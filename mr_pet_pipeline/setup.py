from setuptools import setup, find_packages

setup(
    name="mr-pet-pipeline",
    version="1.0.0",
    packages=find_packages(),
    install_requires=[
        'pyyaml>=6.0',
        'pandas>=1.5.0',
    ],
    entry_points={
        'console_scripts': [
            'mr-pet-pipeline=scripts.run_pipeline:main',
        ],
    },
)