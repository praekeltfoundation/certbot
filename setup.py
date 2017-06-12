import codecs
import os
import sys

from setuptools import setup, find_packages

HERE = os.path.abspath(os.path.dirname(__file__))


def read(*parts):  # Stolen from txacme
    with codecs.open(os.path.join(HERE, *parts), 'rb', 'utf-8') as f:
        return f.read()


def readme():
    # Prefer the ReStructuredText README, but fallback to Markdown if it hasn't
    # been generated
    if os.path.exists('README.rst'):
        return read('README.rst')
    else:
        return read('README.md')


install_requires = [
    'acme >= 0.10.0',
    'cryptography',
    'klein',
    'requests',
    # treq.testing broken on older versions of treq with Twisted 17.1.0
    'treq >= 17.3.1',
    # Despite treq & txacme depending on Twisted[tls], we don't get all the tls
    # extras unless we depend on the option too, I guess, because pip.
    'Twisted[tls]',
    'txacme >= 0.9.1',
    'uritools >= 1.0.0'
]
if sys.version_info < (3, 3):
    install_requires.append('ipaddress')

setup(
    name='marathon-acme',
    version='0.1.1',
    license='MIT',
    url='https://github.com/praekeltfoundation/marathon-acme',
    description=("Automated management of Let's Encrypt certificates for apps "
                 "running on Mesosphere Marathon"),
    author='Jamie Hewland',
    author_email='jamie@praekelt.com',
    long_description=readme(),
    packages=find_packages(),
    install_requires=install_requires,
    classifiers=[
        'Development Status :: 3 - Alpha',
        'Framework :: Twisted',
        'Intended Audience :: System Administrators',
        'License :: OSI Approved :: MIT License',
        'Natural Language :: English',
        'Programming Language :: Python',
        'Programming Language :: Python :: 2',
        'Programming Language :: Python :: 2.7',
        'Programming Language :: Python :: 3',
        'Programming Language :: Python :: 3.5',
        'Programming Language :: Python :: 3.6',
        'Programming Language :: Python :: Implementation :: CPython',
        'Programming Language :: Python :: Implementation :: PyPy'
    ],
    entry_points={
        'console_scripts': ['marathon-acme = marathon_acme.cli:_main'],
    }
)
