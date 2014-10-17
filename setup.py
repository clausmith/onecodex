"""
``onecodex``
---------

``onecodex`` provides a command line client for interaction with the
One Codex API.



Links
`````
* `One Codex: <https://www.onecodex.com/>`
* `API Docs: <http://docs.onecodex.com/>`

"""
from setuptools import setup


setup(
    name='onecodex',
    version='0.0.1',
    url='http://github.com/refgenomics/onecodex/',
    license='All rights reserved',
    author='Nick Boyd Greenfield',
    author_email='nick@onecodex.com',
    description='One Codex Command Line Client',
    long_description=__doc__,
    packages=['onecodex'],
    zip_safe=True,
    platforms='any',
    install_requires=[
        'requests>=2.4.3',
    ],
    test_suite='nose.collector',
    entry_points={
        'console_scripts': ['onecodex = onecodex.cli:main']
    },
)
