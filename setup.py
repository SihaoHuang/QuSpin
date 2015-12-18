def configuration(parent_package='', top_path=None):
	from numpy.distutils.misc_util import Configuration
	config = Configuration(None, parent_package, top_path)
	config.set_options(
	assume_default_configuration=True,
	delegate_options_to_subpackages=True,
	quiet=True)

	config.add_subpackage('exact_diag_py')

	return config


def setup_package():
	try:
		import numpy
	except:
		raise ImportError("build requires numpy for fortran extensions")


	metadata = dict(
		name='exact_diag_py',
		maintainer="Phillip Weinberg, Marin Bukov",
		maintainer_email="weinbe58@bu.edu,mbukov.bu.edu",
		download_url="https://github.com/weinbe58/exact_diag_py",
		license='MIT',
		platforms=["Unix"]
	)

	from numpy.distutils.core import setup
	metadata['configuration'] = configuration

	setup(**metadata)


if __name__ == '__main__':
	setup_package()


