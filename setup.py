from setuptools import setup, find_packages


setup(
    name="certbot",
    version='0.0.1',
    license='MIT',
    url="https://github.com/praekeltfoundation/certbot",
    description="A robot for managing Let's Encrypt! certs in Seed Stack",
    author='Jamie Hewland',
    author_email='jamie@praekelt.com',
    packages=find_packages(),
    install_requires=[
        'Twisted',
    ],
    classifiers=[
        'Development Status :: 4 - Beta',
        'Intended Audience :: System Administrators',
        'License :: OSI Approved :: MIT License',
        'Operating System :: POSIX',
        'Programming Language :: Python',
    ],
)
