#!/usr/bin/python3

import glob
import os
import platform
from setuptools import setup

arch = platform.architecture()[0]
if '64' in arch:
	arch = '64'
else:
	arch = '32'

PACKAGE_NAME = "scrapedin"
install_requires = [
	'selenium (>=3.4.3)',
	'tabulate (>=0.8.2)'
]
install_location = '/usr/local/bin/'
webdriver = 'geckodriver'

setup(
	name=PACKAGE_NAME,
	version='0.2.dev0',
	description="Generate a list of potential targets for phishing using LinkedIn",
	author="",
	install_requires=install_requires,
	platforms=["Unix"],
	python_requires='>=3.6',
	scripts=glob.glob('scrapedin.py'),
	data_files=[(install_location, [os.path.join('webdriver', arch, webdriver)])],
)
