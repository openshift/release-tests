# QE TRT (Technical Release Team)

QE TRT will make QE tasks of z-stream release more efficient and easier, improve test coverage and automate this process and release the existing release leaders' and managers' energy, and the most energy from component teams on z-stream release.

## Install the tools
Clone this repo, and run:
```yaml
MacBook-Pro:release-tests jianzhang$ pip install -e .
Defaulting to user installation because normal site-packages is not writeable
Obtaining file:///Users/jianzhang/goproject/src/github.com/openshift/release-tests
  Preparing metadata (setup.py) ... done
Requirement already satisfied: semver in /Users/jianzhang/Library/Python/3.10/lib/python/site-packages (from release-tests==1.0.1) (3.0.0)
Requirement already satisfied: requests in /Library/Frameworks/Python.framework/Versions/3.10/lib/python3.10/site-packages (from release-tests==1.0.1) (2.27.1)
Requirement already satisfied: charset-normalizer~=2.0.0 in /Library/Frameworks/Python.framework/Versions/3.10/lib/python3.10/site-packages (from requests->release-tests==1.0.1) (2.0.12)
Requirement already satisfied: idna<4,>=2.5 in /Library/Frameworks/Python.framework/Versions/3.10/lib/python3.10/site-packages (from requests->release-tests==1.0.1) (3.3)
Requirement already satisfied: urllib3<1.27,>=1.21.1 in /Library/Frameworks/Python.framework/Versions/3.10/lib/python3.10/site-packages (from requests->release-tests==1.0.1) (1.26.9)
Requirement already satisfied: certifi>=2017.4.17 in /Library/Frameworks/Python.framework/Versions/3.10/lib/python3.10/site-packages (from requests->release-tests==1.0.1) (2022.12.7)
Installing collected packages: release-tests
  Running setup.py develop for release-tests
Successfully installed release-tests

MacBook-Pro:release-tests jianzhang$ pip list
Package                  Version   Editable project location
------------------------ --------- -----------------------------------------------------------------
...
...
release-tests            1.0.1     /Users/jianzhang/goproject/src/github.com/openshift/release-tests
...
...

MacBook-Pro:release-tests jianzhang$ job
Usage: job [OPTIONS] COMMAND [ARGS]...

Options:
  --debug / --no-debug
  --help                Show this message and exit.

Commands:
  get_payloads  Check the latest payload of each version.
  get_results   Return the Prow job executed info.
  run           Run a Prow job via API call.
  run_required  Run required jobs from a file

```
