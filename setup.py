
from setuptools import find_packages, setup
import tools


setup(
    name='release-tests',
    version=tools.version,
    url='https://github.com/openshift/release-tests',
    license='GPLv3',
    author='Jian Zhang',
    author_email='jiazha@redhat.com',
    description='job like tool that works with Prow and Github',
    long_description=__doc__,
    packages=find_packages(),
    include_package_data=True,
    zip_safe=False,
    platforms='any',
    install_requires=['semver', 'requests', 'pyyaml', 'click'],
    entry_points={
        'console_scripts': [
            'job = tools.job:cli',
        ],
    },
    classifiers=[
        'License :: OSI Approved :: BSD License',
    ]
)