import setuptools

setuptools.setup(
    name='rime',
    version='2.0.dev1',
    scripts=['bin/rime', 'bin/rime_init'],
    packages=['rime', 'rime.basic', 'rime.basic.targets', 'rime.core',
              'rime.util'],
    package_dir={'rime': 'rime'},
    install_requires=['six'],
    tests_require=['pytest', 'mock'],
)
