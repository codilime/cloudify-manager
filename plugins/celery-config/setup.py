from setuptools import setup


setup(
    name='cloudify-celery-config',
    description='Celery processes configuration.',
    packages=['celery_config'],
    install_requires=[
        'celery'
    ]
)
