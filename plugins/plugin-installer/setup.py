__author__ = 'elip'

from setuptools import setup

setup(
    name='cloudify-plugin-installer-plugin',
    version='3.0',
    author='elip',
    author_email='elip@gigaspaces.com',
    packages=['plugin_installer'],
    license='LICENSE',
    description='Plugin for installing plugins into an existing celery worker',
    zip_safe=False,
    install_requires=[
        "cloudify-plugins-common==3.0",
    ],
    tests_require=[
        "nose"
    ],
)
