install:
	pip3 install --use-pep517 -e . && pip3 install -e prow/ && oar -h

uninstall:
	pip3 uninstall -y oar job

clean-install: uninstall install
