# devcontainer_template
Developer Container Template

# Practices
- Dockerfile
Dockerfile should container 2 types which are Development and Production
- Compose Services
Services are available in 2 types:
    - Development
    This are meant for development purpose in devcontainer
    - Production
    This sound be use without the need for any mounting of any volumes unless absolute necessary.
    The image should not contain any source code rather binaries will do to light weight the image

# How to add template to new repository
```dotnetcli
git remote add dev_container_template git@github.com:Amizzuddin/devcontainer_template.git && \
git fetch dev_container_template && \
git merge dev_container_template/main --allow-unrelated-histories
```
once done remove remote
```dotnetcli
git remote remove dev_container_template
```

# TODO
- Need to update run.sh
