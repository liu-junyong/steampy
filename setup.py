from setuptools import setup
import sys

if not sys.version_info[0] == 3 and sys.version_info[1] < 5:
    sys.exit('Python < 3.5 is not supported')

version = '0.76a'

setup(
    name='steampy',
    packages=['steampy', 'test', 'examples', ],
    version=version,
    description='A Steam lib for trade automation,fork from :https://github.com/bukson/steampy',
    author='liujunyong,origin author:bukson',
    author_email='liu.junyong@gmail.com',
    license='MIT',
    url='https://gitee.com/liu_junyong/steampy',
    download_url='https://gitee.com/liu_junyong/steampy/' + version,
    keywords=['steam', 'trade', ],
    classifiers=[],
    install_requires=[
        "requests",
        "beautifulsoup4",
        "rsa"
    ],
)
