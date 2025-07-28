from setuptools import find_packages, setup

setup(
    name='ontoProbe',
    packages=find_packages(include=['ontoProbe']),
    version='0.1.0',
    description='My first Python library',
    author='Lucas Vianna de Uzêda Moreira',
    package_data={'ontoProbe': ['metamodel.tx']},
    install_requires=[
        'textx',
        'rdflib',
        'jmespath',
        'tabulate'
    ],
    setup_requires=[],
    tests_require=[],
    test_suite='tests'
)