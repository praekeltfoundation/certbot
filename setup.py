from setuptools import setup, find_packages


setup(
    name='marathon-acme',
    version='0.0.1',
    license='MIT',
    url='https://github.com/praekeltfoundation/marathon-acme',
    description=("Automated management of Let's Encrypt certificates for apps "
                 "running on Mesosphere Marathon"),
    author='Jamie Hewland',
    author_email='jamie@praekelt.com',
    packages=find_packages(),
    install_requires=[
        'klein==15.3.1',
        'treq',
        'Twisted',
        'txacme',
        'uritools>=1.0.0'
    ],
    classifiers=[
        'Development Status :: 2 - Pre-Alpha',
        'Framework :: Twisted',
        'Intended Audience :: System Administrators',
        'License :: OSI Approved :: MIT License',
        'Natural Language :: English',
        'Programming Language :: Python',
        'Programming Language :: Python :: 2.7',
        'Programming Language :: Python :: 3',
        'Programming Language :: Python :: Implementation :: CPython',
        'Programming Language :: Python :: Implementation :: PyPy'
    ],
    entry_points={
        'console_scripts': ['marathon-acme = marathon_acme.cli:main'],
    }
)
