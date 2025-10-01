RED=\033[0;31m
GREEN=\033[0;32m
YELLOW=\033[0;33m
ORANGE=\033[38;5;214m
BLUE=\033[0;34m
PURPLE=\033[0;35m
CYAN=\033[0;36m
NO_COLOR=\033[0m

# command make -f <script_name>.mk <command>
hello:
	@echo "Hello, World!"

print_help:
	@echo "Usage:"
	@echo ""
	@echo "make ${YELLOW}command ${PURPLE}target${NO_COLOR}"
	@echo ""
	@echo "Available ${YELLOW}command${NO_COLOR}:"
	@echo ""
	@echo "  ${CYAN}init${NO_COLOR}       Generate files required for development/deployment"
	@echo "  ${CYAN}build${NO_COLOR}      Build container image"
	@echo "  ${CYAN}push${NO_COLOR}       Push to registry"
	@echo "  ${CYAN}pull${NO_COLOR}       Pull from registry"
	@echo "  ${CYAN}test${NO_COLOR}       Test Pull/Build image"
	@echo "  ${CYAN}terminate${NO_COLOR}  Terminate running test image"
	@echo "Available ${PURPLE}target${NO_COLOR}"
	@echo "  ${CYAN}dev${NO_COLOR}      Devcontainer"
	@echo "  ${CYAN}prod${NO_COLOR}     Production"

ls_docker:
	docker ps -a