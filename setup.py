import setuptools

setuptools.setup(
    name='rime',
    version='2.0.dev1',
    scripts=['bin/rime', 'bin/rime_init'],
    packages=['rime', 'rime.basic', 'rime.basic.targets', 'rime.basic.util',
              'rime.core', 'rime.plugins', 'rime.plugins.judge_system',
              'rime.util'],
    package_dir={'rime': 'rime'},
    install_requires=['six'],
    tests_require=['pytest', 'mock'],
)
