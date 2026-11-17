# Thin wrapper: all logic lives in tasks.py so Windows (no make) can run the same targets.
PYTHON ?= python3
ARGS ?=

.PHONY: install setup test check run clean

install:
	$(PYTHON) tasks.py install

setup:
	$(PYTHON) tasks.py setup

test:
	$(PYTHON) tasks.py test $(ARGS)

check:
	$(PYTHON) tasks.py check $(ARGS)

run:
	$(PYTHON) tasks.py run $(ARGS)

clean:
	$(PYTHON) tasks.py clean
