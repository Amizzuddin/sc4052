#!/bin/bash

# --- PreCommit ---
# Run below command to update pre-commit configs, if needed (Note that it will take a while to update)
# pre-commit autoupdate
pre-commit install
pre-commit run --all-files

# --- Git ---
# Update all submodules gitdir folder structure in dev containers
# find . -type f -name ".git" | while read FILE; do sed -i 's@.*git@gitdir: '"$PWD"'\/.git@' $FILE; done