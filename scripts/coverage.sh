#!/bin/bash

coverage run -m pytest workspace/tests -vs && coverage report --format=markdown > reports/test_coverage.md
