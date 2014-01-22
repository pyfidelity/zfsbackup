from setuptools import setup, find_packages


setup(name='zfsbackup',
    version='0.5',
    description='Tool for handling local and remote backups of ZFS filesystems.',
    url='http://mij.oltrelinux.com/devel/zfsbackup/',
    author='Mij',
    author_email='mij@sshguard.net',
    classifiers=[
        'Environment :: Console',
        'Intended Audience :: System Administrators',
        'Operating System :: Unix',
        'Programming Language :: Python',
        'Topic :: System :: Archiving :: Backup',
        'Topic :: System :: Filesystems',
        'Topic :: Utilities',
    ],
    packages=find_packages(),
    entry_points='''
        [console_scripts]
        zfsbackup = zfsbackup.zfsbackup:main
    ''',
)
